import asyncio
import copy
import json
from pathlib import Path

import pytest

from factory.metrics.capability_knowledge import plugin_records, register_plugins
from factory.metrics.capability_registry import registry
from factory.metrics.knowledge import retrieve
from factory.metrics.neo4j_store import snapshot_value
from tests.metrics.test_knowledge_backends import repository as repository_fixture
from tests.metrics.test_plugin_generation import ControlledGateway
from tests.metrics.test_runtime import task

ROOT = Path(__file__).resolve().parents[2]
UNRELATED = [
    'banana pizza 天气', '用深度学习 LSTM 预测客户流失',
    '检测信用卡交易异常', "monitor my cat's mood", '发现股票价格突增',
    '监控宠物情绪并告警', '订单缺失时报警', '预测明天的天气',
    'monitor credit card fraud', '检测客户消费周期异常',
]
RELATED = [
    '服务器负载突然变高时告警', '主机 load 飙升报警', '请发现 QPS 突增',
    '内存持续升高', 'CPU 利用率超过阈值时告警', '磁盘 IOPS 突增',
    '网络吞吐下降时报警', '请求错误率异常', 'alert on server latency spikes',
    '用 EWMA 检测时序异常',
]
repository = repository_fixture


def snapshot():
    plugins = registry()
    nodes, relations, _ = plugin_records(plugins.get('fixed_threshold'), plugins.directories['fixed_threshold'])
    return snapshot_value(nodes, relations)


def conditions(requirement='内存异常', **changes):
    return dict(requirement=requirement, metric_kind='gauge', allowed_methods=['fixed_threshold', 'rolling_mad'],
                history_points=60, origin='mock', **changes)


@pytest.mark.parametrize('query', RELATED)
def test_common_operations_requests_retrieve_generation_specs(query):
    result = retrieve(snapshot(), **conditions(query))
    assert result['status'] == 'RETRIEVED'
    assert result['relevance_score'] > 0
    assert result['capabilities'] and result['chunks']


def test_dataset_metric_requires_an_explicit_mention_and_respects_word_boundaries():
    for query, expected in [('checkout_duration 突增时告警', 'RETRIEVED'),
                            ('CHECKOUT_DURATION 飙升', 'RETRIEVED'),
                            ('checkout_duration_extra 突增', 'NO_RELEVANT_CAPABILITY'),
                            ('检测信用卡交易异常', 'NO_RELEVANT_CAPABILITY')]:
        assert retrieve(snapshot(), **conditions(query, metric_name='checkout_duration'))['status'] == expected


@pytest.mark.parametrize('query', UNRELATED)
def test_unrelated_query_has_no_model_knowledge_and_does_not_mutate_snapshot(query, monkeypatch):
    frozen = snapshot()
    original = copy.deepcopy(frozen)
    def no_io(*args, **kwargs):
        raise AssertionError('retrieve must not read files or consult the live registry')
    monkeypatch.setattr(Path, 'read_text', no_io)
    result = retrieve(frozen, **conditions(query))
    assert result['status'] == 'NO_RELEVANT_CAPABILITY'
    assert result['relevance_score'] == 0
    assert not any(result[key] for key in ('knowledge_ids', 'capabilities', 'chunks', 'experiences'))
    assert result == retrieve(frozen, **conditions(query)) and frozen == original


@pytest.mark.parametrize('query', UNRELATED)
def test_gate_stops_direct_planner_before_model_call(query):
    from factory.metrics.planning import plan
    gateway = ControlledGateway()
    found = retrieve(snapshot(), **conditions(query))
    with pytest.raises(ValueError, match='NO_RELEVANT_CAPABILITY'):
        asyncio.run(plan(gateway, task(), {}, found))
    assert not gateway.calls


def test_irrelevant_queries_do_not_bypass_scope_gate_when_retrieval_is_disabled():
    result = retrieve(snapshot(), **conditions(UNRELATED[0], enabled=False))
    assert result['mode'] == 'none' and result['status'] == 'NO_RELEVANT_CAPABILITY'
    result = retrieve(snapshot(), **conditions(enabled=False))
    assert result['mode'] == 'none' and result.get('status') != 'NO_RELEVANT_CAPABILITY'


def test_both_backends_freeze_the_same_gate_and_positive_results(repository):
    register_plugins(repository)
    for query in [*UNRELATED, *RELATED, 'checkout_duration 突增时告警']:
        bound = conditions(query, metric_name='checkout_duration')
        frozen, found = repository.freeze(**bound)
        assert found == retrieve(frozen, **bound)
        assert found['status'] == ('NO_RELEVANT_CAPABILITY' if query in UNRELATED else 'RETRIEVED')
        if query not in UNRELATED:
            assert found['capabilities'] and found['chunks']


@pytest.mark.parametrize('query', UNRELATED)
def test_task_graph_rejects_without_planning_generation_or_sandbox(query, tmp_path, monkeypatch):
    import factory.metrics.workflow as workflow
    from factory.metrics.local_store import LocalKnowledgeStore
    from factory.metrics.model import make_gateway
    from factory.metrics.runtime import MetricsStore
    from factory.metrics.synthetic import generate, write_dataset

    class NoExecution:
        def __init__(self, *args, **kwargs):
            pass
        def cleanup_orphans(self):
            pass
        def detector(self, *args, **kwargs):
            raise AssertionError('irrelevant queries must not execute generated code')
    monkeypatch.setattr(workflow, 'MetricsRunner', NoExecution)
    knowledge = LocalKnowledgeStore(tmp_path / 'knowledge.sqlite')
    register_plugins(knowledge)
    data = tmp_path / 'data'
    write_dataset(data, generate('memory_shift'))
    state = tmp_path / 'state'
    store = MetricsStore(state / 'runtime.sqlite')
    gateway = make_gateway(store, mode='mock')
    async def forbidden(*args, **kwargs):
        raise AssertionError('irrelevant queries must not call any model stage')
    monkeypatch.setattr(gateway, 'ask', forbidden)
    result = asyncio.run(workflow.run(store, gateway, state=state, dataset_root=data,
        knowledge=knowledge, snapshot=knowledge.snapshot(), image='sha256:' + 'a' * 64,
        task_id='unrelated-query', task_input={'requirement': query, 'anomaly_target': 'upper',
                                              'explicit_constraints': {}}))
    report = json.loads((Path(result['directory']) / 'report.json').read_text())
    assert result['status'] == 'NEEDS_INPUT'
    assert report['retrieval']['status'] == 'NO_RELEVANT_CAPABILITY'
    assert not report['candidates'] and 'planning' not in report and 'proposal' not in report
    assert not report['model_operations'] and not report['final_test_executed']
    events = json.loads((Path(result['directory']) / 'orchestration.json').read_text())['events']
    assert not {'plan_candidates', 'run_candidate', 'final_evaluate'} & {e['node'] for e in events}


@pytest.mark.parametrize('provided_snapshot', [False, True])
def test_task_passes_bound_metric_to_freeze_and_retrieval(provided_snapshot, tmp_path, monkeypatch):
    import factory.metrics.workflow as workflow
    from factory.metrics.local_store import LocalKnowledgeStore
    from factory.metrics.model import make_gateway
    from factory.metrics.runtime import MetricsStore
    from factory.metrics.synthetic import generate, write_dataset

    class NoExecution:
        def __init__(self, *args, **kwargs):
            pass
        def cleanup_orphans(self):
            pass

    monkeypatch.setattr(workflow, 'MetricsRunner', NoExecution)
    knowledge = LocalKnowledgeStore(tmp_path / 'knowledge.sqlite')
    register_plugins(knowledge)
    data = tmp_path / 'data'
    bundle = generate('memory_shift')
    bundle['manifest'] = bundle['manifest'].model_copy(update={'metric': 'checkout_duration'})
    bundle['experiment']['dataset'] = bundle['manifest'].model_dump(mode='json')
    write_dataset(data, bundle)
    reached = []

    async def stop_at_planning(gateway, task, context, found):
        assert context['metric'] == 'checkout_duration'
        assert found['status'] == 'RETRIEVED' and found['capabilities']
        reached.append(True)
        raise ValueError('NEEDS_INPUT: controlled stop after successful retrieval')

    monkeypatch.setattr(workflow, 'plan', stop_at_planning)
    state = tmp_path / 'state'
    store = MetricsStore(state / 'runtime.sqlite')
    result = asyncio.run(workflow.run(store, make_gateway(store, mode='mock'), state=state,
        dataset_root=data, knowledge=knowledge, snapshot=knowledge.snapshot() if provided_snapshot else None,
        image='sha256:' + 'a' * 64, task_id='bound-metric',
        task_input={'requirement': 'checkout_duration 突增时告警', 'anomaly_target': 'upper', 'explicit_constraints': {}}))
    report = json.loads((Path(result['directory']) / 'report.json').read_text())
    assert reached == [True] and not report['model_operations'] and not report['final_test_executed']
