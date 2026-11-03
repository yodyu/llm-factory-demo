"""Simplified creation inputs retain strict CSV contracts and read-only selection."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from factory.metrics.app import INDICATORS
from factory.metrics.data import encode_csv
from factory.metrics.upload import inspect_upload, simple_upload_options, upload_example
from tests.metrics.test_upload import observations


@pytest.mark.parametrize("scenario", INDICATORS)
def test_complete_example_validates_for_selected_indicator(scenario):
    raw = upload_example(scenario)
    options = simple_upload_options(raw, scenario=scenario, display_name="example.csv")
    points, summary = inspect_upload(raw, **options)
    assert len(points) == 360 and summary['history_points'] == 200
    assert summary['fit_points'] == 60 and summary['method'] == 'fixed_threshold'
    assert summary['metric_kind'] == ('rate' if scenario == 'network_missing' else 'gauge')
    assert summary['splits'][2]['points'] == 160


@pytest.mark.parametrize("mutation", ['header', 'short', 'host', 'irregular', 'columns', 'range', 'encoding'])
def test_simplified_upload_rejects_bad_inputs(mutation):
    lines = encode_csv(observations()).decode().splitlines()
    if mutation == 'header':
        lines[0] = 'time,server,reading'
    if mutation == 'short':
        lines = lines[:201]
    if mutation == 'host':
        lines[3] = lines[3].replace('customer-host-7', 'another-host')
    if mutation == 'irregular':
        lines[3] = lines[3].replace('00:02:00', '00:02:01')
    if mutation == 'columns':
        lines[2] += ',extra'
    if mutation == 'range':
        lines[5] = lines[5].rsplit(',', 1)[0] + ',101'
    raw = b'\xff\xfe' if mutation == 'encoding' else '\n'.join(lines).encode()
    with pytest.raises(ValueError):
        options = simple_upload_options(raw, scenario='cpu_spike', display_name='bad.csv')
        inspect_upload(raw, **options)


def creation_app(tmp_path, monkeypatch, *, allow_parse=False):
    from streamlit.testing.v1 import AppTest
    from factory.metrics.model import ModelGateway
    def forbidden(*a, **kw): raise AssertionError('browsing must not execute')
    monkeypatch.setattr('factory.metrics.background.submit', forbidden)
    if not allow_parse:
        monkeypatch.setattr(ModelGateway, 'ask', forbidden)
    monkeypatch.setenv('FACTORY_METRICS_STATE', str(tmp_path / 'state'))
    monkeypatch.setenv('FACTORY_METRICS_IMAGE', 'sha256:' + 'a'*64)
    config = tmp_path / 'knowledge.json'
    config.write_text('{}')
    monkeypatch.setenv('FACTORY_METRICS_KNOWLEDGE', str(config))
    monkeypatch.delenv('FACTORY_METRICS_MODEL_ENV', raising=False)
    monkeypatch.delenv('FACTORY_METRICS_CAMPAIGN', raising=False)
    if allow_parse:
        from factory.metrics.ui_settings import save_settings
        save_settings(tmp_path / 'state', {'model_mode': 'mock', 'retrieval': 'structured', 'round_limit': 60})
    return AppTest.from_file(Path(__file__).resolve().parents[2] / 'streamlit_app.py').run()


def test_language_page_browsing_is_read_only(tmp_path, monkeypatch):
    from tests.metrics.test_app import nav, submit_button
    app = creation_app(tmp_path, monkeypatch)
    assert not app.exception and submit_button(app).disabled
    assert not app.selectbox and not app.number_input
    assert len(app.get('file_uploader')) == 2
    app.button(key='example-内存缓慢漂移').click().run()
    assert '内存' in app.text_area[0].value
    nav(app, '配置')
    nav(app, '创建任务')
    assert '内存' in app.text_area[0].value
    assert not (tmp_path / 'state').exists()


def test_single_editor_reparse_invalidates_draft_and_has_no_override_controls(tmp_path, monkeypatch):
    from tests.metrics.test_app import submit_button
    app = creation_app(tmp_path, monkeypatch, allow_parse=True)
    app.button(key='understand-requirement').click().run()
    assert not app.exception and not submit_button(app).disabled
    original = app.session_state['requirement_draft']
    assert original['values']['threshold'] == 90
    assert not app.text_input and not app.number_input
    assert not any(b.label in {'更新理解','应用修正'} for b in app.button)
    assert not any('高级设置' in e.label for e in app.expander)
    app.text_area(key='create_requirement').set_value('用模拟数据检测CPU超过95%连续两点报警').run()
    assert submit_button(app).disabled and 'requirement_draft' not in app.session_state
    app.button(key='understand-requirement').click().run()
    assert not app.exception and not submit_button(app).disabled
    assert app.session_state['requirement_draft']['values']['threshold'] == 95
    assert app.session_state['requirement_draft']['values']['persistence_points'] == 2
    assert app.session_state['requirement_draft']['turns'] == ['用模拟数据检测CPU超过95%连续两点报警']
    assert not app.text_input and not app.number_input
    app.text_area(key='create_requirement').set_value('模拟CPU低于20%连续两点报警').run()
    assert not app.exception and submit_button(app).disabled
    assert not (tmp_path / 'state' / 'runs').exists()
    app.button(key='understand-requirement').click().run()
    assert app.session_state['requirement_draft']['values']['direction'] == 'lower'


def test_conflict_requires_editing_the_single_editor(tmp_path, monkeypatch):
    from tests.metrics.test_app import submit_button
    app = creation_app(tmp_path, monkeypatch, allow_parse=True)
    app.text_area(key='create_requirement').set_value('模拟CPU超过90%，高于85%报警').run()
    app.button(key='understand-requirement').click().run()
    assert not app.exception and submit_button(app).disabled
    app.text_area(key='create_requirement').set_value('模拟CPU超过95%报警').run()
    assert submit_button(app).disabled
    app.button(key='understand-requirement').click().run()
    assert not app.exception and not submit_button(app).disabled


def test_bad_upload_then_valid_file_requires_reparse(tmp_path, monkeypatch):
    import streamlit as st
    from tests.metrics.test_app import submit_button
    app = creation_app(tmp_path, monkeypatch, allow_parse=True)
    raw = [b'timestamp,host_id,value\ninvalid,server-a,3\n']
    monkeypatch.setattr(st, 'file_uploader', lambda *a, **kw: None if kw.get('key') == 'create_labels' else SimpleNamespace(name='data.csv', getvalue=lambda: raw[0]))
    app.button(key='example-上传 CSV').click().run()
    app.button(key='understand-requirement').click().run()
    assert not app.exception and submit_button(app).disabled
    raw[0] = upload_example('cpu_spike')
    app.run()
    assert submit_button(app).disabled
    app.button(key='understand-requirement').click().run()
    assert not app.exception and not submit_button(app).disabled
    raw[0] = raw[0].replace(b',35', b',36', 1)
    app.run()
    assert not app.exception and submit_button(app).disabled


def test_labels_default_to_trusted_and_survive_editing_but_still_require_alignment(tmp_path, monkeypatch):
    import csv
    import io
    import streamlit as st
    from tests.metrics.test_app import submit_button
    app = creation_app(tmp_path, monkeypatch, allow_parse=True)
    raw = upload_example('cpu_spike')
    rows = list(csv.DictReader(io.StringIO(raw.decode())))
    labels = [('timestamp,host_id,is_anomaly\n' + ''.join(f"{r['timestamp']},{r['host_id']},0\n" for r in rows[200:])).encode()]
    def uploaded(*a, **kw):
        content = labels[0] if kw.get('key') == 'create_labels' else raw
        return SimpleNamespace(name='example.csv', getvalue=lambda: content)
    monkeypatch.setattr(st, 'file_uploader', uploaded)
    app.button(key='example-上传 CSV').click().run()
    app.button(key='understand-requirement').click().run()
    assert not app.exception and not submit_button(app).disabled
    assert not app.text_input
    from factory.metrics.requirements import DEFAULT_LABEL_SOURCE
    assert app.session_state['requirement_draft']['values']['label_source'] == DEFAULT_LABEL_SOURCE
    app.text_area(key='create_requirement').set_value('上传CPU超过90%连续两点报警').run()
    assert submit_button(app).disabled
    app.button(key='understand-requirement').click().run()
    assert not app.exception and not submit_button(app).disabled
    assert app.session_state['requirement_draft']['values']['threshold'] == 90
    assert app.session_state['requirement_draft']['values']['label_source'] == DEFAULT_LABEL_SOURCE
    labels[0] = labels[0].rsplit(b'\n', 2)[0] + b'\n'
    app.button(key='understand-requirement').click().run()
    assert not app.exception and submit_button(app).disabled


def test_unlabelled_effect_preference_discloses_actual_engineering_selection(tmp_path, monkeypatch):
    import streamlit as st
    from tests.metrics.test_app import submit_button
    app = creation_app(tmp_path, monkeypatch, allow_parse=True)
    raw = upload_example('cpu_spike')
    monkeypatch.setattr(st, 'file_uploader', lambda *a, **kw: None if kw.get('key') == 'create_labels'
        else SimpleNamespace(name='data.csv', getvalue=lambda: raw))
    app.text_area(key='create_requirement').set_value('上传CSV，CPU升高，超过85%，尽量少误报，召回率不低于90%').run()
    app.button(key='understand-requirement').click().run()
    assert not app.exception and not submit_button(app).disabled
    assert any('实际按工程可用性' in c.value for c in app.caption)
    assert not any('使用事件 F0.5' in c.value for c in app.caption)
    assert any('效果及验收目标标记为未评估' in i.value for i in app.info)
    assert app.session_state['requirement_draft']['values']['min_event_recall'] == .9


def test_confirmation_card_preserves_explicit_conditions_and_action_stage(tmp_path, monkeypatch):
    from tests.metrics.test_app import submit_button, visible_text
    app = creation_app(tmp_path, monkeypatch, allow_parse=True)
    assert app.button(key='understand-requirement').proto.type == 'primary'
    assert '理解需求后，在这里核对检测方案。' in visible_text(app)
    app.text_area(key='create_requirement').set_value('模拟CPU超过85%，连续三点报警，窗口30点，召回率不低于90%').run()
    app.button(key='understand-requirement').click().run()
    assert not app.exception and not submit_button(app).disabled
    assert submit_button(app).proto.type == 'primary'
    assert app.button(key='understand-requirement').proto.type == 'secondary'
    table = str(app.table[0].value)
    for value in ('检测对象','数据来源','检测目标','告警条件','候选方法','验收目标','85','连续 3','90%'):
        assert value in table
    assert '历史窗口（点）：30' in visible_text(app)
    app.text_area(key='create_requirement').set_value('模拟CPU超过95%报警').run()
    assert not app.exception and submit_button(app).disabled
    assert '原草稿已过期' in visible_text(app)
    assert app.button(key='understand-requirement').proto.type == 'primary'
    assert app.button(key='understand-requirement').label == '重新理解需求'


def test_example_menu_labels_and_upload_contracts(tmp_path, monkeypatch):
    from factory.metrics.creation import EXAMPLE_LABELS
    app = creation_app(tmp_path, monkeypatch)
    assert not app.exception
    assert list(EXAMPLE_LABELS.values()) == ['CPU 持续高负载','内存利用率逐渐升高','使用已有监控 CSV','磁盘 I/O 延迟异常']
    assert [app.button(key='example-'+key).label for key in EXAMPLE_LABELS] == list(EXAMPLE_LABELS.values())
    assert any(e.proto.popover.label == '填入示例' for e in app.get('popover'))
    assert [e.proto.label for e in app.get('file_uploader')] == ['监控数据 CSV（可选）','异常标签 CSV（可选）']
    assert all(list(e.proto.type) == ['.csv'] and e.proto.max_upload_size_mb == 16 for e in app.get('file_uploader'))
    assert app.get('file_uploader')[1].proto.help == '用于评估检测效果，需与监控数据匹配。'
    assert [e.label for e in app.expander] == ['数据格式说明']
    assert not app.info  # The empty confirmation card has no large blue callout.
    app.button(key='example-上传 CSV').click().run()
    assert not app.exception and len(app.get('file_uploader')) == 2
    assert not (tmp_path / 'state').exists()


def label_bytes(raw):
    import csv
    import io
    rows = list(csv.DictReader(io.StringIO(raw.decode())))
    return ('timestamp,host_id,is_anomaly\n' + ''.join(f"{r['timestamp']},{r['host_id']},0\n" for r in rows[200:])).encode()


def test_example_and_upload_changes_do_not_call_model_or_discard_attachments(tmp_path, monkeypatch):
    import streamlit as st
    from factory.metrics.creation import EXAMPLE_LABELS
    from factory.metrics.model import ModelGateway
    from factory.metrics.requirements import EXAMPLES
    from tests.metrics.test_app import submit_button, visible_text
    app = creation_app(tmp_path, monkeypatch, allow_parse=True)
    attachments = {'create_upload':upload_example('cpu_spike')}
    attachments['create_labels'] = label_bytes(attachments['create_upload'])
    calls = []
    def uploaded(*a, **kw):
        calls.append((kw['key'], attachments[kw['key']]))
        return SimpleNamespace(name=kw['key']+'.csv', getvalue=lambda: attachments[kw['key']])
    monkeypatch.setattr(st, 'file_uploader', uploaded)
    app.button(key='example-上传 CSV').click().run()
    app.button(key='understand-requirement').click().run()
    assert not app.exception and not submit_button(app).disabled
    original = dict(attachments)
    async def forbidden(*a, **kw):
        raise AssertionError('examples, uploads and edits must not call a model')
    with monkeypatch.context() as blocked:
        blocked.setattr(ModelGateway, 'ask', forbidden)
        for key in EXAMPLE_LABELS:
            calls.clear()
            app.button(key='example-'+key).click().run()
            assert not app.exception and app.text_area(key='create_requirement').value == EXAMPLES[key]
            assert 'requirement_draft' not in app.session_state and submit_button(app).disabled
            assert dict(calls) == original
        app.text_area(key='create_requirement').set_value('上传CPU超过95%连续两点告警').run()
        assert not app.exception and submit_button(app).disabled
    app.button(key='understand-requirement').click().run()
    assert not app.exception and not submit_button(app).disabled
    assert app.session_state['requirement_draft']['values']['threshold'] == 95
    with monkeypatch.context() as blocked:
        blocked.setattr(ModelGateway, 'ask', forbidden)
        attachments['create_upload'] = attachments['create_upload'].replace(b',35', b',36', 1)
        app.run()
        assert not app.exception and submit_button(app).disabled
        assert '草稿已过期' in visible_text(app)
        attachments['create_labels'] = attachments['create_labels'].rsplit(b'\n', 2)[0] + b'\n'
        app.run()
        assert not app.exception and submit_button(app).disabled
    app.button(key='understand-requirement').click().run()
    assert not app.exception and submit_button(app).disabled
    assert any('CSV 格式校验失败' in e.value for e in app.error)


def test_labels_without_observations_keep_existing_validation(tmp_path, monkeypatch):
    import streamlit as st
    from tests.metrics.test_app import submit_button, visible_text
    app = creation_app(tmp_path, monkeypatch, allow_parse=True)
    content = label_bytes(upload_example('cpu_spike'))
    monkeypatch.setattr(st, 'file_uploader', lambda *a, **kw: None if kw['key'] == 'create_upload'
        else SimpleNamespace(name='labels.csv', getvalue=lambda: content))
    app.run()
    assert not app.exception and submit_button(app).disabled
    app.button(key='understand-requirement').click().run()
    assert not app.exception and submit_button(app).disabled
    assert '真实标签必须与观测 CSV 一起上传。' in visible_text(app)
    app.button(key='example-上传 CSV').click().run()
    app.button(key='understand-requirement').click().run()
    assert not app.exception and submit_button(app).disabled
    assert '请上传观测 CSV' in visible_text(app)
