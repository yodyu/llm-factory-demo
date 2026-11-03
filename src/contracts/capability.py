"""Trusted, versioned capability plugin manifest; never generated executable code."""
from typing import Literal

from pydantic import Field, model_validator
from jsonschema import Draft202012Validator

from .base import Contract, Hash, Identifier, RelativePath


class SpecSource(Contract):
    path: RelativePath
    sha256: Hash
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def material_range(self):
        if not self.path.startswith('materials/') or self.end_line < self.start_line:
            raise ValueError('spec source requires a materials/ path and ordered line range')
        return self


class CapabilityCard(Contract):
    method_id: Identifier
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    display_name: str = Field(min_length=1)
    task_type: str = Field(min_length=1)
    inputs: dict
    outputs: dict
    config_schema: dict
    defaults: dict
    supported_directions: list[Literal["upper", "lower", "two_sided"]] = Field(min_length=1)
    metric_kinds: list[Literal["gauge", "rate"]] = Field(min_length=1)
    min_history: int = Field(ge=0)
    algorithm_spec: str = Field(min_length=1)
    spec_sources: list[SpecSource] = Field(min_length=1, max_length=32)
    evaluation_metrics: list[str] = Field(min_length=1)
    dependency_profile: str = Field(min_length=1)
    verification: Literal["reference", "property_only"]
    calibration: Literal["fixed", "quantile"] = "quantile"
    default_candidate: bool = False
    candidate_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_schemas(self):
        identities = [(source.path, source.start_line, source.end_line) for source in self.spec_sources]
        if len(set(identities)) != len(identities):
            raise ValueError('duplicate spec source range')
        for schema in (self.inputs, self.outputs, self.config_schema):
            Draft202012Validator.check_schema(schema)
            # All schemas are offline documents; remote schema resolution is forbidden.
            def visit(value):
                if isinstance(value, dict):
                    if "$ref" in value and not value["$ref"].startswith("#/"):
                        raise ValueError("external schema references forbidden")
                    for item in value.values():
                        visit(item)
                elif isinstance(value, list):
                    for item in value:
                        visit(item)
            visit(schema)
        Draft202012Validator(self.config_schema).validate(self.defaults)
        if self.defaults.get("direction") not in self.supported_directions:
            raise ValueError("default direction not supported")
        return self
