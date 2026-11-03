"""Real Neo4j integration; missing configuration is an explicit skip, never acceptance."""
import asyncio
import copy
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from factory.metrics.knowledge import LegacySQLiteKnowledgeStore, checked_extraction, import_material, retrieve
from factory.metrics.neo4j_store import Neo4jKnowledgeStore, KnowledgeUnavailable
from factory.metrics.knowledge_migration import migrate
from factory.metrics.publication import publish, publish_pending
from factory.metrics.runtime import MetricsStore
from tests.metrics.test_knowledge import extracted


@pytest.fixture
def graph():
    config=os.environ.get('FACTORY_NEO4J_CONFIG', os.environ.get('METRICS_NEO4J_CONFIG'))
    if not config:
        pytest.skip('需要设置 FACTORY_NEO4J_CONFIG')
    c=json.loads(Path(config).read_text())
    auth=Path(c['auth_file']).read_text().strip().split('/',1)
    graph=Neo4jKnowledgeStore(c['uri'],tuple(auth),namespace='metrics-test-'+uuid4().hex,database=c.get('database','neo4j'))
    graph.initialize()
    yield graph
    graph._execute(lambda tx:tx.run('MATCH (n) WHERE n.namespace=$ns DETACH DELETE n',ns=graph.namespace).consume(),write=True)
    graph.close()


def material(tmp_path, origin='mock', **overrides):
    (tmp_path/'material.txt').write_text('MAD needs past history; memory gauge single host\n')
    source,chunks=import_material(tmp_path,'material.txt')
    return checked_extraction(source,chunks,extracted(source,chunks,**overrides),origin=origin,response_evidence={})


def conditions(**changes):
    return dict(requirement='内存 memory MAD',metric_kind='gauge',allowed_methods=['fixed_threshold','rolling_mad'],history_points=60,origin='mock',**changes)


def test_real_schema_edges_conflicts_idempotency_and_stable_freeze(graph,tmp_path):
    nodes,relations=material(tmp_path)
    graph.add(nodes,relations)
    frozen,result=graph.freeze(**conditions())
    assert result==retrieve(frozen,**conditions()) and result['chunks']
    graph.add(nodes,relations)
    assert graph.snapshot()==frozen
    props=graph._execute(lambda tx:dict(tx.run('MATCH (n:Capability {namespace:$ns}) RETURN n.method_id AS method,n.single_host AS single,n.metric_kinds AS metrics,n.verification_status AS status',ns=graph.namespace).single()))
    assert props==dict(method='rolling_mad',single=True,metrics=['gauge'],status='extracted_unverified')
    changed=copy.deepcopy(nodes)
    changed[0]['payload']['path']='other.txt'
    with pytest.raises(ValueError,match='conflict'):
        graph.add(changed,relations)
    changed=copy.deepcopy(relations)
    changed[0]['provenance']={'changed':True}
    with pytest.raises(ValueError,match='relationship conflict'):
        graph.add(nodes,changed)
    with pytest.raises(ValueError,match='endpoints'):
        graph.add([], [{'source':'missing','target':nodes[0]['id'],'relation':'DERIVED_FROM','provenance':{}}])
    assert graph.snapshot()==frozen
    graph.add(*material(tmp_path,origin='llm_api'))
    assert frozen['snapshot_id']!=graph.snapshot()['snapshot_id']
    assert retrieve(frozen,**conditions())==result


def test_real_condition_parity_and_citation_validation(graph,tmp_path):
    nodes,relations=material(tmp_path)
    graph.add(nodes,relations)
    for metric in ('gauge','rate'):
        for history in (5,60):
            for origin in ('mock','llm_api'):
                for methods in (['fixed_threshold'],['rolling_mad']):
                    c=conditions()
                    c.update(metric_kind=metric,history_points=history,origin=origin,allowed_methods=methods)
                    snapshot,result=graph.freeze(**c)
                    assert result==retrieve(snapshot,**c)
    broken=copy.deepcopy(nodes)
    cap=next(n for n in broken if n['kind']=='Capability')
    cap['payload']['citations'][0]['quote']='invented quote'
    from factory.metrics.knowledge import identity
    cap['id']=identity('capability',cap['payload'])
    edges=copy.deepcopy(relations)
    for edge in edges:
        if edge['source']==next(n['id'] for n in nodes if n['kind']=='Capability'):
            edge['source']=cap['id']
    with pytest.raises(ValueError,match='citation'):
        graph.add(broken,edges)
    assert not graph.details([cap['id']])


def test_real_migration_preserves_source_repeat_and_retrieval(graph,tmp_path):
    old=LegacySQLiteKnowledgeStore(tmp_path/'old.sqlite')
    old.add(*material(tmp_path))
    original=(tmp_path/'old.sqlite').read_bytes()
    first=migrate(tmp_path/'old.sqlite',tmp_path/'backup1',graph)
    second=migrate(tmp_path/'old.sqlite',tmp_path/'backup2',graph)
    assert first['all_queries_equal'] and second['all_queries_equal']
    assert second['nodes_added']==0 and first['target_snapshot_id']==second['target_snapshot_id']
    assert original==(tmp_path/'old.sqlite').read_bytes()
    report=tmp_path/'snapshot.json'
    report.write_text(json.dumps(old.snapshot()))
    third=migrate(report,tmp_path/'backup3',graph)
    assert third['source_snapshot_id']==first['source_snapshot_id']


def report_fixture():
    return json.loads((Path(__file__).resolve().parents[2]/'case-example/metrics/delivery/real-memory-v1/report.json').read_text())


@pytest.mark.parametrize('source', ['builtin_simulation', 'uploaded_csv'])
def test_real_publication_and_receipt_failure_recovery_no_new_execution(graph,tmp_path,monkeypatch,source):
    from contracts.metrics import MetricsTask
    report=report_fixture()
    report['data_source'] = {'type': source}
    store=MetricsStore(tmp_path/'runtime.sqlite')
    store.create_task(MetricsTask.model_validate(report['task']))
    original=store.register_document
    def fail_receipt(task_id,payload,role):
        if role=='knowledge-publication-receipt':
            raise OSError('controlled local receipt failure')
        return original(task_id,payload,role)
    monkeypatch.setattr(store,'register_document',fail_receipt)
    pending=publish_pending(store,graph,report)
    assert pending['status']=='PENDING_RETRY'
    frozen=graph.snapshot()
    overview=graph.local_graph(limit=100)
    assert {n['kind'] for n in overview['nodes']} == {n['kind'] for n in frozen['nodes']}
    assert any(n['kind']=='Experience' for n in frozen['nodes'])
    monkeypatch.setattr(store,'register_document',original)
    receipt=publish_pending(store,graph,report)
    assert receipt['status']=='PUBLISHED' and publish_pending(store,graph,report)==receipt
    assert graph.snapshot()==frozen
    with store._transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM operations WHERE resource='model'").fetchone()[0]==0
        assert db.execute("SELECT status FROM operations WHERE resource='knowledge-publication'").fetchone()[0]=='SUCCEEDED'
    for n in frozen['nodes']:
        if n['kind']=='Experience':
            value=n['payload']
            assert 'final' not in value
    result=retrieve(frozen,requirement='memory',metric_kind='gauge',allowed_methods=['fixed_threshold','rolling_mad'],history_points=60)
    assert all('final' not in e and isinstance(e['development_feedback'], list) for e in result['experiences'])
    failed=[e for e in result['experiences'] if not e['reusable_implementation']]
    assert all(e['effect_status']=='NOT_QUALIFIED_FOR_REUSE' for e in failed)


def test_missing_neo4j_is_an_error_not_empty_snapshot():
    graph=Neo4jKnowledgeStore('bolt://127.0.0.1:1',('test','test-password'),namespace='test-offline')
    try:
        with pytest.raises(KnowledgeUnavailable,match='UNAVAILABLE'):
            graph.snapshot()
    finally:
        graph.close()


def test_graph_ui_live_details_empty_and_failure_are_readonly(graph,tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    graph.add(*material(tmp_path))
    before=graph.snapshot()
    monkeypatch.setattr('factory.metrics.knowledge_store.open_knowledge',lambda config:graph)
    monkeypatch.setattr(graph,'close',lambda:None)
    script="from factory.metrics.graph_view import show_graph\nshow_graph('unused', '"+str(tmp_path)+"')"
    app=AppTest.from_string(script).run(timeout=20)
    assert not app.exception and app.selectbox[0].label=='查看范围'
    assert not app.text_input and not app.slider
    app.selectbox(key='graph_method').set_value('fixed_threshold').run()
    assert any('没有匹配实体' in x.value for x in app.info)
    def unavailable(*args,**kwargs):raise KnowledgeUnavailable('controlled')
    monkeypatch.setattr(graph,'local_graph',unavailable)
    app.run()
    assert any('连接或配置不可用' in x.value for x in app.error)
    assert graph.snapshot()==before


def test_real_neo4j_full_mock_workflow_export_offline_replay(graph,tmp_path):
    image=os.environ.get('FACTORY_METRICS_IMAGE', os.environ.get('METRICS_DOCKER_IMAGE'))
    if not image:
        pytest.skip('需要设置 FACTORY_METRICS_IMAGE')
    from factory.metrics.model import make_gateway
    from factory.metrics.synthetic import generate,write_dataset
    from factory.metrics.workflow import run
    from factory.metrics.reports import export_run
    from factory.metrics.replay import replay_bundle
    graph.add(*material(tmp_path))
    data=tmp_path/'data'
    write_dataset(data,generate('memory_shift'))
    store=MetricsStore(tmp_path/'state/runtime.sqlite')
    gateway=make_gateway(store,mode='mock')
    snapshot,retrieval=graph.freeze(**conditions())
    result=asyncio.run(run(store,gateway,state=tmp_path/'state',task_input={'requirement':'内存 memory MAD','anomaly_target':'upper','explicit_constraints':{'threshold':85.0}},
        dataset_root=data,snapshot=snapshot,knowledge=graph,image=image,frozen_retrieval=retrieval))
    assert result['status']=='COMPLETED' and result['publication']['status']=='PUBLISHED',result
    folder=Path(result['directory'])
    report=json.loads((folder/'report.json').read_text())
    assert report['knowledge_snapshot']==snapshot and report['retrieval']==retrieval
    output=tmp_path/'export.zip'
    exported=export_run(store,folder,output,dataset_root=data)
    # Replay has no repository/config argument; does not even instantiate a Neo4j driver.
    replay=replay_bundle(output,exported['sha256'],state=tmp_path/'replay',image=image)
    assert replay['model_calls']==0 and replay['effect_matches_recorded']


def test_frozen_task_continues_with_unreachable_graph_then_retries(graph,tmp_path):
    image=os.environ.get('FACTORY_METRICS_IMAGE', os.environ.get('METRICS_DOCKER_IMAGE'))
    if not image:
        pytest.skip('需要设置 FACTORY_METRICS_IMAGE')
    from factory.metrics.model import make_gateway
    from factory.metrics.synthetic import generate,write_dataset
    from factory.metrics.workflow import run
    graph.add(*material(tmp_path))
    frozen,retrieval=graph.freeze(**conditions())
    unavailable=Neo4jKnowledgeStore('bolt://127.0.0.1:1',('test','test-password'),namespace=graph.namespace)
    data=tmp_path/'data'
    write_dataset(data,generate('memory_shift'))
    store=MetricsStore(tmp_path/'state/runtime.sqlite')
    gateway=make_gateway(store,mode='mock')
    try:
        result=asyncio.run(run(store,gateway,state=tmp_path/'state',task_input={'requirement':'内存 memory MAD','anomaly_target':'upper','explicit_constraints':{'threshold':85.0}},
            dataset_root=data,snapshot=frozen,knowledge=unavailable,image=image,frozen_retrieval=retrieval))
        assert result['status']=='COMPLETED' and result['publication']['status']=='PENDING_RETRY'
        report=json.loads((Path(result['directory'])/'report.json').read_text())
        with store._transaction() as db:
            count=db.execute('SELECT COUNT(*) FROM operations').fetchone()[0]
        assert publish_pending(store,graph,report)['status']=='PUBLISHED'
        with store._transaction() as db:
            assert db.execute('SELECT COUNT(*) FROM operations').fetchone()[0]==count
        assert report['knowledge_snapshot']==frozen
    finally:
        unavailable.close()


def test_experience_model_view_is_allowlisted_even_for_legacy_payload():
    from factory.metrics.neo4j_store import snapshot_value
    payload={'method_id':'fixed_threshold','metric_kind':'gauge','origin':'mock','reusable_implementation':False,
             'final':{'labels':['DO_NOT_SEND'],'precision':1},'input':'DO_NOT_SEND','metrics':{'f1':1}}
    snapshot=snapshot_value([{'id':'risk','kind':'Experience','payload':payload}],[])
    view=retrieve(snapshot,**conditions())
    assert view['experiences'] and 'DO_NOT_SEND' not in json.dumps(view)


def test_real_reextraction_reuses_immutable_source_edges_with_explicit_evidence(graph,tmp_path):
    from factory.metrics.knowledge import ingest
    from factory.metrics.model import make_gateway
    from tests.metrics.test_runtime import task
    graph.add(*material(tmp_path))
    old=graph.snapshot()
    store=MetricsStore(tmp_path/'runtime.sqlite')
    gateway=make_gateway(store,mode='mock')
    store.create_task(task(model_profile_id=gateway.client.profile.profile_id))
    result=asyncio.run(ingest(tmp_path,['material.txt'],graph,gateway,'metrics-1',origin='mock'))
    assert result['sources'][0]['status']=='source_checked'
    assert result['sources'][0]['reused_immutable_source_edges']
    current=graph.snapshot()
    assert all(r in current['relations'] for r in old['relations'])


def test_successful_experience_requires_real_graph_evidence(graph):
    report=report_fixture()
    publish(graph,report)
    graph._execute(lambda tx:tx.run("MATCH (e:Experience {namespace:$ns})-[r:LEARNED_FROM]->() WHERE e.reusable_implementation=true DELETE r",ns=graph.namespace).consume(),write=True)
    c=conditions()
    c['origin']='llm_api'
    with pytest.raises(ValueError,match='graph evidence incomplete'):
        graph.freeze(**c)


def test_concurrent_graph_update_rejects_inconsistent_freeze(graph,tmp_path,monkeypatch):
    graph.add(*material(tmp_path))
    original=graph._snapshot
    def changed(tx):
        snapshot=original(tx)
        graph.add(*material(tmp_path,origin='llm_api'))
        return snapshot
    monkeypatch.setattr(graph,'_snapshot',changed)
    with pytest.raises((KnowledgeUnavailable,ValueError)):
        graph.freeze(**conditions())


def test_service_resolves_trusted_deployment_alias_before_docker(graph,tmp_path):
    image=os.environ.get('FACTORY_METRICS_IMAGE', os.environ.get('METRICS_DOCKER_IMAGE'))
    if not image:
        pytest.skip('需要设置 FACTORY_METRICS_IMAGE')
    from types import SimpleNamespace
    from factory.metrics.service import run_command
    from factory.metrics.synthetic import generate,write_dataset
    config_path = os.environ.get('FACTORY_NEO4J_CONFIG', os.environ.get('METRICS_NEO4J_CONFIG'))
    source_config = json.loads(Path(config_path).read_text())
    source_config['namespace'] = graph.namespace
    config=tmp_path/'config.json'
    config.write_text(json.dumps(source_config))
    real=tmp_path/'real'
    real.mkdir()
    alias=tmp_path/'alias'
    alias.symlink_to(real,target_is_directory=True)
    data=tmp_path/'data'
    write_dataset(data,generate('memory_shift'))
    request=tmp_path/'request.json'
    request.write_text(json.dumps({'requirement':'检测内存升高','anomaly_target':'upper','explicit_constraints':{'threshold':85.0}}))
    args=SimpleNamespace(knowledge=config,task=request,dataset=data,state=alias/'state',mode='mock',retrieval='structured',campaign=None,env_file=None,image=image,task_id='trusted-alias',fault_injection=False)
    result=asyncio.run(run_command(args))
    assert result['status']=='COMPLETED' and result['publication']['status']=='PUBLISHED'
    assert Path(result['directory']).is_relative_to(real)
    report = json.loads((Path(result['directory']) / 'report.json').read_text())
    assert report['generation_protocol'] == 'capability-generation/2'
    assert all(c['versions'][-1]['specification_sha256'] for c in report['candidates'])
