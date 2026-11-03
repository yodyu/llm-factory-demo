"""CSV and simulation share four-role generation, comparison and frozen evaluation."""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from contracts.metrics import MetricPoint, MetricsDataset
from factory.metrics.data import encode_csv, load_role
from factory.metrics.upload import prepare_upload, simple_upload_options, comparison_split
from factory.metrics.workflow import run, trusted_labels
from factory.metrics.evaluation import select_development


def inputs():
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    points = [MetricPoint(timestamp=start+timedelta(minutes=i), host_id='normalized-host',
        value=None if 330 <= i < 336 else 95.0 if 220 <= i < 225 or 360 <= i < 365 else 35.0 + (i % 3)*0.1)
        for i in range(440)]
    labels = ('timestamp,host_id,is_anomaly\n' + ''.join(
        f"{p.timestamp.isoformat()},{p.host_id},{int(220 <= i < 225 or 360 <= i < 365)}\n"
        for i, p in enumerate(points) if i >= 200)).encode()
    return encode_csv(points), labels


@pytest.mark.parametrize('labelled', [True, False])
def test_normalization_disjoint_roles_labels_and_history(tmp_path, labelled):
    raw, labels = inputs()
    summary = prepare_upload(tmp_path/'data', raw, labels=labels if labelled else None,
        label_source='private-source-marker', **simple_upload_options(raw, scenario='cpu_spike', display_name='cpu.csv'))
    manifest = MetricsDataset.model_validate_json((tmp_path/'data/manifest.json').read_text())
    development = load_role(tmp_path/'data', manifest, 'development')
    test = load_role(tmp_path/'data', manifest, 'test')
    dev_labels, dev_hash = trusted_labels(tmp_path/'data', manifest, 'development')
    test_labels, test_hash = trusted_labels(tmp_path/'data', manifest, 'test')
    assert dev_hash == test_hash
    assert summary['pipeline'] == 'four-role-comparison/1'
    assert summary['development_points'] == summary['test_points'] == 120
    assert set(manifest.roles) == {'train','calibration','development','test'}
    assert len(development) == len(test) == 180
    assert development[-1].timestamp < test[60].timestamp
    assert {p.timestamp for p in development[60:]}.isdisjoint(p.timestamp for p in test[60:])
    assert development[-60:] == test[:60]  # preceding warmup, not shared scoring data
    if labelled:
        assert sum(dev_labels) == sum(test_labels) == 5
        assert not any(dev_labels[:60]) and not any(test_labels[:60])
    else:
        assert dev_labels is None and test_labels is None


def test_split_is_chronological_not_label_driven():
    assert comparison_split(441) == {'development_end':320,'development_points':120,'test_points':121}
    with pytest.raises(ValueError, match='202'):
        comparison_split(201)


def test_engineering_selection_never_uses_alarm_count_as_accuracy():
    def candidate(cid, coverage, runtime):
        return {'candidate_id':cid,'role':'development','report':{'execution_status':'SUCCEEDED',
            'engineering_status':'PASSED','effect_status':'NOT_EVALUATED',
            'coverage':{'value':coverage},'runtime_seconds':runtime}}
    result = select_development([candidate('fixed',1.0,0.5), candidate('mad',0.99,0.1)])
    assert result['selected'] == 'fixed' and result['basis'] == 'engineering_only'
    assert '未验证检测效果' in result['reason']


def test_normal_only_labels_do_not_prefer_false_alarms_over_undefined_f1():
    def candidate(cid, fp):
        return {'candidate_id':cid,'role':'development','report':{'execution_status':'SUCCEEDED',
            'engineering_status':'PASSED','effect_status':'MEASURED','event':{'tp':0,'fn':0,'fp':fp,
            'f1':{'value':0 if fp else None}},'normal_false_alarms_per_host_hour':{'value':float(fp)},
            'coverage':{'value':1.0},'runtime_seconds':0.1}}
    selected = select_development([candidate('no_alarm',0),candidate('false_alarm',1)])
    assert selected['selected'] == 'no_alarm'
    assert selected['basis'] == 'normal_only_development'
    assert '未验证异常召回能力' in selected['reason']


@pytest.mark.parametrize('labelled', [True, False])
def test_csv_shared_workflow_compares_both_and_only_tests_winner(tmp_path, labelled):
    from factory.metrics.runtime import MetricsStore
    from factory.metrics.model import make_gateway
    from factory.metrics.knowledge import LegacySQLiteKnowledgeStore
    from factory.metrics.reports import export_run
    from factory.metrics.replay import replay_bundle
    from factory.runtime.artifacts import digest
    image = os.environ.get('FACTORY_METRICS_IMAGE', os.environ.get('METRICS_DOCKER_IMAGE'))
    if not image:
        pytest.skip('需要设置 FACTORY_METRICS_IMAGE')
    raw, labels = inputs()
    data = tmp_path/'data'
    prepare_upload(data, raw, labels=labels if labelled else None, label_source='private-source-marker',
        **simple_upload_options(raw, scenario='cpu_spike', display_name='cpu.csv'))
    state = tmp_path/'state'
    store = MetricsStore(state/'runtime.sqlite')
    gateway = make_gateway(store, mode='mock')
    knowledge = LegacySQLiteKnowledgeStore(tmp_path/'knowledge.sqlite')
    outcome = asyncio.run(run(store,gateway,state=state,dataset_root=data,snapshot=knowledge.snapshot(),knowledge=knowledge,
        image=image,task_id='csv-comparison',task_input={'requirement':'检测CPU异常升高并比较两种方法',
        'anomaly_target':'upper','explicit_constraints':{'threshold':85.0,'direction':'upper','persistence_points':2.0}}))
    directory = Path(outcome['directory'])
    report = json.loads((directory/'report.json').read_text())
    assert report['status'] == 'COMPLETED', report.get('failure')
    assert {c['plan']['config']['method_id'] for c in report['candidates']} == {'fixed_threshold','rolling_mad'}
    assert all(c['role'] == 'development' for c in report['candidates'])
    assert len(report['selection']['ranking']) == 2
    assert report['selection']['basis'] == ('labelled_development' if labelled else 'engineering_only')
    assert report['final']['phase'] == 'test'
    assert report['benchmark']['execution_status'] == 'SUCCEEDED'
    if labelled:
        assert all(c['report']['point']['total'] == 120 for c in report['candidates'])
        assert report['final']['point']['total'] == 120
        assert len(report['final']['truth_events']) == 1
        assert report['final']['point']['tp'] + report['final']['point']['fn'] == 5
    else:
        assert report['final']['effect_status'] == 'NOT_EVALUATED'
        assert 'event' not in report['final']
    with store._transaction() as db:
        operations = [r[0] for r in db.execute("SELECT operation_id FROM operations WHERE resource='metrics-code'")]
        prompts = [store.document(r[0]) for r in db.execute("SELECT reference FROM task_artifacts WHERE role='model-prompt'")]
    assert sum(':final-test' in op for op in operations) == 1
    assert sum(':development-' in op for op in operations) == 2
    text = json.dumps(prompts)
    assert 'private-source-marker' not in text and 'user-labels' not in text and '2026-11-01T06:00' not in text
    receipt = json.loads((directory/'publication.json').read_text())
    assert receipt['status'] == 'PUBLISHED'
    from factory.metrics.publication import publish_pending
    published = knowledge.snapshot()
    assert publish_pending(store, knowledge, report) == receipt
    assert knowledge.snapshot() == published
    experiences = [n['payload'] for n in published['nodes'] if n['kind'] == 'Experience']
    assert len(experiences) == 2
    selected = next(e for e in experiences if e['reusable_implementation'])
    assert selected['effect_status'] == ('MEASURED' if labelled else 'NOT_EVALUATED')
    bundle=tmp_path/'delivery.zip'
    export_run(store,directory,bundle,dataset_root=data)
    # New canonical upload bundles remain replayable without a model or re-selection.
    replay = replay_bundle(bundle,digest(bundle.read_bytes()),state=tmp_path/'replay',image=image)
    assert replay['status'] == 'COMPLETED', replay
    assert replay['effect_matches_recorded'] is True

@pytest.mark.parametrize('labelled,policy,criteria', [
    (False, 'balanced', {}), (False, 'precision', {}), (False, 'recall', {}),
    (False, 'recall', {'min_event_recall': .9}),
    (True, 'recall', {'min_event_recall': .9}),
])
def test_effect_goals_survive_actual_task_graph(tmp_path, labelled, policy, criteria):
    from factory.metrics.runtime import MetricsStore
    from factory.metrics.model import make_gateway
    from factory.metrics.knowledge import LegacySQLiteKnowledgeStore
    from factory.metrics.evaluation import acceptance_result
    from contracts.metrics_requirement import AcceptanceCriteria
    from factory.metrics.review import result_outcome
    image = os.environ.get('FACTORY_METRICS_IMAGE', os.environ.get('METRICS_DOCKER_IMAGE'))
    if not image:
        pytest.skip('需要设置 FACTORY_METRICS_IMAGE；模型为 mock')
    raw, labels = inputs()
    data, state = tmp_path/'data', tmp_path/'state'
    prepare_upload(data, raw, labels=labels if labelled else None, label_source='controlled regression labels',
        **simple_upload_options(raw, scenario='cpu_spike', display_name='cpu.csv'))
    store = MetricsStore(state/'runtime.sqlite')
    knowledge = LegacySQLiteKnowledgeStore(tmp_path/'knowledge.sqlite')
    from factory.metrics.requirements import build_draft, controlled_extract, request_from_draft
    text = '上传CSV，CPU升高，超过85%，' + {'balanced':'比较两种方法', 'precision':'尽量少误报', 'recall':'尽量少漏报'}[policy]
    if criteria:
        text += '，召回率不低于90%'
    draft = build_draft([text], [controlled_extract(text)], binding='controlled-input',
                        upload_present=True, labels_present=labelled)
    request = request_from_draft(draft, current_binding=draft.binding).model_dump(mode='json')
    outcome = asyncio.run(run(store, make_gateway(store,mode='mock'), state=state, dataset_root=data,
        snapshot=knowledge.snapshot(), knowledge=knowledge, image=image, task_id='effect-goal', task_input=request))
    directory = Path(outcome['directory'])
    report = json.loads((directory/'report.json').read_text())
    assert report['status'] == 'COMPLETED', report.get('failure')
    frozen = json.loads((directory/'task.json').read_text())
    assert frozen == report['task']
    assert frozen['requirement'] == request['requirement'] and frozen['selection_policy'] == policy
    assert frozen['acceptance_criteria'] == AcceptanceCriteria(**criteria).model_dump()
    assert report['requirement_understanding'] == draft.model_dump(mode='json')
    markdown = (directory/'report.md').read_text()
    assert request['requirement'] in markdown and policy in markdown
    assert report['business_acceptance'] == acceptance_result(report['final'], AcceptanceCriteria(**criteria))
    with store._transaction() as db:
        ref = db.execute("SELECT evidence_ref FROM phase_history WHERE task_id=? AND phase='COMPLETED'",
                         ('effect-goal',)).fetchone()[0]
    assert store.document(ref)['acceptance_status'] == report['final']['acceptance_status']
    assert report['final_test_executed'] and result_outcome(report)['succeeded']
    if not labelled:
        assert report['selection']['basis'] == 'engineering_only'
        assert report['final']['effect_status'] == 'NOT_EVALUATED'
        assert not {'point','event','normal_false_alarms_per_host_hour'} & report['final'].keys()
        if policy != 'balanced':
            assert report['selection']['warnings']
        if criteria:
            assert report['business_acceptance']['status'] == 'NOT_EVALUATED'
        assert not result_outcome(report)['measured']
    else:
        assert report['selection']['basis'] == 'labelled_development'
        assert report['final']['effect_status'] == 'MEASURED'
        assert report['business_acceptance']['status'] in {'PASSED','FAILED'}
    experiences = [n['payload'] for n in knowledge.snapshot()['nodes'] if n['kind']=='Experience']
    reusable = next(e for e in experiences if e['reusable_implementation'])
    assert reusable['effect_status'] == report['final']['effect_status']
    if criteria:
        assert reusable['acceptance_status'] == report['business_acceptance']['status']


@pytest.mark.parametrize('fault', ['source', 'method'])
def test_unlabelled_effect_goal_never_hides_code_or_method_failure(tmp_path, monkeypatch, fault):
    from contracts.metrics_knowledge import GeneratedCode
    from factory.metrics.runtime import MetricsStore
    from factory.metrics.model import make_gateway
    from factory.metrics.knowledge import LegacySQLiteKnowledgeStore
    image = os.environ.get('FACTORY_METRICS_IMAGE', os.environ.get('METRICS_DOCKER_IMAGE'))
    if not image:
        pytest.skip('需要设置 FACTORY_METRICS_IMAGE；使用受控源码')
    raw, _ = inputs()
    data, state = tmp_path/'data', tmp_path/'state'
    prepare_upload(data, raw, **simple_upload_options(raw, scenario='cpu_spike', display_name='cpu.csv'))
    source = 'import os\n' if fault == 'source' else (
        Path(__file__).resolve().parents[2]/'materials/metrics/reference_fixed.py').read_text().replace(
            'value - self.config["threshold"]', 'value + self.config["threshold"]')
    async def faulty(*a, **kw):
        return GeneratedCode(source=source, knowledge_ids=[], explanation='controlled failure')
    monkeypatch.setattr('factory.metrics.workflow.generate', faulty)
    store = MetricsStore(state/'runtime.sqlite')
    knowledge = LegacySQLiteKnowledgeStore(tmp_path/'knowledge.sqlite')
    outcome = asyncio.run(run(store, make_gateway(store,mode='mock'), state=state, dataset_root=data,
        snapshot=knowledge.snapshot(), knowledge=knowledge, image=image, task_id='failed-goal',
        task_input={'requirement':'CPU升高，尽量少误报', 'anomaly_target':'upper',
                    'allowed_methods':['fixed_threshold'], 'explicit_constraints':{'threshold':85.},
                    'selection_policy':'precision', 'budgets':{'repair_rounds':0}}))
    report = json.loads((Path(outcome['directory'])/'report.json').read_text())
    assert report['status'] == 'FAILED' and not report['final_test_executed']
    assert not report.get('final') and report['selection']['selected'] is None
    assert all(not c['versions'][-1]['validation']['passed'] for c in report['candidates'])
