"""Language changes must alter frozen behavior; ambiguity must never execute."""
import asyncio
import json

import pytest

from contracts.metrics_requirement import AcceptanceCriteria, RequirementClaim, RequirementExtraction
from factory.metrics.requirements import EXAMPLES, binding_for, build_draft, controlled_extract, interpret_command, request_from_draft


def draft(*turns, **kwargs):
    return build_draft(list(turns), [controlled_extract(t) for t in turns], binding=binding_for(list(turns)), **kwargs)


def test_explicit_constraints_and_revision_keep_provenance():
    original = draft(EXAMPLES['CPU 持续升高'])
    assert not original.issues
    request = request_from_draft(original, current_binding=original.binding)
    assert request.explicit_constraints == {'threshold': 90., 'direction': 'upper', 'persistence_points': 3.}
    changed = draft(EXAMPLES['CPU 持续升高'], '阈值改成95%，连续两点才报警')
    assert not changed.issues
    assert changed.values['threshold'] == 95 and changed.values['persistence_points'] == 2
    assert changed.evidence['threshold']['turn'] == 2
    assert original.values['threshold'] == 90


def test_conflicts_block_until_explicit_followup_and_defaults_are_not_user_values():
    text = '模拟CPU升高，超过90%报警，高于85%也报警'
    conflicted = draft(text)
    assert any('冲突' in i for i in conflicted.issues)
    with pytest.raises(ValueError, match='NEEDS_INPUT'):
        request_from_draft(conflicted, current_binding=conflicted.binding)
    resolved = draft(text, '阈值为95%')
    assert not resolved.issues and resolved.values['threshold'] == 95
    unspecified = draft('检测内存缓慢升高，模拟数据')
    request = request_from_draft(unspecified, current_binding=unspecified.binding)
    assert 'threshold' not in request.explicit_constraints
    assert unspecified.evidence['persistence_points']['origin'] == 'protocol_default'
    assert unspecified.values['scenario'] == 'memory_drift'


def test_attachment_or_settings_changes_make_old_draft_unsubmittable():
    item = draft('模拟CPU升高')
    for args in ({'upload': b'changed'}, {'labels': b'changed'}, {'mode': 'api'}, {'profile': 'new-model'},
                 {'label_source': 'new'}, {'retrieval': 'none'}, {'overrides': {'threshold': 90}}):
        changed = binding_for(item.turns, **args)
        with pytest.raises(ValueError, match='已改变'):
            request_from_draft(item, current_binding=changed)


def test_uploaded_labels_have_a_trusted_default_without_source_input():
    from factory.metrics.requirements import DEFAULT_LABEL_SOURCE
    item = draft('上传CPU超过85%连续两点报警', upload_present=True, labels_present=True)
    assert not item.issues
    assert item.values['label_source'] == DEFAULT_LABEL_SOURCE
    assert item.evidence['label_source']['origin'] == 'protocol_default'


@pytest.mark.parametrize('text,part', [
    ('CPU超过90%且低于20%', '冲突'),
    ('模拟CPU升高连续五点', '连续采样点'),
    ('模拟CPU升高连续90秒', '整数倍'),
    ('模拟CPU超过50ms', '单位'),
    ('模拟CPU超过190%', '有效范围'),
    ('模拟CPU升高，窗口10点', '历史窗口'),
    ('用上传CPU CSV检测升高', '请上传'),
])
def test_invalid_requests_remain_needs_input(text, part):
    item = draft(text)
    assert any(part in i for i in item.issues), item.issues


def test_duration_conversion_is_explicit_and_uploaded_interval_is_used():
    item = draft('模拟CPU升高持续3分钟')
    assert not item.issues and item.values['persistence_points'] == 3
    assert '首点至触发点间隔 120 秒' in item.evidence['persistence_points']['conversion']
    uploaded = draft('上传CPU升高持续60秒', upload_present=True, sampling_seconds=30)
    assert not uploaded.issues and uploaded.values['persistence_points'] == 2
    wrong = draft('上传CPU升高持续60秒连续三点', upload_present=True, sampling_seconds=30)
    assert any('不一致' in i for i in wrong.issues)


def test_missing_preference_and_disk_value_do_not_become_resource_constraints():
    assert not draft('模拟CPU升高，允许短暂缺失，阈值85%').issues
    item = draft('模拟磁盘延迟小于40ms，只用固定阈值')
    assert not item.issues and item.values['direction'] == 'lower'
    assert any('原始累计计数器' in i for i in draft('模拟网络原始累计计数器升高').defaults)


def test_single_method_lower_and_two_sided_and_network_unit_conversion():
    lower = draft('模拟CPU降低，低于20%，只用固定阈值')
    assert not lower.issues and lower.values['methods'] == ['fixed_threshold']
    assert request_from_draft(lower, current_binding=lower.binding).anomaly_target == 'lower'
    both = draft('模拟CPU双向偏离，只用滚动MAD')
    assert not both.issues and both.values['direction'] == 'two_sided'
    assert draft('模拟CPU双向偏离').values['methods'] == ['rolling_mad']
    network = draft('模拟网络速率升高，超过2 KB/s连续两点报警')
    assert not network.issues and network.values['threshold'] == 2000


def test_preferences_and_business_gates_need_labels_and_are_not_thresholds():
    text = 'CPU持续升高，尽量少误报，每小时正常误报不超过1次，召回率不低于90%'
    item = draft('模拟数据，' + text)
    assert not item.issues and item.values['selection_policy'] == 'precision'
    request = request_from_draft(item, current_binding=item.binding)
    assert 'threshold' not in request.explicit_constraints
    assert request.acceptance_criteria.max_false_alarms_per_hour == 1
    assert request.acceptance_criteria.min_event_recall == .9
    item = draft('上传CSV，' + text, upload_present=True)
    assert not item.issues and any('需要真实标签' in i for i in item.defaults)


def test_unverifiable_model_numeric_and_quote_are_rejected():
    for claim in [RequirementClaim(key='threshold', value=95., quote='CPU升高'),
                  RequirementClaim(key='threshold', value=95., quote='不存在的95%')]:
        with pytest.raises(ValueError, match='依据|原文'):
            build_draft(['CPU升高'], [RequirementExtraction(claims=[claim])], binding='x')
    # Deterministic explicit user values win over a conflicting model value.
    text = 'CPU超过90%，模拟数据'
    result = build_draft([text], [RequirementExtraction(claims=[RequirementClaim(key='threshold', value=.9, quote='90%')])], binding='x')
    assert result.values['threshold'] == 90


@pytest.mark.parametrize('key', ['min_event_f1', 'min_event_recall', 'max_false_alarms_per_hour'])
def test_metric_name_digit_is_not_a_model_invented_acceptance_gate(key):
    text = '检测上传CSV的CPU异常升高，固定阈值85%，按开发段事件F1比较选择方案。'
    extraction = RequirementExtraction(claims=[RequirementClaim(key=key, value=1.0, quote='按开发段事件F1比较选择方案')])
    item = build_draft([text], [extraction], binding='recorded', upload_present=True, labels_present=True)
    assert not item.issues and key not in item.values
    request = request_from_draft(item, current_binding='recorded')
    assert all(value is None for value in request.acceptance_criteria.model_dump().values())


@pytest.mark.parametrize('text,value', [('F1不低于0.8',.8), ('事件f1至少90%',.9),
                                      ('事件F1 >= 0.85',.85), ('F1达到1',1.0), ('F1为0.75',.75)])
def test_explicit_f1_gates_are_preserved_without_using_name_digit(text,value):
    original = '上传CSV的CPU异常升高，' + text
    item = build_draft([original], [RequirementExtraction(claims=[
        RequirementClaim(key='min_event_f1', value=1.0, quote=text)])],
        binding='recorded', upload_present=True, labels_present=True)
    assert not item.issues
    assert item.values['min_event_f1'] == value


def test_other_clause_numbers_and_cleared_editor_do_not_leave_f1_gate():
    assert 'min_event_f1' not in draft('模拟CPU按事件F1比较，最少历史至少15点').values
    first = draft('模拟CPU升高，F1不低于1')
    assert first.values['min_event_f1'] == 1.0
    # Reinterpreting the replacement editor text creates a fresh independent draft.
    replacement = draft('模拟CPU升高，按事件F1比较')
    assert not replacement.issues and 'min_event_f1' not in replacement.values


def test_mock_parse_is_audited_and_uses_no_csv_or_label_payload(tmp_path):
    item, extractions = asyncio.run(interpret_command(state=tmp_path / 'state', mode='mock',
        turns=[EXAMPLES['CPU 持续升高']], binding='bound'))
    assert not item.issues and item.parse_task_id.startswith('understand-')
    path = tmp_path / 'state' / 'drafts' / item.parse_task_id
    assert json.loads((path / 'draft.json').read_text())['model_mode'] == 'mock'
    assert len(extractions) == 1
    from factory.metrics.runtime import MetricsStore
    store = MetricsStore(tmp_path / 'state/runtime.sqlite')
    assert store.task(item.parse_task_id)['status'] == 'SUCCEEDED'


def test_acceptance_and_preference_ranking_use_only_development():
    from factory.metrics.evaluation import acceptance_result, select_development
    def candidate(name, tp, fp, fn):
        f1 = 2*tp/(2*tp+fp+fn)
        return {'candidate_id': name, 'role': 'development', 'report': {
            'execution_status': 'SUCCEEDED', 'engineering_status': 'PASSED', 'effect_status': 'MEASURED',
            'event': {'tp': tp, 'fp': fp, 'fn': fn, 'f1': {'value': f1}, 'recall': {'value': tp/(tp+fn)}},
            'coverage': {'value': 1.}, 'normal_false_alarms_per_host_hour': {'value': float(fp)}, 'runtime_seconds': 1.}}
    precise, recall = candidate('precise', 4, 0, 6), candidate('recall', 10, 5, 0)
    assert select_development([precise, recall], policy='precision')['selected'] == 'precise'
    assert select_development([precise, recall], policy='recall')['selected'] == 'recall'
    gate = AcceptanceCriteria(max_false_alarms_per_hour=1., min_event_recall=.9)
    assert select_development([precise, recall], acceptance=gate)['selected'] is not None
    assert select_development([precise, recall], acceptance=gate, strict=True)['selected'] is None
    assert acceptance_result({'effect_status': 'NOT_EVALUATED'}, gate)['status'] == 'NOT_EVALUATED'
    with pytest.raises(ValueError, match='only accepts development'):
        select_development([{**precise, 'role': 'final'}])
