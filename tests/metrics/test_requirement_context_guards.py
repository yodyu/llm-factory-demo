"""Sampling metadata and excluded capabilities cannot become alarm constraints."""
import pytest

from contracts.metrics_requirement import RequirementClaim, RequirementExtraction
from factory.metrics.requirements import build_draft, controlled_extract, request_from_draft


def draft(text, *, source='simulation', interval=60, extraction=None):
    return build_draft([text], [extraction or controlled_extract(text)], binding='context-guard',
                       upload_present=source == 'upload', sampling_seconds=interval)


@pytest.mark.parametrize('sampling', ['每60秒采样', '每 60 秒一点', '每分钟一点', '采样间隔为60秒', '每1分钟采样一次'])
@pytest.mark.parametrize('source', ['simulation', 'upload'])
def test_matching_sampling_metadata_is_supported(sampling, source):
    text = f"{'上传CSV' if source == 'upload' else '模拟数据'}检测CPU异常升高，{sampling}，连续2个异常采样点才告警，不要求根因定位。"
    item = draft(text, source=source)
    assert not item.issues
    assert item.values['persistence_points'] == 2
    assert item.evidence['persistence_points']['origin'] == 'user_explicit'
    assert 'duration_seconds' not in item.values
    request = request_from_draft(item, current_binding=item.binding)
    assert request.explicit_constraints['persistence_points'] == 2


def test_model_sampling_as_duration_and_false_limitations_are_corrected():
    text = '上传CSV检测单主机CPU异常升高，每60秒采样，连续2个异常采样点告警，不要求根因定位或在线采集。'
    output = RequirementExtraction(claims=[RequirementClaim(key='duration_seconds', value=60, quote=text)],
        unsupported=['模拟数据当前固定每60秒一点；上传数据按CSV时间网格读取，不支持指定重采样。',
                     '当前仅支持单主机单指标离线检测；不提供根因定位或在线采集。'])
    item = draft(text, source='upload', extraction=output)
    assert not item.issues and 'duration_seconds' not in item.values
    assert item.values['persistence_points'] == 2


@pytest.mark.parametrize('text,part', [
    ('模拟CPU升高，每30秒采样', '不一致'),
    ('上传CSV检测CPU升高，每60秒采样', 'CSV 时间网格'),
    ('模拟CPU升高，每60秒采样，每30秒采样', '冲突'),
    ('上传CSV检测CPU升高，持续60秒，连续2个采样点', '不一致'),
])
def test_actual_unsupported_requests_and_alarm_conflicts_remain_blocked(text, part):
    interval = 30 if 'CSV 时间网格' == part else 60
    item = draft(text, source='upload' if '上传' in text else 'simulation', interval=interval)
    assert any(part in issue for issue in item.issues), item.issues


@pytest.mark.parametrize('exclusion', ['不要求根因定位', '无需在线采集', '不需要根因定位和在线采集', '不做多主机和多指标', '不需要重采样'])
def test_explicit_exclusions_are_not_requested_features(exclusion):
    item = draft('模拟CPU异常升高，' + exclusion)
    assert not item.issues


def test_real_duration_keeps_existing_coverage_convention():
    item = draft('上传CSV检测CPU异常升高，每30秒采样，持续60秒，连续2个采样点', source='upload', interval=30)
    assert not item.issues
    assert item.values['duration_seconds'] == 60 and item.values['persistence_points'] == 2
    wrong = draft('上传CSV检测CPU异常升高，每60秒采样，持续60秒，连续2个采样点', source='upload')
    assert any('采样间隔不是告警持续时间' in issue for issue in wrong.issues)


def test_unknown_model_limitation_is_visible_without_blocking_demo():
    text = '模拟CPU升高，每60秒采样'
    item = draft(text, extraction=RequirementExtraction(unsupported=['要求接入未知自定义插件']))
    assert not item.issues and any('要求接入未知自定义插件' in x for x in item.defaults)
    item = draft(text, extraction=RequirementExtraction(unsupported=['采样数据需要未知自定义插件']))
    assert not item.issues and any('采样数据需要未知自定义插件' in x for x in item.defaults)


def test_later_sampling_metadata_does_not_replace_an_explicit_alarm_duration():
    turns = ['上传CSV检测CPU异常升高持续120秒', '采样间隔为60秒']
    item = build_draft(turns, [controlled_extract(t) for t in turns], binding='revision', upload_present=True)
    assert not item.issues
    assert item.values['duration_seconds'] == 120 and item.values['persistence_points'] == 2
