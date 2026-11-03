"""Small independent capability probes and strict structured-text parsing."""

from dataclasses import dataclass
from typing import Literal, TypeVar

from pydantic import BaseModel, ValidationError

from contracts import ErrorCode, FactoryError
from contracts.base import strict_json_loads
from contracts.ports import ModelRequest

from .transport import ModelCallError
from .transport import _finite_json

T = TypeVar("T", bound=BaseModel)


def _schema_path(location, schema):
    """Retain nested locations, but never echo model-supplied mapping keys."""
    root, candidates, path = schema, [schema], ""
    for part in location:
        expanded = []
        pending = list(candidates)
        while pending:
            node = pending.pop()
            if "$ref" in node:
                reference = node["$ref"]
                if reference.startswith("#/$defs/"):
                    pending.append(root["$defs"][reference.removeprefix("#/$defs/")])
            elif "anyOf" in node or "oneOf" in node:
                pending.extend(node.get("anyOf", node.get("oneOf", [])))
            else:
                expanded.append(node)
        if type(part) is int and 0 <= part <= 1000000:
            candidates = [node["items"] for node in expanded if "items" in node]
            suffix = f"[{part}]"
        elif isinstance(part, str):
            candidates = [node["properties"][part] for node in expanded if part in node.get("properties", {})]
            suffix = ("." if path else "") + part
        else:
            break
        if not candidates:
            break
        path += suffix
    return path or "$"


def validate_structured(text: str, model: type[T]) -> T:
    """Parse exactly one JSON document without coercing or repairing its text.

    The caller supplies a strict Pydantic schema. Duplicate keys, Markdown fences,
    non-JSON numbers, trailing text and schema failures are rejected. Error details
    never include the raw model output or Pydantic input values.
    """
    issues = [{"field": "$", "type": "json_invalid"}]
    try:
        value = strict_json_loads(text)
        if not _finite_json(value):
            raise ValueError("nonfinite JSON value")
        return model.model_validate(value, strict=True)
    except ValidationError as error:
        shape = []
        if isinstance(value, dict) and value.get("type") == "object" and "properties" in value:
            shape = [{"field": "$", "type": "schema_instead_of_instance"}]
        elif (
            isinstance(value, dict)
            and len(value) == 1
            and next(iter(value)) in {"plan", "result", "data", "output"}
        ):
            shape = [{"field": "$", "type": "unexpected_wrapper"}]
        issues = (
            shape
            + [
                {
                    "field": str(item["loc"][0])
                    if item["loc"] and item["loc"][0] in model.model_fields
                    else "$",
                    "path": _schema_path(item["loc"], model.model_json_schema()),
                    "type": item["type"],
                }
                for item in error.errors(
                    include_input=False, include_context=False, include_url=False
                )
            ]
        )[:12]
    except (ValueError, TypeError, RecursionError):
        pass
    # Raise after leaving the validation handler, so the exception chain does
    # not retain Pydantic input values or JSONDecodeError.doc.
    raise ModelCallError(
        ErrorCode.MODEL_OUTPUT_INVALID, "structured_output_invalid", validation_issues=issues
    ) from None


@dataclass(frozen=True)
class CapabilityCheck:
    capability: Literal["generation", "embedding"]
    profile_id: str
    status: Literal["passed", "failed"]
    error_code: str | None = None
    response_ref: str | None = None
    reason: str | None = None
    http_status: int | None = None


def _failed(capability, profile_id, error):
    return CapabilityCheck(
        capability,
        profile_id,
        "failed",
        error.code.value,
        reason=error.reason if isinstance(error, ModelCallError) else None,
        http_status=error.http_status if isinstance(error, ModelCallError) else None,
    )


async def check_generation(
    client, task_id: str, call_id: str, *, timeout_seconds: float = 10.0
) -> CapabilityCheck:
    """Verify one short non-streaming text call, charging its normal task budget."""
    profile_id = client.profile.profile_id
    try:
        response = await client.generate(
            ModelRequest(
                task_id=task_id,
                call_id=call_id,
                profile_id=profile_id,
                messages=[{"role": "user", "content": "Reply with a short greeting."}],
                timeout_seconds=timeout_seconds,
            )
        )
        if not response.text.strip():
            raise ModelCallError(ErrorCode.MODEL_OUTPUT_INVALID, "empty_generation_text")
    except FactoryError as exc:
        return _failed("generation", profile_id, exc)
    return CapabilityCheck("generation", profile_id, "passed", response_ref=response.response_ref)


async def check_embedding(client, task_id: str, call_id: str) -> CapabilityCheck:
    """Verify embedding independently; vector shape and values are client checks."""
    profile_id = client.profile.profile_id
    try:
        await client.embed(task_id, call_id, ["A small imaginary blue kite."], profile_id)
    except FactoryError as exc:
        return _failed("embedding", profile_id, exc)
    return CapabilityCheck("embedding", profile_id, "passed")
