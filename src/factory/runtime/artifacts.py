"""Immutable content-addressed files. A trusted directory is required."""

import hashlib
import os
import re
import tempfile
from pathlib import Path


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class ArtifactStore:
    def __init__(self, root: Path):
        root = Path(root)
        if root.is_symlink():
            raise ValueError("artifact root must not be a symlink")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = root.resolve()

    def _path(self, reference: str) -> Path:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", reference):
            raise ValueError("invalid artifact reference")
        return self.root / reference.removeprefix("sha256:")

    def put(self, data: bytes) -> str:
        reference = digest(data)
        target = self._path(reference)
        fd, name = tempfile.mkstemp(prefix=".pending-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(name, target)  # Atomic publication without overwriting an existing file.
            except FileExistsError:
                if self.read(reference) != data:
                    raise ValueError("artifact hash collision or corrupt existing content")
            directory = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(name).unlink(missing_ok=True)
        return reference

    def read(self, reference: str) -> bytes:
        path = self._path(reference)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            import stat

            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("artifact must be a regular file")
            data = stream.read()
        if digest(data) != reference:
            raise ValueError("artifact content hash mismatch")
        return data
