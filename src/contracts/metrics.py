"""Independent single-host numeric contracts; no ops ScenarioPackage dependency."""

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import AfterValidator, BeforeValidator, ConfigDict, Field, SerializeAsAny, model_validator

from .base import Contract, Hash, Identifier, RelativePath
from .metrics_requirement import AcceptanceCriteria

DATASET_VERSION = "metrics-dataset/1"
PROTOCOL = "metrics-evaluation/1"
# Includes unscored history in a role. Shared by upload and trusted execution.
MAX_UPLOAD_POINTS = 50_000
Role = Literal["train", "calibration", "development", "test"]
def _registered_method(value):
    from factory.metrics.capability_registry import validate_method
    return validate_method(value)


Method = Annotated[Identifier, AfterValidator(_registered_method)]


def _default_methods():
    from factory.metrics.capability_registry import default_methods
    return default_methods()
Origin = Literal["llm_api", "mock", "reference", "fault_injection", "historical"]


def utc_timestamp(value: object) -> datetime:
    if isinstance(value, str):
        if "T" not in value or not value.endswith(("Z", "+00:00")):
            raise ValueError("UTC ISO 8601 timestamp required")
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("timezone-aware UTC timestamp required")
    if value.utcoffset().total_seconds() != 0:
        raise ValueError("UTC timestamp required")
    return value.astimezone(timezone.utc)


Time = Annotated[datetime, BeforeValidator(utc_timestamp)]


class MetricPoint(Contract):
    timestamp: Time
    host_id: Identifier
    value: float | None


class ProcessedPoint(MetricPoint):
    original_present: bool
    imputation: Literal["none", "forward_fill", "unavailable"]
    missing_streak: int = Field(ge=0)

    @model_validator(mode="after")
    def consistent(self):
        if self.original_present:
            if self.value is None or self.imputation != "none" or self.missing_streak != 0:
                raise ValueError("original observation metadata inconsistent")
        elif self.missing_streak < 1 or self.imputation == "none":
            raise ValueError("missing observation metadata inconsistent")
        elif (self.value is None) != (self.imputation == "unavailable"):
            raise ValueError("imputed value metadata inconsistent")
        return self


class Score(Contract):
    timestamp: Time
    host_id: Identifier
    status: Literal["ok", "insufficient_history", "missing_input", "invalid_input"]
    score: float | None
    evidence: dict[str, float | str | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def consistent(self):
        if (self.status == "ok") != (self.score is not None):
            raise ValueError("score must be finite exactly when status is ok")
        return self


class RoleFile(Contract):
    path: RelativePath
    sha256: Hash
    prefix_points: int = Field(ge=0)


class MetricsDataset(Contract):
    """Trusted registry only. Never send this full manifest to a model/worker."""

    schema_version: Literal["metrics-dataset/1"] = DATASET_VERSION
    dataset_id: Identifier
    host_id: Identifier
    metric: Identifier
    unit: str = Field(min_length=1)
    metric_kind: Literal["gauge", "rate"]
    sampling_seconds: int = Field(gt=0)
    valid_range: list[float] = Field(min_length=2, max_length=2)
    roles: dict[Role, RoleFile]

    @model_validator(mode="after")
    def boundaries(self):
        if set(self.roles) != {"train", "calibration", "development", "test"}:
            raise ValueError("all four roles required")
        if self.valid_range[0] >= self.valid_range[1]:
            raise ValueError("valid_range must increase")
        paths = [entry.path for entry in self.roles.values()]
        if len(set(paths)) != 4:
            raise ValueError("role files must be distinct")
        return self


class DetectorConfig(Contract):
    """Configuration validated by the explicitly installed capability registry."""
    model_config = ConfigDict(extra="allow", strict=True, frozen=True, allow_inf_nan=False)
    method_id: Method

    @model_validator(mode="after")
    def plugin_parameters(self):
        from factory.metrics.capability_registry import registry
        from jsonschema import ValidationError
        raw = self.model_dump()
        raw.pop("method_id")
        try:
            values = registry().validate_config(self.method_id, raw)
        except ValidationError as error:
            raise ValueError("invalid capability configuration: " + error.message) from None
        for key, value in values.items():
            if key in type(self).model_fields:
                object.__setattr__(self, key, value)
            else:
                self.__pydantic_extra__[key] = value
        return self


# Compatibility names only; frozen reports retain their original parameter schema.
def __getattr__(name):
    if name in {'FixedConfig', 'MADConfig'}:
        from importlib import import_module
        return getattr(import_module('.legacy_metrics', __package__), name)
    raise AttributeError(name)


class MetricsBudgets(Contract):
    model_calls: int = Field(default=16, ge=0, le=16)
    repair_rounds: int = Field(default=2, ge=0, le=2)
    candidates: int = Field(default=2, ge=1, le=16)
    wall_seconds: int = Field(default=900, gt=0, le=900)


class MetricsRequest(Contract):
    """The structured target is authoritative; planning must preserve it."""
    schema_version: Literal["metrics-request/1"] = "metrics-request/1"
    requirement: str = Field(min_length=1, max_length=16000)
    anomaly_target: Literal["upper", "lower", "two_sided"]
    explicit_constraints: dict[str, str | float]
    ranking_preferences: list[str] = Field(default_factory=list)
    allowed_methods: list[Method] = Field(default_factory=_default_methods)
    budgets: MetricsBudgets = Field(default_factory=MetricsBudgets)
    expected_metric: Identifier | None = None
    selection_policy: Literal["balanced", "precision", "recall"] = "balanced"
    evaluation_objective: Literal["event_detection", "sustained_coverage"] = "event_detection"
    acceptance_criteria: AcceptanceCriteria = Field(default_factory=AcceptanceCriteria)
    requirement_draft: dict | None = None


class MetricsTask(Contract):
    schema_version: Literal["metrics-task/1"] = "metrics-task/1"
    task_id: Identifier
    requirement: str = Field(min_length=1, max_length=16000)
    dataset_id: Identifier
    metric: Identifier
    anomaly_target: str = Field(min_length=1)
    explicit_constraints: dict[str, str | float]
    ranking_preferences: list[str]
    allowed_methods: list[Method]
    knowledge_snapshot: Hash
    validation_protocol: Literal["metrics-evaluation/1"] = PROTOCOL
    budgets: MetricsBudgets = Field(default_factory=MetricsBudgets)
    model_mode: Literal["api", "mock"]
    model_profile_id: Identifier
    selection_policy: Literal["balanced", "precision", "recall"] = "balanced"
    evaluation_objective: Literal["event_detection", "sustained_coverage"] = "event_detection"
    acceptance_criteria: AcceptanceCriteria = Field(default_factory=AcceptanceCriteria)
    requirement_draft: dict | None = None

    @model_validator(mode="after")
    def supported(self):
        if not self.requirement.strip() or not self.allowed_methods:
            raise ValueError("nonempty requirement and methods required")
        if len(set(self.allowed_methods)) != len(self.allowed_methods):
            raise ValueError("duplicate method")
        return self


class CandidatePlan(Contract):
    candidate_id: Identifier
    config: SerializeAsAny[DetectorConfig]
    persistence_points: int = Field(default=2, ge=1, le=3)
    parameter_sources: dict[str, str]
    knowledge_ids: list[Identifier]
    limitations: list[str]
    capability_id: Identifier | None = None
    selection_reason: str = ""


class EvaluationPolicy(Contract):
    protocol: Literal["metrics-evaluation/1"] = PROTOCOL
    minimum_coverage: float = Field(default=0.95, ge=0, le=1)
    persistence_points: int = Field(default=2, ge=1, le=3)
    forward_fill_limit: Literal[3] = 3


class Event(Contract):
    event_id: Identifier
    host_id: Identifier
    metric: Identifier
    start_at: Time
    end_at: Time
    trigger_at: Time

    @model_validator(mode="after")
    def half_open(self):
        if not self.start_at <= self.trigger_at < self.end_at:
            raise ValueError("event must contain trigger in nonempty half-open interval")
        return self
