"""Bounded pipe regressions; only trusted test programs execute on host."""
import subprocess
import sys
import time
import pytest
from contracts import ErrorCode
from execution.runner import _Pipe, _TransportError, _stop


def child(source):
    return subprocess.Popen([sys.executable, '-u', '-c', source], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)

@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
def test_pipe_flood_rejected_at_hard_limit(stream):
    process = child(f"import sys; sys.{stream}.write('x' * 100000); sys.{stream}.flush()")
    pipe = _Pipe(process, 65536, 65536)
    try:
        with pytest.raises(_TransportError) as error:
            pipe.exchange(time.monotonic() + 3)
        assert error.value.code == ErrorCode.RESOURCE_LIMIT
        assert len(pipe.stdout) <= 65536 and len(pipe.stderr) <= 65536
    finally:
        pipe.close()
        _stop(process)

def test_pipe_closed_streams_do_not_hide_a_running_process():
    process = subprocess.Popen([sys.executable, '-u', '-c',
        'import os; os.close(1); os.close(2)\nwhile True: pass'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    pipe = _Pipe(process, 65536, 65536)
    try:
        with pytest.raises(_TransportError) as error:
            pipe.exchange(time.monotonic() + .1)
        assert error.value.code == ErrorCode.CODE_TIMEOUT
    finally:
        pipe.close()
        _stop(process)


def test_stream_retains_cumulative_quota_and_task_deadline():
    from execution.runner import JsonStream, StreamBudget
    from contracts import FactoryError
    class Wire:
        def exchange(self, deadline, raw, **kwargs):
            self.deadline = deadline
            return b'{"ok":true}'
    wire = Wire()
    end = time.monotonic() + .2
    stream = JsonStream(wire, end, budget=StreamBudget(output_bytes=15))
    assert stream.request({}) == {'ok':True}
    assert wire.deadline <= end
    with pytest.raises(FactoryError, match='total output'):
        stream.request({})
