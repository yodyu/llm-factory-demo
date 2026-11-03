import copy
import json
from pathlib import Path

import pytest

from factory.metrics.evaluation import select_development


@pytest.mark.parametrize("name", ["reproduction-v2", "transfer-memory-v2"])
@pytest.mark.parametrize("runtimes", [(0.01, 100), (100, 0.01)])
def test_frozen_development_point_quality_wins_independently_of_runtime(name, runtimes):
    path = Path(__file__).resolve().parents[2] / "case-example/metrics/delivery" / name
    candidates = copy.deepcopy(json.loads((path / "report.json").read_text())["candidates"])
    for candidate, runtime in zip(candidates, runtimes):
        candidate["report"]["runtime_seconds"] = runtime
    result = select_development(candidates)
    winner = next(c for c in candidates if c["candidate_id"] == result["selected"])
    assert winner["plan"]["config"]["method_id"] == "fixed_threshold"
    assert result["tie_broken_by"] == "point_f1"
    assert "runtime" not in " ".join(result["criteria"])
    assert any("LOW_EVENT_COUNT" in warning for warning in result["warnings"])


def test_report_exposes_selection_criteria_and_decisive_field():
    from factory.metrics.reports import markdown
    path = Path(__file__).resolve().parents[2] / "case-example/metrics/delivery/transfer-memory-v2/report.json"
    report = json.loads(path.read_text())
    report["selection"] = select_development(report["candidates"])
    text = markdown(report)
    assert '"tie_broken_by": "point_f1"' in text
    assert "point_f1_desc" in text


def test_engineering_selection_records_actual_decisive_field():
    candidates = [{"candidate_id": cid, "role": "development", "report": {
        "execution_status": "SUCCEEDED", "engineering_status": "PASSED",
        "effect_status": "NOT_EVALUATED", "coverage": {"value": coverage},
        "runtime_seconds": runtime}} for cid, coverage, runtime in (("a", 1.0, 100), ("b", .99, .01))]
    result = select_development(candidates)
    assert result["selected"] == "a" and result["tie_broken_by"] == "coverage"
    candidates[1]["report"]["coverage"]["value"] = 1.0
    assert select_development(candidates)["tie_broken_by"] == "candidate_id"
    candidates[1]["report"]["coverage"] = {"value": 1.0, "numerator": 50, "denominator": 50}
    assert select_development(candidates)["tie_broken_by"] == "candidate_id"


def tradeoff_candidates():
    def counts(tp, fp, fn):
        return {'tp': tp, 'fp': fp, 'fn': fn, 'f1': {'value': 2*tp/(2*tp+fp+fn)}}
    return [{'candidate_id': cid, 'role': 'development', 'report': {
        'execution_status': 'SUCCEEDED', 'engineering_status': 'PASSED', 'effect_status': 'MEASURED',
        'event': counts(*event), 'point': counts(*point), 'coverage': {'value': 1.0},
        'normal_false_alarms_per_host_hour': {'value': 0}, 'matched_delay_seconds': {'median': 1}}}
        for cid, event, point in [('A', (9, 0, 1), (2, 0, 8)), ('B', (2, 0, 8), (9, 0, 1))]]


@pytest.mark.parametrize('policy', ['balanced', 'recall', 'precision'])
@pytest.mark.parametrize('objective,winner,primary', [('event_detection','A','event'), ('sustained_coverage','B','point')])
def test_frozen_objective_reaches_orchestration_selection_and_report(policy, objective, winner, primary):
    from types import SimpleNamespace
    from contracts.metrics import MetricsTask
    from factory.metrics.orchestration.nodes import task_actions
    from factory.metrics.ui_presentation import selection_explanation
    from factory.metrics.reports import markdown
    source = Path(__file__).resolve().parents[2] / 'case-example/metrics/delivery/real-memory-v1/report.json'
    report = json.loads(source.read_text())
    task = MetricsTask.model_validate({**report['task'], 'evaluation_objective': objective, 'selection_policy': policy})
    candidates = tradeoff_candidates()
    # Use real plans only for report rendering; scores are controlled development data.
    for candidate in candidates:
        candidate.update(plan=copy.deepcopy(report['candidates'][0]['plan']), versions=[])
    report.update(task=task.model_dump(mode='json'), candidates=candidates)
    ctx = SimpleNamespace(task=task, report=report, legacy_upload=False)
    task_actions(ctx, None)['select_candidate']({})
    selected = report['selection']
    assert selected['selected'] == winner
    assert selected['objective'] == report['task']['evaluation_objective'] == objective
    assert selected['criteria'][0].startswith(primary + '_')
    assert selected['tie_broken_by'].startswith(primary + '_')
    assert primary + '_' in markdown(report)
    explanation = selection_explanation(report)
    assert explanation['评价目标'] == ('事件发现' if objective == 'event_detection' else '持续区间覆盖')
    assert ('开发事件' if primary == 'event' else '开发点级') in explanation['排序顺序'].split(' → ')[0]


@pytest.mark.parametrize('objective', ['event_detection', 'sustained_coverage'])
@pytest.mark.parametrize('policy,winner', [('balanced','precise'), ('precision','precise'), ('recall','recall')])
def test_policy_changes_primary_fbeta(objective, policy, winner):
    candidates = tradeoff_candidates()
    primary = 'point' if objective == 'sustained_coverage' else 'event'
    for candidate, cid, tp, fp, fn in zip(candidates, ['precise','recall'], [5,9], [0,4], [5,1]):
        candidate['candidate_id'] = cid
        candidate['report'][primary] = {'tp':tp,'fp':fp,'fn':fn,'f1':{'value':2*tp/(2*tp+fp+fn)}}
    # Balanced prefers recall here (18/23 > 10/15); precision prefers exact alarms.
    expected = 'recall' if policy == 'balanced' else winner
    assert select_development(candidates, objective=objective, policy=policy)['selected'] == expected


def test_old_task_default_is_explicit_and_does_not_mutate_input():
    from contracts.metrics import MetricsTask
    source = Path(__file__).resolve().parents[2] / 'case-example/metrics/delivery/real-memory-v1/report.json'
    values = json.loads(source.read_text())['task']
    values.pop('evaluation_objective', None)
    before = copy.deepcopy(values)
    assert MetricsTask.model_validate(values).evaluation_objective == 'event_detection'
    assert values == before
    assert select_development(tradeoff_candidates())['objective'] == 'event_detection'
