"""Whitelisted model context and immutable user constraints."""

from statistics import mean

from factory.metrics.capability_registry import registry, card_for
from contracts.metrics_knowledge import PlanningOutput

def allowed_constraints():
    return {"persistence_points"} | {key for card in registry().cards.values()
                                     for key in card.config_schema["properties"]}


def validate_detection_target(task):
    """Validate detection requests without a model, including absent direction.

    MetricsTask also serves ingestion/check-only jobs. This boundary is called
    only for detection planning, never for those non-detection task purposes.
    """
    target = task.anomaly_target
    if target not in {"upper", "lower", "two_sided"}:
        raise ValueError("NEEDS_INPUT: unsupported detection anomaly_target: " + target)
    if "direction" in task.explicit_constraints and task.explicit_constraints["direction"] != target:
        raise ValueError(
            f"NEEDS_INPUT: anomaly_target={target} conflicts with explicit_constraints.direction="
            f"{task.explicit_constraints['direction']}; resolve the request instead of overriding it"
        )
    for method in task.allowed_methods:
        card = registry().get(method)
        if card.task_type != "time_series_anomaly_detection":
            raise ValueError("NEEDS_INPUT: capability task type is incompatible")
        if target not in card.supported_directions:
            raise ValueError("NEEDS_INPUT: " + method + " supports " + "/".join(card.supported_directions) + " only; unsupported " + target)


def public_context(task, manifest, train, retrieval):
    values = [p.value for p in train if p.value is not None]
    # Never serialize task/dataset registries wholesale. No test paths, labels,
    # injection parameters or seeds enter this allowlisted model view.
    cards = retrieval.get('capabilities', [])
    available = ([{'method_id': c['method_id'], 'defaults': c['defaults'], 'config_schema': c['parameters'],
                   'supported_directions': c['supported_directions'], 'assumptions': c['constraints']} for c in cards]
                 if retrieval.get('schema_version') == 'metrics-knowledge/2' else
                 [{'method_id': m, **{k: getattr(registry().get(m), k) for k in
                      ('defaults', 'config_schema', 'supported_directions', 'assumptions')}} for m in task.allowed_methods])
    return {"requirement": task.requirement, "metric": task.metric, "unit": manifest.unit,
            "metric_kind": manifest.metric_kind, "sampling_seconds": manifest.sampling_seconds,
            "valid_range": manifest.valid_range, "anomaly_target": task.anomaly_target,
            "explicit_constraints": task.explicit_constraints, "allowed_methods": task.allowed_methods,
            "knowledge_schema": retrieval.get("schema_version", "metrics-knowledge/1"),
            "available_methods": available,
            "train_summary": {"count": len(train), "valid_count": len(values), "missing_count": len(train) - len(values),
                              "minimum": min(values) if values else None, "maximum": max(values) if values else None,
                              "mean": mean(values) if values else None},
            "knowledge": {**{key: retrieval[key] for key in ("knowledge_ids", "chunks", "experiences")},
                          "capabilities": retrieval.get("capabilities", [])}}


def validate_plan(output, task, retrieval):
    validate_detection_target(task)
    if not output.supported:
        raise ValueError("NEEDS_INPUT: " + "; ".join(output.limitations))
    if output.anomaly_target != task.anomaly_target:
        raise ValueError(f"planning anomaly_target mismatch: expected {task.anomaly_target}, got {output.anomaly_target}")
    if len(output.candidates) > task.budgets.candidates:
        raise ValueError("candidate budget exceeded")
    if len({c.candidate_id for c in output.candidates}) != len(output.candidates):
        raise ValueError("duplicate candidate IDs")
    methods = {c.config.method_id for c in output.candidates}
    if not methods <= set(task.allowed_methods):
        raise ValueError("candidate method not permitted by task")
    allowed_ids = set(retrieval["knowledge_ids"])
    normalized = []
    for candidate in output.candidates:
        unknown = set(candidate.knowledge_ids) - allowed_ids
        bad_sources = {k:v for k,v in candidate.parameter_sources.items() if v.startswith('knowledge:') and v[10:] not in allowed_ids}
        if unknown or bad_sources:
            candidate = candidate.model_copy(update={
                'knowledge_ids':[k for k in candidate.knowledge_ids if k in allowed_ids],
                'parameter_sources':{k:('user_explicit' if k in task.explicit_constraints else 'candidate_assumption')
                    if k in bad_sources else v for k,v in candidate.parameter_sources.items()},
                'limitations':candidate.limitations + ['演示纠正：已移除未提供的知识引用，相关参数不再标记为知识依据。']})
        cards = [c for c in retrieval.get('capabilities', []) if c['method_id'] == candidate.config.method_id]
        if retrieval.get('schema_version') == 'metrics-knowledge/2' and not retrieval.get('knowledge_off'):
            chosen = next((c for c in cards if c['id'] == candidate.capability_id), None)
            if chosen is None:
                raise ValueError('NEEDS_KNOWLEDGE: plan must reference a supplied capability specification')
            if not candidate.selection_reason:
                raise ValueError('candidate selection reason required')
            if chosen['id'] not in candidate.knowledge_ids:
                raise ValueError('capability must be cited by plan')
        normalized.append(candidate)
        if candidate.config.direction != task.anomaly_target:
            raise ValueError(
                f"candidate {candidate.candidate_id} direction mismatch: expected {task.anomaly_target}, got {candidate.config.direction}"
            )
        for key, value in task.explicit_constraints.items():
            actual = candidate.persistence_points if key == "persistence_points" else getattr(candidate.config, key, None)
            if key != "persistence_points" and key not in card_for(candidate.config).config_schema["properties"]:
                continue
            if actual != value:
                raise ValueError("model changed explicit constraint: " + key)
        if "threshold" in task.explicit_constraints and "threshold" in card_for(candidate.config).config_schema["properties"]:
            if candidate.parameter_sources.get("threshold") != "user_explicit":
                raise ValueError("explicit threshold source must be user_explicit")
        for source in candidate.parameter_sources.values():
            if source not in {"user_explicit", "protocol_default", "candidate_assumption"} and not (
                source.startswith("knowledge:") and source[10:] in allowed_ids
            ):
                raise ValueError("invalid parameter provenance")
    return output.model_copy(update={'candidates': normalized})


async def plan(gateway, task, context, retrieval):
    if retrieval.get('status') == 'NO_RELEVANT_CAPABILITY':
        raise ValueError('NEEDS_INPUT: NO_RELEVANT_CAPABILITY: requirement is outside retrieved capability scope')
    validate_detection_target(task)
    if set(task.explicit_constraints) - allowed_constraints():
        raise ValueError("NEEDS_INPUT: unsupported explicit constraint; business gates are not implemented")
    if task.ranking_preferences and task.ranking_preferences != ["event_f1", "coverage", "false_alarm_rate"]:
        raise ValueError("NEEDS_INPUT: only the documented default ranking is supported")
    if context.get('knowledge_schema') == 'metrics-knowledge/2' and not context.get('knowledge_off'):
        if not any(c.get('algorithm_spec') for c in context.get('knowledge', {}).get('capabilities', [])):
            raise ValueError('NEEDS_KNOWLEDGE: no frozen generative capability')
        fields = {'persistence_points'} | {key for c in context['knowledge']['capabilities']
            if c['method_id'] in task.allowed_methods for key in c['parameters']['properties']}
        if set(task.explicit_constraints) - fields:
            raise ValueError('NEEDS_INPUT: explicit parameter is not supported by selected capabilities')

    context = {**context, 'candidate_budget': task.budgets.candidates}
    instructions = ("理解需求，从已提供Capability选择1到candidate_budget个候选；可比较同一能力的多个配置，不得添加未请求方法。"
             "每个候选必须填写capability_id、knowledge_ids、selection_reason；结合需求解释适配性及assumptions。"
             "演示模式以结构化任务范围为准：原文中的额外未接入能力列入limitations，先输出支持范围内的检测方案。"
             "不支持则 supported=false，candidates=[] 并说明限制。明确用户值不可覆盖。"
             "结构化任务anomaly_target是可信目标；输出anomaly_target及每个候选direction必须与它完全一致，不能改成其他方向。"
             "parameter_sources 的值仅允许 user_explicit、protocol_default、candidate_assumption 或 knowledge:<给定ID>。"
             "没有业务阈值依据时固定阈值只能标 candidate_assumption，不能宣称业务阈值。"
             "方法参数从available_methods的defaults读取；persistence_points=2。"
             "knowledge_ids 仅引用本次 input.knowledge.knowledge_ids，不能引用源文件名。")
    output = await gateway.ask(task.task_id, "plan", PlanningOutput, context, instructions)
    try:
        return validate_plan(output, task, retrieval)
    except ValueError as error:
        # One bounded correction, with the same frozen inputs and explicit values.
        corrected = await gateway.ask(task.task_id, "plan-correction-1", PlanningOutput,
            {**context, 'previous_plan':output.model_dump(mode='json'), 'validation_feedback':str(error)},
            instructions + '修正上述计划字段差异；不得改变用户明确数值和结构化检测目标。')
        return validate_plan(corrected, task, retrieval)
