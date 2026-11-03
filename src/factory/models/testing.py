"""Explicit, deterministic model transport for tests and offline examples.

Scripted payloads and exception objects remain in process memory only. Call
summaries contain no prompts, input texts, authorization headers or provider
responses. This transport never falls through to a real network request.
"""

from collections import deque
from collections.abc import Iterable
from copy import deepcopy

from contracts import ErrorCode

from .transport import ModelCallError


class ScriptedTransport:
    mode = "mock"

    def __init__(self, script: Iterable[dict | Exception]):
        self._script = deque(script)
        self.calls: list[dict] = []

    def __repr__(self) -> str:
        return f"ScriptedTransport(remaining={len(self._script)}, calls={len(self.calls)})"

    def _next(self, operation: str, model: str, input_count: int, timeout: float) -> dict:
        self.calls.append(
            {"operation": operation, "model": model, "input_count": input_count, "timeout": timeout}
        )
        if not self._script:
            raise ModelCallError(ErrorCode.MODEL_ERROR, "mock_script_exhausted")
        item = self._script.popleft()
        if isinstance(item, Exception):
            raise item
        return deepcopy(item)

    async def chat(self, *, messages: list[dict[str, str]], model: str, timeout: float) -> dict:
        return self._next("chat", model, len(messages), timeout)

    async def embed(self, *, texts: list[str], model: str, timeout: float) -> dict:
        return self._next("embed", model, len(texts), timeout)
