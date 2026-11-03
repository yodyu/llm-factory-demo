import asyncio
import json
from types import SimpleNamespace

from jsonschema import Draft202012Validator
from pydantic import ValidationError
import pytest

from contracts.metrics_requirement import (
    RequirementClaim, RequirementExtraction, allowed_requirement_keys,
)
from factory.metrics.requirements import EXAMPLES, interpret_command


def key_enum():
    return RequirementExtraction.model_json_schema()['$defs']['RequirementClaim']['properties']['key']['enum']


def test_model_schema_exposes_exact_dynamic_key_enum_without_freezing_plugin_parameters(monkeypatch):
    assert set(key_enum()) == allowed_requirement_keys()
    assert 'alpha' in key_enum() and 'metric' not in key_enum() and 'deliverables' not in key_enum()
    import factory.metrics.capability_registry as plugins
    monkeypatch.setattr(plugins, 'registry', lambda: SimpleNamespace(cards={
        'future': SimpleNamespace(config_schema={'properties': {'new_sensitivity': {'type': 'number'}}})}))
    assert 'new_sensitivity' in key_enum() and 'alpha' not in key_enum()
    assert RequirementClaim(key='new_sensitivity', value=.25, quote='0.25').value == .25


@pytest.mark.parametrize('key,value', [
    ('metric', 'memory_utilization'), ('target_scope', 'single_host'), ('entity_scope', 'single_host'),
    ('missing_data_tolerance', 'short_gaps_allowed'), ('method_count', 2),
    ('deliverables', ['detection_code', 'validation_report']), ('deliverable_detection_code', True),
])
def test_recorded_invalid_response_shapes_are_rejected_by_schema_and_runtime(key, value):
    result = {'claims': [{'key': key, 'value': value, 'quote': '单主机内存利用率'}], 'unsupported': []}
    assert not Draft202012Validator(RequirementExtraction.model_json_schema()).is_valid(result)
    with pytest.raises(ValidationError):
        RequirementExtraction.model_validate(result)


def test_interpreter_sends_the_same_whitelist_as_its_schema_and_preserves_memory_example(tmp_path):
    from factory.metrics.runtime import MetricsStore
    draft, _ = asyncio.run(interpret_command(state=tmp_path, mode='mock',
        turns=[EXAMPLES['内存缓慢漂移']], binding='memory-regression'))
    assert not draft.issues and draft.values['scenario'] == 'memory_drift'
    store = MetricsStore(tmp_path / 'runtime.sqlite')
    with store._transaction() as db:
        refs = db.execute("SELECT reference FROM task_artifacts WHERE task_id=? AND role='model-prompt'",
                          (draft.parse_task_id,)).fetchall()
    assert len(refs) == 1
    messages = store.document(refs[0][0])['messages']
    public = json.loads(messages[1]['content'])
    sent_enum = public['output_schema']['$defs']['RequirementClaim']['properties']['key']['enum']
    assert sent_enum == public['input']['allowed_claim_keys'] == key_enum()
    assert '不得自行增加字段' in messages[0]['content']
