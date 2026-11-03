"""Numeric ledger adapter reusing budget, operation and artifact primitives.

The independent database has a distinct application ID and schema version.
It never migrates an ops database or fabricates an ops ScenarioPackage.
"""

from contracts import ErrorCode, FactoryError
from contracts.base import strict_json_loads
from contracts.metrics import MetricsTask
from factory.runtime.artifacts import digest
from factory.runtime.store import RuntimeStore

APPLICATION_ID = 0x4D455452

SCHEMA = (
    """CREATE TABLE tasks (
        task_id TEXT PRIMARY KEY, spec TEXT NOT NULL, spec_hash TEXT NOT NULL,
        started_at REAL NOT NULL, deadline REAL NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
        report_ref TEXT, lifecycle_version TEXT NOT NULL CHECK(lifecycle_version='metrics-task/1'),
        job_kind TEXT NOT NULL CHECK(job_kind='metrics_factory'), run_context TEXT NOT NULL,
        phase TEXT NOT NULL DEFAULT 'CREATED')""",
    """CREATE TABLE operations (
        operation_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id), resource TEXT NOT NULL,
        input_hash TEXT NOT NULL, reserved_at REAL NOT NULL, deadline REAL NOT NULL, status TEXT NOT NULL,
        result_ref TEXT, attempt INTEGER NOT NULL DEFAULT 1, metadata TEXT NOT NULL DEFAULT '{}',
        source_task_id TEXT, spec_hash TEXT, CHECK(source_task_id IS NULL AND spec_hash IS NULL))""",
    "CREATE INDEX operations_task_resource ON operations(task_id,resource)",
    "CREATE TABLE artifacts (reference TEXT PRIMARY KEY, size_bytes INTEGER NOT NULL CHECK(size_bytes>=0))",
    "CREATE TABLE task_artifacts (task_id TEXT REFERENCES tasks(task_id), reference TEXT REFERENCES artifacts(reference), role TEXT NOT NULL, PRIMARY KEY(task_id,reference,role))",
    "CREATE TABLE phase_history (task_id TEXT REFERENCES tasks(task_id), ordinal INTEGER, phase TEXT NOT NULL, evidence_ref TEXT NOT NULL, PRIMARY KEY(task_id,ordinal))",
)

PHASES = {
    "CREATED": {"DATA_READY"}, "DATA_READY": {"KNOWLEDGE_READY"},
    "KNOWLEDGE_READY": {"PLANNED"}, "PLANNED": {"VALIDATING"},
    "VALIDATING": {"SELECTED"}, "SELECTED": {"FINAL_EVALUATED"},
    "FINAL_EVALUATED": {"COMPLETED"}, "COMPLETED": set(),
    "FAILED": set(), "BUDGET_EXHAUSTED": set(), "NEEDS_INPUT": set(),
}


class MetricsStore(RuntimeStore):
    def __init__(self, *args, campaign=None, **kwargs):
        self.campaign = campaign
        super().__init__(*args, **kwargs)

    def _call_key(self, operation_id):
        return digest((str(self.path.resolve()) + ":" + operation_id).encode())

    def _migrate(self):
        with self._transaction() as db:
            app_id = db.execute("PRAGMA application_id").fetchone()[0]
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if tables and app_id != APPLICATION_ID:
                raise ValueError("refuse non-metrics database; use a new independent state")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if tables and version != 101:
                raise ValueError("unsupported metrics schema version")
            if not tables:
                for statement in SCHEMA:
                    db.execute(statement)
                db.execute(f"PRAGMA application_id={APPLICATION_ID}")
                db.execute("PRAGMA user_version=101")

    def create_task(self, spec: MetricsTask) -> dict:
        if not isinstance(spec, MetricsTask):
            raise TypeError("MetricsTask required; ops tasks are not supported")
        raw = self._json(spec.model_dump(mode="json"))
        reference = digest(raw.encode())
        context = spec.model_dump(mode="json")
        # The persisted spec retains the per-candidate repair cap; inherited
        # reservation logic additionally enforces this aggregate upper bound.
        context["budgets"]["repair_rounds"] *= context["budgets"]["candidates"]
        with self._transaction() as db:
            old = db.execute("SELECT * FROM tasks WHERE task_id=?", (spec.task_id,)).fetchone()
            if old:
                if old["spec_hash"] != reference:
                    raise FactoryError(ErrorCode.INPUT_CONFLICT, "metrics task ID is immutable")
                return dict(old)
            now = self.clock()
            db.execute("""INSERT INTO tasks(task_id,spec,spec_hash,started_at,deadline,lifecycle_version,job_kind,run_context)
                          VALUES (?,?,?,?,?,'metrics-task/1','metrics_factory',?)""",
                       (spec.task_id, raw, reference, now, now + spec.budgets.wall_seconds, self._json(context)))
            return dict(self._required(db, spec.task_id))

    def model_context(self, task_id):
        row = self.task(task_id)
        if row["phase"] in {"SELECTED", "FINAL_EVALUATED", "COMPLETED", "FAILED", "BUDGET_EXHAUSTED", "NEEDS_INPUT"}:
            raise FactoryError(ErrorCode.INVALID_INPUT, "model calls forbidden after selection or terminal state")
        spec = MetricsTask.model_validate(strict_json_loads(row["spec"]))
        if digest(self._json(spec.model_dump(mode="json")).encode()) != row["spec_hash"]:
            raise FactoryError(ErrorCode.DATA_HASH_MISMATCH, "metrics spec digest mismatch")
        return {**spec.model_dump(mode="json"), "binding_hash": row["spec_hash"]}

    def _source_binding(self, db, task, source_task_id=None, spec_hash=None):
        if source_task_id is not None or spec_hash is not None:
            raise ValueError("metrics evidence binds the immutable task through its operation hash")
        return None, None

    def reserve(self, task_id, resource, *args, **kwargs):
        if resource in {"model", "repair"}:
            self.model_context(task_id)
        row = super().reserve(task_id, resource, *args, **kwargs)
        if resource == "model" and self.campaign and row["is_new"]:
            try:
                self.campaign.reserve(self._call_key(row["operation_id"]), row["input_hash"])
            except FactoryError:
                super().mark_operation(row["operation_id"], "FAILED")
                raise
        return row

    def mark_operation(self, operation_id, status, result_ref=None):
        super().mark_operation(operation_id, status, result_ref)
        if self.campaign and self.operation(operation_id)["resource"] == "model":
            self.campaign.mark(self._call_key(operation_id), status)

    def phase(self, task_id, phase: str, evidence: dict):
        reference = self.register_document(task_id, evidence, "phase-" + phase)
        with self._transaction() as db:
            row = self._required(db, task_id)
            current = row["phase"]
            if current == phase:
                old = db.execute("SELECT evidence_ref FROM phase_history WHERE task_id=? ORDER BY ordinal DESC LIMIT 1", (task_id,)).fetchone()
                if old and old[0] == reference:
                    return reference
                raise FactoryError(ErrorCode.INPUT_CONFLICT, "phase evidence is immutable")
            if phase not in PHASES.get(current, set()) and not (
                PHASES.get(current) and phase in {"FAILED", "BUDGET_EXHAUSTED", "NEEDS_INPUT"}
            ):
                raise ValueError("illegal metrics phase transition")
            ordinal = db.execute("SELECT COUNT(*) FROM phase_history WHERE task_id=?", (task_id,)).fetchone()[0]
            db.execute("INSERT INTO phase_history VALUES (?,?,?,?)", (task_id, ordinal, phase, reference))
            status = "SUCCEEDED" if phase == "COMPLETED" else "FAILED" if phase in {"FAILED", "BUDGET_EXHAUSTED", "NEEDS_INPUT"} else "RUNNING"
            db.execute("UPDATE tasks SET phase=?,status=? WHERE task_id=?", (phase, status, task_id))
        return reference
