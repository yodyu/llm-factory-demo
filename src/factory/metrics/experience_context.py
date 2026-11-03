"""Bounded development feedback and candidate-specific experience ordering."""

from copy import deepcopy
import json

# Only contract-check structure and point outputs may enter reusable feedback.
# In particular no final/test payloads, labels, effect metrics, or arbitrary context.
FEEDBACK_FIELDS = frozenset({
    "check", "passed", "point_index", "development_input", "difference", "allowed_changes",
    "code", "line", "message", "expected", "actual", "issues", "field", "fields", "type",
    "expected_schema", "title", "properties", "required", "additionalProperties",
    "anyOf", "enum", "$defs", "$ref", "description", "items", "default",
    "timestamp", "host_id", "value", "status", "score", "evidence", "original_present",
    "imputation", "missing_streak", "property", "points", "layer",
})


def development_feedback(value, depth=0):
    """Bound and project old payloads too; never copy a whole validation or run."""
    if depth > 12:
        return None
    if isinstance(value, dict):
        return {key: development_feedback(item, depth + 1)
                for key, item in value.items() if key in FEEDBACK_FIELDS}
    if isinstance(value, list):
        return [development_feedback(item, depth + 1) for item in value[:32]]
    if value is None or type(value) in (str, bool, int, float):
        return value
    return None


def prioritize_experiences(experiences, methods):
    """Same method first, then actionable check feedback; IDs never decide priority."""
    order = {method: index for index, method in enumerate(dict.fromkeys(methods))}

    def key(item):
        semantic = {k: v for k, v in item.items()
                    if k not in {"id", "implementation_id", "validation_id"}}
        return (order.get(item.get("method_id"), len(order)),
                not bool(item.get("development_feedback")),
                not bool(item.get("implementation_verified")),
                json.dumps(semantic, ensure_ascii=False, sort_keys=True))

    return sorted(experiences, key=key)


def candidate_context(context, method):
    """Keep the frozen shared view intact while adapting ordering to this candidate."""
    result = deepcopy(context)
    knowledge = result.get("knowledge", {})
    knowledge["experiences"] = prioritize_experiences(knowledge.get("experiences", []), [method])
    return result
