"""Recover cosmetic/model-output failures without inventing evaluation success."""
import asyncio
import json
import os
from pathlib import Path

import pytest

from contracts.metrics_knowledge import GeneratedCode
from contracts.metrics_requirement import AcceptanceCriteria
from factory.metrics.evaluation import select_development, acceptance_result
from factory.metrics.requirements import build_draft, controlled_extract
from tests.metrics.test_runtime import task


def candidate(cid='fixed', *, labelled=True, engineering='PASSED'):
    result={'execution_status':'SUCCEEDED','engineering_status':engineering,
            'effect_status':'MEASURED' if labelled else 'NOT_EVALUATED',
            'coverage':{'value':.8 if engineering=='COVERAGE_FAILED' else 1.0},'runtime_seconds':.1}
    if labelled:
        result.update(event={'tp':2,'fp':1,'fn':1,'f1':{'value':2/3},'recall':{'value':2/3}},
                      normal_false_alarms_per_host_hour={'value':.25})
    return {'candidate_id':cid,'role':'development','report':result}


def test_unmet_gate_produces_best_proposal_but_never_passes_acceptance():
    item=candidate()
    criteria=AcceptanceCriteria(min_event_f1=1)
    result=select_development([item],acceptance=criteria)
    assert result['selected']=='fixed' and result['warnings']
    assert acceptance_result(item['report'],criteria)['status']=='FAILED'
    assert select_development([item],acceptance=criteria,strict=True)['selected'] is None


def test_unlabelled_preference_and_low_coverage_produce_explicit_warnings():
    item=candidate(labelled=False,engineering='COVERAGE_FAILED')
    result=select_development([item],policy='recall',acceptance=AcceptanceCriteria(min_event_f1=.9))
    assert result['selected']=='fixed' and result['basis']=='engineering_only'
    assert item['report']['engineering_status']=='COVERAGE_FAILED'
    assert len(result['warnings'])>=3
    assert acceptance_result(item['report'],AcceptanceCriteria(min_event_f1=.9))['status']=='NOT_EVALUATED'


def test_demo_does_not_rank_execution_or_method_failures():
    item=candidate()
    item['report']['engineering_status']='FAILED'
    assert select_development([item])['selected'] is None
    with pytest.raises(ValueError,match='development'):
        select_development([{**candidate(),'role':'test'}])


def test_optional_capabilities_and_missing_labels_are_advisories():
    text='上传CSV的CPU升高，比较固定阈值和MAD，希望根因定位和Isolation Forest，召回率不低于90%'
    draft=build_draft([text],[controlled_extract(text)],binding='demo',upload_present=True)
    assert not draft.issues and any('演示提示' in x for x in draft.defaults)
    assert draft.values['min_event_recall']==.9


def test_unknown_generated_citations_are_disclosed_and_removed_not_code_replaced():
    from factory.metrics.generation import generate
    from contracts.metrics import CandidatePlan,FixedConfig
    source='def create_detector(config):\n    return None\n'
    class Gateway:
        async def ask(self,*a,**kw):
            return GeneratedCode(source=source,knowledge_ids=['sent','invented'],explanation='model output')
    result=asyncio.run(generate(Gateway(),task(),CandidatePlan(candidate_id='fixed',config=FixedConfig(threshold=85),
        parameter_sources={},knowledge_ids=[],limitations=[]),{'knowledge':{'knowledge_ids':['sent']}},version=0))
    assert result.source==source and result.knowledge_ids==['sent']
    assert 'invented' in result.explanation and '演示纠正' in result.explanation


def test_plan_field_error_has_one_bounded_correction():
    from factory.metrics.planning import plan
    from tests.metrics.test_planning import output_for
    class Gateway:
        def __init__(self):self.stages=[]
        async def ask(self,tid,stage,*a,**kw):
            self.stages.append(stage)
            return output_for('lower' if len(self.stages)==1 else 'upper')
    gateway=Gateway()
    result=asyncio.run(plan(gateway,task(),{}, {'knowledge_ids':[]}))
    assert result.anomaly_target=='upper' and gateway.stages==['plan','plan-correction-1']


@pytest.mark.parametrize('failure_stage', ['code', 'planning'])
def test_failed_candidates_yield_unverified_plan_not_fake_detection(tmp_path,monkeypatch,failure_stage):
    from factory.metrics.synthetic import generate,write_dataset
    from factory.metrics.knowledge import LegacySQLiteKnowledgeStore
    from factory.metrics.runtime import MetricsStore
    from factory.metrics.model import make_gateway
    from factory.metrics.workflow import run
    from execution.metrics_runner import MetricsRunner
    image=os.environ.get('FACTORY_METRICS_IMAGE', os.environ.get('METRICS_DOCKER_IMAGE'))
    if not image:
        pytest.skip('需要设置 FACTORY_METRICS_IMAGE')
    data=tmp_path/'data'
    write_dataset(data,generate('cpu_spike'))
    state=tmp_path/'state'
    store=MetricsStore(state/'runtime.sqlite')
    gateway=make_gateway(store,mode='mock')
    knowledge=LegacySQLiteKnowledgeStore(tmp_path/'knowledge.sqlite')
    if failure_stage == 'planning':
        async def unavailable(*a,**kw):raise ValueError('controlled model unavailable')
        gateway.ask=unavailable
    async def unsafe(*a,**kw):return GeneratedCode(source='import os\n',knowledge_ids=[],explanation='controlled unsafe sample')
    monkeypatch.setattr('factory.metrics.workflow.generate',unsafe)
    monkeypatch.setattr(MetricsRunner,'detector',lambda *a,**kw: (_ for _ in ()).throw(AssertionError('unsafe code must not run')))
    outcome=asyncio.run(run(store,gateway,state=state,dataset_root=data,snapshot=knowledge.snapshot(),knowledge=knowledge,
        image=image,task_id='plan-only',task_input={'requirement':'CPU升高','anomaly_target':'upper',
        'explicit_constraints':{'threshold':85.0},'budgets':{'repair_rounds':0}}))
    report=json.loads((Path(outcome['directory'])/'report.json').read_text())
    assert outcome['status']=='PLAN_ONLY' and not report['final_test_executed']
    assert len(report['proposal']['candidates'])==2 and report.get('final') is None
    from factory.metrics.review import result_outcome
    view=result_outcome(report)
    assert view['level']=='warning' and not view['succeeded'] and not view['measured']
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('FACTORY_METRICS_STATE',str(state))
    monkeypatch.setenv('FACTORY_METRICS_KNOWLEDGE',str(knowledge.path))
    page=AppTest.from_file(Path(__file__).resolve().parents[2]/'streamlit_app.py')
    page.session_state['page']='结果概览'
    page.run(timeout=20)
    assert not page.exception
    assert any('方案草稿' in w.value for w in page.warning)
    methods = {value for table in page.table if '方法' in table.value for value in table.value['方法']}
    assert {'固定阈值', '滚动 MAD'} <= methods
    assert any('fixed_threshold' in str(item.value) and 'rolling_mad' in str(item.value) for item in page.json)
    assert [m.value for m in page.metric]==['—']*4


def test_demo_end_to_end_unknown_citations_and_unmet_goal_still_complete(tmp_path):
    from factory.metrics.synthetic import generate,write_dataset
    from factory.metrics.knowledge import LegacySQLiteKnowledgeStore
    from factory.metrics.runtime import MetricsStore
    from factory.metrics.model import make_gateway
    from factory.metrics.workflow import run
    from factory.metrics.review import result_outcome
    image=os.environ.get('FACTORY_METRICS_IMAGE', os.environ.get('METRICS_DOCKER_IMAGE'))
    if not image:
        pytest.skip('需要设置 FACTORY_METRICS_IMAGE')
    data=tmp_path/'data'
    write_dataset(data,generate('cpu_spike'))
    state=tmp_path/'state'
    store=MetricsStore(state/'runtime.sqlite')
    gateway=make_gateway(store,mode='mock')
    knowledge=LegacySQLiteKnowledgeStore(tmp_path/'knowledge.sqlite')
    ask=gateway.ask
    async def with_bad_citation(tid,stage,*a,**kw):
        result=await ask(tid,stage,*a,**kw)
        return result.model_copy(update={'knowledge_ids':['not-provided']}) if stage.startswith('code-') else result
    gateway.ask=with_bad_citation
    outcome=asyncio.run(run(store,gateway,state=state,dataset_root=data,snapshot=knowledge.snapshot(),knowledge=knowledge,
        image=image,task_id='demo-complete',task_input={'requirement':'CPU升高，F1达到1', 'anomaly_target':'upper',
        'explicit_constraints':{'threshold':85.0},'acceptance_criteria':{'min_event_f1':1.0}}))
    report=json.loads((Path(outcome['directory'])/'report.json').read_text())
    assert report['status']=='COMPLETED' and report['final_test_executed']
    assert report['business_acceptance']['status']=='FAILED'
    assert report['selection']['selected'] and report['selection']['warnings']
    assert result_outcome(report)['level']=='warning'
    for c in report['candidates']:
        assert c['versions'][0]['knowledge_ids']==[]
        assert '演示纠正' in c['versions'][0]['explanation']


def test_explicit_strict_entry_still_requires_measured_acceptance():
    item = candidate(labelled=False)
    assert select_development([item], acceptance=AcceptanceCriteria(min_event_recall=.9), strict=True)['selected'] is None
    with pytest.raises(ValueError, match='labels'):
        select_development([item], policy='precision', strict=True)
