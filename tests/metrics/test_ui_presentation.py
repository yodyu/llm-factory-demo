"""UI reflects plugin parameters and frozen selection evidence without execution."""
import copy
import json
from pathlib import Path
import shutil

import pytest

from factory.metrics.evaluation import select_development
from factory.metrics.requirements import build_draft, controlled_extract
from factory.metrics.ui_presentation import (
    candidate_label, config_summary, parameter_preview, selection_explanation,
    comparison_columns, comparison_value,
)

ROOT = Path(__file__).resolve().parents[2]


def draft_for(text):
    return build_draft([text], [controlled_extract(text)], binding='controlled')


def test_parameter_preview_separates_explicit_values_from_plugin_defaults():
    draft = draft_for('用模拟数据比较EWMA和固定阈值检测内存持续升高，alpha为0.2，固定阈值85%')
    rows = parameter_preview(draft)
    alpha = next(r for r in rows if r['参数'] == 'alpha')
    assert alpha == {'方法': 'EWMA', '参数': 'alpha', '值': '0.2', '来源': '来自描述'}
    threshold = next(r for r in rows if r['参数'] == '固定阈值')
    assert threshold['方法'] == '固定阈值' and threshold['来源'] == '来自描述'
    assert any(r['方法'] == 'EWMA' and r['来源'] == '插件默认（候选起点）' for r in rows)
    assert not any(r['方法'] == '固定阈值' and r['参数'] == 'alpha' for r in rows)


def test_new_plugin_parameter_is_visible_without_ui_code_changes(tmp_path, monkeypatch):
    target = tmp_path / 'plugins/new_example'
    shutil.copytree(ROOT / 'capabilities/ewma', target)
    path = target / 'capability.json'
    card = json.loads(path.read_text())
    card.update(method_id='new_example', display_name='新插件', aliases=['新插件'])
    card['defaults']['sensitivity'] = 0.4
    card['config_schema']['properties']['sensitivity'] = {'type': 'number', 'title': '敏感度'}
    path.write_text(json.dumps(card))
    monkeypatch.setenv('FACTORY_CAPABILITIES_DIRECTORY', str(target.parent))
    draft = draft_for('用新插件检测模拟内存，sensitivity为0.7')
    assert {'方法': '新插件', '参数': '敏感度', '值': '0.7', '来源': '来自描述'} in parameter_preview(draft)


def test_same_method_variants_keep_frozen_config_and_distinct_identifiers(monkeypatch):
    def forbidden():
        raise AssertionError('frozen reports must not consult live plugin defaults')
    monkeypatch.setattr('factory.metrics.capability_registry.registry', forbidden)
    slow = {'candidate_id': 'slow', 'plan': {'config': {'method_id': 'ewma', 'alpha': 0.2}}}
    fast = {'candidate_id': 'fast', 'plan': {'config': {'method_id': 'ewma', 'alpha': 0.8}}}
    assert candidate_label(slow, {'ewma': 'EWMA'}) != candidate_label(fast, {'ewma': 'EWMA'})
    assert config_summary(slow) == 'alpha=0.2' and config_summary(fast) == 'alpha=0.8'
    assert config_summary({'plan': {}}) == '参数未记录'


@pytest.mark.parametrize('objective,primary', [('sustained_coverage', '开发点级 F1'), ('event_detection', '开发事件 F1')])
def test_comparison_matches_actual_selector_and_never_uses_final_results(objective, primary):
    report = json.loads((ROOT / 'case-example/metrics/delivery/transfer-memory-v2/report.json').read_text())
    report['selection'] = select_development(report['candidates'], objective=objective)
    before = copy.deepcopy(report)
    columns = comparison_columns(report)
    assert columns[0][1] == primary
    explanation = selection_explanation(report)
    assert explanation['实际决胜项'] == '开发点级 F1'
    assert explanation['排序顺序'].startswith(primary)
    values = [comparison_value(c['report'], columns[0][0], report['selection']) for c in report['candidates']]
    report['final'] = {'point': {'f1': {'value': -999}}, 'event': {'f1': {'value': -999}}}
    assert values == [comparison_value(c['report'], columns[0][0], report['selection']) for c in report['candidates']]
    report['final'] = before['final']
    assert report == before


def test_fbeta_uses_recorded_development_counts_and_unlabelled_never_gets_accuracy():
    result = {'effect_status': 'MEASURED', 'point': {'tp': 2, 'fp': 2, 'fn': 0}}
    selection = {'beta': 0.5, 'criteria': ['point_fbeta_desc', 'event_fbeta_desc']}
    assert comparison_columns({'selection': selection})[0][1] == '开发点级 F0.5'
    assert comparison_value(result, 'point_fbeta_desc', selection) == '0.5556'
    result['effect_status'] = 'NOT_EVALUATED'
    assert comparison_value(result, 'point_fbeta_desc', selection) == '未评估（无可用标签）'
    unlabelled = [{'candidate_id': 'only', 'role': 'development', 'report': {
        'execution_status': 'SUCCEEDED', 'engineering_status': 'PASSED',
        'effect_status': 'NOT_EVALUATED', 'coverage': {'value': 1.0}}}]
    recorded = select_development(unlabelled)
    assert comparison_columns({'selection': recorded}) == [('coverage_desc', '开发覆盖率（降序）')]
    assert selection_explanation({'selection': recorded})['实际决胜项'] == '仅一个合格候选'


def test_legacy_selection_missing_fields_are_not_reconstructed():
    report = {'selection': {'selected': 'old'}, 'final': {'event': {'f1': {'value': 1}}}}
    explanation = selection_explanation(report)
    assert explanation['评价目标'] == explanation['实际决胜项'] == '未记录'
    assert explanation['排序顺序'] == '未记录，不从最终测试反推'


def test_creation_page_shows_dynamic_alpha_and_objective(tmp_path, monkeypatch):
    from tests.metrics.test_creation_input import creation_app
    from tests.metrics.test_app import submit_button, visible_text
    app = creation_app(tmp_path, monkeypatch, allow_parse=True)
    app.text_area(key='create_requirement').set_value('用EWMA检测模拟内存持续升高，alpha为0.2').run()
    app.button(key='understand-requirement').click().run()
    assert not app.exception and not submit_button(app).disabled
    tables = '\n'.join(str(t.value) for t in app.table)
    assert all(value in tables for value in ('alpha', '0.2', '来自描述', '插件默认（候选起点）', '持续区间覆盖'))
    assert '算法参数与来源' in [e.label for e in app.expander]
    assert '候选起点' in visible_text(app)


def test_result_page_displays_same_method_variants_and_actual_decision(tmp_path, monkeypatch):
    from tests.metrics.test_result_presentation import review_case
    from tests.metrics.test_app import visible_text
    def change(report):
        report['selection'] = select_development(report['candidates'], objective='sustained_coverage')
        for candidate, alpha in zip(report['candidates'], (0.2, 0.8)):
            candidate['plan']['config'] = {'method_id': 'ewma', 'alpha': alpha}
    app, report, _, _, _ = review_case(tmp_path, monkeypatch, change=change)
    text = visible_text(app)
    assert '持续区间覆盖' in text and '实际决胜项：开发点级 F1' in text
    comparison = next(frame.value for frame in app.dataframe if '候选' in frame.value.columns and '排名' in frame.value.columns)
    assert len(set(comparison['候选'])) == len(report['candidates'])
    assert '参数' not in comparison.columns
    assert 'alpha=0.2' in text and 'alpha=0.8' in text
    assert comparison.columns.tolist().index('开发点级 F1') < comparison.columns.tolist().index('开发事件 F1')


@pytest.mark.parametrize('objective,label', [('sustained_coverage','点级 F1'), ('event_detection','事件 F1')])
def test_summary_final_metric_uses_recorded_objective(objective, label):
    from streamlit.testing.v1 import AppTest
    report = {'status':'COMPLETED', 'selection':{'objective':objective, 'selected':'a'},
              'final':{'execution_status':'SUCCEEDED','effect_status':'MEASURED',
                       'point':{'f1':{'value':.4}}, 'event':{'f1':{'value':.9}}}}
    app = AppTest.from_string('from factory.metrics.app import show_summary\n'
                             'import streamlit as st\nshow_summary(st.session_state["report"])')
    app.session_state['report'] = report
    app.run()
    assert not app.exception and app.metric[0].label == label
    assert app.metric[0].value == ('0.4000' if objective == 'sustained_coverage' else '0.9000')
