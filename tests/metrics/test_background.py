"""Background execution and read-only visibility, with no automatic retry."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from factory.metrics.background import execute, submit, task_records, _write


def arguments(tmp_path):
    request = tmp_path / 'request.json'
    request.write_text(json.dumps({'requirement':'CPU检测'}))
    return SimpleNamespace(task_id='ui-background-test', state=tmp_path/'state', task=request,
        dataset=tmp_path/'data', knowledge=tmp_path/'knowledge.json', campaign=None, env_file=None,
        snapshot=None, image='approved-image', mode='mock', retrieval='none', fault_injection=False)


def launch(tmp_path, monkeypatch):
    calls = []
    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(pid=999999999)
    monkeypatch.setattr('factory.metrics.background.subprocess.Popen', popen)
    args = arguments(tmp_path)
    result = submit(args)
    return args, result, calls


def test_submit_persists_before_worker_and_detaches_from_page(tmp_path, monkeypatch):
    args, result, calls = launch(tmp_path, monkeypatch)
    job = args.state/'jobs'/args.task_id/'job.json'
    assert job.exists() and calls[0][0][-1] == str(job.resolve())
    assert calls[0][1]['start_new_session'] is True
    assert calls[0][1]['stdin'] is not None
    assert result['status'] == 'QUEUED' and result['task_id'] == args.task_id
    assert not Path(result['directory']).exists()
    with pytest.raises(FileExistsError):
        submit(args)
    assert len(calls) == 1


def test_worker_calls_existing_pipeline_once_and_survives_a_new_viewer(tmp_path, monkeypatch):
    args, result, calls = launch(tmp_path, monkeypatch)
    count = []
    async def run(actual):
        count.append(actual)
        assert actual.task_id == args.task_id and isinstance(actual.state, Path)
        return {**result, 'status':'COMPLETED'}
    monkeypatch.setattr('factory.metrics.service.run_command', run)
    job = args.state/'jobs'/args.task_id/'job.json'
    assert execute(job) == 0
    assert execute(job) == 0
    assert len(count) == 1
    record = task_records(args.state)[0]
    assert record['status'] == 'COMPLETED' and not record['active']


def test_failed_worker_keeps_visible_record_and_never_retries(tmp_path, monkeypatch):
    args, _, _ = launch(tmp_path, monkeypatch)
    calls = []
    async def fail(actual):
        calls.append(actual.task_id)
        raise ValueError('controlled failure')
    monkeypatch.setattr('factory.metrics.service.run_command', fail)
    job = args.state/'jobs'/args.task_id/'job.json'
    assert execute(job) == 1
    assert task_records(args.state)[0]['status'] == 'FAILED'
    assert execute(job) == 0 and len(calls) == 1


def test_running_task_without_report_renders_and_reading_never_launches(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    args, result, calls = launch(tmp_path, monkeypatch)
    folder = args.state/'jobs'/args.task_id
    (folder/'process.json').unlink()  # queued before process assignment
    before = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in args.state.rglob('*') if p.is_file()}
    monkeypatch.setenv('FACTORY_METRICS_STATE', str(args.state))
    app = AppTest.from_file(Path(__file__).resolve().parents[2]/'streamlit_app.py')
    app.session_state['page'] = '结果概览'
    app.run(timeout=10)
    assert not app.exception
    assert args.task_id in '\n'.join(str(e.value) for e in app.markdown)
    assert any('任务仍在后台运行' in e.value for e in app.info)
    assert str(Path(result['directory'])/'report.json') in app.selectbox(key='review_task').options or app.session_state['selected_task'] == str(Path(result['directory'])/'report.json')
    assert len(calls) == 1
    assert not app.metric and any('等待启动' in c.value for c in app.caption)
    app.run()
    assert not app.exception and len(calls) == 1
    app.radio(key='result-section-widget').set_value('模型用量').run()
    assert not app.exception and not app.metric and len(calls) == 1
    assert any('尚无最终报告' in e.value for e in app.info)
    assert {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in args.state.rglob('*') if p.is_file()} == before


def test_dead_worker_is_visible_as_interrupted_without_touching_status(tmp_path, monkeypatch):
    args, _, _ = launch(tmp_path, monkeypatch)
    status = args.state/'jobs'/args.task_id/'status.json'
    _write(status, {'status':'RUNNING'})
    before = status.read_bytes()
    record = task_records(args.state)[0]
    assert record['status'] == 'INTERRUPTED' and not record['active']
    assert status.read_bytes() == before


def test_phase_display_uses_known_boundaries_without_estimated_progress():
    from factory.metrics.app import running_steps
    steps = running_steps('VALIDATING')
    assert [s['状态'] for s in steps] == ['✓ 已完成']*3 + ['● 进行中'] + ['○ 待执行']*2
    assert [s['阶段'] for s in steps] == ['准备数据','检索知识','规划方案','生成与验证','最终评价','保存结果']
    assert running_steps('unknown') == []
    assert '%' not in str(steps) and '剩余' not in str(steps)
