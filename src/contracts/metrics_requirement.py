"""Evidence-bearing language input. Drafts are separate from frozen run specs."""

from typing import Literal

from pydantic import Field, model_validator

from contracts.base import Contract

RequirementKey = str
SEMANTIC_KEYS = {'scenario', 'data_source', 'direction', 'persistence_points', 'duration_seconds',
                 'methods', 'selection_policy', 'max_false_alarms_per_hour', 'min_event_recall',
                 'min_event_f1', 'label_source', 'evaluation_objective'}


def allowed_requirement_keys():
    from factory.metrics.capability_registry import registry
    return SEMANTIC_KEYS | {key for card in registry().cards.values()
                           for key in card.config_schema['properties']}


def requirement_key_schema(schema):
    # Resolve at schema-generation time, after imports and with the current plugins.
    schema['enum'] = sorted(allowed_requirement_keys())


class RequirementClaim(Contract):
    key: RequirementKey = Field(json_schema_extra=requirement_key_schema)
    value: str | float | int | list[str]
    quote: str = Field(min_length=1, max_length=16000)

    @model_validator(mode="after")
    def value_matches_key(self):
        from factory.metrics.capability_registry import registry
        if self.key not in allowed_requirement_keys():
            raise ValueError('unregistered requirement parameter')
        enumerations = {
            "scenario": {"cpu_spike", "memory_shift", "memory_drift", "disk_peaks", "network_missing", "periodic"},
            "data_source": {"simulation", "upload"}, "direction": {"upper", "lower", "two_sided"},
            "selection_policy": {"balanced", "precision", "recall"},
            "evaluation_objective": {"event_detection", "sustained_coverage"},
        }
        if self.key in enumerations:
            if not isinstance(self.value, str) or self.value not in enumerations[self.key]:
                raise ValueError("unsupported value for " + self.key)
        elif self.key == "methods":
            if not isinstance(self.value, list) or not self.value or len(set(self.value)) != len(self.value) or not set(self.value) <= set(registry().cards):
                raise ValueError("one or two distinct supported methods required")
        elif self.key == "label_source":
            if not isinstance(self.value, str) or not 1 <= len(self.value) <= 500:
                raise ValueError("nonempty label source up to 500 characters required")
        elif type(self.value) not in (int, float):
            raise ValueError("numeric value required for " + self.key)
        return self


class RequirementExtraction(Contract):
    claims: list[RequirementClaim] = Field(default_factory=list, max_length=40)
    unsupported: list[str] = Field(default_factory=list, max_length=20)


class AcceptanceCriteria(Contract):
    max_false_alarms_per_hour: float | None = Field(default=None, ge=0)
    min_event_recall: float | None = Field(default=None, ge=0, le=1)
    min_event_f1: float | None = Field(default=None, ge=0, le=1)


class RequirementDraft(Contract):
    schema_version: Literal["metrics-requirement-draft/1"] = "metrics-requirement-draft/1"
    turns: list[str]
    binding: str
    revision: int
    values: dict[str, str | float | int | list[str]]
    evidence: dict[str, dict]
    issues: list[str]
    defaults: list[str]
    model_mode: Literal["api", "mock"]
    parse_task_id: str | None = None
    model_usage: dict = Field(default_factory=dict)
