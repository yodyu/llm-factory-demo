"""Atomic operation/evidence primitives shared by the numeric ledger.

RESERVED, SENT and UNKNOWN consume quota. Reusing an ID never authorizes resend.
The concrete MetricsStore owns task schema and lifecycle; legacy DBs are refused.
"""
import json
import math
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from contracts import ErrorCode, FactoryError
from .artifacts import ArtifactStore
from .security import SecretGuard

LIMITS = {"model": "model_calls", "repair": "repair_rounds"}
TIMEOUTS = {"model": 60, "metrics-code": 10}


class RuntimeStore:
    def __init__(
        self,
        path: Path,
        guard: SecretGuard | None = None,
        clock=time.time,
        *,
        artifacts: ArtifactStore | None = None,
    ):
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValueError("database must not be a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.guard = guard or SecretGuard()
        self.clock = clock
        self.artifact_store = artifacts or ArtifactStore(self.path.parent / "artifacts")
        self._migrate()

    @contextmanager
    def _transaction(self):
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _json(self, value: object) -> str:
        self.guard.require_public(value)
        return json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )

    @staticmethod
    def _required(db, task_id):
        row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError("unknown task")
        return row

    def task(self, task_id: str) -> dict:
        with self._transaction() as db:
            return dict(self._required(db, task_id))

    def set_task_status(self, task_id: str, status: str) -> None:
        transitions = {
            "PENDING": {"RUNNING", "FAILED"},
            "RUNNING": {"SUCCEEDED", "FAILED", "RUNNING"},
            "SUCCEEDED": {"SUCCEEDED"},
            "FAILED": {"FAILED"},
        }
        with self._transaction() as db:
            row = self._required(db, task_id)
            if status not in transitions[row["status"]]:
                raise ValueError("illegal task transition (terminal tasks cannot be restarted)")
            db.execute("UPDATE tasks SET status=? WHERE task_id=?", (status, task_id))

    def reserve(
        self,
        task_id: str,
        resource: str,
        operation_id: str,
        input_hash: str,
        *,
        timeout_seconds: float | None = None,
        remaining_required: int = 0,
        attempt: int = 1,
        source_task_id: str | None = None,
        spec_hash: str | None = None,
    ) -> dict:
        from pydantic import TypeAdapter
        from contracts.base import Hash

        TypeAdapter(Hash).validate_python(input_hash)
        if resource not in {*LIMITS, "metrics-code"} or not operation_id:
            raise ValueError("invalid operation resource or identifier")
        self.guard.require_public([task_id, operation_id])
        if type(attempt) is not int or attempt < 1:
            raise ValueError("attempt must be a positive integer")
        if (
            isinstance(remaining_required, bool)
            or not isinstance(remaining_required, int)
            or remaining_required < 0
        ):
            raise ValueError("remaining_required must be a nonnegative integer")
        cap = TIMEOUTS.get(resource, 600)
        timeout = cap if timeout_seconds is None else timeout_seconds
        if isinstance(timeout, bool) or not math.isfinite(timeout) or not 0 < timeout <= cap:
            raise ValueError("invalid operation timeout")
        with self._transaction() as db:
            task = self._required(db, task_id)
            previous = db.execute(
                "SELECT * FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if previous:
                if (
                    previous["task_id"],
                    previous["resource"],
                    previous["input_hash"],
                    previous["attempt"],
                ) != (task_id, resource, input_hash, attempt):
                    raise FactoryError(
                        ErrorCode.INPUT_CONFLICT, "operation ID reused for different input"
                    )
                if source_task_id is not None or spec_hash is not None:
                    if (previous["source_task_id"], previous["spec_hash"]) != (
                        source_task_id,
                        spec_hash,
                    ):
                        raise FactoryError(
                            ErrorCode.INPUT_CONFLICT,
                            "operation ID reused for different specification",
                        )
                return {**dict(previous), "is_new": False}
            source_task_id, spec_hash = self._source_binding(db, task, source_task_id, spec_hash)
            now = self.clock()
            if now >= task["deadline"]:
                raise FactoryError(ErrorCode.DEADLINE_EXCEEDED, "original task deadline exhausted")
            if task["status"] in ("FAILED", "SUCCEEDED"):
                raise ValueError("terminal task cannot reserve new operations")
            if resource in LIMITS:
                used = db.execute(
                    "SELECT COUNT(*) FROM operations WHERE task_id=? AND resource=?",
                    (task_id, resource),
                ).fetchone()[0]
                context = task["run_context"]
                limit = json.loads(context)["budgets"][LIMITS[resource]]
                if used + 1 + remaining_required > limit:
                    raise FactoryError(
                        ErrorCode.BUDGET_EXHAUSTED,
                        "operation budget or reserved mandatory quota exhausted",
                    )
            deadline = min(now + timeout, task["deadline"])
            db.execute(
                "INSERT INTO operations(operation_id,task_id,resource,input_hash,reserved_at,deadline,status,attempt,source_task_id,spec_hash) VALUES (?,?,?,?,?,?,'RESERVED',?,?,?)",
                (
                    operation_id,
                    task_id,
                    resource,
                    input_hash,
                    now,
                    deadline,
                    attempt,
                    source_task_id,
                    spec_hash,
                ),
            )
            return {
                **dict(
                    db.execute(
                        "SELECT * FROM operations WHERE operation_id=?", (operation_id,)
                    ).fetchone()
                ),
                "is_new": True,
            }

    def operation(self, operation_id: str) -> dict:
        with self._transaction() as db:
            row = db.execute(
                "SELECT * FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if row is None:
                raise KeyError("unknown operation")
            return dict(row)

    def mark_operation(self, operation_id: str, status: str, result_ref: str | None = None) -> None:
        allowed = {
            "RESERVED": {"SENT", "FAILED", "UNKNOWN"},
            "SENT": {"SUCCEEDED", "FAILED", "UNKNOWN"},
            "UNKNOWN": {"SUCCEEDED", "FAILED"},
            "SUCCEEDED": set(),
            "FAILED": set(),
        }
        self.guard.require_public(result_ref)
        with self._transaction() as db:
            row = db.execute(
                "SELECT * FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if row is None:
                raise KeyError("unknown operation")
            if row["status"] == status and row["result_ref"] == result_ref:
                return
            if status not in allowed[row["status"]] or (status == "SUCCEEDED" and not result_ref):
                raise ValueError("illegal operation transition or missing result reference")
            if status == "SENT" and self.clock() >= row["deadline"]:
                raise FactoryError(ErrorCode.DEADLINE_EXCEEDED, "reserved operation has expired")
            db.execute(
                "UPDATE operations SET status=?,result_ref=? WHERE operation_id=?",
                (status, result_ref, operation_id),
            )

    def recover_uncertain(self, task_id: str) -> int:
        """Only call after obtaining exclusive ownership of the interrupted task.

        The caller must first stop orphan containers. This method never resets
        counters, renews the deadline, or sends any request automatically.
        """
        with self._transaction() as db:
            self._required(db, task_id)
            return db.execute(
                "UPDATE operations SET status='UNKNOWN' WHERE task_id=? AND status IN ('RESERVED','SENT')",
                (task_id,),
            ).rowcount

    def record_operation_metadata(self, operation_id: str, metadata: dict) -> None:
        """Only transport/cost metadata; never raw prompts, responses or exceptions."""
        allowed = {
            "profile_id",
            "actual_model",
            "input_tokens",
            "output_tokens",
            "elapsed_seconds",
            "failure_code",
        }
        if set(metadata) - allowed:
            raise ValueError("unapproved operation metadata field")
        for key, value in metadata.items():
            if (
                key in ("input_tokens", "output_tokens")
                and value is not None
                and (type(value) is not int or value < 0)
            ):
                raise ValueError("usage must be a nonnegative integer or null")
            if key == "elapsed_seconds" and (
                type(value) not in (int, float) or not math.isfinite(value) or value < 0
            ):
                raise ValueError("elapsed time must be finite and nonnegative")
            if (
                key in ("profile_id", "actual_model", "failure_code")
                and value is not None
                and not isinstance(value, str)
            ):
                raise ValueError("metadata identifier must be a string or null")
        raw = self._json(metadata)
        with self._transaction() as db:
            row = db.execute(
                "SELECT metadata FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if row is None:
                raise KeyError("unknown operation")
            if row[0] not in ("{}", raw):
                raise FactoryError(ErrorCode.INPUT_CONFLICT, "operation metadata is immutable")
            db.execute("UPDATE operations SET metadata=? WHERE operation_id=?", (raw, operation_id))

    def artifact_owned(self, task_id: str, reference: str, role: str | None = None) -> bool:
        with self._transaction() as db:
            query = "SELECT 1 FROM task_artifacts WHERE task_id=? AND reference=?"
            params = [task_id, reference]
            if role is not None:
                query += " AND role=?"
                params.append(role)
            return db.execute(query, params).fetchone() is not None

    def _migrate(self):
        raise NotImplementedError("use MetricsStore for numeric task registration")

    def document(self, reference):
        from contracts.base import strict_json_loads
        return strict_json_loads(self.artifact_store.read(reference))

    def register_document(self, task_id, value, role):
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        raw = self._json(value).encode()
        reference = self.artifact_store.put(raw)
        self.attach_artifact(task_id, reference, len(raw), role)
        return reference

    def attach_artifact(self, task_id, reference, size_bytes, role):
        from pydantic import TypeAdapter
        from contracts.base import Hash
        if type(size_bytes) is not int or size_bytes < 0:
            raise ValueError("invalid artifact size")
        TypeAdapter(Hash).validate_python(reference)
        self.guard.require_public([reference, role])
        with self._transaction() as db:
            self._required(db, task_id)
            row = db.execute("SELECT size_bytes FROM artifacts WHERE reference=?", (reference,)).fetchone()
            if row and row[0] != size_bytes:
                raise ValueError("artifact size conflict")
            db.execute("INSERT OR IGNORE INTO artifacts VALUES (?,?)", (reference, size_bytes))
            db.execute("INSERT OR IGNORE INTO task_artifacts VALUES (?,?,?)", (task_id, reference, role))
