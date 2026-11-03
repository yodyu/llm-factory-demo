"""Whitelist-only graph events; model prompts and private graph state are never streamed."""

from functools import wraps
import asyncio
import inspect
import time

from contracts import ErrorCode, FactoryError
from factory.metrics.execution_ops import failure


FATAL_CODES = {ErrorCode.BUDGET_EXHAUSTED, ErrorCode.DEADLINE_EXCEEDED, ErrorCode.SANDBOX_UNAVAILABLE}


def error_status(error):
    if isinstance(error, FactoryError) and error.code == ErrorCode.BUDGET_EXHAUSTED:
        return "BUDGET_EXHAUSTED"
    if isinstance(error, ValueError) and str(error).startswith("NEEDS_INPUT:"):
        return "NEEDS_INPUT"
    return "FAILED"


def emit(ctx, node, event, state, *, candidate=False, error=None):
    value = {"node": node, "event": event, "at_seconds": time.monotonic() - ctx.started}
    if candidate:
        value.update(candidate_id=state["candidate_id"], version=state.get("version", 0))
    if error:
        value["code"] = error["code"]
    ctx.store.guard.require_public(value)
    ctx.events.append(value)


def node(ctx, name, action, *, candidate=False, propagate=False):
    """Capture business failures as graph routes; cancellation always reaches the outer guard."""
    @wraps(action)
    async def invoke(state):
        if not candidate:
            ctx.load_report(state)
        emit(ctx, name, "started", state, candidate=candidate)
        try:
            result = action(state)
            if inspect.isawaitable(result):
                result = await result
            result = result or {}
        except asyncio.CancelledError:
            ctx.cancelled = True
            emit(ctx, name, "failed", state, candidate=candidate, error={"code": "INTERRUPTED"})
            raise
        except Exception as error:
            # Some LangGraph versions wrap a node-raised CancelledError. A parent
            # adapter must not turn a cancelled subgraph into a local candidate failure.
            if ctx.cancelled:
                raise asyncio.CancelledError() from error
            info = failure(error)
            emit(ctx, name, "failed", state, candidate=candidate, error=info)
            if propagate or not ctx.registered:
                raise
            result = {"error": info, "error_status": error_status(error)}
            if candidate:
                result.pop("error_status")
                result["fatal"] = isinstance(error, FactoryError) and error.code in FATAL_CODES
            else:
                result["report_ref"] = ctx.save_progress()
            return result
        emit(ctx, name, "finished", {**state, **result}, candidate=candidate)
        if not candidate and ctx.registered:
            result["report_ref"] = ctx.save_progress()
        return result
    return invoke
