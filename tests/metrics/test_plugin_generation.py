import asyncio
import copy

import pytest

from contracts.metrics import CandidatePlan, DetectorConfig
from contracts.metrics_knowledge import GeneratedCode
from factory.metrics.generation import generate, INTERFACE
from factory.metrics.capability_knowledge import plugin_records
from factory.metrics.capability_registry import registry
from tests.metrics.test_runtime import task


class ControlledGateway:
    def __init__(self):
        self.calls = []
    async def ask(self, *args):
        self.calls.append(args)
        return GeneratedCode(source='def create_detector(config):\n    return None\n', knowledge_ids=[], explanation='controlled')


def fixture():
    plugins = registry()
    card = plugins.get('fixed_threshold')
    _, _, cap = plugin_records(card, plugins.directories[card.method_id])
    plan = CandidatePlan(candidate_id='new', config=DetectorConfig(method_id=card.method_id),
        capability_id=cap['id'], knowledge_ids=[cap['id']], parameter_sources={}, limitations=[], selection_reason='source-linked')
    context = {'knowledge_schema': 'metrics-knowledge/2', 'knowledge': {'capabilities': [{'id': cap['id'], **cap['payload']}],
        'knowledge_ids': [cap['id']], 'chunks': [], 'experiences': []}}
    return plan, context


def test_generic_instructions_have_no_formula_and_frozen_spec_controls_input():
    for forbidden in ('median', 'MAD', 'x-T'):
        assert forbidden not in INTERFACE
    plan, context = fixture()
    gateway = ControlledGateway()
    first = asyncio.run(generate(gateway, task(), plan, context, version=0))
    assert gateway.calls[0][3]['capability']['algorithm_spec'] == context['knowledge']['capabilities'][0]['algorithm_spec']
    changed = copy.deepcopy(context)
    changed['knowledge']['capabilities'][0]['algorithm_spec'] = 'revised-frozen-specification'
    second = asyncio.run(generate(gateway, task(), plan, changed, version=1))
    assert gateway.calls[1][3]['capability']['algorithm_spec'] == 'revised-frozen-specification'
    assert first.specification_sha256 != second.specification_sha256
    assert first.capability_version == context['knowledge']['capabilities'][0]['version'] and first.capability_id == plan.capability_id
    import json
    from factory.metrics.mock import MockTransport
    data = {'stage': 'code-new-v0', 'input': {'frozen_plan': plan.model_dump(mode='json'),
            'task': {'knowledge': {'knowledge_ids': ['unrelated-first-id', plan.capability_id]}}}}
    response = asyncio.run(MockTransport().chat(messages=[{}, {'content': json.dumps(data)}], model='controlled', timeout=1))
    parsed = json.loads(response['choices'][0]['message']['content'])
    assert parsed['knowledge_ids'] == [plan.capability_id]



def test_missing_frozen_spec_stops_before_model_request():
    plan, context = fixture()
    gateway = ControlledGateway()
    context['knowledge']['capabilities'] = []
    with pytest.raises(ValueError, match='NEEDS_KNOWLEDGE'):
        asyncio.run(generate(gateway, task(), plan, context, version=0))
    assert gateway.calls == []


def test_explicit_knowledge_off_removes_specs_experience_and_plan_explanations():
    plan, context = fixture()
    context['knowledge_off'] = True
    context['available_methods'] = [{'description': 'secret_formula_marker'}]
    context['knowledge']['experiences'] = [{'advice': 'secret_formula_marker'}]
    plan = plan.model_copy(update={'selection_reason': 'secret_formula_marker', 'limitations': ['secret_formula_marker']})
    gateway = ControlledGateway()
    result = asyncio.run(generate(gateway, task(), plan, context, version=0))
    assert 'secret_formula_marker' not in str(gateway.calls[0][3])
    assert 'capability' not in gateway.calls[0][3]
    assert result.specification_sha256 is None


def test_no_frozen_spec_also_stops_before_planning_model():
    from factory.metrics.planning import plan as plan_candidates
    gateway = ControlledGateway()
    with pytest.raises(ValueError, match='NEEDS_KNOWLEDGE'):
        asyncio.run(plan_candidates(gateway, task(), {'knowledge_schema': 'metrics-knowledge/2',
            'knowledge': {'capabilities': []}}, {'knowledge_ids': []}))
    assert gateway.calls == []
    candidate, context = fixture()
    with pytest.raises(ValueError, match='NEEDS_INPUT'):
        asyncio.run(plan_candidates(gateway, task(allowed_methods=['fixed_threshold'],
            explicit_constraints={'alpha': .2}), context, {'knowledge_ids': [candidate.capability_id]}))
    assert gateway.calls == []


def test_three_candidates_and_single_method_are_budgeted_without_forcing_other_methods():
    from contracts.metrics import MetricsBudgets
    from contracts.metrics_knowledge import PlanningOutput
    from factory.metrics.planning import validate_plan
    from factory.metrics.evaluation import select_development
    plan, context = fixture()
    cap = context['knowledge']['capabilities'][0]
    candidates = [plan.model_copy(update={'candidate_id': f'variant-{i}',
        'config': DetectorConfig(method_id=plan.config.method_id, threshold=85. + i)}) for i in range(3)]
    output = PlanningOutput(supported=True, understanding='three variations', anomaly_target='upper',
                            limitations=[], candidates=candidates)
    spec = task(allowed_methods=[plan.config.method_id], explicit_constraints={}, budgets=MetricsBudgets(candidates=3))
    found = {'schema_version': 'metrics-knowledge/2', 'capabilities': [cap], 'knowledge_ids': [cap['id']]}
    assert len(validate_plan(output, spec, found).candidates) == 3
    with pytest.raises(ValueError, match='budget'):
        validate_plan(output, spec.model_copy(update={'budgets': MetricsBudgets(candidates=2)}), found)
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    report = json.loads((root / 'case-example/metrics/delivery/transfer-memory-v2/report.json').read_text())['candidates'][0]['report']
    measured = [{'candidate_id': c.candidate_id, 'role': 'development', 'report': report} for c in candidates]
    assert len(select_development(measured, candidate_limit=3)['ranking']) == 3
    with pytest.raises(ValueError, match='budget'):
        select_development(measured, candidate_limit=2)


def test_natural_language_discovers_new_plugin_and_its_numeric_parameters():
    from factory.metrics.requirements import build_draft, controlled_extract, binding_for, request_from_draft
    text = '用EWMA检测模拟内存持续升高，alpha为0.2'
    draft = build_draft([text], [controlled_extract(text)], binding=binding_for([text]))
    request = request_from_draft(draft, current_binding=draft.binding)
    assert request.allowed_methods == ['ewma']
    assert request.explicit_constraints['alpha'] == .2
    invalid = text.replace('0.2', '2.0')
    draft = build_draft([invalid], [controlled_extract(invalid)], binding=binding_for([invalid]))
    with pytest.raises(ValueError, match='NEEDS_INPUT'):
        request_from_draft(draft, current_binding=draft.binding)


@pytest.mark.parametrize('wording,expected', [
    ('比较全部方法', {'fixed_threshold', 'rolling_mad', 'ewma', 'probe'}),
    ('比较所有方法', {'fixed_threshold', 'rolling_mad', 'ewma', 'probe'}),
    ('比较三种方法：固定阈值、滚动MAD和EWMA', {'fixed_threshold', 'rolling_mad', 'ewma'}),
])
def test_all_methods_and_explicit_subset_with_new_nondefault_plugin(tmp_path, monkeypatch, wording, expected):
    import json
    import shutil
    from pathlib import Path
    from factory.metrics.capability_registry import methods
    from factory.metrics.requirements import build_draft, controlled_extract, binding_for, request_from_draft
    root = Path(__file__).resolve().parents[2]
    plugins = tmp_path / 'plugins'
    shutil.copytree(root / 'capabilities', plugins)
    shutil.copytree(plugins / 'fixed_threshold', plugins / 'probe')
    path = plugins / 'probe/capability.json'
    card = json.loads(path.read_text())
    card.update(method_id='probe', aliases=['探针'], default_candidate=False)
    path.write_text(json.dumps(card, ensure_ascii=False))
    monkeypatch.setenv('FACTORY_CAPABILITIES_DIRECTORY', str(plugins))
    text = '用模拟数据检测内存持续升高，' + wording
    draft = build_draft([text], [controlled_extract(text)], binding=binding_for([text]))
    request = request_from_draft(draft, current_binding=draft.binding)
    assert set(methods()) == {'fixed_threshold', 'rolling_mad', 'ewma', 'probe'}
    assert set(request.allowed_methods) == expected
    assert draft.evidence['methods']['origin'] == 'user_explicit'
    assert request.budgets.candidates == len(expected)
