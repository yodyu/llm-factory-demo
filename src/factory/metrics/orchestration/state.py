"""Reference-only graph channels and per-invocation dependencies."""

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TypedDict
import time

from contracts.metrics import MetricsDataset, MetricsRequest, MetricsTask


class TaskInput(TypedDict):
    graph_version: str
    registered: bool
    error: dict | None


class TaskOutput(TypedDict, total=False):
    report_ref: str
    publication_ref: str
    export_result: dict
    error: dict | None


class TaskState(TypedDict, total=False):
    graph_version: str
    registered: bool
    task_id: str
    request_ref: str
    manifest_ref: str
    task_ref: str
    snapshot_ref: str
    retrieval_ref: str
    public_context_ref: str
    report_ref: str
    plan_ref: str
    candidate_order: list[str]
    candidate_cursor: int
    current_candidate_id: str | None
    candidate_result_refs: dict[str, str]
    candidate_output: dict
    selection_ref: str
    final_ref: str
    data_mode: str
    error: dict | None
    error_status: str
    cleanup_result: dict
    publication_ref: str
    export_result: dict


class CandidateInput(TypedDict):
    candidate_id: str
    plan_ref: str
    public_context_ref: str


class CandidateOutput(TypedDict, total=False):
    record_ref: str
    error: dict | None
    fatal: bool


class CandidateState(TypedDict, total=False):
    candidate_id: str
    plan_ref: str
    public_context_ref: str
    record_ref: str
    version: int
    source_ref: str
    generated_ref: str
    validation_ref: str
    repair_op: str | None
    error: dict | None
    fatal: bool


@dataclass
class RunContext:
    """Never serialized or streamed; each graph invocation owns a separate instance."""

    store: Any
    gateway: Any
    knowledge: Any
    state: Path
    dataset_root: Path
    task_input: dict
    image: str
    snapshot: dict | None = None
    frozen_retrieval: dict | None = None
    retrieval_mode: str = "structured"
    requested_task_id: str | None = None
    fault_injection: bool = False
    export_delivery: bool = False
    generate: Callable | None = None
    plan: Callable | None = None
    final_evaluate: Callable | None = None
    load_role: Callable | None = None
    runner_factory: Callable | None = None
    started: float = field(default_factory=time.monotonic)
    request: MetricsRequest | None = None
    manifest: MetricsDataset | None = None
    manifest_raw: bytes = b""
    task: MetricsTask | None = None
    upload: dict | None = None
    legacy_upload: bool = False
    directory: Path | None = None
    runner: Any = None
    report: dict = field(default_factory=dict)
    active_candidate: dict | None = None
    events: list[dict] = field(default_factory=list)
    cleaned: bool = False
    cancelled: bool = False
    report_frozen: bool = False
    sealed_report: dict | None = None
    sealed_evidence: dict | None = None
    publication: dict | None = None
    export_result: dict | None = None

    @property
    def registered(self):
        return self.task is not None and bool(self.report)

    def document(self, value, role):
        return self.store.register_document(self.task.task_id, value, role)

    def load_report(self, state):
        if state.get("report_ref"):
            self.report = deepcopy(self.store.document(state["report_ref"]))

    def save_progress(self):
        return self.document(self.report, "graph-progress")

    def candidate_directory(self, candidate_id):
        from factory.metrics.knowledge import identity
        return self.directory / identity("candidate", candidate_id)
