"""Evidence-linked extraction and model outputs, never business-validation claims."""

from typing import Literal

from pydantic import Field, model_validator

from contracts.base import Contract, Identifier
from contracts.metrics import CandidatePlan


class Citation(Contract):
    chunk_id: Identifier
    quote: str = Field(min_length=1, max_length=2000)
    symbol: str | None


class ExtractedCapability(Contract):
    local_id: Identifier
    name: str = Field(min_length=1)
    method_id: Identifier | None = Field(description=(
        "Algorithm identifier, e.g. fixed_threshold, rolling_mad or ewma; null for general material. "
        "Never put a runtime/dependency profile such as metrics-py312-stdlib/1 here."
    ))
    summary: str = Field(min_length=1)
    metric_kinds: list[Literal["gauge", "rate"]] = Field(min_length=1)
    single_host: bool
    min_history: int | None = Field(ge=0, le=600)
    dependency_profile: str = Field(description="Runtime/dependency profile, e.g. metrics-py312-stdlib/1; not an algorithm identifier.")
    conditions_status: Literal["evidenced", "unknown", "conflict"]
    constraints: list[str]
    limitations: list[str]
    citations: list[Citation] = Field(min_length=1)

    version: str | None = None
    task_type: str | None = None
    inputs: dict | None = None
    outputs: dict | None = None
    parameters: dict | None = None
    defaults: dict | None = None
    algorithm_spec: str | None = Field(default=None, description=(
        "Use only with a complete source-evidenced specification: version, task_type, inputs, outputs, "
        "parameters, evaluation_metrics, supported_directions and field_evidence for all eight fields. "
        "If the material lacks any required field, set all specification extensions to null and retain "
        "the supported facts in summary, constraints, limitations and citations. Do not invent missing metadata."
    ))
    evaluation_metrics: list[str] | None = None
    supported_directions: list[str] | None = None
    verification_level: str | None = None
    field_evidence: dict[str, Citation] | None = None


class Extraction(Contract):
    capabilities: list[ExtractedCapability] = Field(min_length=1, max_length=8)


class PlanningOutput(Contract):
    supported: bool
    understanding: str
    anomaly_target: Literal["upper", "lower", "two_sided"] = Field(
        description="Must equal the trusted task anomaly_target; all candidate directions must match."
    )
    limitations: list[str]
    candidates: list[CandidatePlan] = Field(max_length=16)

    @model_validator(mode="after")
    def count(self):
        if self.supported and not 1 <= len(self.candidates) <= 16:
            raise ValueError("supported task must produce one to sixteen candidates")
        if not self.supported and self.candidates:
            raise ValueError("unsupported task cannot produce candidates")
        return self


class GeneratedCode(Contract):
    source: str = Field(min_length=1, max_length=262144)
    knowledge_ids: list[Identifier]
    explanation: str
    capability_id: str | None = None
    capability_version: str | None = None
    specification_sha256: str | None = None
    plugin_hashes: dict[str, str] = Field(default_factory=dict)


class DataContract(Contract):
    name: str
    definition: dict
    citations: list[Citation] = Field(min_length=1)
    origin: str


class Metric(DataContract):
    pass


class Environment(DataContract):
    pass
