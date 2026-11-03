import asyncio

import pytest

from contracts.metrics import CandidatePlan, FixedConfig, MADConfig
from contracts.metrics_knowledge import PlanningOutput
from factory.metrics.planning import plan, validate_plan
from tests.metrics.test_runtime import task


def test_model_cannot_override_explicit_threshold_and_unknown_citations_are_removed():
    spec = task(explicit_constraints={"threshold": 85.0})
    fixed = CandidatePlan(candidate_id="fixed", config=FixedConfig(threshold=85.0),
                          parameter_sources={"threshold": "user_explicit"}, knowledge_ids=[], limitations=[])
    mad = CandidatePlan(candidate_id="mad", config=MADConfig(), parameter_sources={}, knowledge_ids=[], limitations=[])
    output = PlanningOutput(supported=True, understanding="检测升高", anomaly_target="upper", limitations=[], candidates=[fixed, mad])
    assert validate_plan(output, spec, {"knowledge_ids": []}) == output
    wrong = fixed.model_copy(update={"config": FixedConfig(threshold=90.0)})
    with pytest.raises(ValueError, match="changed explicit"):
        validate_plan(output.model_copy(update={"candidates": [wrong, mad]}), spec, {"knowledge_ids": []})
    wrong = fixed.model_copy(update={"knowledge_ids": ["not-sent"]})
    corrected = validate_plan(output.model_copy(update={"candidates": [wrong, mad]}), spec, {"knowledge_ids": []})
    assert corrected.candidates[0].knowledge_ids == []
    assert '未提供的知识引用' in corrected.candidates[0].limitations[-1]


def test_unsupported_explicit_ranking_stops_before_model_request():
    class Forbidden:
        async def ask(self, *_args, **_kwargs):
            raise AssertionError("unsupported ranking must not consume a model call")
    with pytest.raises(ValueError, match="NEEDS_INPUT"):
        asyncio.run(plan(Forbidden(), task(ranking_preferences=["false_alarm_rate"]), {}, {"knowledge_ids": []}))


def output_for(direction):
    return PlanningOutput(supported=True, understanding="检测指定方向", anomaly_target=direction, limitations=[], candidates=[
        CandidatePlan(candidate_id="fixed", config=FixedConfig(threshold=15.0, direction=direction),
                      parameter_sources={"threshold": "candidate_assumption"}, knowledge_ids=[], limitations=[]),
        CandidatePlan(candidate_id="mad", config=MADConfig(direction=direction),
                      parameter_sources={}, knowledge_ids=[], limitations=[]),
    ])


@pytest.mark.parametrize("direction", ["upper", "lower"])
@pytest.mark.parametrize("explicit", [False, True])
def test_valid_target_and_candidates_agree_with_or_without_redundant_constraint(direction, explicit):
    spec = task(anomaly_target=direction, explicit_constraints={"direction": direction} if explicit else {})
    assert validate_plan(output_for(direction), spec, {"knowledge_ids": []})


@pytest.mark.parametrize("candidate_index", [0, 1])
def test_lower_target_rejects_upper_candidate_without_explicit_direction(candidate_index):
    output = output_for("lower")
    candidates = list(output.candidates)
    wrong_config = candidates[candidate_index].config.model_copy(update={"direction": "upper"})
    candidates[candidate_index] = candidates[candidate_index].model_copy(update={"config": wrong_config})
    with pytest.raises(ValueError, match="direction mismatch: expected lower, got upper"):
        validate_plan(output.model_copy(update={"candidates": candidates}), task(anomaly_target="lower"), {"knowledge_ids": []})


def test_plan_target_mismatch_is_rejected_even_when_all_candidates_agree():
    with pytest.raises(ValueError, match="planning anomaly_target mismatch"):
        validate_plan(output_for("lower").model_copy(update={"anomaly_target": "upper"}),
                      task(anomaly_target="lower"), {"knowledge_ids": []})


@pytest.mark.parametrize("spec,message", [
    (task(anomaly_target="lower", explicit_constraints={"direction": "upper"}), "conflicts"),
    (task(anomaly_target="upper", explicit_constraints={"direction": "lower"}), "conflicts"),
    (task(anomaly_target="two_sided"), "supports upper/lower only"),
    (task(anomaly_target="unknown"), "unsupported detection"),
])
def test_unsupported_or_conflicting_targets_never_call_model(spec, message):
    class Forbidden:
        calls = 0
        async def ask(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("invalid target must be rejected before a model request")
    gateway = Forbidden()
    with pytest.raises(ValueError, match="NEEDS_INPUT:.*" + message):
        asyncio.run(plan(gateway, spec, {}, {"knowledge_ids": []}))
    assert gateway.calls == 0


def test_lower_controlled_planning_preserves_target_without_direction_constraint():
    from factory.metrics.mock import MockTransport
    import json
    context = {"explicit_constraints": {}, "anomaly_target": "lower", "knowledge": {"knowledge_ids": []}}
    response = asyncio.run(MockTransport().chat(messages=[{}, {"content": json.dumps({"stage": "plan", "input": context})}],
                                                model="controlled", timeout=1))
    output = PlanningOutput.model_validate_json(response["choices"][0]["message"]["content"])
    assert validate_plan(output, task(anomaly_target="lower"), {"knowledge_ids": []})


def test_parameter_provenance_check_remains_active():
    output = output_for("upper")
    fixed = output.candidates[0].model_copy(update={"parameter_sources": {"threshold": "unverified-claim"}})
    with pytest.raises(ValueError, match="invalid parameter provenance"):
        validate_plan(output.model_copy(update={"candidates": [fixed, output.candidates[1]]}), task(), {"knowledge_ids": []})


@pytest.mark.parametrize("target,explicit", [("lower", {"direction": "upper"}), ("two_sided", {})])
def test_workflow_records_needs_input_without_model_or_algorithm_execution(tmp_path, monkeypatch, target, explicit):
    import json
    from pathlib import Path
    from factory.metrics.workflow import run
    from factory.metrics.synthetic import generate, write_dataset
    from factory.metrics.knowledge import LegacySQLiteKnowledgeStore as KnowledgeStore
    from factory.metrics.runtime import MetricsStore
    from factory.metrics.model import make_gateway
    from execution.metrics_runner import MetricsRunner

    def forbidden(*_args, **_kwargs):
        raise AssertionError("unsupported detection cannot execute an algorithm")
    async def forbidden_ask(*_args, **_kwargs):
        raise AssertionError("unsupported detection cannot request a model")
    state = tmp_path / "state"
    store = MetricsStore(state / "runtime.sqlite")
    gateway = make_gateway(store, mode="mock")
    monkeypatch.setattr(gateway, "ask", forbidden_ask)
    monkeypatch.setattr(MetricsRunner, "detector", forbidden)
    data = tmp_path / "data"
    write_dataset(data, generate("memory_shift"))
    knowledge = KnowledgeStore(tmp_path / "knowledge.sqlite")
    result = asyncio.run(run(store, gateway, state=state,
                            task_input={"requirement": "检测指定方向", "anomaly_target": target, "explicit_constraints": explicit},
                            dataset_root=data, snapshot=knowledge.snapshot(), knowledge=knowledge, image="sha256:" + "a" * 64))
    report = json.loads((Path(result["directory"]) / "report.json").read_text())
    assert result["status"] == "NEEDS_INPUT" and not report["model_operations"]
    assert not report["final_test_executed"] and not report["candidates"]
