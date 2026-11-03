"""Frozen cases and explicitly controlled display variants; no generated metrics."""
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from factory.metrics.review import metric_text, recorded_repairs, result_outcome
from tests.metrics.test_app import forbid_execution, nav, visible_text

ROOT = Path(__file__).resolve().parents[2]


def review_case(tmp_path, monkeypatch, case='csv-upload/builtin', change=None):
    from streamlit.testing.v1 import AppTest
    directory = tmp_path / 'state/runs/case'
    shutil.copytree(ROOT / 'case-example/metrics' / case, directory)
    report = json.loads((directory / 'report.json').read_text())
    if change:
        change(report)
        (directory / 'report.json').write_text(json.dumps(report))
    # This independent review has no live graph; never claim a new publication.
    monkeypatch.setenv('FACTORY_METRICS_STATE', str(directory.parents[1]))
    monkeypatch.setenv('FACTORY_METRICS_KNOWLEDGE', str(tmp_path / 'absent.sqlite'))
    monkeypatch.delenv('FACTORY_METRICS_CAMPAIGN', raising=False)
    monkeypatch.delenv('FACTORY_METRICS_MODEL_ENV', raising=False)
    calls = forbid_execution(monkeypatch)
    monkeypatch.setattr('factory.metrics.knowledge.LegacySQLiteKnowledgeStore.add', lambda *a, **k: (_ for _ in ()).throw(AssertionError('read-only')))
    before = hashes(tmp_path)
    app = AppTest.from_file(ROOT / 'streamlit_app.py')
    app.session_state['page'] = '结果概览'
    app.run(timeout=20)
    assert not app.exception
    assert hashes(tmp_path) == before and not calls
    return app, report, directory, calls, before


def hashes(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('case', ['csv-upload/builtin', 'csv-upload/upload-labelled', 'csv-upload/upload-unlabelled'])
def test_frozen_success_metrics_curves_downloads_and_closed_details(tmp_path, monkeypatch, case):
    app, report, _, calls, before = review_case(tmp_path, monkeypatch, case)
    source = report['data_source']
    source_name = '上传CSV' if source['type'] == 'uploaded_csv' else '内置模拟数据'
    assert any('数据来源：' + source_name in e.value for e in app.caption)
    assert any(source['host_id'] in e.value for e in app.caption)
    assert len(app.metric) == 4 and not app.error
    if case.endswith('unlabelled'):
        assert [m.label for m in app.metric] == ['预测告警数','检测覆盖率','评分耗时（秒）','检测数据点数']
        assert [m.value for m in app.metric] == [str(len(report['final']['predicted_events'])),
            metric_text(report['final']['coverage'], percent=True), metric_text({'value':report['final']['runtime_seconds']}), '160']
        notices = [e.value for e in app.warning if '准确性与漏检情况尚未评估' in e.value]
        assert notices == ['未提供标签，准确性与漏检情况尚未评估。']
        assert not any('无法评价准确性' in e.value or '准确性与漏检情况尚未评估' in e.value for e in app.caption)
        assert any('—（未评价 / 未记录）' in str(frame.value) for frame in app.dataframe)
    else:
        assert [m.label for m in app.metric] == ['事件 F1','正常误报频次','检测延迟（秒）','检测覆盖率']
        assert [m.value for m in app.metric] == [metric_text(report['final']['event']['f1']),
            metric_text(report['final']['normal_false_alarms_per_host_hour']),
            metric_text({'value':report['final']['matched_delay_seconds']['median']}),
            metric_text(report['final']['coverage'], percent=True)]
        assert any('效果：已测量' in e.value and '业务验收：未定义门槛' in e.value for e in app.caption)
    assert app.get('vega_lite_chart')
    assert all(not e.proto.expanded for e in app.expander)
    assert '选优依据与冻结记录' in [e.label for e in app.expander]
    downloads = [e.proto.label for e in app.get('download_button')]
    assert '下载报告 JSON' in downloads
    assert downloads[0] == '下载交付包'
    if case.startswith('csv-upload/upload-'):
        assert '包含上传数据' in app.get('download_button')[0].proto.help
    assert len([v for v in downloads if '交付包' in v]) == 1
    assert any('逐点检测 CSV' in v for v in downloads)
    chosen = app.session_state['selected_task']
    for section in ('知识与依据','验证过程','结果概览'):
        nav(app, section)
        assert not app.exception and app.session_state['selected_task'] == chosen
    assert hashes(tmp_path) == before and not calls


@pytest.mark.parametrize('kind', ['generation', 'execution', 'validation'])
def test_failure_visible_and_stale_success_metrics_suppressed(tmp_path, monkeypatch, kind):
    def change(r):
        r['status'] = r['completion_status'] = 'FAILED'
        r['failure'] = {'code':'CONTROLLED_DISPLAY_FAILURE','message':'受控展示失败：' + kind}
        r['stage_status'] = {'engineering':'FAILED' if kind == 'validation' else 'PASSED', 'detection':'FAILED' if kind == 'execution' else 'NOT_EVALUATED'}
        if kind == 'execution':
            r['final']['execution_status'] = 'FAILED'
        else:
            r['final'] = None
    app, _, _, _, _ = review_case(tmp_path, monkeypatch, change=change)
    assert any('受控展示失败' in e.value for e in app.error)
    assert [m.value for m in app.metric] == ['—'] * 4
    assert not app.success
    assert '不代表效果或业务通过' in visible_text(app)
    nav(app, '验证过程')
    assert any('受控展示失败' in e.value for e in app.error)


def test_zero_null_missing_and_unmeasured_are_distinct(tmp_path, monkeypatch):
    def change(r):
        r['final']['event']['precision'] = {'value':0.0}
        r['final']['event']['recall'] = {'value':None, 'null_reason':'no_truth_events'}
        r['final']['event'].pop('f1')
        r['final']['normal_false_alarms_per_host_hour'] = {'value':0.0}
        r['final']['matched_delay_seconds']['median'] = None
        r['final']['matched_delay_seconds']['null_reason'] = 'no_matched_events'
        r['final']['matched_delay_seconds']['missed_events'] = 0
    app, _, _, _, _ = review_case(tmp_path, monkeypatch, change=change)
    assert [m.value for m in app.metric[:3]] == ['—', '0.0000', '—']
    assert 'not_recorded' in app.metric[0].proto.help and 'no_matched_events' in app.metric[2].proto.help
    assert any('no_truth_events' in str(t.value) for t in app.table)
    assert any('事件 Precision' in str(t.value) and '0.0%' in str(t.value) for t in app.table)
    assert any('漏检事件数' in str(t.value) and '0' in str(t.value) for t in app.table)


def test_sparse_history_no_source_no_curve_no_fake_download(tmp_path, monkeypatch):
    def change(r):
        for key in ('data_source','curves','benchmark','candidates','planning','knowledge_snapshot','retrieval'):
            r.pop(key, None)
        r['final'] = None
    app, _, directory, _, _ = review_case(tmp_path, monkeypatch, change=change)
    assert '未保存冻结数据来源摘要' in visible_text(app)
    assert '未保存曲线所需产物' in visible_text(app)
    assert '独立模拟基准' not in visible_text(app)
    assert not app.get('vega_lite_chart')
    assert not any('源码' in e.proto.label for e in app.get('download_button'))
    for section in ('知识与依据','验证过程'):
        nav(app, section)
        assert not app.exception


@pytest.mark.parametrize('status', ['NOT_APPLICABLE','NOT_EVALUATED','FAILED'])
def test_unexecuted_or_failed_benchmark_has_small_honest_state(tmp_path, monkeypatch, status):
    def change(r): r['benchmark'] = {'execution_status':status, 'reason':'受控基准原因'}
    app, _, _, _, _ = review_case(tmp_path, monkeypatch, case='csv-upload/upload-labelled', change=change)
    assert not any('独立模拟基准' in e.label for e in app.expander)
    nav(app, '运行与验证')
    assert '受控基准原因' in visible_text(app)
    assert not any(e.label == '独立模拟基准（不代表当前上传数据或生产效果）' for e in app.expander)


def test_multiple_candidates_repairs_and_original_errors_are_traceable(tmp_path, monkeypatch):
    app, report, _, _, _ = review_case(tmp_path, monkeypatch, case='delivery/real-memory-v1')
    assert len(report['candidates']) > 1 and len(recorded_repairs(report)) == 2
    nav(app, '验证过程')
    assert '实际修复次数：2' in visible_text(app)
    assert any('第 2 轮代码修复' in e.label for e in app.expander)
    assert all(not e.proto.expanded for e in app.expander)
    assert any('v2 源码' in e.proto.label for e in app.get('download_button'))
    assert any('首条未通过检查' in c.value for c in app.caption)


def test_reading_second_task_preserves_identity_and_does_not_write(tmp_path, monkeypatch):
    app, _, directory, calls, _ = review_case(tmp_path, monkeypatch)
    second = directory.parent / 'second'
    shutil.copytree(ROOT / 'case-example/metrics/csv-upload/upload-unlabelled', second)
    before = hashes(tmp_path)
    app.run()
    for path in (second, directory):
        app.selectbox(key='review_task').set_value(str(path / 'report.json')).run()
        for section in ('知识与依据','验证过程','结果概览'):
            nav(app, section)
            assert not app.exception and app.session_state['selected_task'] == str(path / 'report.json')
    assert hashes(tmp_path) == before and not calls


def test_unknown_business_status_does_not_claim_acceptance():
    r = {'status':'COMPLETED', 'selection':{'selected':'a'}, 'final':{'execution_status':'SUCCEEDED','effect_status':'MEASURED'}}
    assert '门槛' not in result_outcome(r)['summary']
    r['final']['acceptance_status'] = 'MEASURED_NO_ACCEPTANCE_THRESHOLD'
    assert '未定义业务验收门槛' in result_outcome(r)['summary']


def test_stale_benchmark_evaluation_is_not_shown_as_effect(tmp_path, monkeypatch):
    def change(r):
        r['benchmark']['evaluation']['execution_status'] = 'FAILED'
    app, _, _, _, _ = review_case(tmp_path, monkeypatch, case='csv-upload/upload-labelled', change=change)
    nav(app, '运行与验证')
    assert '未记录成功的效果评价' in visible_text(app)
    assert not any(e.label == '独立模拟基准（不代表当前上传数据或生产效果）' for e in app.expander)


@pytest.mark.parametrize('status', ['RUNNING','PLAN_ONLY'])
def test_incomplete_status_never_reuses_stale_final_metrics(tmp_path, monkeypatch, status):
    def change(r):
        r['status'] = r['completion_status'] = status
    app, _, _, _, _ = review_case(tmp_path, monkeypatch, change=change)
    assert [m.value for m in app.metric] == ['—'] * 4
    assert not app.success and not app.get('vega_lite_chart')


def test_unlabelled_missing_records_are_not_inferred_from_upload_size(tmp_path, monkeypatch):
    def change(r):
        r['final'].pop('predicted_events')
        r['curves'].pop('detection')
    app, report, _, _, _ = review_case(tmp_path, monkeypatch, case='csv-upload/upload-unlabelled', change=change)
    assert report['data_source']['points'] == 360
    assert app.metric[0].value == app.metric[3].value == '—'
    assert '未保存曲线所需产物' in visible_text(app)
    assert 'not_recorded' in app.metric[3].proto.help


def test_failed_acceptance_and_coverage_remain_prominent(tmp_path, monkeypatch):
    def change(r):
        r['business_acceptance'] = {'status':'FAILED', 'checks':[]}
        r['final']['engineering_status'] = 'COVERAGE_FAILED'
    app, _, _, _, _ = review_case(tmp_path, monkeypatch, change=change)
    assert any('验收目标未满足' in w.value and 'COVERAGE_FAILED' in w.value for w in app.warning)
    assert '业务验收：未通过' in visible_text(app)
    assert any('业务验收：未通过' in c.value for c in app.caption)
    nav(app, '运行与验证')
    stages = next(t.value for t in app.table if '已记录阶段' in t.value.columns)
    assert stages.set_index('已记录阶段').loc['工程验证', '状态'] == '覆盖率不足'


def test_measured_effect_does_not_invent_missing_label_metadata(tmp_path, monkeypatch):
    def change(r):
        r['data_source'].pop('labels', None)
        r['final'].pop('truth_events', None)
    app, _, _, _, _ = review_case(tmp_path, monkeypatch, change=change)
    assert '真实标签：未记录' in visible_text(app)


def test_selected_mad_summary_never_borrows_business_threshold(tmp_path, monkeypatch):
    from factory.metrics.app import detection_goal
    report = json.loads((ROOT/'case-example/metrics/csv-upload/upload-unlabelled/report.json').read_text())
    plan = next(c for c in report['planning']['candidates'] if c['config']['method_id'] == 'rolling_mad')
    report['candidates'].append({'candidate_id':'controlled-mad', 'plan':plan})
    report['selection']['selected'] = 'controlled-mad'
    report['final']['config'] = plan['config']
    report['final']['threshold'] = 3.5
    summary = detection_goal(report)
    assert '滚动 MAD' in summary and '分数阈值：3.5' in summary and '窗口：' not in summary
    assert '85' not in summary
    assert '85' in report['task']['requirement']


def test_common_header_download_and_tab_selection_survive_task_changes(tmp_path, monkeypatch):
    app, _, directory, calls, _ = review_case(tmp_path, monkeypatch, case='csv-upload/upload-unlabelled')
    before = hashes(tmp_path)
    for section in ('运行与验证','知识依据','模型用量','结果概览'):
        nav(app, section)
        assert not app.exception
        assert app.session_state['page'] == '任务结果'
        assert app.session_state['selected_task'] == str(directory/'report.json')
        assert app.selectbox(key='review_task').value == str(directory/'report.json')
        assert len([h for h in app.subheader if h.value == '内存异常检测']) == 1
        assert [e.proto.label for e in app.get('download_button')].count('下载交付包') == 1
        assert app.button(key='nav-查看结果').proto.type == 'primary'
    assert hashes(tmp_path) == before and not calls


def test_missing_delivery_never_offers_a_download(tmp_path, monkeypatch):
    app, _, directory, calls, _ = review_case(tmp_path, monkeypatch)
    (directory/'delivery.zip').unlink()
    before = hashes(tmp_path)
    for section in ('运行与验证','知识依据','模型用量','结果概览'):
        nav(app, section)
        assert not any('交付包' in e.proto.label for e in app.get('download_button'))
        assert any('交付包未记录' in e.value for e in app.caption)
    assert hashes(tmp_path) == before and not calls


def test_curve_event_location_survives_hidden_section(tmp_path, monkeypatch):
    app, report, _, calls, _ = review_case(tmp_path, monkeypatch, case='csv-upload/upload-unlabelled')
    key = report['task']['task_id'] + '-detection-event'
    app.selectbox(key=key).set_value(0).run()
    assert not app.exception
    nav(app, '运行与验证')
    nav(app, '知识依据')
    nav(app, '结果概览')
    assert not app.exception and app.selectbox(key=key).value == 0 and not calls


def test_proposal_only_preserves_draft_and_never_claims_detection(tmp_path, monkeypatch):
    def change(r):
        r['status'] = r['completion_status'] = 'PLAN_ONLY'
        r['proposal'] = {'status':'PLAN_ONLY', 'notice':'仅方案草稿，尚未完成代码验证',
                         'candidates':r['planning']['candidates']}
    app, _, _, calls, _ = review_case(tmp_path, monkeypatch, change=change)
    assert '检测方案草稿（尚未完成代码验证）' in visible_text(app)
    assert [m.value for m in app.metric] == ['—']*4
    assert not app.success and not app.get('vega_lite_chart') and not calls


def test_overview_has_one_event_table_one_comparison_and_unique_supplemental_metrics(tmp_path, monkeypatch):
    app, report, _, calls, _ = review_case(tmp_path, monkeypatch)
    assert [e.value for e in app.markdown].count('#### 候选方案比较') == 1
    assert len([f for f in app.dataframe if '开始 UTC' in f.value.columns]) == 1
    assert len([f for f in app.dataframe if '排名' in f.value.columns]) == 1
    event_frame = next(f.value for f in app.dataframe if '开始 UTC' in f.value.columns)
    assert {'事件ID', '候选', '版本'} <= set(event_frame.columns)
    assert len(event_frame) == len(report['final']['predicted_events'])
    details = next(t.value for t in app.table if '指标' in t.value.columns)
    assert not {'事件 F1', '正常误报频次', '检测延迟（秒）', '检测覆盖率'} & set(details['指标'])
    assert '报告与源码下载' not in [e.label for e in app.expander]
    assert any(e.proto.popover.label == '下载与原始记录' for e in app.get('popover'))
    assert not calls


def test_materials_group_by_source_without_losing_distinct_fragments(tmp_path, monkeypatch):
    def change(report):
        report.setdefault('retrieval', {})['chunks'] = [
            {'source': 'same.py', 'start_line': 1, 'end_line': 2, 'text': 'first fragment'},
            {'source': 'same.py', 'start_line': 8, 'end_line': 9, 'text': 'second fragment'},
        ]
    app, _, _, calls, _ = review_case(tmp_path, monkeypatch, change=change)
    nav(app, '知识依据')
    sources = next(t.value for t in app.table if '引用材料' in t.value.columns)
    assert sources.to_dict('records') == [{'引用材料': 'same.py', '片段数': 2}]
    assert {'first fragment', 'second fragment'} <= {e.value for e in app.code}
    assert any('1 — 2' in c.value for c in app.caption)
    assert any('8 — 9' in c.value for c in app.caption)
    assert not calls


def test_coverage_selection_does_not_repeat_development_coverage_column(tmp_path, monkeypatch):
    def change(report):
        report['selection']['criteria'] = ['coverage_desc', 'candidate_id']
    app, _, _, _, _ = review_case(tmp_path, monkeypatch, change=change)
    comparison = next(f.value for f in app.dataframe if '排名' in f.value.columns)
    assert len([c for c in comparison.columns if c.startswith('开发覆盖率')]) == 1
