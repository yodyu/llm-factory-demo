"""Read-only UI projections; recorded candidates are never reselected here."""
import json
import math

from factory.metrics.review import metric_text


OBJECTIVES = {'event_detection': '事件发现', 'sustained_coverage': '持续区间覆盖'}
POLICIES = {'balanced': '综合选优', 'precision': '偏好少误报', 'recall': '偏好少漏报'}


def parameter_text(value):
    if isinstance(value, (dict, list, bool)) or value is None:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def parameter_preview(draft):
    """Live plugin defaults are candidate starting points, not frozen plans."""
    from factory.metrics.capability_registry import registry
    from factory.metrics.requirements import LABELS
    plugins = registry()
    rows = []
    for method in draft.values.get('methods', []):
        card = plugins.get(method)
        for key, schema in card.config_schema['properties'].items():
            if key in draft.values:
                value = draft.values[key]
                origin = draft.evidence.get(key, {}).get('origin')
                source = {'user_explicit': '来自描述', 'manual': '手动指定',
                          'protocol_default': '系统默认'}.get(origin, '来源未记录')
            elif key in card.defaults:
                value, source = card.defaults[key], '插件默认（候选起点）'
            else:
                value, source = '待规划', '尚未指定'
            rows.append({'方法': card.display_name, '参数': schema.get('title') or LABELS.get(key, key),
                         '值': parameter_text(value), '来源': source})
    return rows


def candidate_label(candidate, names):
    plan = candidate.get('plan') or {}
    method = (plan.get('config') or {}).get('method_id')
    return names.get(method, method or '方法未记录') + ' · ' + str(candidate.get('candidate_id', '标识未记录'))


def config_summary(candidate):
    # Only frozen configuration values; never fill old reports from live plugins.
    config = (candidate.get('plan') or {}).get('config') or {}
    return '；'.join(f'{key}={parameter_text(value)}' for key, value in sorted(config.items())
                    if key != 'method_id') or '参数未记录'


def criterion_label(key, selection):
    if not key:
        return '未记录'
    for prefix, name in (('point', '开发点级'), ('event', '开发事件')):
        if key.startswith(prefix + '_f1'):
            return name + ' F1'
        if key.startswith(prefix + '_fbeta'):
            beta = selection.get('beta')
            return name + (f' F{beta:g}' if type(beta) in (int, float) and math.isfinite(beta) and beta > 0 else ' Fβ（β未记录）')
    return {'false_alarm_rate_asc': '开发正常误报频次（升序）', 'false_alarm_rate': '开发正常误报频次',
            'matched_delay_asc': '开发匹配延迟（升序）', 'matched_delay_seconds': '开发匹配延迟',
            'coverage_desc': '开发覆盖率（降序）', 'coverage': '开发覆盖率',
            'candidate_id': '候选标识（稳定决胜）',
            'engineering_pass': '工程检查通过（前提）',
            'only_eligible_candidate': '仅一个合格候选'}.get(key, key or '未记录')


def selection_explanation(report):
    selection = report.get('selection') or {}
    objective = selection.get('objective') or (report.get('task') or {}).get('evaluation_objective')
    policy = selection.get('policy')
    basis = {'labelled_development': '有标签开发集', 'engineering_only': '工程可用性（无可用效果评价）',
             'normal_only_development': '仅正常样本的开发集'}.get(selection.get('basis'), '未记录')
    criteria = selection.get('criteria') or []
    return {'评价目标': OBJECTIVES.get(objective, '未记录'), '实际选优偏好': POLICIES.get(policy, '未记录'),
            '比较依据': basis,
            '排序顺序': ' → '.join(criterion_label(key, selection) for key in criteria) or '未记录，不从最终测试反推',
            '实际决胜项': criterion_label(selection.get('tie_broken_by'), selection)}


def comparison_columns(report):
    selection = report.get('selection') or {}
    criteria = selection.get('criteria') or []
    # Legacy reports may have measured metrics but no recorded ordering.
    columns = [key for key in criteria if key not in {'candidate_id', 'engineering_pass'}][:2] if criteria else ['point_f1_desc', 'event_f1_desc']
    return [(key, criterion_label(key, selection)) for key in columns]


def comparison_value(result, key, selection):
    if key.startswith(('point_', 'event_')):
        if result.get('effect_status') == 'NOT_EVALUATED':
            return '未评估（无可用标签）'
        counts = result.get(key.split('_', 1)[0]) or {}
        if '_f1' in key:
            return metric_text(counts.get('f1'))
        beta = selection.get('beta')
        if type(beta) not in (int, float) or not math.isfinite(beta) or beta <= 0:
            return '未记录（beta）'
        if any(type(counts.get(k)) not in (int, float) or not math.isfinite(counts[k]) or counts[k] < 0
               for k in ('tp', 'fp', 'fn')):
            return '未记录（开发集计数）'
        beta2 = beta * beta
        denominator = (1 + beta2) * counts['tp'] + beta2 * counts['fn'] + counts['fp']
        return metric_text({'value': (1 + beta2) * counts['tp'] / denominator if denominator else None,
                            'null_reason': 'undefined_fbeta'})
    if key.startswith('coverage'):
        return metric_text(result.get('coverage'), percent=True)
    if key.startswith('false_alarm_rate'):
        return metric_text(result.get('normal_false_alarms_per_host_hour'))
    if key.startswith('matched_delay'):
        delay = result.get('matched_delay_seconds') or {}
        return metric_text({'value': delay.get('median'), 'null_reason': delay.get('null_reason', 'not_recorded')})
    return '未记录'
