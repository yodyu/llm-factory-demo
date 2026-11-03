"""Trusted scoring from independent injection labels; no model or detector imports."""

import math
from collections.abc import Sequence
from datetime import timedelta
from statistics import median

from contracts.metrics import Event, EvaluationPolicy, MetricPoint, Score
from factory.metrics.data import validate_grid


def nearest_rank(values: Sequence[float], q: float) -> float:
    if (not values or not 0 < q <= 1
            or any(not math.isfinite(x) for x in values)):
        raise ValueError("finite values and q in (0,1] required")
    return sorted(values)[math.ceil(q * len(values)) - 1]


def calibrate(scores: Sequence[Score], *, quantile: float, prefix_points: int) -> dict:
    """No label argument exists. Only scoring-region, judgeable scores are used."""
    if not 0 <= prefix_points < len(scores):
        raise ValueError("invalid prefix length")
    values = [s.score for s in scores[prefix_points:] if s.status == "ok"]
    if len(values) < 100:
        raise ValueError(f"CALIBRATION_INSUFFICIENT_SCORES: {len(values)} < 100; need {100-len(values)} more valid calibration scores; add history or explicitly choose an uncalibrated registered method")
    return {"threshold": nearest_rank(values, quantile), "quantile": quantile,
            "score_count": len(values), "rule": "nearest-rank", "labels_used": False}


def alarms(scores: Sequence[Score], *, threshold: float, persistence_points: int) -> list[bool]:
    if not math.isfinite(threshold) or type(persistence_points) is not int or not 1 <= persistence_points <= 3:
        raise ValueError("invalid threshold or persistence")
    result, consecutive = [], 0
    for score in scores:
        consecutive = consecutive + 1 if score.status == "ok" and score.score > threshold else 0
        result.append(consecutive >= persistence_points)
    return result


def events_from_flags(points: Sequence[MetricPoint], flags: Sequence[bool], *, metric: str,
                      sampling_seconds: int, id_prefix: str) -> list[Event]:
    if len(points) != len(flags) or any(type(flag) is not bool for flag in flags):
        raise ValueError("boolean flags must align with observations")
    if not points:
        return []
    validate_grid(points, host_id=points[0].host_id, sampling_seconds=sampling_seconds)
    result, start = [], None
    for index in range(len(flags) + 1):
        active = index < len(flags) and flags[index]
        if active and start is None:
            start = index
        if not active and start is not None:
            result.append(Event(event_id=f"{id_prefix}-{len(result):04d}", host_id=points[start].host_id,
                                metric=metric, start_at=points[start].timestamp,
                                trigger_at=points[start].timestamp,
                                end_at=points[index - 1].timestamp + timedelta(seconds=sampling_seconds)))
            start = None
    return result


def _canonical(events: Sequence[Event]):
    if len({event.event_id for event in events}) != len(events):
        raise ValueError("duplicate event ID")
    groups = {}
    for event in events:
        groups.setdefault((event.host_id, event.metric), []).append(event)
    for group in groups.values():
        ordered = sorted(group, key=lambda e: (e.start_at, e.event_id))
        if any(a.end_at > b.start_at for a, b in zip(ordered, ordered[1:])):
            raise ValueError("overlapping events are not canonical")


def match_events(predicted: Sequence[Event], truth: Sequence[Event]) -> dict:
    """Canonical truth intervals are disjoint: a trigger can have only one owner.

    Choosing each owner's earliest prediction maximizes cardinality, then
    minimizes total delay; stable IDs break remaining ties. No exponential
    matching search is needed for this single-stream point-label protocol.
    """
    _canonical(predicted)
    _canonical(truth)
    pairs = []
    for target in sorted(truth, key=lambda e: e.event_id):
        eligible = [p for p in predicted
                    if (p.host_id, p.metric) == (target.host_id, target.metric)
                    and target.start_at <= p.trigger_at < target.end_at
                    and max(target.start_at, p.start_at) < min(target.end_at, p.end_at)]
        if eligible:
            winner = min(eligible, key=lambda p: (p.trigger_at, p.event_id))
            pairs.append({"truth_id": target.event_id, "prediction_id": winner.event_id,
                          "delay_seconds": (winner.trigger_at - target.start_at).total_seconds()})
    return {"tp": len(pairs), "fp": len(predicted) - len(pairs), "fn": len(truth) - len(pairs),
            "pairs": pairs,
            "unmatched_truth_ids": sorted({e.event_id for e in truth} - {p["truth_id"] for p in pairs}),
            "unmatched_prediction_ids": sorted({e.event_id for e in predicted} - {p["prediction_id"] for p in pairs})}


def _ratio(numerator: int | float, denominator: int | float, null_reason: str) -> dict:
    return {"value": numerator / denominator if denominator else None,
            "numerator": numerator, "denominator": denominator,
            "null_reason": None if denominator else null_reason}


def _classification(tp: int, fp: int, fn: int) -> dict:
    return {"precision": _ratio(tp, tp + fp, "no_predictions"),
            "recall": _ratio(tp, tp + fn, "no_true_anomalies"),
            "f1": _ratio(2 * tp, 2 * tp + fp + fn, "no_predictions_or_true_anomalies")}


def evaluate(points: Sequence[MetricPoint], scores: Sequence[Score], labels: Sequence[bool], *,
             host_id: str, metric: str, sampling_seconds: int, prefix_points: int,
             threshold: float, elapsed_seconds: float, policy: EvaluationPolicy) -> dict:
    """Call only after complete successful execution. Raises on any interface error.

    Caller owns role authorization, immutable bindings and elapsed measurement.
    Whole-execution failure must be recorded separately, never as an empty run.
    """
    validate_grid(points, host_id=host_id, sampling_seconds=sampling_seconds)
    if not (len(points) == len(scores) == len(labels)):
        raise ValueError("output/label grid length mismatch")
    if (any(type(label) is not bool for label in labels)
            or not 0 <= prefix_points < len(points) or any(labels[:prefix_points])):
        raise ValueError("invalid labels or prefix (prefix must be normal)")
    if not math.isfinite(elapsed_seconds) or elapsed_seconds < 0:
        raise ValueError("invalid measured runtime")
    for index, (point, score) in enumerate(zip(points, scores)):
        if point.timestamp != score.timestamp or point.host_id != score.host_id:
            raise ValueError(f"output[{index}]: timestamp/host mismatch")
    points, scores, labels = points[prefix_points:], scores[prefix_points:], labels[prefix_points:]
    # Only detector/preprocessor state is warmed by prefix; persistence starts here.
    predicted = alarms(scores, threshold=threshold, persistence_points=policy.persistence_points)
    judgeable = [s.status == "ok" for s in scores]
    tp = sum(label and prediction for label, prediction in zip(labels, predicted))
    fp = sum(not label and prediction for label, prediction in zip(labels, predicted))
    fn = sum(label and not prediction for label, prediction in zip(labels, predicted))
    tn = sum(not label and not prediction and ok for label, prediction, ok in zip(labels, predicted, judgeable))
    abstained_normal = sum(not label and not ok for label, ok in zip(labels, judgeable))
    truth = events_from_flags(points, labels, metric=metric, sampling_seconds=sampling_seconds, id_prefix="truth")
    events = events_from_flags(points, predicted, metric=metric, sampling_seconds=sampling_seconds, id_prefix="pred")
    matched = match_events(events, truth)
    normal_seconds = sum(not label for label in labels) * sampling_seconds
    normal_times = {point.timestamp for point, label in zip(points, labels) if not label}
    false_normal_triggers = sum(event.event_id in matched["unmatched_prediction_ids"]
                                and event.trigger_at in normal_times for event in events)
    delays = [pair["delay_seconds"] for pair in matched["pairs"]]
    coverage = _ratio(sum(judgeable), len(points), "no_scoring_points")
    return {"protocol": policy.protocol, "execution_status": "SUCCEEDED",
            "engineering_status": "PASSED" if coverage["value"] >= policy.minimum_coverage else "COVERAGE_FAILED",
            "effect_status": "MEASURED", "acceptance_status": "MEASURED_NO_ACCEPTANCE_THRESHOLD",
            "point": {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "abstained_normal": abstained_normal,
                      "total": len(points), **_classification(tp, fp, fn)},
            "event": {**matched, **_classification(matched["tp"], matched["fp"], matched["fn"])},
            "coverage": coverage,
            "normal_false_alarms_per_host_hour": _ratio(false_normal_triggers * 3600, normal_seconds, "no_normal_time"),
            "matched_delay_seconds": {"median": median(delays) if delays else None,
                                      "maximum": max(delays) if delays else None,
                                      "null_reason": None if delays else "no_matched_events",
                                      "missed_events": matched["fn"]},
            "runtime_seconds": elapsed_seconds, "peak_memory_bytes": None,
            "peak_memory_null_reason": "not_measured",
            "predicted_events": [event.model_dump(mode="json") for event in events],
            "truth_events": [event.model_dump(mode="json") for event in truth]}


def acceptance_result(report, criteria) -> dict:
    """Undefined or unmeasured quantities never satisfy a business gate."""
    fields = {"max_false_alarms_per_hour": (report.get("normal_false_alarms_per_host_hour") or {}).get("value"),
              "min_event_recall": (report.get("event", {}).get("recall") or {}).get("value"),
              "min_event_f1": (report.get("event", {}).get("f1") or {}).get("value")}
    checks = []
    for name, threshold in criteria.model_dump().items():
        if threshold is None:
            continue
        actual = fields[name] if report.get("effect_status") == "MEASURED" else None
        passed = actual is not None and (actual <= threshold if name.startswith("max_") else actual >= threshold)
        checks.append({"metric": name, "threshold": threshold, "actual": actual,
                       "status": "NOT_EVALUATED" if actual is None else "PASSED" if passed else "FAILED"})
    status = ("NOT_DEFINED" if not checks else "FAILED" if any(c["status"] == "FAILED" for c in checks)
              else "NOT_EVALUATED" if any(c["status"] == "NOT_EVALUATED" for c in checks) else "PASSED")
    return {"status": status, "checks": checks}


SELECTION_PROTOCOL = "metrics-selection/2"


def _select_development(candidates: Sequence[dict], *, policy="balanced", acceptance=None,
                        objective="event_detection", candidate_limit=16) -> dict:
    """Ranks measured development results only; never accepts final results."""
    if len(candidates) > candidate_limit or len({c["candidate_id"] for c in candidates}) != len(candidates):
        raise ValueError("distinct candidates within the declared budget required")
    if any(c["role"] != "development" for c in candidates):
        raise ValueError("selection only accepts development results")
    if policy not in {"balanced", "precision", "recall"}:
        raise ValueError("unsupported selection policy")
    if objective not in {"event_detection", "sustained_coverage"}:
        raise ValueError("unsupported evaluation objective")
    eligible = [c for c in candidates if c["report"]["execution_status"] == "SUCCEEDED"
                and c["report"]["engineering_status"] == "PASSED"]
    if not eligible:
        return {"status": "NO_ELIGIBLE_CANDIDATE", "ranking": [], "selected": None}
    if acceptance is not None and any(v is not None for v in acceptance.model_dump().values()):
        eligible = [c for c in eligible if acceptance_result(c["report"], acceptance)["status"] == "PASSED"]
        if not eligible:
            return {"status": "NO_CANDIDATE_MEETS_ACCEPTANCE", "ranking": [], "selected": None}
    unlabelled = all(c["report"].get("effect_status") == "NOT_EVALUATED" for c in eligible)
    if unlabelled:
        if policy != "balanced":
            raise ValueError("NEEDS_INPUT: effect preference requires development labels")
        ranking = sorted(eligible, key=lambda c: (-c["report"]["coverage"]["value"], c["candidate_id"]))
        return {"status": "SELECTED_ENGINEERING_ONLY", "ranking": [c["candidate_id"] for c in ranking],
                "selected": ranking[0]["candidate_id"], "basis": "engineering_only",
                "reason": "无开发标签：仅按工程可用性、覆盖率和候选ID选择，未验证检测效果。",
                "criteria": ["engineering_pass", "coverage_desc", "candidate_id"]}
    if all(c["report"].get("event", {}).get("tp") == 0 and c["report"].get("event", {}).get("fn") == 0
           and c["report"].get("effect_status") == "MEASURED" for c in eligible):
        # A no-alarm candidate has undefined F1, not zero. Do not prefer a
        # false-alarm candidate just because its F1 happens to be defined.
        ranking = sorted(eligible, key=lambda c: ((c["report"]["normal_false_alarms_per_host_hour"]["value"] is None),
            c["report"]["normal_false_alarms_per_host_hour"]["value"] or 0,
            -c["report"]["coverage"]["value"], c["candidate_id"]))
        return {"status": "SELECTED_NORMAL_ONLY", "selected": ranking[0]["candidate_id"],
                "ranking": [c["candidate_id"] for c in ranking], "basis": "normal_only_development",
                "reason": "开发标签均为正常：按正常误报频次、覆盖率和ID选择；未验证异常召回能力。",
                "criteria": ["false_alarm_rate_asc", "coverage_desc", "candidate_id"]}
    defined = [c for c in eligible if (c["report"].get("event") or {}).get("f1", {}).get("value") is not None]
    if not defined:
        return {"status": "UNDEFINED_SELECTION_METRIC", "ranking": [], "selected": None}

    def utility(counts):
        beta2 = {"balanced": 1.0, "precision": 0.25, "recall": 4.0}[policy]
        denominator = (1 + beta2) * counts["tp"] + beta2 * counts["fn"] + counts["fp"]
        return (1 + beta2) * counts["tp"] / denominator if denominator else None

    def descending(value):
        return (value is None, -value if value is not None else 0)

    def rank(candidate):
        report = candidate["report"]
        rate = report["normal_false_alarms_per_host_hour"]["value"]
        event_utility = descending(utility(report["event"]))
        point_utility = descending(utility(report["point"])) if report.get("point") else (True, 0)
        primary = ((point_utility + event_utility)
                   if objective == "sustained_coverage" and report.get("point") else
                   ((True, 0) + event_utility if objective == "sustained_coverage" else event_utility))
        if objective == "event_detection":
            primary += point_utility
        delay = report.get("matched_delay_seconds", {}).get("median")
        return (*primary, rate is None, rate if rate is not None else 0,
                delay is None, delay if delay is not None else 0,
                -report["coverage"]["value"], candidate["candidate_id"])

    ranking = [candidate["candidate_id"] for candidate in sorted(defined, key=rank)]
    return {"status": "SELECTED", "ranking": ranking, "selected": ranking[0], "basis": "labelled_development",
            "reason": "按开发集目标及次级 Fβ、正常误报频次、匹配延迟、覆盖率和候选ID排序；最终测试不参与选择。",
            "policy": policy, "beta": {"balanced": 1.0, "precision": 0.5, "recall": 2.0}[policy],
            "criteria": (["point_f1_desc", "event_f1_desc"] if objective == "sustained_coverage" else
                         ["event_f1_desc", "point_f1_desc"]) if policy == "balanced" else
                        (["point_fbeta_desc", "event_fbeta_desc"] if objective == "sustained_coverage" else
                         ["event_fbeta_desc", "point_fbeta_desc"])} | {
            "tie_broken_by": _decisive_field(sorted(defined, key=rank), rank, objective, policy)}


def _decisive_field(ranking, rank, objective, policy):
    if len(ranking) < 2:
        return "only_eligible_candidate"
    primary = ["point", "event"] if objective == "sustained_coverage" else ["event", "point"]
    names = [f"{field}_{'f1' if policy == 'balanced' else 'fbeta'}" for field in primary]
    # Each optional metric contributes (is_undefined, value) to the sort key.
    fields = [names[0]] * 2 + [names[1]] * 2 + ["false_alarm_rate"] * 2
    fields += ["matched_delay_seconds"] * 2 + ["coverage", "candidate_id"]
    return next((field for field, a, b in zip(fields, rank(ranking[0]), rank(ranking[1]))
                 if a != b), "candidate_id")


def select_development(candidates: Sequence[dict], *, policy="balanced", acceptance=None, strict=False,
                       objective="event_detection", candidate_limit=16) -> dict:
    """Select development results; legacy tasks without a target default to events.

    New task callers must pass the frozen evaluation_objective explicitly.
    Loading an old task applies its schema default in memory, never rewriting it.
    """
    if type(candidate_limit) is not int or not 1 <= candidate_limit <= 16:
        raise ValueError("candidate limit must be within 1..16")
    result = _select_with_recovery(candidates, policy=policy, acceptance=acceptance, strict=strict, objective=objective, candidate_limit=candidate_limit)
    criteria = result.get("criteria", [])
    if result.get("basis") == "labelled_development":
        criteria += ["false_alarm_rate_asc", "matched_delay_asc", "coverage_desc", "candidate_id"]
    low_count = any(c["report"].get("effect_status") == "MEASURED"
                    and (c["report"].get("event", {}).get("tp", 0)
                         + c["report"].get("event", {}).get("fn", 0)) < 5 for c in candidates)
    if low_count:
        result["warnings"] = [*result.get("warnings", []),
                              "LOW_EVENT_COUNT: 真实事件少于5个，事件F1不足以支持统计结论。"]
    if "tie_broken_by" not in result:
        ordered = result.get("ranking", [])
        decisive = "only_eligible_candidate" if result.get("selected") else None
        if len(ordered) >= 2:
            by_id = {c["candidate_id"]: c["report"] for c in candidates}
            first, second = (by_id[cid] for cid in ordered[:2])
            decisive = "candidate_id"
            if first.get("coverage", {}).get("value") != second.get("coverage", {}).get("value"):
                decisive = "coverage"
            if (result.get("basis") == "normal_only_development"
                and first.get("normal_false_alarms_per_host_hour", {}).get("value")
                != second.get("normal_false_alarms_per_host_hour", {}).get("value")):
                decisive = "false_alarm_rate"
        result["tie_broken_by"] = decisive
    return {**result, "protocol": SELECTION_PROTOCOL, "objective": objective,
            "requested_policy": policy, "policy": result.get("policy", "balanced" if result.get("basis") == "engineering_only" else policy),
            "criteria": criteria,
            "tie_broken_by": result.get("tie_broken_by", "candidate_id" if result.get("selected") else None)}


def _select_with_recovery(candidates, *, policy, acceptance, strict, objective, candidate_limit):
    """Demo default: output the best usable proposal, retaining unmet gates as warnings.

    Strict ranking remains available for explicit acceptance tests. Source/method
    checks and successful execution are prerequisites, never bypassed here.
    """
    if strict:
        return _select_development(candidates, policy=policy, acceptance=acceptance, objective=objective, candidate_limit=candidate_limit)
    # Validate the shared structural contract before applying recovery policies.
    if len(candidates) > candidate_limit or len({c['candidate_id'] for c in candidates}) != len(candidates):
        raise ValueError('distinct candidates within the declared budget required')
    if any(c['role'] != 'development' for c in candidates):
        raise ValueError('selection only accepts development results')
    if policy not in {'balanced', 'precision', 'recall'}:
        raise ValueError('unsupported selection policy')
    usable = [c for c in candidates if c['report']['execution_status'] == 'SUCCEEDED'
              and c['report']['engineering_status'] in {'PASSED', 'COVERAGE_FAILED'}]
    if not usable:
        return {'status':'NO_ELIGIBLE_CANDIDATE','ranking':[],'selected':None}
    warnings = []
    passed = [c for c in usable if c['report']['engineering_status'] == 'PASSED']
    if passed:
        usable = passed
    else:
        warnings.append('可用候选覆盖率未达到95%，仍输出可运行方案；缺失区间及覆盖率按实际结果展示。')
    if len(usable) < len(candidates):
        warnings.append('部分候选不可用，已继续比较其余可运行候选。')
    if acceptance is not None and any(v is not None for v in acceptance.model_dump().values()):
        meeting = [c for c in usable if acceptance_result(c['report'], acceptance)['status'] == 'PASSED']
        if meeting:
            usable = meeting
        else:
            warnings.append('没有候选满足全部验收目标，演示模式仍输出当前最佳方案；验收未通过或未评估的状态保留。')
    unlabelled = all(c['report'].get('effect_status') == 'NOT_EVALUATED' for c in usable)
    effective_policy = policy
    if unlabelled and policy != 'balanced':
        effective_policy = 'balanced'
        warnings.append('缺少真实标签，效果偏好暂不能验证；改按工程可用性、覆盖率和ID选择。')
    ranked = [{**c, 'report':{**c['report'], 'engineering_status':'PASSED'}} for c in usable]
    result = _select_development(ranked, policy=effective_policy, objective=objective, candidate_limit=candidate_limit)
    if result['selected'] is None:
        ordered = sorted(usable, key=lambda c: (-c['report']['coverage']['value'],c['candidate_id']))
        result = {'status':'SELECTED_ENGINEERING_ONLY','selected':ordered[0]['candidate_id'],
                  'ranking':[c['candidate_id'] for c in ordered], 'basis':'engineering_only',
                  'criteria':['coverage_desc', 'candidate_id'],
                  'reason':'开发效果指标未定义，按覆盖率和ID输出可运行方案，不宣称检测效果最优。'}
        warnings.append(result['reason'])
    if warnings:
        result = {**result,'warnings':warnings,'reason':result.get('reason','') + ' ' + ' '.join(warnings)}
    return result
