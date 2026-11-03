import hashlib
import json
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from contracts import FactoryError
from factory.metrics.budget import CallBudget, read_campaign
from factory.metrics.ui_settings import load_settings, save_settings, configured_model_id, initialize_campaign
from factory.metrics.usage import model_usage
from tests.metrics import test_app

archived_page = test_app.archived_page


def test_round_reauthorization_preserves_all_legacy_calls_and_is_idempotent(tmp_path):
    path = tmp_path / 'campaign.sqlite'
    budget = CallBudget(path)
    for i in range(60):
        budget.reserve(str(i), 'hash')
        budget.mark(str(i), 'SENT')
        budget.mark(str(i), 'UNKNOWN' if i == 59 else 'SUCCEEDED')
    with pytest.raises(FactoryError):
        budget.reserve('exhausted', 'hash')
    with sqlite3.connect(path) as db:
        original = db.execute('SELECT call_key,input_hash,status,sent FROM calls ORDER BY call_key').fetchall()
    assert budget.authorize_round(150, 'ui-action-one') == 2
    assert budget.authorize_round(150, 'ui-action-one') == 2
    assert CallBudget(path).summary()['remaining'] == 150
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT call_key,input_hash,status,sent FROM calls ORDER BY call_key').fetchall() == original
    assert budget.reserve('59', 'hash') == 1
    assert budget.reserve('new', 'new-hash') == 2
    budget.mark('59', 'SUCCEEDED')  # Late completion stays in its original round.
    with sqlite3.connect(path) as db:
        now = db.execute("SELECT call_key,input_hash,status,sent FROM calls WHERE round_id=1 ORDER BY call_key").fetchall()
    assert [r[:2] + r[3:] for r in now] == [r[:2] + r[3:] for r in original]
    assert read_campaign(path)['used'] == 1 and read_campaign(path)['lifetime_reserved'] == 61
    assert read_campaign(path)['rounds'][1]['已预约'] == 60
    with pytest.raises(ValueError):
        budget.authorize_round(300, 'ui-action-one')
    with pytest.raises(ValueError):
        budget.authorize_round(1000, 'bad')


@pytest.mark.parametrize('cap', [60, 150, 300, 600])
def test_round_cap_and_concurrent_reservations_are_enforced(tmp_path, cap):
    budget = CallBudget(tmp_path / 'campaign.sqlite', limit=1)
    budget.authorize_round(cap, 'authorized')
    def reserve(i):
        try:
            budget.reserve('new-'+str(i), 'hash')
            return True
        except FactoryError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(cap + 5))) == cap
    assert budget.summary()['remaining'] == 0


def test_read_campaign_never_creates_or_migrates_ledger(tmp_path):
    path = tmp_path / 'campaign.sqlite'
    assert read_campaign(path) is None and not path.exists()
    CallBudget(path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    assert read_campaign(path)['round'] == 1
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    with sqlite3.connect(path) as db:
        assert [r[1] for r in db.execute('PRAGMA table_info(calls)')] == ['call_key', 'input_hash', 'status', 'sent']


def test_budget_writer_uses_wal_and_configurable_lock_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv('FACTORY_BUDGET_LOCK_TIMEOUT', '0.25')
    budget = CallBudget(tmp_path / 'campaign.sqlite')
    with budget.transaction() as db:
        assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        assert db.execute('PRAGMA busy_timeout').fetchone()[0] == 250
    assert CallBudget(budget.path, lock_timeout=2).lock_timeout == 2
    for value in ('0', '-1', 'nan', 'inf', 'invalid'):
        monkeypatch.setenv('FACTORY_BUDGET_LOCK_TIMEOUT', value)
        with pytest.raises(ValueError):
            CallBudget(tmp_path / 'invalid.sqlite')
    assert not (tmp_path / 'invalid.sqlite').exists()


def test_settings_persist_and_only_allowlisted_model_id_is_exposed(tmp_path):
    state = tmp_path / 'state'
    assert load_settings(state) == {'model_mode': 'api', 'round_limit': 60}
    assert not state.exists()
    save_settings(state, {'model_mode': 'api', 'retrieval': 'none', 'round_limit': 600})
    assert load_settings(state) == {'model_mode': 'api', 'round_limit': 600}
    assert 'retrieval' not in json.loads((state / 'ui-settings.json').read_text())
    env = tmp_path / 'runtime.env'
    env.write_text('LLM_API_KEY=not-displayed\nLLM_BASE_URL=not-displayed\nLLM_MODEL="review-model-id"\n')
    assert configured_model_id(env) == 'review-model-id'
    assert configured_model_id(tmp_path / 'missing') is None
    with pytest.raises(ValueError):
        save_settings(state, {'model_mode': 'api', 'retrieval': 'none', 'round_limit': 1000})


def test_legacy_retrieval_preference_is_ignored_without_rewriting_file(tmp_path):
    state = tmp_path / 'state'
    state.mkdir()
    path = state / 'ui-settings.json'
    path.write_text(json.dumps({'retrieval': 'none', 'model_mode': 'mock', 'round_limit': 150}))
    before = path.read_bytes()
    assert load_settings(state) == {'model_mode': 'mock', 'round_limit': 150}
    assert path.read_bytes() == before


def test_campaign_initialization_preserves_existing_ledger(tmp_path):
    initialize_campaign(None)
    path = tmp_path / 'private' / 'campaign.sqlite'
    initialize_campaign(path)
    assert read_campaign(path)['remaining'] == 60
    budget = CallBudget(path)
    budget.reserve('existing-call', 'hash')
    budget.authorize_round(150, 'existing-round')
    before = path.read_bytes()
    initialize_campaign(path)
    assert path.read_bytes() == before
    assert read_campaign(path)['limit'] == 150
    assert read_campaign(path)['lifetime_reserved'] == 1
    path.write_bytes(b'invalid ledger')
    initialize_campaign(path)
    assert path.read_bytes() == b'invalid ledger'
    link = tmp_path / 'link.sqlite'
    link.symlink_to(path)
    with pytest.raises(ValueError):
        initialize_campaign(link)


def test_first_page_initializes_campaign_without_model_calls(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from tests.metrics.test_app import forbid_execution
    campaign = tmp_path / 'campaign.sqlite'
    monkeypatch.setenv('FACTORY_METRICS_STATE', str(tmp_path / 'state'))
    monkeypatch.setenv('FACTORY_METRICS_CAMPAIGN', str(campaign))
    monkeypatch.setenv('FACTORY_METRICS_KNOWLEDGE', str(tmp_path / 'missing.json'))
    calls = forbid_execution(monkeypatch)
    app = AppTest.from_file(Path(__file__).resolve().parents[2] / 'streamlit_app.py').run()
    assert not app.exception
    assert read_campaign(campaign)['remaining'] == 60
    assert calls == []


def test_task_usage_includes_retries_and_unknown_tokens_without_inventing_zero():
    report = {'origin': 'llm_api', 'model_operations': [
        {'status': 'SUCCEEDED', 'result_ref': 'one', 'metadata': json.dumps({'input_tokens': 100, 'output_tokens': 30})},
        {'status': 'FAILED', 'result_ref': 'failure', 'metadata': json.dumps({'input_tokens': None, 'output_tokens': None})},
        {'status': 'UNKNOWN', 'metadata': '{}'},
        {'status': 'FAILED', 'metadata': '{}'},  # Budget rejected before send.
    ]}
    usage = model_usage(report)
    assert usage['requests'] == 3 and usage['reservations'] == 4
    assert usage['input_tokens'] == 100 and usage['output_tokens'] == 30
    assert usage['total_tokens'] is None and usage['missing_usage_requests'] == 2
    unknown = model_usage({'origin': 'llm_api', 'model_operations': [{'status': 'UNKNOWN', 'metadata': '[]'}]})
    assert unknown['input_tokens'] is None and unknown['output_tokens'] is None and unknown['total_tokens'] is None
    report['model_operations'] = report['model_operations'][:1]
    assert model_usage(report)['total_tokens'] == 130
    report['task'] = {'model_mode': 'mock'}
    assert model_usage(report)['requests'] == model_usage(report)['total_tokens'] == 0
    assert model_usage({'origin': 'historical', 'model_calls': 0})['kind'] == 'replay'
    assert model_usage({'origin': 'llm_api'})['kind'] == 'not_recorded'


def test_configuration_page_controls_and_reauthorization_do_not_call_models(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from tests.metrics.test_app import nav, forbid_execution, submit_button, visible_text
    state = tmp_path / 'ui'
    campaign = tmp_path / 'campaign.sqlite'
    CallBudget(campaign)
    with sqlite3.connect(campaign) as db:
        db.executemany("INSERT INTO calls VALUES (?,?,'SUCCEEDED',1)", [(str(i), 'hash') for i in range(60)])
    env = tmp_path / 'runtime.env'
    env.write_text('LLM_MODEL=review-model\nLLM_API_KEY=not-displayed\n')
    monkeypatch.setenv('FACTORY_METRICS_STATE', str(state))
    monkeypatch.setenv('FACTORY_METRICS_CAMPAIGN', str(campaign))
    monkeypatch.setenv('FACTORY_METRICS_MODEL_ENV', str(env))
    monkeypatch.setenv('FACTORY_METRICS_KNOWLEDGE', str(tmp_path / 'missing-knowledge.json'))
    calls = forbid_execution(monkeypatch)
    app = AppTest.from_file(Path(__file__).resolve().parents[2] / 'streamlit_app.py').run()
    assert not app.radio
    nav(app, '配置')
    assert [radio.key for radio in app.radio] == ['settings_model_mode']
    assert '检索' not in visible_text(app)
    app.radio(key='settings_model_mode').set_value('api').run()
    assert app.text_input(key='configured_model_id').disabled
    assert app.text_input(key='configured_model_id').value == 'review-model'
    app.selectbox(key='settings_round_limit').set_value(150).run()
    assert read_campaign(campaign)['remaining'] == 0
    app.button(key='authorize-model-round').click().run()
    assert not app.exception and read_campaign(campaign)['remaining'] == 150
    nav(app, '创建任务')
    assert not app.radio and '检索增强' not in visible_text(app)
    assert submit_button(app).disabled  # Knowledge unavailable; no request attempted.
    assert calls == [] and read_campaign(campaign)['lifetime_reserved'] == 60
    restarted = AppTest.from_file(Path(__file__).resolve().parents[2] / 'streamlit_app.py').run()
    assert '真实模型：review-model' in visible_text(restarted)


def test_saved_configuration_drives_submission_and_report_usage(archived_page, tmp_path, monkeypatch):
    import shutil
    from streamlit.testing.v1 import AppTest
    from tests.metrics.test_app import submit_button, visible_text, nav
    directory, archived, _ = archived_page
    state = directory.parents[1]
    campaign = tmp_path / 'existing-campaign.sqlite'
    CallBudget(campaign)
    env = tmp_path / 'model.env'
    env.write_text('LLM_MODEL=controlled-ui-api-fixture\n')
    monkeypatch.setenv('FACTORY_METRICS_MODEL_ENV', str(env))
    monkeypatch.setenv('FACTORY_METRICS_CAMPAIGN', str(campaign))
    monkeypatch.setenv('FACTORY_METRICS_IMAGE', 'sha256:' + 'a' * 64)
    # A real legacy preferences file must not disable retrieval for new Web jobs.
    (state / 'ui-settings.json').write_text(json.dumps({'retrieval': 'none', 'model_mode': 'api', 'round_limit': 300}))
    captured = []
    def controlled_result(args):
        captured.append(args)
        target = state / 'runs' / 'controlled-result'
        shutil.copytree(directory, target)
        report = dict(archived)
        report['task'] = {**archived['task'], 'task_id': args.task_id, 'model_mode': 'api'}
        report['origin'] = 'llm_api'
        report['model_operations'] = [{'status': 'SUCCEEDED', 'result_ref': 'controlled-fixture', 'metadata': json.dumps({'input_tokens': 10, 'output_tokens': 5})}]
        (target / 'report.json').write_text(json.dumps(report))
        return {'task_id': args.task_id, 'directory': str(target), 'status': 'COMPLETED'}
    # The page now submits detached jobs; control the submission boundary, not
    # the former synchronous workflow alias. Background execution is tested separately.
    monkeypatch.setattr('factory.metrics.background.submit', controlled_result)
    async def controlled_interpret(**kwargs):
        from factory.metrics.requirements import build_draft, controlled_extract
        extractions = [controlled_extract(t) for t in kwargs['turns']]
        draft = build_draft(kwargs['turns'], extractions, binding=kwargs['binding'], mode=kwargs['mode'])
        return draft, extractions
    monkeypatch.setattr('factory.metrics.creation.interpret_command', controlled_interpret)
    app = AppTest.from_file(Path(__file__).resolve().parents[2] / 'streamlit_app.py').run()
    assert not app.radio and submit_button(app).disabled
    app.button(key='understand-requirement').click().run()
    assert not app.exception and not submit_button(app).disabled
    submit_button(app).click().run()
    assert not app.exception and len(captured) == 1
    assert captured[0].mode == 'api' and captured[0].retrieval == 'structured' and captured[0].campaign == campaign
    nav(app, '模型用量')
    assert any(m.label == '总 token' and m.value == '15' for m in app.metric)
    nav(app, '创建任务')
    assert '最近任务与模型用量' in visible_text(app) and any(m.value == '15' for m in app.metric)
    assert read_campaign(campaign)['used'] == 0  # UI fixture never invokes a provider.


def test_invalid_persisted_cap_is_rejected_without_reset(tmp_path):
    path = tmp_path / 'campaign.sqlite'
    CallBudget(path)
    with sqlite3.connect(path) as db:
        db.execute('UPDATE budget SET limit_calls=1000')
    before = path.read_bytes()
    with pytest.raises(ValueError):
        CallBudget(path)
    with pytest.raises(ValueError):
        read_campaign(path)
    assert path.read_bytes() == before
