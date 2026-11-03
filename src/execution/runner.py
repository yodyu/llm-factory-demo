"""Bounded Docker JSON streams for numeric detectors; no scenario adapters."""
import fcntl
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from types import SimpleNamespace

from contracts import ErrorCode, FactoryError
from contracts.base import strict_json_loads
from factory.runtime import ArtifactStore, RuntimeStore
from factory.runtime.artifacts import digest

LOG_LIMIT = 65536
OUTPUT_LIMIT = 2 * 1024 * 1024
LABEL = "llm-factory.managed=metrics-v1"


def docker_command_from_env():
    """A command prefix, never a shell command; explicit runner arguments win."""
    command = tuple(shlex.split(os.environ.get("FACTORY_DOCKER_COMMAND", "docker")))
    if not command:
        raise ValueError("FACTORY_DOCKER_COMMAND must contain an executable")
    return command


@dataclass(frozen=True)
class StreamBudget:
    """Trusted host allocation; never accepted from worker messages."""
    output_bytes: int = OUTPUT_LIMIT
    input_bytes: int = 32 * 1024 * 1024
    request_bytes: int = 1024 * 1024
    seconds: float = 10

    def __post_init__(self):
        if (not 0 < self.output_bytes <= OUTPUT_LIMIT + 50000 * 4096
                or not 0 < self.input_bytes <= 393 * 1024 * 1024
                or not 0 < self.request_bytes <= 32 * 1024 * 1024
                or not 0 < self.seconds <= 210):
            raise ValueError("stream allocation exceeds trusted hard cap")


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


class _TransportError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)

def _stop(process):
    if process is None:
        return
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                process.kill()
            except (ProcessLookupError, PermissionError):
                pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream:
            stream.close()

class _Pipe:
    """Simultaneously write stdin and drain both pipes with hard byte limits."""

    def __init__(self, process, stdout_limit, stderr_limit):
        self.process = process
        self.stdout_limit, self.stderr_limit = stdout_limit, stderr_limit
        self.stdout, self.stderr = bytearray(), bytearray()
        self.selector = selectors.DefaultSelector()
        for stream, kind in ((process.stdout, "stdout"), (process.stderr, "stderr")):
            os.set_blocking(stream.fileno(), False)
            self.selector.register(stream, selectors.EVENT_READ, kind)
        self.eof = set()

    def _read(self, key):
        chunk = os.read(key.fd, 65536)
        if not chunk:
            self.eof.add(key.data)
            self.selector.unregister(key.fileobj)
            return
        target = self.stdout if key.data == "stdout" else self.stderr
        limit = self.stdout_limit if key.data == "stdout" else self.stderr_limit
        if len(target) + len(chunk) > limit:
            raise _TransportError(ErrorCode.RESOURCE_LIMIT, "sandbox output or log limit exceeded")
        target.extend(chunk)

    def pending(self):
        while ready := self.selector.select(0):
            for key, _ in ready:
                if key.data != "stdin":
                    self._read(key)
        if self.stdout:
            raise _TransportError(ErrorCode.CODE_CONTRACT_ERROR, "unsolicited worker response")

    def exchange(self, deadline, data=None, *, line=False):
        position = 0
        if data is not None:
            os.set_blocking(self.process.stdin.fileno(), False)
            self.selector.register(self.process.stdin, selectors.EVENT_WRITE, "stdin")
        try:
            while True:
                if time.monotonic() >= deadline:
                    raise _TransportError(
                        ErrorCode.CODE_TIMEOUT, "sandbox execution deadline exceeded"
                    )
                if line and b"\n" in self.stdout:
                    raw, rest = bytes(self.stdout).split(b"\n", 1)
                    if rest or position != len(data or b""):
                        raise _TransportError(
                            ErrorCode.CODE_CONTRACT_ERROR, "extra or premature worker response"
                        )
                    self.stdout.clear()
                    # Drain bytes already ready; a second response is forbidden.
                    self.pending()
                    return raw
                if self.eof == {"stdout", "stderr"}:
                    try:
                        self.process.wait(timeout=max(0.001, deadline - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        raise _TransportError(
                            ErrorCode.CODE_TIMEOUT, "process did not exit before deadline"
                        ) from None
                    if line:
                        raise _TransportError(
                            ErrorCode.CODE_EXECUTION_ERROR,
                            "worker exited without a complete response",
                        )
                    return bytes(self.stdout)
                for key, _ in self.selector.select(min(0.05, max(0, deadline - time.monotonic()))):
                    if key.data != "stdin":
                        self._read(key)
                    else:
                        try:
                            position += os.write(key.fd, data[position : position + 65536])
                        except BrokenPipeError:
                            raise _TransportError(
                                ErrorCode.CODE_EXECUTION_ERROR, "worker closed its input"
                            ) from None
                        if position == len(data):
                            self.selector.unregister(key.fileobj)
        finally:
            if self.process.stdin:
                try:
                    self.selector.unregister(self.process.stdin)
                except KeyError:
                    pass

    def close(self):
        self.selector.close()

class JsonStream:
    """Public bounded JSON-lines transport; the host never imports worker code."""

    def __init__(self, pipe, deadline, *, budget=None, request_timeout=10):
        self.pipe, self.deadline = pipe, deadline
        self.budget = budget or StreamBudget()
        self.request_timeout = request_timeout
        self.input_bytes = self.output_bytes = 0

    def request(self, value):
        raw = canonical_json(value) + b"\n"
        self.input_bytes += len(raw)
        if len(raw) > self.budget.request_bytes or self.input_bytes > self.budget.input_bytes:
            raise FactoryError(ErrorCode.RESOURCE_LIMIT, "stream input limit exceeded")
        try:
            response = self.pipe.exchange(min(self.deadline, time.monotonic() + self.request_timeout), raw, line=True)
        except _TransportError as error:
            raise FactoryError(error.code, error.message) from None
        self.output_bytes += len(response) + 1  # Include the JSON-lines delimiter.
        if self.output_bytes > self.budget.output_bytes:
            raise FactoryError(ErrorCode.RESOURCE_LIMIT, "stream total output limit exceeded")
        return strict_json_loads(response)

class LocalSandboxRunner:
    managed_label = LABEL
    container_prefix = "llmf-metrics-"
    def __init__(
        self,
        store: RuntimeStore,
        artifacts: ArtifactStore,
        package_root: Path,
        work_root: Path,
        *,
        image: str,
        docker_command: tuple[str, ...] | None = None,
        timeout_seconds: float = 10,
    ):
        if docker_command is None:
            docker_command = docker_command_from_env()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
            raise ValueError("pin a locally approved, full Docker image ID")
        if (
            type(timeout_seconds) not in (int, float)
            or not 0 < timeout_seconds <= 10
            or not docker_command
            or any(not isinstance(x, str) or not x for x in docker_command)
        ):
            raise ValueError("invalid execution timeout or Docker command")
        self.store, self.artifacts = store, artifacts
        self.package_root = Path(package_root)
        root = Path(work_root).absolute()
        if any(p.is_symlink() for p in (root, *root.parents)) or any(
            c in str(root) for c in ",\n\r"
        ):
            raise ValueError("trusted work directory without symlinks or mount delimiters required")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.work_root = root.resolve()
        self.image, self.docker_command, self.timeout_seconds = (
            image,
            tuple(docker_command),
            timeout_seconds,
        )
        self.lock_root = self.store.path.absolute().parent / (self.store.path.name + ".sandbox-locks")
        if self.lock_root.is_symlink():
            raise ValueError("sandbox lock directory must be trusted")
        self.lock_root.mkdir(exist_ok=True, mode=0o700)
        self._workers = set()
        self.cleanup_failures = set()

    def _control(
        self, args, deadline, *, limit=LOG_LIMIT, failure_code=ErrorCode.SANDBOX_UNAVAILABLE
    ):
        remaining = min(5, deadline - time.monotonic())
        if remaining <= 0:
            raise _TransportError(ErrorCode.CODE_TIMEOUT, "sandbox execution deadline exceeded")
        try:
            process = subprocess.Popen(
                [*self.docker_command, *args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError:
            raise _TransportError(
                ErrorCode.SANDBOX_UNAVAILABLE, "Docker command unavailable"
            ) from None
        pipe = _Pipe(process, limit, LOG_LIMIT)
        try:
            raw = pipe.exchange(time.monotonic() + remaining)
            if process.returncode:
                raise _TransportError(failure_code, "Docker control operation failed")
            return raw
        finally:
            pipe.close()
            _stop(process)

    def _slot(self, task_id):
        folder = self.lock_root
        for index in range(3):
            name = digest(task_id.encode())[7:] + f"-{index}.lock"
            fd = os.open(folder / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except BlockingIOError:
                os.close(fd)
        raise _TransportError(ErrorCode.RESOURCE_LIMIT, "task already has three sandbox containers")

    def _container_command(
        self, name, code_dir, input_dir=None, *, task_id="", lifetime_seconds=600
    ):
        mounts = ["--mount", f"type=bind,source={code_dir},target=/code,readonly"]
        if input_dir is not None:
            mounts += ["--mount", f"type=bind,source={input_dir},target=/input,readonly"]
        return [
            "create",
            "--name",
            name,
            "--label",
            self.managed_label,
            "--label",
            "llm-factory.task=" + digest(task_id.encode())[7:],
            "--pull",
            "never",
            "--network",
            "none",
            "--user",
            "65534:65534",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--cpus",
            "1",
            "--memory",
            "512m",
            "--memory-swap",
            "512m",
            "--pids-limit",
            "64",
            "--ulimit",
            "nofile=128:128",
            "--ulimit",
            "core=0:0",
            "--ulimit",
            "fsize=3145728:3145728",
            "--log-driver",
            "none",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=67108864,mode=1777",
            "--tmpfs",
            "/output:rw,nosuid,nodev,noexec,size=4194304,mode=1777",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "PYTHONUNBUFFERED=1",
            "--env",
            "OPENBLAS_NUM_THREADS=1",
            "--env",
            "OMP_NUM_THREADS=1",
            "--env",
            "MKL_NUM_THREADS=1",
            "--workdir",
            "/tmp",
            *mounts,
            "--entrypoint",
            "python3",
            self.image,
            "-I",
            "-u",
            "-c",
            "import sys,time; time.sleep(float(sys.argv[1]))",
            str(lifetime_seconds),
        ]

    def _start(self, task_id, verified, raw, deadline):
        if self.cleanup_failures or any(self.work_root.glob("run-*/cleanup-pending.json")):
            raise _TransportError(
                ErrorCode.SANDBOX_UNAVAILABLE,
                "recover pending container cleanup before launching code",
            )
        slot = self._slot(task_id)
        name = self.container_prefix + uuid.uuid4().hex
        handle = None
        try:
            directory = Path(tempfile.mkdtemp(prefix="run-", dir=self.work_root))
            handle = {"name": name, "directory": directory, "slot": slot}
            with (directory / "container.json").open("x") as journal:
                json.dump({"container": name}, journal)
                journal.flush()
                os.fsync(journal.fileno())
            code = directory / "code"
            code.mkdir(mode=0o755)
            for filename, data in verified.files.items():
                (code / filename).write_bytes(data)
                (code / filename).chmod(0o444)
            code.chmod(0o555)
            source = None
            if raw is not None:
                source = directory / "input"
                source.mkdir(mode=0o755)
                (source / "input.json").write_bytes(raw)
                (source / "input.json").chmod(0o444)
                source.chmod(0o555)
            lifetime = max(0, min(600, self.store.task(task_id)["deadline"] - self.store.clock()))
            self._control(
                self._container_command(
                    name, code, source, task_id=task_id, lifetime_seconds=lifetime
                ),
                deadline,
            )
            self._control(["start", name], deadline)
            return handle
        except BaseException:
            if handle:
                self._cleanup(handle)
            else:
                os.close(slot)
            raise

    def _cleanup(self, handle):
        if handle is None:
            return True
        name = handle["name"]
        try:
            # An absent container is safe only after a successful daemon query.
            found = self._control(
                ["ps", "-aq", "--filter", "name=^/" + name + "$", "--filter", "label=" + self.managed_label],
                time.monotonic() + 5,
            )
            if found.strip():
                self._control(["rm", "--force", "--volumes", name], time.monotonic() + 5)
        except _TransportError:
            self.cleanup_failures.add(name)
            # Preserve the journal and mounted files for explicit recovery.
            (handle["directory"] / "cleanup-pending.json").write_text(
                json.dumps({"container": name})
            )
            return False
        finally:
            if handle.get("slot") is not None:
                os.close(handle["slot"])
                handle["slot"] = None
        self.cleanup_failures.discard(name)
        for path in handle["directory"].iterdir():
            if path.is_dir():
                path.chmod(0o700)
        shutil.rmtree(handle["directory"])
        return True

    def cleanup_orphans(self):
        """Call only with exclusive ownership of this runner's work directory."""
        for journal in self.work_root.glob("run-*/container.json"):
            value = json.loads(journal.read_text())
            name = value["container"]
            if not re.fullmatch(re.escape(self.container_prefix) + r"[0-9a-f]{32}", name):
                raise ValueError("invalid cleanup journal")
            self._cleanup({"name": name, "directory": journal.parent, "slot": None})

    @contextmanager
    def open_json_stream(self, task_id, files, *, worker="worker.py", budget=None):
        """Copied code only, bounded stdin/stdout, shared hardened container lifecycle.

        Caller validates generated source/profile before opening. This API
        carries no scenario or task payload into the container.
        """
        if worker not in files or any(
            not re.fullmatch(r"[a-z_]+\.py", key) or not isinstance(raw, bytes)
            or len(raw) > 256 * 1024 for key, raw in files.items()
        ):
            raise ValueError("bounded flat Python files required")
        budget = budget or StreamBudget(seconds=self.timeout_seconds)
        remaining = self.store.task(task_id)["deadline"] - self.store.clock()
        deadline = time.monotonic() + min(budget.seconds, remaining)
        handle = process = pipe = None
        try:
            handle = self._start(task_id, SimpleNamespace(files=files), None, deadline)
            process = subprocess.Popen(
                [*self.docker_command, "exec", "-i", handle["name"], "python3", "-I", "-B", "/code/" + worker],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True,
            )
            pipe = _Pipe(process, 128 * 1024, LOG_LIMIT)
            yield JsonStream(pipe, deadline, budget=budget, request_timeout=self.timeout_seconds)
        except _TransportError as error:
            raise FactoryError(error.code, error.message) from None
        finally:
            if pipe:
                pipe.close()
            _stop(process)
            if handle and not self._cleanup(handle):
                raise FactoryError(ErrorCode.SANDBOX_UNAVAILABLE, "stream container cleanup pending")

    def close(self):
        for worker in tuple(self._workers):
            worker.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
