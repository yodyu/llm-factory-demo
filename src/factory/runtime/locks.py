"""Per-task process ownership shared by text CLI and UI."""
from contextlib import contextmanager
import fcntl
import os
from contracts import ErrorCode, FactoryError, content_hash

@contextmanager
def _task_lock(directory, task_id):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / (content_hash({"task_id": task_id})[7:] + ".lock")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise FactoryError(
                ErrorCode.INPUT_CONFLICT, "another owner is already running this task"
            ) from None
        yield
    finally:
        os.close(descriptor)
