"""Detached UI jobs; state reads never start, resume or retry model operations."""
import asyncio
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

from factory.metrics.knowledge import identity

ACTIVE = {'QUEUED', 'RUNNING', 'PENDING'}
PATHS = {'state', 'task', 'dataset', 'knowledge', 'campaign', 'env_file', 'snapshot'}


def _write(path, value):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        json.dump(value, stream, ensure_ascii=False)
        temporary = Path(stream.name)
    os.replace(temporary, path)


def submit(args):
    """Persist visibility before spawning; page lifetime does not own the child."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', args.task_id):
        raise ValueError('invalid background task ID')
    state = Path(args.state).resolve()
    folder = state / 'jobs' / args.task_id
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    values = {key: str(Path(value).resolve()) if key in PATHS and value is not None else value for key, value in vars(args).items()}
    request = json.loads(Path(args.task).read_text())
    record = {'task_id': args.task_id, 'requirement': request['requirement'], 'submitted_at': time.time(),
              'directory': str(state / 'runs' / identity('task', args.task_id)), 'args': values}
    _write(folder / 'job.json', record)
    _write(folder / 'status.json', {'status': 'QUEUED', 'updated_at': time.time()})
    root = Path(__file__).resolve().parents[3]
    env = {**os.environ, 'PYTHONPATH': str(root / 'src') + ':' + str(root)}
    try:
        with (folder / 'worker.log').open('ab') as log:
            process = subprocess.Popen([sys.executable, '-m', 'factory.metrics.background', str(folder / 'job.json')],
                cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True)
        # Separate file: the launcher must never overwrite a fast child's status.
        _write(folder / 'process.json', {'pid': process.pid})
    except Exception:
        _write(folder / 'status.json', {'status': 'FAILED', 'message': '后台进程启动失败。', 'updated_at': time.time()})
        raise
    return {'task_id': args.task_id, 'status': 'QUEUED', 'directory': record['directory']}


def execute(job_path):
    folder = Path(job_path).parent
    with (folder / 'worker.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        if json.loads((folder / 'status.json').read_text())['status'] != 'QUEUED':
            return 0  # Never automatically resend uncertain or completed requests.
        _write(folder / 'status.json', {'status': 'RUNNING', 'pid': os.getpid(), 'updated_at': time.time()})
        try:
            job = json.loads(Path(job_path).read_text())
            values = {key: Path(value) if key in PATHS and value is not None else value for key, value in job['args'].items()}
            from factory.metrics.service import run_command
            result = asyncio.run(run_command(SimpleNamespace(**values)))
            _write(folder / 'status.json', {'status': result['status'], 'result': result, 'updated_at': time.time()})
            return 0 if result['status'] in {'COMPLETED', 'PARTIAL_SUCCESS'} else 1
        except BaseException as error:
            _write(folder / 'status.json', {'status': 'FAILED', 'code': type(error).__name__,
                'message': '后台执行未完成，请查看已保存的任务报告或服务器记录。', 'updated_at': time.time()})
            return 1


def task_records(state):
    """Read reports, pending jobs and existing workflow phases without opening a writer."""
    state = Path(state).resolve()
    records = {}
    for path in state.glob('runs/*/report.json'):
        try:
            report = json.loads(path.read_text())
            task = report['task']
            records[task['task_id']] = {'path': str(path), 'task_id': task['task_id'], 'status': report['status'],
                'requirement': task.get('requirement', ''), 'title': (report.get('data_source') or {}).get('display_name') or task.get('dataset_id'),
                'started_at': path.stat().st_mtime, 'phase': 'COMPLETED', 'active': False}
        except (OSError, ValueError, KeyError):
            continue
    database = state / 'runtime.sqlite'
    if database.is_file():
        try:
            with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True, timeout=2) as db:
                for task_id, status, phase, spec, started in db.execute('SELECT task_id,status,phase,spec,started_at FROM tasks'):
                    task = json.loads(spec)
                    if task.get('anomaly_target') not in {'upper', 'lower', 'two_sided'}:
                        continue
                    if task_id not in records:
                        records[task_id] = {'path': str(state / 'runs' / identity('task', task_id) / 'report.json'),
                            'task_id': task_id, 'status': status, 'phase': phase, 'requirement': task.get('requirement', ''),
                            'title': task.get('metric', ''), 'started_at': started, 'active': status in ACTIVE}
                    elif status in ACTIVE and phase != 'COMPLETED':
                        records[task_id].update(phase=phase, active=True)
        except (sqlite3.Error, ValueError, KeyError):
            pass
    for path in state.glob('jobs/*/job.json'):
        try:
            job = json.loads(path.read_text())
            status = json.loads(path.with_name('status.json').read_text())
            active = status['status'] in ACTIVE
            if active and path.with_name('process.json').is_file():
                pid = json.loads(path.with_name('process.json').read_text())['pid']
                try:
                    os.kill(pid, 0)
                    proc = Path(f'/proc/{pid}')
                    if proc.exists() and ((proc / 'stat').read_text().split()[2] == 'Z'
                                          or str(path).encode() not in (proc / 'cmdline').read_bytes()):
                        raise ProcessLookupError()
                except ProcessLookupError:
                    active = False
                    status = {'status': 'INTERRUPTED', 'message': '后台进程已退出；保留已有记录，不自动重新调用模型。'}
            current = records.get(job['task_id'], {})
            records[job['task_id']] = {**current, 'task_id': job['task_id'],
                'path': str(Path(job['directory']) / 'report.json'), 'requirement': job['requirement'],
                'title': current.get('title') or job['requirement'][:40], 'phase': current.get('phase', 'QUEUED'),
                'started_at': current.get('started_at', job['submitted_at']), 'status': status['status'],
                'active': active, 'message': status.get('message')}
        except (OSError, ValueError, KeyError):
            continue
    return sorted(records.values(), key=lambda item: item['started_at'], reverse=True)


if __name__ == '__main__':
    raise SystemExit(execute(Path(sys.argv[1])))
