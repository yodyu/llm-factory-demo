"""Read-only bounded plots of digest-bound artifacts; no scoring imports."""
import json
from contextlib import nullcontext
from datetime import datetime, timedelta
from pathlib import Path

import altair as alt
import streamlit as st

from factory.runtime.artifacts import digest
from factory.metrics.upload import read_curve


def remember_view(key):
    saved = dict(st.session_state.get('curve_view_state', {}))
    saved[key] = st.session_state[key]
    st.session_state['curve_view_state'] = saved


def view_binding(key):
    # Streamlit cleans up widgets on inactive sections. Keep a separate,
    # task-scoped display value so returning to a curve retains its view.
    saved = st.session_state.get('curve_view_state', {})
    if key not in st.session_state and key in saved:
        st.session_state[key] = saved[key]
    return {'key':key, 'on_change':remember_view, 'args':(key,)}


def show_curve(directory, binding, *, key, compact=False):
    if not binding:
        st.info("该记录未保存曲线所需产物")
        return
    try:
        data = read_curve(directory, binding)
    except (OSError, ValueError, KeyError):
        st.error("曲线产物缺失或摘要不匹配；不会重新运行检测。")
        return
    source_name = {"uploaded_csv": "上传CSV", "builtin_simulation": "内置模拟数据", "independent_benchmark": "独立模拟基准"}.get(data["source"]["type"], "未记录")
    if not compact:
        st.caption(f"{source_name} · 任务 {data['task_id']} · 候选 {data['candidate_id']} · {data['version']} · UTC · {data['source'].get('display_name', '')}")
    rows, result = data["rows"], data["result"]
    history_area, event_area = st.columns([1.3, 1.5], vertical_alignment='center') if compact else (nullcontext(), nullcontext())
    with history_area:
        if any(r["role"] == "fit_history" for r in rows):
            if not st.toggle("显示完整拟合/校准历史（仅原始观测，不计入效果）", **view_binding(key+"-history")):
                rows = [r for r in rows if r["role"] in {"warmup", "detection"}]
    events = result.get("predicted_events", [])
    if not isinstance(events, list):
        events = []
    matches = {p["prediction_id"]: p for p in result.get("event", {}).get("pairs", [])}
    event_rows = [{"事件ID": e["event_id"], "开始 UTC": e["start_at"], "结束 UTC（半开）": e["end_at"],
        "首次触发 UTC": e["trigger_at"], "持续秒": (datetime.fromisoformat(e["end_at"].replace('Z','+00:00')) - datetime.fromisoformat(e["start_at"].replace('Z','+00:00'))).total_seconds(),
        "候选": data["candidate_id"], "版本": data["version"],
        "匹配": "未评价" if "truth_events" not in result else "匹配" if e["event_id"] in matches else "未匹配预测",
        "延迟秒": matches.get(e["event_id"], {}).get("delay_seconds")} for e in events]
    with event_area:
        selected = st.selectbox("定位预测事件", [None] + list(range(len(events))),
            format_func=lambda i: "全部 / 默认时间窗口" if i is None else f"预测告警 {i+1} · {events[i]['start_at']}",
            label_visibility='collapsed' if compact else 'visible', help='定位预测事件；时间均为 UTC。', **view_binding(key+"-event"))
    if selected is not None:
        event = events[selected]
        start = datetime.fromisoformat(event["start_at"].replace("Z", "+00:00")) - timedelta(seconds=10*data["sampling_seconds"])
        end = datetime.fromisoformat(event["end_at"].replace("Z", "+00:00")) + timedelta(seconds=10*data["sampling_seconds"])
        rows = [r for r in rows if start <= datetime.fromisoformat(r["timestamp"]) <= end]
    if len(rows) > 2000:
        offset = st.number_input("图形窗口起始点（完整结果另行下载）", 0, len(rows)-1, 0 if selected is not None else max(0, len(rows)-2000), **view_binding(key+"-offset"))
        rows = rows[offset:offset+2000]
        st.caption("按连续时间窗口展示最多2000点，未降采样；窗口内保留全部缺失与异常。指标仍基于完整数据，事件表列出全部事件。")
    if not rows:
        st.info("当前窗口无观测。")
        return
    tooltips = [alt.Tooltip("timestamp:N", title="时间 UTC"), "value:Q", "imputation:N", "status:N", "score:Q", "evidence:N"]
    # Explicit segments prevent nulls being bridged by Vega's line aggregation.
    segment = score_segment = 0
    plotted = []
    for row in rows:
        if row["value"] is None:
            segment += 1
        if row["score"] is None:
            score_segment += 1
        plotted.append({**row, "segment": segment, "score_segment": score_segment, "evidence": json.dumps(row["evidence"], ensure_ascii=False)})
    base = alt.Chart(alt.Data(values=plotted)).encode(x=alt.X("timestamp:T", title="时间（UTC）", scale=alt.Scale(type="utc")))
    original = base.mark_line(color="#2563eb").encode(y=alt.Y("value:Q", title=f"监控值 ({data['unit']})"), detail="segment:N", tooltip=tooltips)
    prediction = base.transform_filter("datum.prediction === true").mark_point(color="#dc2626", size=55).encode(y="value:Q", tooltip=tooltips)
    layers = []
    for role, color in (("fit_history", "#dbeafe"), ("calibration_history", "#fef3c7"), ("warmup", "#cbd5e1")):
        region = [r for r in rows if r["role"] == role]
        if region:
            region_end = (datetime.fromisoformat(region[-1]["timestamp"]) + timedelta(seconds=data["sampling_seconds"])).isoformat()
            layers.append(alt.Chart(alt.Data(values=[{"start": region[0]["timestamp"], "end": region_end, "阶段": role}])).mark_rect(color=color, opacity=0.25).encode(x=alt.X("start:T", scale=alt.Scale(type="utc")), x2="end:T", tooltip="阶段:N"))
    intervals = [{**e, "类别": "预测告警（待核查）"} for e in events]
    intervals += [{**e, "类别": "真实标签"} for e in result.get("truth_events", [])]
    left = datetime.fromisoformat(rows[0]["timestamp"])
    right = datetime.fromisoformat(rows[-1]["timestamp"]) + timedelta(seconds=data["sampling_seconds"])
    intervals = [{**e, "start_at": max(left, datetime.fromisoformat(e["start_at"].replace("Z", "+00:00"))).isoformat(),
                  "end_at": min(right, datetime.fromisoformat(e["end_at"].replace("Z", "+00:00"))).isoformat()}
                 for e in intervals if datetime.fromisoformat(e["start_at"].replace("Z", "+00:00")) < right
                 and datetime.fromisoformat(e["end_at"].replace("Z", "+00:00")) > left]
    if intervals:
        categories = ["预测告警（待核查）"] + (["真实标签"] if "truth_events" in result else [])
        layers.append(alt.Chart(alt.Data(values=intervals)).mark_rect(opacity=0.14).encode(x=alt.X("start_at:T", scale=alt.Scale(type="utc")), x2="end_at:T",
            color=alt.Color("类别:N", scale=alt.Scale(domain=categories, range=["#dc2626", "#16a34a"][:len(categories)])), tooltip=["类别:N", "start_at:N", "end_at:N"]))
    layers += [original, prediction]
    if "threshold" in data["config"]:
        layers.append(alt.Chart(alt.Data(values=[{"T": data["config"]["threshold"]}])).mark_rule(color="#a16207", strokeDash=[6,4]).encode(y="T:Q", tooltip="T:Q"))
    st.altair_chart(alt.layer(*layers).properties(height=280 if compact else 320).interactive(bind_y=False)
        .configure_axis(labelFontSize=12, titleFontSize=12, labelColor='#475569', titleColor='#0F172A', gridColor='#E2E8F0')
        .configure_legend(labelFontSize=12, titleFontSize=12, labelColor='#475569', orient='bottom'), width='stretch')
    st.caption('蓝线：监控值 · 红点 / 红区间：预测告警（待核查） · 灰色：暖机 · 缺失处断线'
               + (' · 绿色：真实标签。' if 'truth_events' in result else '。'))
    st.markdown('#### 预测告警事件')
    if event_rows:
        st.dataframe([{k: str(v) if v is not None else '—（未评价 / 未记录）' for k, v in row.items()}
                      for row in event_rows], column_order=['开始 UTC', '结束 UTC（半开）', '首次触发 UTC', '持续秒', '匹配', '延迟秒'],
                     hide_index=True, width='stretch', height=180)
        st.caption('通过表格列菜单可查看事件 ID、候选和版本。')
    else:
        st.info('无预测告警事件。' if 'predicted_events' in result else '预测告警事件未记录。')
    with st.popover('事件与逐点下载'):
        for suffix, title in (("points.csv", "逐点检测 CSV"), ("events.json", "异常事件 JSON")):
            file = Path(directory) / binding["path"].replace("curve.json", suffix)
            if file.is_file():
                raw = file.read_bytes()
                if digest(raw) != binding.get("downloads", {}).get(file.name):
                    st.error("下载产物摘要不匹配：" + file.name)
                    continue
                st.download_button("下载"+title, raw, file_name=file.name, key=key+suffix, on_click="ignore")
    with st.expander("曲线与分数说明", expanded=False) if compact else nullcontext():
        if compact:
            st.caption(f"{source_name} · 任务 {data['task_id']} · 候选 {data['candidate_id']} · {data['version']} · UTC · {data['source'].get('display_name', '')}")
        st.caption("蓝线：原始观测；红点/红区间：预测告警；" + ("绿区间：真实标签；" if "truth_events" in result else "无标签，预测需核查；") +
            "浅蓝/浅黄背景：拟合/校准历史（开启完整历史时）；灰色：历史暖机。缺失保留断点；未告警不等于确认正常。主图默认显示暖机与待检测区间，完整分界见冻结数据划分表。")
        st.caption(f"冻结方法 {data['config']} · 实际分数阈值 {data['threshold']}。业务阈值T为棕色虚线；MAD阈值不画在监控值轴。")
        with st.container():
            st.caption("分数越大越异常，不代表概率。不可判断点无分数；MAD阈值仅用于分数轴。")
            score_line = base.mark_line(color="#7c3aed").encode(y=alt.Y("score:Q", title="异常分数"), detail="score_segment:N", tooltip=tooltips)
            threshold = alt.Chart(alt.Data(values=[{"threshold": data["threshold"]}])).mark_rule(color="#dc2626", strokeDash=[6,4]).encode(y="threshold:Q")
            st.altair_chart((score_line + threshold).properties(height=200).interactive(bind_y=False), width='stretch')
