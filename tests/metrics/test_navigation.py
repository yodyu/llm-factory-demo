"""Global navigation and lazy task sections preserve durable review state."""
import hashlib
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.metrics import test_app
from tests.metrics.test_app import forbid_execution, nav

archived_page = test_app.archived_page


@pytest.mark.parametrize('route', ('创建任务', '任务结果', '知识图谱', '配置', '查看结果',
                                   '结果概览', '知识与依据', '验证过程', '运行与验证', '知识依据'))
def test_four_global_entries_and_legacy_routes(route):
    app = AppTest.from_string('from factory.metrics.app import navigation\nnavigation()\n'
                             'import streamlit as st\nst.button("正文操作", key="body-action", type="primary")')
    app.session_state['page'] = route
    app.session_state['selected_task'] = 'saved/report.json'
    app.session_state['review_task'] = 'saved/report.json'
    app.session_state['requirement_draft'] = {'binding':'frozen'}
    app.run()
    assert not app.exception
    expected = route if route in {'创建任务','知识图谱','配置'} else '任务结果'
    assert app.session_state['page'] == expected
    assert [b.label for b in app.sidebar.button] == ['创建任务','任务结果','知识图谱','系统配置']
    active = [button.key for button in app.sidebar.button if button.proto.type == 'primary']
    assert active == ['nav-查看结果' if expected == '任务结果' else 'nav-'+expected]
    assert not app.button(key='nav-查看结果').disabled
    assert app.button(key='body-action').proto.type == 'primary'
    assert app.session_state['selected_task'] == app.session_state['review_task'] == 'saved/report.json'
    assert app.session_state['requirement_draft'] == {'binding':'frozen'}
    sections = {'结果概览':'结果概览','知识与依据':'知识与依据','验证过程':'验证过程',
                '运行与验证':'验证过程','知识依据':'知识与依据'}
    if route in sections:
        assert app.session_state['result_section'] == sections[route]
    app.button(key='nav-配置').click().run()
    assert not app.exception and app.session_state['page'] == '配置'


def test_navigation_roundtrip_keeps_task_and_is_readonly(archived_page, tmp_path, monkeypatch):
    directory, _, _ = archived_page
    calls = forbid_execution(monkeypatch)
    def files():
        return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob('*') if p.is_file()}
    before = files()
    app = AppTest.from_file(Path(__file__).resolve().parents[2]/'streamlit_app.py')
    app.session_state['page'] = '知识与依据'
    app.session_state['selected_task'] = str(directory/'report.json')
    app.run()
    chosen = app.session_state['selected_task']
    assert app.radio(key='result-section-widget').value == '知识与依据'
    for route in ('运行与验证','知识依据','创建任务','任务结果','系统配置','任务结果','结果概览'):
        nav(app, route)
        assert not app.exception and app.session_state['selected_task'] == chosen
        assert len([b for b in app.sidebar.button if b.proto.type == 'primary']) == 1
        if app.session_state['page'] == '任务结果':
            assert app.selectbox(key='review_task').value == chosen
            assert len([e for e in app.get('download_button') if '交付包' in e.proto.label]) == int((directory/'delivery.zip').is_file())
            if not (directory/'delivery.zip').is_file():
                assert any('交付包未记录' in e.value for e in app.caption)
    assert files() == before and calls == []


@pytest.mark.parametrize('relative_state', [False, True])
def test_sections_render_only_selected_body_and_graph_keeps_scope(archived_page, monkeypatch, relative_state):
    directory, _, _ = archived_page
    if relative_state:
        state = directory.parents[1]
        monkeypatch.chdir(state.parent)
        monkeypatch.setenv('FACTORY_METRICS_STATE', state.name)
    calls = forbid_execution(monkeypatch)
    from factory.metrics import app as module
    seen = []
    for name in ('show_knowledge','show_repairs','show_summary','show_publication','show_model_usage'):
        original = getattr(module, name)
        def record(*args, _name=name, _original=original, **kwargs):
            seen.append(_name)
            return _original(*args, **kwargs)
        monkeypatch.setattr(module, name, record)
    app = AppTest.from_file(Path(__file__).resolve().parents[2]/'streamlit_app.py')
    app.session_state['page'] = '结果概览'
    app.run()
    assert seen == ['show_summary']
    seen.clear()
    nav(app, '运行与验证')
    assert seen == ['show_repairs']
    seen.clear()
    nav(app, '知识依据')
    assert seen == ['show_knowledge','show_publication']
    seen.clear()
    nav(app, '模型用量')
    assert seen == ['show_model_usage']
    assert list(app.radio(key='result-section-widget').options) == ['结果概览','运行与验证','知识依据','模型用量']
    nav(app, '知识依据')
    selected = app.session_state['selected_task']
    app.button(key='open-task-graph').click().run()
    assert not app.exception
    assert app.session_state['page'] == '知识图谱'
    assert app.session_state['graph_scope'] == selected
    assert app.session_state['selected_task'] == selected and not calls


def test_same_name_tasks_survive_browser_serialization_refresh_and_completion(archived_page, monkeypatch):
    import copy
    import json
    import shutil
    from factory.metrics import app as module
    from factory.metrics import background
    directory, report, _ = archived_page
    second = directory.parent / 'second-identical-title'
    shutil.copytree(directory, second)
    other = copy.deepcopy(report)
    other['task']['task_id'] = 'same-title-second-task'
    other['selection']['selected'] = 'identifiable-second-candidate'
    (second/'report.json').write_text(json.dumps(other))
    paths = [str(directory/'report.json'), str(second/'report.json')]
    labels = [module.task_label(p) for p in paths]
    assert labels[0] != labels[1]
    # Streamlit 1.66 sends formatted strings over the wire, not Python paths.
    from streamlit.elements.widgets.selectbox import SelectboxSerde
    serde = SelectboxSerde(paths, formatted_options=labels,
        formatted_option_to_option_index={label:i for i,label in enumerate(labels)}, format_func=module.task_label)
    assert all(serde.deserialize(serde.serialize(path)) == path for path in paths)
    calls = forbid_execution(monkeypatch)
    seen = []
    expected = [None]
    for name in ('show_summary','show_repairs','show_knowledge','show_model_usage'):
        original = getattr(module, name)
        def record(*args, _original=original, **kwargs):
            # Each renderer receives the same selected report through render_report.
            rendered = next(arg for arg in args if isinstance(arg, dict) and 'task' in arg)
            if expected[0] is not None:
                assert rendered['task']['task_id'] == expected[0]['task']['task_id']
                assert rendered['selection'] == expected[0]['selection']
                assert rendered['candidates'] == expected[0]['candidates']
                assert rendered.get('model_operations') == expected[0].get('model_operations')
                assert rendered.get('retrieval') == expected[0].get('retrieval')
            seen.append(rendered['task']['task_id'])
            return _original(*args, **kwargs)
        monkeypatch.setattr(module, name, record)
    app = AppTest.from_file(Path(__file__).resolve().parents[2]/'streamlit_app.py')
    app.session_state['page'] = '任务结果'
    app.run()
    for path in paths:
        expected[0] = report if path == paths[0] else other
        app.selectbox(key='review_task').set_value(path).run()
        for section in ('结果概览','运行与验证','知识依据','模型用量') * 2:
            nav(app, section)
            assert not app.exception
            assert app.session_state['selected_task'] == app.selectbox(key='review_task').value == path
        # Reverse sort order by changing mtime, without modifying report bytes.
        import os
        import time
        os.utime(directory/'report.json', (time.time()+60, time.time()+60))
        app.run()
        assert app.session_state['selected_task'] == path
    # A job already selected while active keeps its path as it becomes completed.
    original_records = background.task_records
    active = [True]
    def records(state):
        rows = original_records(state)
        for row in rows:
            if row['path'] == paths[1]:
                row.update(active=active[0], status='RUNNING' if active[0] else 'COMPLETED')
        return rows
    monkeypatch.setattr(background, 'task_records', records)
    app.run()
    assert app.session_state['selected_task'] == paths[1]
    active[0] = False
    app.run()
    assert not app.exception and app.session_state['selected_task'] == paths[1]
    assert seen and not calls
