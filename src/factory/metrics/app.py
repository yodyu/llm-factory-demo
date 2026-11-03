"""Minimal server-only Streamlit UI; candidate execution remains inside Docker."""
from factory.metrics.capability_registry import registry

import os
import sqlite3
from pathlib import Path
from uuid import uuid4

import streamlit as st

from factory.metrics.knowledge import canonical
from factory.metrics.review import (
    knowledge_usage, metric_text, old_validator_affected,
    publication_evidence, read_json, source_bytes, result_outcome, recorded_repairs,
)


ORIGINS = {
    "llm_api": "真实模型产物；失败检查需结合验证协议判断",
    "mock": "受控响应 / 人工参考，不证明真实模型生成能力",
    "reference": "人工参考实现",
    "fault_injection": "故意注入错误的案例，不计自然错误修复率",
    "historical": "冻结历史代码复验，不是本次新生成",
}

METHOD_NAMES = {m: card.display_name for m, card in registry().cards.items()}
METRIC_NAMES = {'cpu_utilization': 'CPU', 'memory_utilization': '内存', 'disk_latency': '磁盘延迟',
                'network_rate': '网络速率', 'network_throughput': '网络速率'}
STATUS_NAMES = {'SUCCEEDED':'成功', 'COMPLETED':'执行完成', 'PASSED':'通过', 'FAILED':'未通过',
    'MEASURED':'已测量', 'NOT_EVALUATED':'未评估', 'NOT_MEASURED':'未测量', 'NOT_DEFINED':'未定义门槛',
    'MEASURED_NO_ACCEPTANCE_THRESHOLD':'未定义门槛', 'COVERAGE_FAILED':'覆盖率不足',
    'RUNNING':'运行中', 'PLAN_ONLY':'仅方案草稿', 'NEEDS_INPUT':'待补充输入', 'PARTIAL_SUCCESS':'部分完成'}


def detection_points(directory, report):
    """Display only explicit final counts or verified, saved detection-role rows."""
    total = ((report.get('final') or {}).get('point') or {}).get('total')
    if type(total) is int and total >= 0:
        return total
    binding = (report.get('curves') or {}).get('detection')
    if directory is not None and binding:
        from factory.metrics.upload import read_curve
        try:
            data = read_curve(directory, binding)
            if (data.get('task_id') == (report.get('task') or {}).get('task_id')
                    and data.get('candidate_id') == (report.get('selection') or {}).get('selected')):
                return sum(row.get('role') == 'detection' for row in data['rows'])
        except (OSError, ValueError, KeyError):
            pass
    return None


def show_summary(report, directory=None):
    final = report.get("final") or {}
    outcome = result_outcome(report)
    event = final.get("event") or {}
    delay = final.get('matched_delay_seconds') or {}
    if outcome['succeeded'] and outcome['no_labels']:
        events = final.get('predicted_events')
        count = detection_points(directory, report)
        cards = [('预测告警数', {'value':len(events)} if isinstance(events, list) else None, False),
                 ('检测覆盖率', final.get('coverage'), True),
                 ('评分耗时（秒）', {'value':final.get('runtime_seconds')}, False),
                 ('检测数据点数', {'value':count}, False)]
    else:
        objective = (report.get('selection') or {}).get('objective') or (report.get('task') or {}).get('evaluation_objective', 'event_detection')
        primary = ('点级 F1', (final.get('point') or {}).get('f1'), False) if objective == 'sustained_coverage' else ('事件 F1', event.get('f1'), False)
        cards = [primary,
                 ('正常误报频次', final.get('normal_false_alarms_per_host_hour'), False),
                 ('检测延迟（秒）', {'value':delay.get('median'), 'null_reason':delay.get('null_reason', 'not_recorded')}, False),
                 ('检测覆盖率', final.get('coverage'), True)]
    reasons = []
    columns = st.columns(4)
    for index, (label, value, percent) in enumerate(cards):
        permitted = outcome['succeeded'] if outcome['no_labels'] or index == 3 else outcome['measured']
        detail = metric_text(value, percent=percent) if permitted else outcome['metric_reason']
        display = detail if permitted and isinstance(value, dict) and value.get('value') is not None and not detail.startswith('未') else '—'
        if permitted and label in {'预测告警数', '检测数据点数'} and isinstance(value, dict) and value.get('value') is not None:
            display = str(value['value'])
        help_text = detail + ('；仅针对匹配成功事件，不包含漏检' if label == '检测延迟（秒）' else '；次/主机小时' if label == '正常误报频次' else '；不含暖机' if label == '检测数据点数' else '；非端到端任务耗时' if label == '评分耗时（秒）' else '')
        columns[index].metric(label, display, help=help_text, border=True)
        if display == '—':
            reasons.append(label + "：" + detail)
    if reasons:
        st.caption("；".join(reasons))


def show_more_metrics(report):
    final = report.get('final') or {}
    outcome = result_outcome(report)
    with st.expander("指标详情", expanded=False):
        st.caption("采用方案的最终测试指标；开发集指标见候选比较，独立基准见运行与验证。")
        reason = "未评估（" + outcome['metric_reason'] + "）"
        rows = [
            {"指标": "事件 Precision", "结果": metric_text((final.get('event') or {}).get('precision'), percent=True) if outcome['measured'] else reason},
            {"指标": "事件 Recall", "结果": metric_text((final.get('event') or {}).get('recall'), percent=True) if outcome['measured'] else reason},
        ] if not outcome['no_labels'] else []
        if outcome['measured']:
            event, point = final.get('event') or {}, final.get('point') or {}
            missed = (final.get('matched_delay_seconds') or {}).get('missed_events')
            rows.append({'指标': '漏检事件数', '结果': str(missed) if missed is not None else '未记录'})
            rows.extend({'指标': '点级 ' + name, '结果': metric_text(point.get(key), percent=key != 'f1')}
                        for key, name in (('precision', 'Precision'), ('recall', 'Recall'), ('f1', 'F1')))
            for title, counts, keys in (('事件', event, ('tp', 'fp', 'fn')), ('点级', point, ('tp', 'fp', 'fn', 'tn'))):
                rows.extend({'指标': title + ' ' + key.upper(), '结果': str(counts[key]) if counts.get(key) is not None else '未记录'}
                            for key in keys)
        if not (outcome['succeeded'] and outcome['no_labels']):
            rows.append({'指标': '评分耗时（秒，非端到端）', '结果': str(final['runtime_seconds']) if outcome['succeeded'] and final.get('runtime_seconds') is not None else '未测量 / 未记录'})
        rows.append({'指标': '峰值内存（字节）', '结果': str(final['peak_memory_bytes']) if final.get('peak_memory_bytes') is not None else '未测量（' + str(final.get('peak_memory_null_reason') or 'not_recorded') + '）'})
        st.table(rows)
        st.caption("暖机不计入效果，不做 point adjustment；容器资源限制不代表实测消耗。")


def show_knowledge(report):
    planning = report.get('planning') or {}
    task = report.get('task') or {}
    st.subheader("方案依据")
    usage = knowledge_usage(report)
    st.write(f"实际提供给模型的知识 {len(usage['supplied'])} 条，显式引用 {len(usage['cited'])} 条；提供经验 {len(usage['supplied_experiences'])} 条，引用 {len(usage['cited_experiences'])} 条。引用不证明效果收益。")
    if not usage['cited_experiences']:
        st.write("未显式引用经验 ID；不宣称经验产生收益。")
    if usage['unprovided_citations']:
        st.error("记录存在未提供知识的引用：" + ', '.join(usage['unprovided_citations']))
    selected = result_outcome(report)['candidate']
    config = (selected.get('plan') or {}).get('config') or {}
    if config:
        st.write('采用方案：' + METHOD_NAMES.get(config.get('method_id'), '方法未记录'))
    if (selected.get('plan') or {}).get('limitations'):
        with st.expander('适用条件与方案限制', expanded=False):
            for limitation in selected['plan']['limitations']:
                st.write('• ' + str(limitation))
    retrieval = report.get('retrieval') or {}
    sources = {}
    for chunk in retrieval.get('chunks') or []:
        sources.setdefault(chunk.get('source') or '来源未记录', []).append(chunk)
    if sources:
        st.table([{'引用材料': source, '片段数': len(chunks)} for source, chunks in sources.items()])
    with st.expander("检索文档与代码片段", expanded=False):
        chunks = retrieval.get('chunks') or []
        if not chunks:
            st.info("未记录检索文档或代码片段；未补充检索理由。")
        nodes = {n['id']: n for n in (report.get('knowledge_snapshot') or {}).get('nodes', [])}
        for source, fragments in sources.items():
            st.markdown('**' + source + '**')
            for chunk in fragments:
                st.caption('行范围：' + str(chunk.get('start_line')) + ' — ' + str(chunk.get('end_line')))
                st.code(chunk.get('text', '未记录'), language='text')
            for capability_id in dict.fromkeys(chunk.get('capability_id') for chunk in fragments):
                capability = nodes.get(capability_id, {}).get('payload') or {}
                st.write("材料声称的适用条件（抽取成功不代表实现已验证）：")
                st.json({k: capability[k] for k in ('metric_kinds','single_host','min_history','dependency_profile','conditions_status','constraints','limitations') if k in capability} or {'status':'未记录'}, expanded=False)
    with st.expander("知识引用 ID 与检索记录", expanded=False):
        st.write("实际提供给模型的知识 ID：", usage['supplied'] or '无 / 未记录')
        st.write("方案和代码显式引用的知识 ID：", usage['cited'] or '无显式引用')
        if usage['references']:
            st.table([{**row, '知识ID': ', '.join(row['知识ID']) or '无显式引用'} for row in usage['references']])
        st.json(retrieval, expanded=False)
    with st.expander("需求、完整计划与校准记录", expanded=False):
        st.write("需求理解：", planning.get('understanding') or '未记录，未从需求反推模型理解')
        if report.get('requirement_understanding'):
            st.json(report['requirement_understanding'], expanded=False)
        if report.get('business_acceptance'):
            st.json(report['business_acceptance'], expanded=False)
        st.write("需求原文：", task.get('requirement', '未记录'))
        st.write("结构化目标：", task.get('anomaly_target', '未记录'))
        st.json(planning, expanded=False)
        for candidate in report.get('candidates') or []:
            st.write("候选方案：", candidate.get('candidate_id', '未记录'))
            st.json({'plan':candidate.get('plan'), 'calibration':candidate.get('calibration')}, expanded=False)


def show_repairs(directory, report):
    candidates = report.get('candidates') or []
    repairs = recorded_repairs(report)
    st.subheader("验证摘要")
    st.write(f"已记录 {len(candidates)} 个候选、{sum(len(c.get('versions') or []) for c in candidates)} 个源码版本；实际修复次数：{len(repairs)}（按已记录代码修复版本计数）。")
    recorded_stages = report.get('stage_status') or {}
    final = report.get('final') or {}
    stages = {'engineering': final.get('engineering_status') or recorded_stages.get('engineering'),
              'detection': final.get('execution_status') or recorded_stages.get('detection'),
              'benchmark': recorded_stages.get('benchmark')}
    if any(stages.values()):
        st.table([{'已记录阶段':label, '状态':STATUS_NAMES.get(stages[key], stages[key])}
                  for key, label in (('engineering','工程验证'), ('detection','最终检测'), ('benchmark','独立模拟基准')) if stages.get(key)])
    if not repairs:
        st.caption("没有已记录的代码修复版本；不生成修复过程。")
    outcome = result_outcome(report)
    if outcome['level'] == 'error':
        st.error(outcome['summary'])
    for candidate in candidates:
        cid = candidate.get('candidate_id', '未记录')
        method = ((candidate.get('plan') or {}).get('config') or {}).get('method_id')
        candidate_name = METHOD_NAMES.get(method, cid)
        versions = candidate.get('versions') or []
        if candidate.get('failure'):
            failure = candidate['failure']
            st.error(f"候选 {candidate_name}：" + str(failure.get('message') or failure.get('code') or '原因未记录'))
        failed_checks = [check for v in versions for check in (v.get('validation') or {}).get('checks', []) if check.get('passed') is False]
        if any(old_validator_affected(v) for v in versions):
            st.warning('此候选包含受旧验证器 v1 缺陷影响的历史判定；不能直接作为算法失败结论。')
        if failed_checks:
            difference = failed_checks[0].get('difference') or {}
            st.caption('首条未通过检查：' + str(difference.get('message') or difference.get('code') or '原因未记录'))
            st.warning(f"候选 {candidate_name} 保留 {len(failed_checks)} 条未通过的检查记录（含历史版本）；请展开对应版本核查。")
        if not versions:
            st.caption(f"候选 {candidate_name} 没有可审查的源码版本，不能计为已通过。")
        for version in versions:
            number = version.get('version', '未记录')
            validation = version.get('validation') or {}
            passed = '通过' if validation.get('passed') is True else '未通过' if validation.get('passed') is False else '未记录'
            iteration = '初始实现' if number == 0 else f'第 {number} 轮代码修复'
            with st.expander(f"{candidate_name} · v{number} · {iteration} · 检查{passed}", expanded=False):
                st.caption(f"候选标识 {cid}；版本来源 {version.get('origin', '未记录')}；协议 {validation.get('protocol', '未记录')}；源码 {version.get('source_sha256', '未记录')}；父版本 {version.get('parent_source_sha256') or '无 / 未记录'}")
                if old_validator_affected(version):
                    st.warning("此原始判定受旧验证器 v1 缺陷影响，不能当作算法本身失败的结论；原记录保留，需使用 v2 独立复验。")
                for check in validation.get('checks') or []:
                    st.write("检查：", check.get('check', '未记录'), '；', '通过' if check.get('passed') is True else '未通过' if check.get('passed') is False else '未记录')
                    if check.get('passed') is False:
                        difference = check.get('difference') or {}
                        st.error(str(difference.get('message') or difference.get('code') or '差异未记录'))
                    st.json(check, expanded=False)
                if version.get('explanation'):
                    st.write("该版本说明：", version['explanation'])
                if candidate.get('failure'):
                    st.json(candidate['failure'], expanded=False)
                try:
                    raw = source_bytes(directory, version)
                except FileNotFoundError:
                    st.caption('该版本的源码文件未单独保存；未提供单独源码下载。')
                except (OSError, ValueError, KeyError) as error:
                    st.warning("该版本源码不可下载：" + str(error))
                else:
                    st.download_button(f"下载 {cid} v{number} 源码", raw, file_name=f"{cid}-v{number}.py", key=f"version-{(report.get('task') or {}).get('task_id', directory.name)}-{cid}-{number}", on_click='ignore')
    with st.expander("原始失败与阶段记录", expanded=False):
        st.json({'failure':report.get('failure'), 'stage_status':report.get('stage_status'), 'final_failure':(report.get('final') or {}).get('failure')}, expanded=False)


def show_publication(directory, report, knowledge_path):
    st.subheader('知识回写')
    try:
        evidence = publication_evidence(directory, report, knowledge_path)
    except (OSError, ValueError, sqlite3.Error, RuntimeError, KeyError) as error:
        st.warning('回写证据未核实：' + str(error))
        return
    st.write('回写回执状态：', evidence['receipt'].get('status', '未记录'))
    for note in evidence['notes']:
        st.warning(note)
    nodes = {n['id']:n for n in evidence['nodes']}
    experiences = [n for n in evidence['nodes'] if n['kind'] == 'Experience']
    if experiences:
        st.table([{'方法':n['payload'].get('method_id', '未记录'),
            '实现版本':nodes.get(n['payload'].get('implementation_id'), {}).get('payload', {}).get('version', '未记录'),
            '经验性质':'获准在新输入重新验证后复用' if n['payload'].get('reusable_implementation') else '风险 / 未获准直接复用',
            '已记录问题':n['payload'].get('issue', '未记录')} for n in experiences])
    with st.expander('回写回执、节点与适用范围', expanded=False):
        st.json(evidence['receipt'], expanded=False)
        for node in experiences:
            value = node['payload']
            st.write('经验：', node['id'])
            st.write('适用范围：', value.get('reuse_scope', '未记录'))
            st.json(value, expanded=False)
        for node in evidence['nodes']:
            if node['kind'] != 'Experience':
                st.write(node['kind'], node['id'])
                st.json(node['payload'], expanded=False)
    st.caption('仅从当前回执与只读知识库核实；缺失节点不会补写，浏览不会发布。')


def show_comparison(directory, report):
    from factory.metrics.ui_presentation import (
        candidate_label, config_summary, selection_explanation, comparison_columns, comparison_value,
    )
    st.markdown('#### 候选方案比较')
    explanation = selection_explanation(report)
    chosen = (report.get('selection') or {}).get('selected')
    selection = report.get('selection') or {}
    adopted = next((c for c in report.get('candidates') or [] if c.get('candidate_id') == chosen), None)
    st.caption(('采用 ' + candidate_label(adopted, METHOD_NAMES) if adopted else '尚未选择方案')
               + ' · 评价目标：' + explanation['评价目标'] + ' · ' + explanation['实际选优偏好']
               + ' · 比较依据：' + explanation['比较依据'] + '；最终测试不参与选择。')
    columns = comparison_columns(report)
    summary = []
    for candidate in report.get('candidates') or []:
        result = candidate.get('report') or {}
        summary.append({'候选':candidate_label(candidate, METHOD_NAMES),
            '排名':selection.get('ranking', []).index(candidate['candidate_id']) + 1 if candidate.get('candidate_id') in selection.get('ranking', []) else '未入选',
            '采用状态':'已采用' if chosen and chosen == candidate.get('candidate_id') else '未采用' if chosen else '尚未选择',
            '工程检查':STATUS_NAMES.get(result.get('engineering_status'), '未记录'),
            **{label:comparison_value(result, key, selection) for key, label in columns},
            **({'开发覆盖率':metric_text(result.get('coverage'), percent=True)}
               if not any(key.startswith('coverage') for key, _ in columns) else {})})
    if summary:
        st.dataframe(summary, hide_index=True, width='stretch')
    else:
        st.info('未记录候选方案。')
    with st.expander("选优依据与冻结记录", expanded=False):
        for label, value in explanation.items():
            st.write(label + '：' + value)
        st.caption("无标签只按工程指标选择，未采用不等于失败；各版本源码及原始检查见「运行与验证」。")
        if any('_fbeta' in key for key, _ in columns):
            st.caption('Fβ 由已记录的开发集 TP/FP/FN 和本次 β 计算，仅用于展示；不重新选优。')
        if selection.get('reason'):
            st.write('选择依据：' + selection['reason'])
        elif selection.get('status') == 'USER_PRESELECTED_METHOD':
            st.caption('此为旧版上传记录：预选方法，未做多候选比较。')
        st.write('冻结选择记录：')
        st.json(report.get('selection') or {'status':'未记录'}, expanded=False)
        st.write('执行 / 工程 / 效果 / 业务状态（分别记录）：')
        final = report.get('final') or {}
        st.json({k:final.get(k, '未记录') for k in ('execution_status','engineering_status','effect_status','acceptance_status')}, expanded=False)
    for candidate in report.get('candidates') or []:
        with st.expander(candidate_label(candidate, METHOD_NAMES) + ' · 参数与工程明细', expanded=False):
            st.write('冻结参数：' + config_summary(candidate))
            st.write('源码版本数：' + str(len(candidate.get('versions') or [])))
            st.write('校准状态：' + str(candidate.get('calibration_status') or (candidate.get('calibration') or {}).get('status') or '未记录'))
            st.json({'calibration': candidate.get('calibration'),
                     'development_report': candidate.get('report')}, expanded=False)


def show_benchmark(directory, report):
    from factory.metrics.charts import show_curve
    from factory.metrics.upload import BENCHMARK_NOTICE
    benchmark = report.get('benchmark')
    if not isinstance(benchmark, dict):
        st.caption('独立模拟基准：该报告未记录；未推断为已执行。')
        return
    evaluation = benchmark.get('evaluation') or {}
    valid = benchmark.get('execution_status') == 'SUCCEEDED' and evaluation.get('execution_status') == 'SUCCEEDED' and evaluation.get('effect_status') == 'MEASURED'
    if not valid:
        st.caption('独立模拟基准：' + str(benchmark.get('execution_status') or '未记录') + ' · ' + str(benchmark.get('reason') or (benchmark.get('failure') or {}).get('message') or ('未记录成功的效果评价' if benchmark.get('execution_status') == 'SUCCEEDED' else '原因未记录')))
        with st.expander('独立基准原始记录', expanded=False):
            st.json(benchmark, expanded=False)
        return
    with st.expander('独立模拟基准（不代表当前上传数据或生产效果）', expanded=False):
        st.info(BENCHMARK_NOTICE)
        st.caption(f"{benchmark.get('generator_version', '未记录')} · {benchmark.get('scenario', '未记录')} · 独立重新拟合与校准")
        show_effect(benchmark['evaluation'])
        show_curve(directory, (report.get('curves') or {}).get('benchmark'), key=(report.get('task') or {}).get('task_id', directory.name)+'-benchmark')
        st.json(benchmark, expanded=False)


def task_title(report):
    metric = (report.get('data_source') or {}).get('metric') or (report.get('task') or {}).get('metric')
    return METRIC_NAMES.get(metric, metric or '指标') + '异常检测'


RESULT_SECTIONS = {'结果概览':'结果概览', '验证过程':'运行与验证', '知识与依据':'知识依据', '模型用量':'模型用量'}


def remember_result_section():
    st.session_state['result_section'] = st.session_state['result-section-widget']


def result_sections(default='结果概览'):
    """A radio dispatches only the selected section; native tabs render all bodies."""
    section = st.session_state.get('result_section', default)
    if section not in RESULT_SECTIONS:
        section = '结果概览'
    st.session_state['result-section-widget'] = section
    with st.container(key='result-sections'):
        return st.radio('结果内容', list(RESULT_SECTIONS), key='result-section-widget',
            format_func=RESULT_SECTIONS.get, horizontal=True, label_visibility='collapsed',
            on_change=remember_result_section)


def detection_goal(report):
    """Read frozen target and selected config; never infer MAD from a business T."""
    task = report.get('task') or {}
    outcome = result_outcome(report)
    plan = outcome['candidate'].get('plan') or {}
    config = (report.get('final') or {}).get('config') or plan.get('config') or {}
    method = config.get('method_id')
    target = {'upper':'持续升高', 'lower':'持续降低', 'two_sided':'双向偏离'}.get(task.get('anomaly_target'), '目标未记录')
    metric = task_title(report).removesuffix('异常检测')
    parts = ['检测目标：' + metric + target,
             '采用方案：' + (METHOD_NAMES.get(method, method or '未记录') if outcome['selected'] else '尚未选择 / 未记录')]
    if outcome['selected'] and 'threshold' in config and config.get('threshold') is not None:
        unit = (report.get('data_source') or {}).get('unit', '')
        parts.append('阈值：' + str(config['threshold']) + ('%' if unit in {'percent', '%'} else (' ' + unit if unit else '（单位未记录）')))
    elif outcome['selected']:
        threshold = (report.get('final') or {}).get('threshold')
        if threshold is not None:
            parts.append('分数阈值：' + str(threshold))
    if outcome['selected'] and plan.get('persistence_points') is not None:
        parts.append('连续 ' + str(plan['persistence_points']) + ' 点告警')
    return ' ｜ '.join(parts)


def report_status(report, outcome):
    source = report.get('data_source') or {}
    final = report.get('final') or {}
    source_name = {'uploaded_csv':'上传CSV', 'builtin_simulation':'内置模拟数据'}.get(source.get('type'), '未记录')
    acceptance = (report.get('business_acceptance') or {}).get('status') or final.get('acceptance_status')
    status_prefix = '' if outcome['succeeded'] else '原始阶段记录（检测未成功，不代表效果或业务通过）：'
    def status_label(label, value):
        text = label + '：' + STATUS_NAMES.get(value, value or '未记录')
        if value == 'FAILED' or value == 'COVERAGE_FAILED':
            return ':red-badge[' + text + ']'
        if value in {'NOT_EVALUATED','NOT_MEASURED','RUNNING','PLAN_ONLY'}:
            return ':orange-badge[' + text + ']'
        if outcome['succeeded'] and value in {'SUCCEEDED','COMPLETED','PASSED','MEASURED'}:
            return ':green-badge[' + text + ']'
        return text
    frozen_source = '数据来源：' + source_name
    if source.get('host_id'):
        frozen_source += ' · 主机：' + source['host_id']
    text = frozen_source + ' · ' + status_prefix + ' · '.join(status_label(label, value)
        for label, value in (('执行', report.get('completion_status') or report.get('status')),
            ('效果', final.get('effect_status')), ('业务验收', acceptance)))
    origin_label = {'mock': '受控示例', 'reference': '人工参考',
                    'fault_injection': '故障注入', 'historical': '历史复验'}.get(report.get('origin'))
    st.caption(text + (' · 来源：' + origin_label if origin_label else ''))


def render_report(directory, report, knowledge_path, section="结果概览", *, header=None):
    task = report.get('task') or {}
    source = report.get('data_source') or {}
    task_id = task.get('task_id') or directory.name
    if header is None:
        with st.container(key='result-header'):
            heading, download = st.columns([3, 1.4], vertical_alignment='center')
    else:
        heading, _, download = header
    heading.subheader(task_title(report))
    with download.popover('下载与原始记录', width='stretch'):
        show_downloads(directory, report)
    outcome = result_outcome(report)
    report_status(report, outcome)
    section = result_sections(section)
    if section == '模型用量':
        show_model_usage(report)
        return
    if section == '知识与依据':
        show_knowledge(report)
        if st.button('在知识图谱中查看', key='open-task-graph'):
            st.session_state['graph_scope'] = str(directory / 'report.json')
            st.session_state['graph_filters'] = {'method':'', 'status':''}
            st.session_state['page'] = '知识图谱'
            st.rerun()
        show_publication(directory, report, knowledge_path)
        return
    if section == '验证过程':
        show_repairs(directory, report)
        if isinstance(report.get('benchmark'), dict):
            show_benchmark(directory, report)
        return
    # Replace just the redundant no-label clause; preserve all failure/coverage/
    # acceptance/benchmark warnings supplied by the existing outcome projection.
    summary = outcome['summary']
    if outcome['no_labels'] and outcome['succeeded']:
        summary = summary.replace('检测已完成；无标签，可查看检测结果，但无法评价准确性。',
            '未提供标签，准确性与漏检情况尚未评估。')
    if outcome['level'] != 'success':
        getattr(st, outcome['level'])(summary)
    elif (report.get('final') or {}).get('matched_delay_seconds', {}).get('missed_events'):
        st.warning('已记录漏检事件：' + str(report['final']['matched_delay_seconds']['missed_events']))
    if report.get('proposal'):
        st.markdown('**检测方案草稿（尚未完成代码验证）**')
        st.table([{'方法':METHOD_NAMES.get(p.get('config',{}).get('method_id'), '未记录'),
                   '验证状态':'尚未完成', '说明':'；'.join(p.get('limitations',[]))}
                  for p in report['proposal']['candidates']])
        with st.expander('方案草稿的完整参数与标识', expanded=False):
            st.json(report['proposal'], expanded=False)
    with st.container(border=True, key='result-summary'):
        goal, original = st.columns([4, 1], vertical_alignment='center')
        goal.write(detection_goal(report))
        with original.popover('原始需求'):
            st.write(task.get('requirement') or '未记录')
    for warning in dict.fromkeys((report.get('selection') or {}).get('warnings', [])):
        st.warning(warning)
    show_summary(report, directory)
    from factory.metrics.charts import show_curve
    st.markdown('#### 检测曲线 · UTC')
    if not source:
        st.info('该历史任务未保存冻结数据来源摘要，不能从当前表单反推。')
    curve = (report.get('curves') or {}).get('detection')
    if curve and not outcome['succeeded']:
        st.info('最终检测未成功或未执行；不展示可能属于旧结果的曲线，请在原始记录中核查。')
    else:
        show_curve(directory, curve, key=task_id+'-detection', compact=True)
    show_comparison(directory, report)
    show_more_metrics(report)
    with st.expander('冻结输入摘要与数据划分', expanded=False):
        last = st.session_state.get('last_metrics_run') or {}
        st.write('本会话最近提交任务' if last.get('task_id') == task_id else '历史保存任务')
        st.caption(f'任务 ID：{task_id} · 当前采用候选 ID：{outcome["selected"] or "未记录"}')
        labels = '未提供' if outcome['no_labels'] else '已提供' if source.get('labels') else '已记录' if isinstance((report.get('final') or {}).get('truth_events'), list) else '未记录'
        st.write('真实标签：' + labels)
        if source:
            st.json({key: value for key, value in source.items() if key != 'splits'}, expanded=False)
            if source.get('splits'):
                st.table(source['splits'])
            if source.get('normal_history_assumption'):
                st.warning(source['normal_history_assumption'])
        else:
            st.caption('来源摘要未记录。')
    if any(old_validator_affected(v) for c in report.get('candidates') or [] for v in c.get('versions') or []):
        st.warning('此封存记录含受方法校验协议 v1 缺陷影响的判定；原记录保留，重新验证应使用协议 v2。')


def show_downloads(directory, report):
    task_id = (report.get('task') or {}).get('task_id') or directory.name
    if (directory / 'delivery.zip').is_file():
        st.download_button('下载交付包', (directory / 'delivery.zip').read_bytes(),
            file_name='delivery.zip', key='delivery-'+task_id, on_click='ignore', type='primary', width='stretch',
            help='交付包包含上传数据。' if (report.get('data_source') or {}).get('type') == 'uploaded_csv' else '下载已保存的交付包。')
    else:
        st.caption('交付包未记录 / 尚未生成')
    with st.expander("原始结果 JSON"):
        st.json(report, expanded=False)
    st.download_button("下载报告 JSON", canonical(report), file_name="metrics-report.json", mime="application/json", on_click="ignore")
    for candidate in report.get("candidates") or []:
        if not candidate.get("versions"):
            continue
        try:
            raw = source_bytes(directory, candidate["versions"][-1])
        except FileNotFoundError:
            st.caption("候选 " + candidate["candidate_id"] + " 的源码文件未单独保存；未提供单独源码下载。")
        except (OSError, ValueError, KeyError) as error:
            st.error(str(error))
        else:
            st.download_button("下载 " + candidate["candidate_id"] + " 源码", raw, file_name=candidate["candidate_id"] + ".py",
                               key="source-" + candidate["candidate_id"], on_click="ignore")


def show_effect(result):
    rows = []
    for scope, title in (("point", "点级"), ("event", "事件级")):
        values = result.get(scope) or {}
        rows.append({"范围": title, "TP": values.get("tp"), "FP": values.get("fp"), "FN": values.get("fn"), "TN": values.get("tn"),
            "Precision": metric_text(values.get("precision"), percent=True), "Recall": metric_text(values.get("recall"), percent=True), "F1": metric_text(values.get("f1"))})
    st.table(rows)
    delay = result.get("matched_delay_seconds") or {}
    st.caption(f"可判断覆盖率 {metric_text(result.get('coverage'), percent=True)} · 正常误报频次 {metric_text(result.get('normal_false_alarms_per_host_hour'))} 次/主机小时 · 匹配发现延迟中位数 {metric_text({'value': delay.get('median'), 'null_reason': delay.get('null_reason') or 'not_recorded'})} 秒 · 漏检事件 {delay.get('missed_events') if delay.get('missed_events') is not None else '未记录'}；暖机不计入分母，不做 point adjustment。")


def campaign_status(path):
    if not path:
        return None
    from factory.metrics.budget import read_campaign
    try:
        return read_campaign(path)
    except (OSError, sqlite3.Error, ValueError):
        return None


def show_model_usage(report):
    from factory.metrics.usage import model_usage
    usage = model_usage(report)
    st.markdown("**本次任务模型用量**")
    origin = report.get('origin', '未记录')
    st.caption('模型来源：' + origin + ' · ' + ORIGINS.get(origin, '来源说明未记录'))
    if usage['kind'] == 'mock':
        st.caption("mock：无消耗 · 真实模型请求 0 次 · token 0")
    elif usage['kind'] == 'replay':
        st.caption("历史代码回放：无模型消耗 · 请求 0 次 · token 0")
    elif usage['kind'] == 'not_recorded':
        st.caption("该历史任务未保存模型用量，次数与 token 未记录。")
    else:
        total = str(usage['total_tokens']) if usage['total_tokens'] is not None else '未完整记录'
        columns = st.columns(3)
        columns[0].metric("请求尝试次数", usage['requests'])
        columns[1].metric("输入 / 输出 token（已记录）", f"{usage['input_tokens'] if usage['input_tokens'] is not None else '未记录'} / {usage['output_tokens'] if usage['output_tokens'] is not None else '未记录'}")
        columns[2].metric("总 token", total)
        st.caption(f"包含规划、生成、修复与重试；额度预约 {usage['reservations']} 次。")
        if usage['missing_usage_requests']:
            st.caption(f"{usage['missing_usage_requests']} 次请求未完整返回 token；未知消耗不按 0 计算，不估算费用。")


def change_ui_setting(state, field, widget):
    from factory.metrics.ui_settings import load_settings, save_settings
    settings = load_settings(state)
    settings[field] = st.session_state[widget]
    save_settings(state, settings)


def show_configuration(state, knowledge_path, campaign, env_file):
    from factory.metrics.ui_settings import load_settings, configured_model_id, ROUND_LIMITS
    from factory.metrics.budget import CallBudget
    settings = load_settings(state)
    st.subheader("系统配置")
    st.caption("修改即时保存，仅用于之后提交的任务；历史任务和报告保持原记录。")
    st.session_state['settings_model_mode'] = settings['model_mode']
    st.radio("模型配置", ['mock', 'api'], format_func=lambda v: 'mock' if v == 'mock' else '真实模型',
             key='settings_model_mode', horizontal=True, on_change=change_ui_setting,
             args=(state, 'model_mode', 'settings_model_mode'))
    if settings['model_mode'] == 'mock':
        st.caption("使用预设受控响应及人工参考代码，不调用真实模型，无请求额度或 token 消耗；Docker 验证与评价仍实际执行。")
    else:
        st.text_input("模型 ID", value=configured_model_id(env_file) or '未配置', disabled=True, key='configured_model_id',
                      help='来自服务器运行配置，仅展示；密钥和接口地址不在页面显示或编辑。')
        budget = campaign_status(campaign)
        if budget:
            st.write(f"当前第 {budget['round']} 轮：已预约 {budget['used']} / {budget['limit']} 次；剩余 {budget['remaining']} 次。历史累计预约 {budget['lifetime_reserved']} 次。")
        else:
            st.warning("额度账本不可用，请检查配置路径和文件。已有额度记录不会自动重置。")
        st.session_state['settings_round_limit'] = settings['round_limit']
        st.selectbox("新一轮默认额度上限", ROUND_LIMITS, key='settings_round_limit',
                     on_change=change_ui_setting, args=(state, 'round_limit', 'settings_round_limit'))
        st.caption("选择上限只保存默认值。点击刷新后才授权新一轮额度，旧轮次和调用记录完整保留，未确定请求不退还原轮额度。")
        st.caption("此处是应用请求次数预算，不是供应商账户余额；刷新不会改变供应商限额或费用。")
        if st.button("刷新请求额度（授权新一轮）", key='authorize-model-round', disabled=budget is None):
            try:
                token = st.session_state.setdefault('budget_authorization', uuid4().hex)
                number = CallBudget(Path(campaign)).authorize_round(settings['round_limit'], token)
                st.session_state['budget_authorization'] = uuid4().hex
                st.session_state['budget_authorized_round'] = number
                st.rerun()
            except (OSError, ValueError, sqlite3.Error) as error:
                st.error("额度授权失败：" + str(error))
        if st.session_state.get('budget_authorized_round'):
            st.success(f"已授权第 {st.session_state['budget_authorized_round']} 轮；未发起任何模型请求。")
        if budget:
            with st.expander("历史额度轮次", expanded=False):
                from datetime import datetime
                from zoneinfo import ZoneInfo
                st.table([{**row, '当前轮': '是' if row['当前轮'] else '否',
                           '开始时间': datetime.fromtimestamp(row['开始时间'], ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S') if row['开始时间'] is not None else '历史轮次，时间未记录'} for row in budget['rounds']])


def main():
    st.set_page_config(page_title="数值监控算法能力工厂", layout="wide", initial_sidebar_state="expanded")
    from factory.metrics.ui_style import apply_style
    apply_style()
    page = navigation()
    if page == '创建任务':
        st.title("数值监控算法能力工厂")
    state = Path(os.environ.get("FACTORY_METRICS_STATE", ".runtime/metrics/ui"))
    snapshot_path = Path(os.environ.get("FACTORY_METRICS_SNAPSHOT", ".runtime/metrics/knowledge-v3.json"))
    knowledge_path = Path(os.environ.get("FACTORY_METRICS_KNOWLEDGE", "secrets/knowledge.json"))
    campaign = os.environ.get("FACTORY_METRICS_CAMPAIGN")
    env_file = os.environ.get("FACTORY_METRICS_MODEL_ENV")
    image = os.environ.get("FACTORY_METRICS_IMAGE")
    from factory.metrics.ui_settings import load_settings, initialize_campaign
    try:
        settings = load_settings(state)
        initialize_campaign(campaign)
    except (OSError, ValueError, sqlite3.Error) as error:
        st.error(str(error))
        return
    budget = campaign_status(campaign)
    if budget and page in {"创建任务", "配置"}:
        st.caption(f"真实模型请求额度：{budget['used']}/{budget['limit']}；剩余 {budget['remaining']} 次")
        if not budget["remaining"]:
            st.info("本轮 API 额度已用完。可查看封存真实案例，或选择 mock 验证流程。")
    if page == "配置":
        show_configuration(state, knowledge_path, campaign, env_file)
        return
    if page == "知识图谱":
        from factory.metrics.graph_view import show_graph
        show_graph(knowledge_path, state)
        return
    if page != "创建任务":
        show_results(state, knowledge_path, page)
        return
    show_create(state, snapshot_path, knowledge_path, campaign, env_file, image, budget, settings)


INDICATORS = {
    "cpu_spike": ("CPU 利用率 · 突增", "CPU 使用比例（%），检测短时或持续的异常升高。"),
    "memory_shift": ("内存利用率 · 阶跃", "内存使用比例（%），检测突然升高后持续维持高位的变化。"),
    "memory_drift": ("内存利用率 · 漂移", "内存使用比例（%），检测逐渐升高的缓慢漂移。"),
    "disk_peaks": ("磁盘 I/O 延迟", "磁盘访问延迟（ms），区分常规短峰与持续高延迟。"),
    "network_missing": ("网络速率", "已换算的网络传输速率（bytes/s），检测持续升高；允许空值表示缺失。不是原始累计计数器。"),
    "periodic": ("CPU 利用率 · 周期", "带周期波动的 CPU 使用比例（%），检测周期背景上的额外升高。"),
}


def show_create(state, snapshot_path, knowledge_path, campaign, env_file, image, budget, settings):
    last = st.session_state.get('last_metrics_run')
    if last and last.get('directory'):
        try:
            recent = read_json(Path(last['directory']), 'report.json')
            with st.expander('最近任务与模型用量', expanded=False):
                st.write(recent['task']['task_id'])
                show_model_usage(recent)
        except (OSError, ValueError, KeyError):
            st.caption('最近任务用量未记录，不能按零消耗推断。')
    from factory.metrics.creation import show_create as language_create
    language_create(state, snapshot_path, knowledge_path, campaign, env_file, image, budget, settings)


def navigation():
    if "page" not in st.session_state:
        st.session_state["page"] = "创建任务"
    page = st.session_state["page"]
    legacy = {'结果概览':'结果概览', '知识与依据':'知识与依据', '验证过程':'验证过程',
              '运行与验证':'验证过程', '知识依据':'知识与依据', '模型用量':'模型用量'}
    if page in legacy:
        st.session_state['result_section'] = legacy[page]
        page = st.session_state['page'] = '任务结果'
    elif page == '查看结果':
        page = st.session_state['page'] = '任务结果'
    with st.sidebar:
        with st.container(key='factory-navigation'):
            with st.container(key='nav-brand'):
                st.markdown('**算法能力工厂**')

            def entry(label, route, icon, key=None):
                if st.button(label, key=key or 'nav-'+route, icon=':material/'+icon+':',
                             type='primary' if page == route else 'secondary', width='stretch'):
                    st.session_state['page'] = route
                    st.rerun()

            entry('创建任务', '创建任务', 'add')
            entry('任务结果', '任务结果', 'grid_view', key='nav-查看结果')
            entry('知识图谱', '知识图谱', 'hub')
            with st.container(key='nav-system'):
                st.divider()
                entry('系统配置', '配置', 'settings')
    return page


RESULT_PAGES = ("结果概览", "知识与依据", "验证过程")


def task_label(path):
    report = read_json(Path(path).parent, "report.json")
    # Streamlit serializes selectbox values through format_func. Duplicate labels
    # deserialize to the last matching option even when Python values are paths.
    task_id = (report.get('task') or {}).get('task_id') or str(Path(path).resolve())
    name = (report.get('data_source') or {}).get('display_name')
    return ' · '.join(str(value) for value in (task_title(report), name, task_id) if value)


def remember_task():
    st.session_state["selected_task"] = st.session_state["review_task"]


def show_results(state, knowledge_path, section):
    from factory.metrics.background import task_records
    records = task_records(state)
    if not records:
        st.info("当前没有运行记录。请先创建任务。")
        return
    by_path = {record['path']: record for record in records}
    options = list(by_path)
    if st.session_state.get("selected_task") not in options:
        if st.session_state.get("selected_task"):
            st.info("原选任务记录已不存在，已切换到当前可用任务。")
        st.session_state["selected_task"] = st.session_state.get("review_task") if st.session_state.get("review_task") in options else options[0]
    # Keep durable state separate from widget state: Streamlit removes hidden widgets.
    st.session_state["review_task"] = st.session_state["selected_task"]
    try:
        def label(path):
            item = by_path[path]
            if Path(path).is_file() and not item['active']:
                return task_label(path)
            status = {'QUEUED':'排队中', 'RUNNING':'运行中', 'PENDING':'运行中', 'FAILED':'失败', 'INTERRUPTED':'已中断'}.get(item['status'], item['status'])
            return f"[{status}] {item.get('title', '')} · {item['task_id']}"
        with st.container(key='result-header'):
            header = st.columns([2.5, 2, 1.5], vertical_alignment='center')
        with header[1]:
            chosen = Path(st.selectbox("查看任务", options, key="review_task", format_func=label, on_change=remember_task, label_visibility="collapsed"))
        st.session_state["selected_task"] = str(chosen)
        item = by_path[str(chosen)]
        if item['active'] or not chosen.is_file():
            header[0].subheader('任务结果')
            header[2].caption('交付包尚未生成')
            show_running_task(state, str(chosen), usage_only=result_sections(section) == '模型用量')
            return
        report = read_json(chosen.parent, "report.json")
        render_report(chosen.parent, report, knowledge_path, section, header=header)
    except (OSError, ValueError, KeyError) as error:
        st.error("无法读取所选任务记录：" + str(error))


@st.fragment(run_every=2)
def show_running_task(state, report_path, *, usage_only=False):
    from factory.metrics.background import task_records
    item = next((r for r in task_records(state) if r['path'] == report_path), None)
    if item is None:
        st.info('正在等待任务记录。')
        return
    if not item['active'] and Path(report_path).is_file():
        st.rerun()
    if usage_only:
        st.info('任务尚无最终报告，暂不展示模型用量。')
        return
    st.subheader('任务运行中' if item['active'] else '任务尚未完成')
    st.write(item['requirement'])
    if item['active']:
        phase = {'QUEUED':'等待后台启动', 'CREATED':'准备数据', 'DATA_READY':'准备知识', 'KNOWLEDGE_READY':'规划方案',
                 'PLANNED':'准备候选', 'VALIDATING':'生成、验证与比较候选', 'SELECTED':'最终测试',
                 'FINAL_EVALUATED':'整理报告与回写', 'COMPLETED':'整理报告与下载包'}.get(item['phase'], item['phase'])
        st.info('任务仍在后台运行，可切页或刷新。当前阶段：' + phase)
        steps = running_steps(item['phase'])
        if steps:
            for column, step in zip(st.columns(6), steps):
                with column.container(border=True):
                    st.caption(step['状态'])
                    st.write(step['阶段'])
    else:
        st.error(item.get('message') or ('任务状态：' + item['status'] + '；尚无最终报告。'))
    with st.expander('任务标识与原始阶段', expanded=False):
        st.write('任务：' + item['task_id'])
        st.caption('原始阶段：' + item['phase'] + '；页面仅轮询已有记录，不会再次提交任务。')


def running_steps(phase):
    phases = {'QUEUED':0, 'CREATED':0, 'DATA_READY':1, 'KNOWLEDGE_READY':2,
              'PLANNED':3, 'VALIDATING':3, 'SELECTED':4, 'FINAL_EVALUATED':5, 'COMPLETED':5}
    if phase not in phases:
        return []
    current = phases[phase]
    return [{'阶段':label, '状态':'✓ 已完成' if index < current else
             ('等待启动' if phase == 'QUEUED' else '● 进行中') if index == current else '○ 待执行'}
            for index, label in enumerate(('准备数据','检索知识','规划方案','生成与验证','最终评价','保存结果'))]


if __name__ == "__main__":
    main()
