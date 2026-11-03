"""Language-first creation page. Browsing never calls a model or executes code."""
from factory.metrics.capability_registry import registry
import asyncio
import csv
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import streamlit as st

from contracts.metrics_requirement import RequirementDraft
from factory.metrics.requirements import (
    EXAMPLES, LABELS, DEFAULT_LABEL_SOURCE, binding_for, interpret_command, request_from_draft,
)
from factory.metrics.synthetic import SCENARIOS, generate, write_dataset
from factory.metrics.workflow import write_json


DISPLAY = {"simulation": "模拟数据（不连接真实服务器）", "upload": "上传 CSV", "upper": "持续升高",
           "lower": "持续降低", "two_sided": "双向偏离", "balanced": "综合选优",
           "precision": "偏好少误报", "recall": "偏好少漏报",
           "cpu_spike": "CPU 利用率 · 突增", "memory_shift": "内存利用率 · 阶跃",
           "memory_drift": "内存利用率 · 漂移", "disk_peaks": "磁盘 I/O 延迟",
           "network_missing": "网络速率", "periodic": "CPU 利用率 · 周期"}
DISPLAY.update({m: c.display_name for m, c in registry().cards.items()})
ORIGINS = {"user_explicit": "来自描述", "manual": "手动修正", "protocol_default": "系统默认", "attachment": "来自附件"}
EXAMPLE_LABELS = {
    'CPU 持续升高':'CPU 持续高负载',
    '内存缓慢漂移':'内存利用率逐渐升高',
    '上传 CSV':'使用已有监控 CSV',
    '磁盘高延迟':'磁盘 I/O 延迟异常',
}


def reset_input():
    if st.session_state.get('requirement_draft'):
        st.session_state['requirement_input_changed'] = True
    st.session_state['requirement_turns'] = [st.session_state['create_requirement']]
    st.session_state.pop('requirement_draft', None)
    st.session_state.pop('requirement_extractions', None)
    st.session_state.pop('requirement_overrides', None)
    st.session_state.pop('requirement_update', None)
    st.session_state.pop('requirement_followup', None)


def choose_example(label):
    st.session_state['create_requirement'] = EXAMPLES[label]
    reset_input()


def display_value(key, value, scenario=None):
    if isinstance(value, list): return ' ＋ '.join(DISPLAY.get(v, v) for v in value)
    if key == 'threshold' and scenario in SCENARIOS:
        return f"{value:g} " + {'percent':'%'}.get(SCENARIOS[scenario][1], SCENARIOS[scenario][1])
    if key == 'persistence_points': return f"连续 {value:g} 个异常采样点"
    return DISPLAY.get(str(value), str(value))


def confirmation_rows(draft):
    from factory.metrics.ui_presentation import OBJECTIVES
    values = draft.values
    gates = []
    for key, name in (('min_event_recall', '事件召回率 ≥'), ('min_event_f1', '事件 F1 ≥')):
        if key in values: gates.append(f'{name} {values[key]:.0%}')
    if 'max_false_alarms_per_hour' in values:
        gates.append(f"正常误报 ≤ {values['max_false_alarms_per_hour']:g} 次/主机小时")
    conditions = []
    if 'threshold' in values:
        conditions.append('阈值 ' + display_value('threshold', values['threshold'], values.get('scenario')))
    if 'persistence_points' in values:
        conditions.append(display_value('persistence_points', values['persistence_points']))
    return [
        {'确认项':'检测对象', '本次任务':DISPLAY.get(values.get('scenario'), '未记录')},
        {'确认项':'数据来源', '本次任务':DISPLAY.get(values.get('data_source'), '未记录')},
        {'确认项':'检测目标', '本次任务':DISPLAY.get(values.get('direction'), '未记录') + '；' + {'precision':'偏好少误报', 'recall':'偏好少漏报', 'balanced':'综合选优'}.get(values.get('selection_policy'), '偏好未记录')},
        {'确认项':'评价目标', '本次任务':OBJECTIVES.get(values.get('evaluation_objective'), '未记录')},
        {'确认项':'告警条件', '本次任务':'；'.join(conditions) or '未指定，待规划确认'},
        {'确认项':'候选方法', '本次任务':display_value('methods', values.get('methods', [])) or '未记录'},
        {'确认项':'验收目标', '本次任务':'；'.join(gates) or '未定义业务验收门槛'},
    ]


def show_create(state, snapshot_path, knowledge_path, campaign, env_file, image, budget, settings):
    from factory.metrics.ui_settings import configured_model_id
    from factory.metrics.upload import simple_upload_options, inspect_upload, label_flags, prepare_upload, upload_example
    mode, retrieval = settings['model_mode'], 'structured'
    profile = configured_model_id(env_file) or ''
    api_ready = bool(profile and campaign and budget and budget['remaining'] > 0)
    parse_ready = mode == 'mock' or api_ready
    model_text = 'mock：受控需求解析 / 人工参考代码，不代表真实模型能力' if mode == 'mock' else '真实模型：' + (profile or '未配置')
    st.caption(model_text)
    left, right = st.columns([1.25, 1], gap='large')
    previous_turns = st.session_state.get('requirement_turns')
    st.session_state.setdefault('create_requirement', previous_turns[0] if previous_turns else EXAMPLES['CPU 持续升高'])
    st.session_state.setdefault('requirement_turns', [st.session_state['create_requirement']])
    with left:
        with st.container(key='create-inputs'):
            title, examples = st.columns([3, 1.4], vertical_alignment='center')
            title.markdown('#### 描述检测需求')
            with examples.popover('填入示例', width='stretch'):
                st.caption('仅填入需求文本；不会上传文件或调用模型。')
                for label, display in EXAMPLE_LABELS.items():
                    st.button(display, key='example-' + label, on_click=choose_example, args=(label,), type='tertiary', width='stretch')
            st.text_area('说明检测对象、数据来源和告警要求', key='create_requirement', height=180,
                         on_change=reset_input, label_visibility='collapsed')
            with st.container(key='create-uploads'):
                observations, labels = st.columns(2, gap='small')
                with observations:
                    upload = st.file_uploader('监控数据 CSV（可选）', type=['csv'], key='create_upload', max_upload_size=16)
                with labels:
                    label_upload = st.file_uploader('异常标签 CSV（可选）', type=['csv'], key='create_labels', max_upload_size=16,
                        help='用于评估检测效果，需与监控数据匹配。')
            with st.expander('数据格式说明'):
                st.code('timestamp,host_id,value\n2026-08-01T00:00:00Z,server-a,35', language='csv')
                st.caption('UTF-8 CSV，三列及顺序固定；单主机、UTC 时间、等间隔，空值保留时间行。最多 16 MiB、50000 点，至少 202 点。')
                st.caption('上传：前 60 点拟合，第 61～200 点校准；余下按时间前半开发、后半最终测试。历史正常是用户假设，系统未验证。标签须完整覆盖第 201 点起的全部数据。')
                st.caption('模拟：每 60 秒一点，独立拟合、校准、开发与测试段；固定种子可复现。缺失最多前向填补 3 点。')
                st.caption('上传标签默认可信；仍校验格式、时间和主机对齐及完整覆盖。标签只供可信评价，不发送给需求理解模型或生成代码。')
                st.code('timestamp,host_id,is_anomaly\n2026-08-01T03:20:00Z,server-a,0', language='csv')
                st.caption('理解与生成共享请求额度；浏览、上传、选择示例和展开帮助不会调用模型。mock 使用受控解析与人工参考代码，不调用真实模型。')
                st.download_button('下载 CPU CSV 格式示例', upload_example('cpu_spike'), file_name='cpu-example.csv', mime='text/csv')
            parse_slot = st.container()
    raw = upload.getvalue() if upload is not None else None
    label_raw = label_upload.getvalue() if label_upload is not None else None
    label_source = DEFAULT_LABEL_SOURCE if label_raw is not None else ''
    turns = [st.session_state['create_requirement']]
    binding_args = dict(upload=raw, labels=label_raw, label_source=label_source, mode=mode, profile=profile, retrieval=retrieval)
    current_binding = binding_for(turns, **binding_args)
    stored = st.session_state.get('requirement_draft')
    draft = RequirementDraft.model_validate(stored) if stored else None
    current = bool(draft and draft.binding == current_binding)
    options, preview, points = None, None, None
    upload_error = ''
    # This only reads local attachment bytes. Dataset creation happens on submit.
    if raw is not None and draft and draft.values.get('scenario') in SCENARIOS:
        try:
            options = simple_upload_options(raw, scenario=draft.values['scenario'], display_name=upload.name)
            options['direction'] = draft.values.get('direction', 'upper')
            options['method'] = next(m for m, card in registry().cards.items() if options['direction'] in card.supported_directions)
            points, preview = inspect_upload(raw, **options)
            from factory.metrics.upload import comparison_split
            comparison_split(len(points))
            if label_raw is not None:
                label_flags(label_raw, points[200:], preview['host_id'])
        except (ValueError, csv.Error, UnicodeError) as error:
            upload_error = 'CSV 格式校验失败：' + str(error)
    sampling = options['sampling_seconds'] if options else 60
    ready = bool(current and not draft.issues and not upload_error and parse_ready and image and knowledge_path.is_file())
    reasons = []
    if mode != 'mock':
        if not profile: reasons.append('模型未配置：请在配置页核对服务器模型 ID。')
        if not campaign or budget is None: reasons.append('请求额度账本未配置或无法读取。')
        elif budget['remaining'] <= 0: reasons.append('请求额度不足：本轮剩余请求为 0。')
    if not draft: reasons.append('需求尚未理解，请先点击“理解需求”。')
    elif not current: reasons.append('草稿已过期，请重新理解当前需求与附件。')
    elif draft.issues: reasons.append('需求尚有冲突或待补充项，请按右侧提示修改原文。')
    if upload_error: reasons.append(upload_error)
    if not image or not knowledge_path.is_file():
        reasons.append('执行环境或知识库配置缺失：生成需要服务器配置隔离镜像和知识库配置文件；此处未探测连接健康状态。')
    with parse_slot:
        if mode == 'api':
            st.caption('理解需求将调用当前模型')
        else:
            st.caption('理解需求使用受控解析，不调用真实模型')
        if st.session_state.get('requirement_input_changed'):
            st.warning('输入已改变，原草稿已过期；请重新理解需求。')
        parse_label = '重新理解需求' if draft or st.session_state.get('requirement_input_changed') else '理解需求'
        if st.button(parse_label, key='understand-requirement', type='secondary' if ready else 'primary', disabled=not parse_ready, width='stretch'):
            if not turns[0].strip():
                st.error('请先描述检测需求。')
            else:
                try:
                    with st.spinner('正在理解需求并校验约束……'):
                        # Uploaded sampling metadata is inferred before any duration
                        # conversion, even when the metric is not yet parsed.
                        if raw is not None and options is None:
                            sample_options = simple_upload_options(raw, scenario='cpu_spike', display_name=upload.name)
                            sampling = sample_options['sampling_seconds']
                        new_binding = binding_for(turns, **binding_args)
                        parsed, extractions = asyncio.run(interpret_command(state=state, mode=mode, turns=turns, binding=new_binding,
                            campaign=Path(campaign) if campaign else None, env_file=Path(env_file) if env_file else None,
                            upload_present=raw is not None, labels_present=label_raw is not None, sampling_seconds=sampling,
                            label_source=label_source, revision=(draft.revision + 1) if draft else 1))
                        st.session_state['requirement_draft'] = parsed.model_dump(mode='json')
                        st.session_state['requirement_extractions'] = extractions
                        st.session_state['requirement_input_changed'] = False
                        st.session_state.pop('requirement_overrides', None)
                        st.session_state.pop('requirement_update', None)
                    st.rerun()
                except Exception:
                    st.error('需求理解未完成，请检查输入、模型配置及额度记录；未启动算法生成，不会自动切换模式或退还请求额度。')
    with right:
        with st.container(border=True, key='task-confirmation'):
            st.markdown('#### 任务确认')
            if not draft:
                st.write('理解需求后，在这里核对检测方案。')
            else:
                st.caption(f"草稿 v{draft.revision} · {'当前输入' if current else '已过期'} · {'受控解析' if draft.model_mode == 'mock' else '模型解析＋确定性校验'}")
                if not current: st.warning('原文、附件或运行配置已改变，请重新理解需求。')
                rows = [{'项目': LABELS[k], '本次任务': display_value(k, v, draft.values.get('scenario')),
                         '来源': ORIGINS.get(draft.evidence.get(k, {}).get('origin'), '系统默认')}
                        for k, v in draft.values.items() if k in LABELS and k != 'label_source']
                st.table(confirmation_rows(draft))
                from factory.metrics.ui_presentation import parameter_preview
                with st.expander('算法参数与来源', expanded=True):
                    st.table(parameter_preview(draft))
                    st.caption('按已选插件分别展示。插件默认值是候选起点，最终冻结配置见结果；固定阈值不作为其他方法的绝对告警阈值。')
                extra = [LABELS[k] + '：' + display_value(k, v, draft.values.get('scenario'))
                         for k, v in draft.values.items() if k in {'window', 'min_history', 'quantile', 'duration_seconds'}]
                if extra: st.caption('关键条件 · ' + '；'.join(extra))
                if 'threshold' not in draft.values: st.caption('未指定业务阈值：规划可提出候选假设，不标记成用户业务阈值。')
                if draft.values.get('selection_policy') in {'precision', 'recall'}:
                    if draft.values.get('data_source') == 'upload' and label_raw is None:
                        st.caption('无真实标签：保留效果偏好，实际按工程可用性、覆盖率和候选标识选优；效果及需标签的验收未评估。')
                    else:
                        with st.expander('选优指标说明', expanded=False):
                            metric = '点级' if draft.values.get('evaluation_objective') == 'sustained_coverage' else '事件'
                            st.caption(f'本次少误报使用{metric} F0.5；少漏报使用{metric} F2。同时考虑精确率和召回率，不以告警少代替准确。')
                if draft.issues:
                    st.warning('需要补充或修改')
                    for issue in draft.issues: st.write('• ' + issue)
                for notice in draft.defaults:
                    if notice.startswith('演示提示：'):
                        st.info(notice)
                with st.expander('提取依据与默认项'):
                    st.table(rows)
                    for key, item in draft.evidence.items():
                        if key == 'label_source': continue
                        st.write(LABELS.get(key, key) + ' · ' + ORIGINS.get(item['origin'], item['origin']))
                        st.caption(item.get('quote', ''))
                        if item.get('conversion'): st.caption(item['conversion'])
                    for default in draft.defaults: st.caption(default)
                    st.caption('需求理解任务：' + (draft.parse_task_id or '未记录'))
                    st.caption(f"本轮理解：请求 {draft.model_usage.get('requests', '未记录')} 次 · token {draft.model_usage.get('total_tokens') if draft.model_usage.get('total_tokens') is not None else '未完整记录'}；生成阶段另计，共享同一额度。")
                if upload_error: st.error(upload_error)
                elif current and preview: st.success(f"CSV 校验通过：{preview['points']} 点 · 每 {sampling} 秒 · 单主机。")
            submitted = st.button('生成并验证', type='primary' if ready else 'secondary', key='generate-requirement', disabled=not ready, width='stretch')
            if not ready:
                for reason in reasons:
                    if not draft and reason == '需求尚未理解，请先点击“理解需求”。':
                        continue  # The empty confirmation card already gives this next step.
                    st.caption(reason)
    if submitted:
        try:
            request = request_from_draft(draft, current_binding=current_binding)
            task_id = 'ui-' + uuid4().hex[:16]
            inputs = state / 'inputs' / task_id
            inputs.mkdir(parents=True, exist_ok=False)
            data = inputs / 'dataset'
            if draft.values['data_source'] == 'upload':
                if options is None: raise ValueError('上传数据尚未通过校验。')
                prepare_upload(data, raw, labels=label_raw, label_source=draft.values.get('label_source'), **options)
            else:
                write_dataset(data, generate(draft.values['scenario'], direction=draft.values['direction'], seed=uuid4().int % (2**32)))
            write_json(inputs / 'requirement-draft.json', draft.model_dump(mode='json'))
            request_file = inputs / 'request.json'
            write_json(request_file, request.model_dump(mode='json'))
            args = SimpleNamespace(state=state, mode=mode, campaign=Path(campaign) if campaign else None,
                env_file=Path(env_file) if env_file else None, task_id=task_id, task=request_file, dataset=data,
                snapshot=snapshot_path, knowledge=knowledge_path, image=image, retrieval=retrieval, fault_injection=False)
            from factory.metrics.background import submit
            result = submit(args)
            st.session_state['last_metrics_run'] = result
            st.session_state['selected_task'] = str(Path(result['directory']) / 'report.json')
            st.session_state['page'] = '结果概览'
            st.rerun()
        except ValueError as error:
            st.error(str(error))
        except Exception:
            st.error('任务未完成，请检查服务器运行记录；不会切换模型或重置额度。')
