import asyncio
import copy
import json
from pathlib import Path

import pytest

from factory.metrics.knowledge import retrieve
from factory.metrics.neo4j_store import snapshot_value
from tests.metrics.test_plugin_generation import ControlledGateway, fixture
from tests.metrics.test_retrieval_small import snapshot, conditions
from tests.metrics.test_runtime import task
from tests.metrics.test_knowledge_backends import repository as repository_fixture

ROOT = Path(__file__).resolve().parents[2]
repository = repository_fixture


def experience(method, name, feedback=None):
    return {'id': name, 'kind': 'Experience', 'payload': {
        'method_id': method, 'metric_kind': 'gauge', 'origin': 'mock',
        'reusable_implementation': False, 'implementation_verified': False,
        'method_validation_protocol': 'metrics-method-check/2',
        'issue': 'contract_failure', 'action': 'repair', 'development_feedback': feedback or []}}


FEEDBACK = [{'check': 'mad_past_only', 'passed': False, 'difference': {
    'code': 'OUTPUT_SCHEMA', 'actual': {'status': 'insufficient_history', 'evidence': None},
    'expected_schema': {'properties': {'evidence': {'type': 'object'}}}}}]


def test_experience_quotas_are_per_method_and_actionable_feedback_precedes_hash_ids():
    frozen = snapshot()
    nodes = frozen['nodes'] + [experience('fixed_threshold', 'aaa-other-' + str(i)) for i in range(4)]
    nodes += [experience('rolling_mad', 'aaa-empty'), experience('rolling_mad', 'zzz-actionable', FEEDBACK)]
    frozen = snapshot_value(nodes, frozen['relations'])
    found = retrieve(frozen, **conditions())
    matching = [e for e in found['experiences'] if e['method_id'] == 'rolling_mad']
    assert matching[0]['id'] == 'zzz-actionable' and matching[0]['development_feedback'] == FEEDBACK
    assert len(found['experiences']) == 4  # Two hints per method, not four lowest hashes.
    from factory.metrics.experience_context import candidate_context
    context = {'knowledge': found}
    view = candidate_context(context, 'rolling_mad')
    assert view['knowledge']['experiences'][0]['id'] == 'zzz-actionable'
    assert context['knowledge']['experiences'][0]['method_id'] == 'fixed_threshold'


@pytest.mark.parametrize('schema', ['metrics-knowledge/1', 'metrics-knowledge/2'])
def test_feedback_reaches_generation_and_final_data_is_excluded_recursively(schema):
    from factory.metrics.generation import generate
    feedback = copy.deepcopy(FEEDBACK)
    feedback[0]['final'] = {'labels': ['FINAL_SENTINEL']}
    feedback[0]['difference']['actual']['labels'] = ['FINAL_SENTINEL']
    node = experience('fixed_threshold', 'concrete-feedback', feedback)
    node['payload']['final'] = {'f1': 'FINAL_SENTINEL'}
    frozen = snapshot()
    found = retrieve(snapshot_value(frozen['nodes'] + [node], frozen['relations']), **conditions())
    assert 'FINAL_SENTINEL' not in json.dumps(found)
    plan, context = fixture()
    context['knowledge_schema'] = schema
    context['knowledge']['experiences'] = [
        {'id': 'other-method', 'method_id': 'rolling_mad', 'development_feedback': []}, *found['experiences']]
    original = copy.deepcopy(context)
    gateway = ControlledGateway()
    asyncio.run(generate(gateway, task(), plan, context, version=0))
    sent = gateway.calls[0][3]['task']['knowledge']['experiences'][0]['development_feedback']
    assert sent == FEEDBACK and context == original


def test_real_memory_failure_retains_recorded_evidence_field_without_inventing_outputs():
    from factory.metrics.publication import publication_payload
    report = json.loads((ROOT / 'case-example/metrics/delivery/real-memory-v1/report.json').read_text())
    payload = publication_payload(report)
    frozen = snapshot_value(payload['nodes'], payload['relations'])
    found = retrieve(frozen, requirement='内存 MAD', metric_kind='gauge',
        allowed_methods=['rolling_mad'], history_points=60, origin='llm_api')
    checks = [check for e in found['experiences'] for check in e['development_feedback']]
    assert checks and all(c['check'] == 'mad_past_only' and c['point_index'] == 0 for c in checks)
    assert all(c['difference']['code'] == 'OUTPUT_SCHEMA'
               and c['difference']['fields'] == [['evidence']] for c in checks)
    # The frozen report did not record actual/expected_schema: do not fabricate them.
    original = next(c for c in report['candidates'] if c['plan']['config']['method_id'] == 'rolling_mad')
    assert checks[0] == next(c for c in original['versions'][0]['validation']['checks'] if not c['passed'])
    assert all('final' not in e for e in found['experiences'])


def test_historical_validator_false_rejections_stay_quarantined():
    node = experience('fixed_threshold', 'old-false-rejection', [
        {'check': 'state_reload', 'difference': {'code': 'STATE_RELOAD_DIFFERENCE'}}])
    node['payload']['method_validation_protocol'] = 'metrics-method-check/1'
    frozen = snapshot()
    found = retrieve(snapshot_value(frozen['nodes'] + [node], frozen['relations']), **conditions())
    assert not found['experiences']
    assert any(e.get('experience_id') == node['id'] for e in found['excluded'])


def test_feedback_and_experience_order_are_identical_in_both_backends(repository):
    from factory.metrics.capability_knowledge import register_plugins
    from factory.metrics.knowledge import identity
    register_plugins(repository)
    nodes = [experience('fixed_threshold', 'ignored'), experience('rolling_mad', 'ignored', FEEDBACK)]
    for node in nodes:
        node['payload']['final'] = {'labels': ['FINAL_SENTINEL']}
        node['id'] = identity('experience', node['payload'])
    repository.add(nodes, [])
    frozen, found = repository.freeze(**conditions())
    assert found == retrieve(frozen, **conditions())
    assert len(found['experiences']) == 2
    assert found['experiences'][1]['development_feedback'] == FEEDBACK
    assert 'FINAL_SENTINEL' not in json.dumps(found)
