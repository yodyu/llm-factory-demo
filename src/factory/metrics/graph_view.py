"""Read-only bounded graph UI; never repairs or publishes missing relationships."""
from factory.metrics.capability_registry import methods
import json
from pathlib import Path

from factory.metrics.review import knowledge_usage, read_json


def graph_html(graph, usage=None, report=None):
    data = json.dumps({"graph": graph, "usage": usage or {},
                       "task_id": (report or {}).get("task", {}).get("task_id"),
                       "selected_candidate": (report or {}).get("selection", {}).get("selected")}, ensure_ascii=False)
    data = data.replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    return Path(__file__).with_name('graph_canvas.html').read_text().replace('GRAPH_DATA', data)


def frozen_graph(report):
    snapshot = report.get('knowledge_snapshot') or {}
    usage = knowledge_usage(report)
    ids = set(usage['supplied']) | set(usage['cited'])
    for _ in range(3):
        adjacent = {r['target'] if r['source'] in ids else r['source']
                    for r in snapshot.get('relations', []) if r['source'] in ids or r['target'] in ids}
        ids.update(sorted(adjacent)[:max(0, 100 - len(ids))])
    nodes = [n for n in snapshot.get('nodes', []) if n['id'] in ids][:100]
    ids = {n['id'] for n in nodes}
    return {'nodes': nodes, 'relations': [r for r in snapshot.get('relations', [])
            if r['source'] in ids and r['target'] in ids], 'scope': 'frozen_task_evidence'}


def show_graph(config, state):
    import streamlit as st
    import streamlit.components.v1 as components
    from factory.metrics.app import task_label
    from factory.metrics.knowledge_store import open_knowledge
    st.subheader('知识图谱')
    reports = sorted(Path(state).resolve().glob('runs/*/report.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    options = [''] + [str(p) for p in reports]
    if st.session_state.get('graph_scope'):
        st.session_state['graph_scope'] = str(Path(st.session_state['graph_scope']).resolve())
    if st.session_state.get('graph_scope', '') not in options:
        st.session_state['graph_scope'] = ''
    st.session_state['graph_scope_widget'] = st.session_state.get('graph_scope', '')
    def remember_scope():
        st.session_state['graph_scope'] = st.session_state['graph_scope_widget']
    selected = st.selectbox('查看范围', options, key='graph_scope_widget', on_change=remember_scope, format_func=lambda p: task_label(p) if p else '全部知识')
    st.session_state['graph_scope'] = selected
    report = read_json(Path(selected).parent, 'report.json') if selected else None
    usage = knowledge_usage(report) if report else {}
    if report:
        st.write('当前关联任务：', task_label(selected))
    filters = st.session_state.get('graph_filters', {'method': '', 'status': ''})
    st.session_state['graph_method'] = filters['method']
    st.session_state['graph_status'] = filters['status']
    def remember_filters():
        st.session_state['graph_filters'] = {'method': st.session_state['graph_method'], 'status': st.session_state['graph_status']}
    with st.expander('高级筛选', expanded=False):
        st.caption('实时 Neo4j 的有界3跳局部关系，最多100个实体，默认显示30个。冻结证据独立保存于原任务。')
        if report:
            st.write('任务 ID：', report['task']['task_id'])
            st.write('冻结快照：', report['task']['knowledge_snapshot'])
        method = st.selectbox('算法方法', ['', *methods()], key='graph_method', on_change=remember_filters, format_func=lambda v: v or '全部方法')
        status = st.selectbox('验证状态', ['', 'extracted_unverified', 'UNVERIFIED', 'PASSED', 'FAILED', 'MEASURED', 'NOT_MEASURED'], key='graph_status', on_change=remember_filters, format_func=lambda v: {'':'全部状态', 'extracted_unverified':'抽取未验证', 'UNVERIFIED':'未验证', 'PASSED':'工程检查通过', 'FAILED':'工程检查失败', 'MEASURED':'效果已测量', 'NOT_MEASURED':'效果未测量'}[v])
    graph = None
    try:
        knowledge = open_knowledge(config)
        try:
            graph = knowledge.local_graph(search=report['task']['task_id'] if report else '', method=method, status=status, limit=100)
        finally:
            knowledge.close()
    except (OSError, ValueError, RuntimeError):
        st.error('Neo4j连接或配置不可用，无法读取实时图谱；未以空图替代。已冻结任务可在下方审查冻结证据。')
    if graph is not None:
        if not graph['nodes']:
            st.info('当前条件没有匹配实体。')
            if report:
                st.warning('当前任务的历史关联缺失或不满足筛选条件。未补写关系；请查看下方冻结证据。')
        else:
            st.caption(f"当前局部图：{len(graph['nodes'])} 个实体 · {len(graph['relations'])} 条关系")
            components.html(graph_html(graph, usage, report), height=880, scrolling=True)
            st.download_button('下载局部图 JSON', json.dumps(graph, ensure_ascii=False, indent=2), file_name='local-graph.json', on_click='ignore')
    if report:
        with st.expander('任务冻结证据（独立于当前图谱）', expanded=graph is None or not graph['nodes']):
            st.caption('原任务冻结时的检索证据，不代表当前 Neo4j 已存在任务关联；不会为展示补造实现或验证节点。高级筛选只作用于当前图谱。')
            st.json({'usage': usage, 'retrieval': report.get('retrieval', {})}, expanded=False)
            frozen = frozen_graph(report)
            if frozen['nodes']:
                components.html(graph_html(frozen, usage, report), height=880, scrolling=True)
                st.download_button('下载冻结局部图 JSON', json.dumps(frozen, ensure_ascii=False), file_name='frozen-local-graph.json', on_click='ignore')
            else:
                st.info('该任务没有可显示的冻结知识实体；原始检索记录如上。')
