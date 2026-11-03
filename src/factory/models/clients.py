"""Budgeted compatible model clients; no prompts or provider exceptions are stored."""

import asyncio
import hashlib
import json
import math
import time
from typing import Callable

from contracts.base import strict_json_loads
from contracts.errors import ErrorCode
from contracts.ports import ModelRequest, ModelResponse
from factory.runtime.security import SecretGuard

from .config import LLMProfile, ModelEndpoint
from .transport import ModelCallError, OpenAITransport


def _json(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()


def _hash(value) -> str:
    return "sha256:" + hashlib.sha256(_json(value)).hexdigest()


def _invalid(reason="response_invalid"):
    return ModelCallError(ErrorCode.MODEL_OUTPUT_INVALID, reason)


def _usage(response, key):
    usage = response.get("usage")
    if usage is None:
        return None
    if not isinstance(usage, dict):
        raise _invalid("usage_invalid")
    value = usage.get(key)
    if value is not None and (type(value) is not int or value < 0):
        raise _invalid("usage_invalid")
    return value


class _Client:
    resource: str

    def __init__(
        self,
        profile,
        endpoint,
        ledger,
        artifacts,
        *,
        transport=None,
        max_attempts=1,
        retry_delay_seconds=0,
        clock=time.time,
    ):
        if type(max_attempts) is not int or not 1 <= max_attempts <= 8:
            raise ValueError("max_attempts must be between one and eight")
        if (
            type(retry_delay_seconds) not in (int, float)
            or not math.isfinite(retry_delay_seconds)
            or not 0 <= retry_delay_seconds <= 60
        ):
            raise ValueError("retry delay must be between zero and sixty seconds")
        if profile.mode == "api" and endpoint is None:
            raise ModelCallError(ErrorCode.INVALID_INPUT, "configuration_missing")
        if transport is None:
            if profile.mode == "mock":
                raise ModelCallError(ErrorCode.INVALID_INPUT, "explicit_mock_required")
            transport = OpenAITransport(endpoint)
        if getattr(transport, "mode", None) != profile.mode:
            raise ModelCallError(ErrorCode.INPUT_CONFLICT, "transport_mode_mismatch")
        self.profile, self.endpoint = profile, endpoint
        self.ledger, self.artifacts, self.transport = ledger, artifacts, transport
        self.max_attempts, self.retry_delay_seconds, self.clock = (
            max_attempts,
            retry_delay_seconds,
            clock,
        )
        self.guard = SecretGuard((endpoint.api_key.get_secret_value(),) if endpoint else ())
        self.guard.require_public(profile.model_dump(mode="json"))

    def _task(self, task_id, profile_id):
        if profile_id != self.profile.profile_id:
            raise ModelCallError(ErrorCode.INPUT_CONFLICT, "profile_mismatch")
        context = self.ledger.model_context(task_id)
        key = "model_profile_id" if self.resource == "model" else "embedding_profile_id"
        if context[key] != profile_id or context["model_mode"] != self.profile.mode:
            raise ModelCallError(ErrorCode.INPUT_CONFLICT, "task_profile_mismatch")
        return context

    def _public(self, value):
        failed = False
        try:
            self.guard.require_public(value)
            guard = getattr(self.ledger, "guard", None)
            if guard is not None:
                guard.require_public(value)
        except ValueError:
            failed = True
        if failed:
            raise ModelCallError(ErrorCode.MODEL_OUTPUT_INVALID, "credential_content_rejected")

    async def _call(
        self,
        task_id,
        call_id,
        payload,
        timeout,
        send: Callable,
        validate: Callable,
        *,
        remaining_required=0,
    ):
        context = self._task(task_id, self.profile.profile_id)
        task_deadline = self.ledger.task(task_id)["deadline"]
        if not call_id or type(call_id) is not str or len(call_id) > 240:
            raise ModelCallError(ErrorCode.INVALID_INPUT, "call_id_invalid")
        if (
            type(timeout) not in (int, float)
            or not math.isfinite(timeout)
            or not 0 < timeout <= (60 if self.resource == "model" else 30)
        ):
            raise ModelCallError(ErrorCode.INVALID_INPUT, "timeout_invalid")
        self._public([task_id, call_id, payload])
        input_hash = _hash(
            {
                "task_hash": context["binding_hash"],
                "call_id": call_id,
                "profile": self.profile.model_dump(mode="json"),
                "endpoint": self.endpoint.base_url if self.endpoint else None,
                "payload": payload,
                "timeout": timeout,
                **({"remaining_required": remaining_required} if remaining_required else {}),
            }
        )
        last_error = None
        binding = (
            {"source_task_id": task_id, "spec_hash": context["binding_hash"]}
            if context.get("spec_revision") is not None
            else {}
        )
        for attempt in range(1, self.max_attempts + 1):
            operation_id = call_id if attempt == 1 else f"{call_id}:attempt:{attempt}"
            reservation = self.ledger.reserve(
                task_id,
                self.resource,
                operation_id,
                input_hash,
                timeout_seconds=timeout,
                attempt=attempt,
                remaining_required=remaining_required,
                **binding,
            )
            if not reservation["is_new"]:
                if reservation["status"] == "SUCCEEDED":
                    saved = strict_json_loads(self.artifacts.read(reservation["result_ref"]))
                    self._public(saved)
                    return saved["response"], reservation["result_ref"]
                if reservation["status"] in ("FAILED", "UNKNOWN") and reservation["result_ref"]:
                    saved = strict_json_loads(self.artifacts.read(reservation["result_ref"]))
                    error = ModelCallError(
                        ErrorCode(saved["code"]),
                        saved["reason"],
                        http_status=saved["http_status"],
                        retryable=saved["retryable"],
                        outcome_unknown=saved["outcome_unknown"],
                        validation_issues=saved.get("validation_issues"),
                    )
                else:
                    raise ModelCallError(
                        ErrorCode.MODEL_ERROR,
                        "operation_in_flight_or_unknown",
                        outcome_unknown=True,
                    )
            else:
                self.ledger.mark_operation(operation_id, "SENT")
                started = time.monotonic()
                error = None
                response = None
                effective_timeout = reservation["deadline"] - self.clock()
                try:
                    if effective_timeout <= 0:
                        raise ModelCallError(ErrorCode.DEADLINE_EXCEEDED, "deadline_exceeded")
                    async with asyncio.timeout(effective_timeout):
                        response = validate(await send(effective_timeout))
                    self._public(response)
                except asyncio.CancelledError:
                    self.ledger.mark_operation(operation_id, "UNKNOWN")
                    raise
                except TimeoutError:
                    error = ModelCallError(ErrorCode.MODEL_TIMEOUT, "timeout", outcome_unknown=True)
                except ModelCallError as failure:
                    error = ModelCallError(
                        failure.code,
                        failure.reason,
                        http_status=failure.http_status,
                        retryable=failure.retryable,
                        outcome_unknown=failure.outcome_unknown,
                        validation_issues=failure.validation_issues,
                    )
                except Exception:
                    # A custom transport may leak credentials through exception text.
                    error = ModelCallError(
                        ErrorCode.MODEL_ERROR, "transport_error", outcome_unknown=True
                    )
                elapsed = time.monotonic() - started
                if error is None:
                    reference = self.artifacts.put(
                        _json({"kind": self.resource, "response": response})
                    )
                    self.ledger.record_operation_metadata(
                        operation_id,
                        {
                            "profile_id": self.profile.profile_id,
                            "actual_model": response["actual_model"],
                            "input_tokens": response["input_tokens"],
                            "output_tokens": response.get("output_tokens"),
                            "elapsed_seconds": elapsed,
                            "failure_code": None,
                        },
                    )
                    self.ledger.mark_operation(operation_id, "SUCCEEDED", reference)
                    return response, reference
                reference = self.artifacts.put(
                    _json(
                        {
                            "kind": "failure",
                            "code": error.code.value,
                            "reason": error.reason,
                            "http_status": error.http_status,
                            "retryable": error.retryable,
                            "outcome_unknown": error.outcome_unknown,
                            **(
                                {"validation_issues": error.validation_issues}
                                if error.validation_issues
                                else {}
                            ),
                        }
                    )
                )
                self.ledger.record_operation_metadata(
                    operation_id,
                    {
                        "profile_id": self.profile.profile_id,
                        "actual_model": None,
                        "input_tokens": None,
                        "output_tokens": None,
                        "elapsed_seconds": elapsed,
                        "failure_code": error.code.value + ":" + error.reason,
                    },
                )
                self.ledger.mark_operation(
                    operation_id, "UNKNOWN" if error.outcome_unknown else "FAILED", reference
                )
            last_error = error
            if not error.retryable or error.outcome_unknown or attempt == self.max_attempts:
                break
            if self.retry_delay_seconds:
                remaining = task_deadline - self.clock()
                if remaining <= 0:
                    raise ModelCallError(ErrorCode.DEADLINE_EXCEEDED, "deadline_exceeded")
                await asyncio.sleep(min(self.retry_delay_seconds, remaining))
                if self.clock() >= task_deadline:
                    raise ModelCallError(ErrorCode.DEADLINE_EXCEEDED, "deadline_exceeded")
        raise last_error from None

    async def aclose(self):
        close = getattr(self.transport, "aclose", None)
        if close:
            await close()


class LLMClient(_Client):
    resource = "model"

    def __init__(
        self, profile: LLMProfile, endpoint: ModelEndpoint | None, ledger, artifacts, **kwargs
    ):
        super().__init__(profile, endpoint, ledger, artifacts, **kwargs)

    def _validate(self, raw):
        if (
            not isinstance(raw, dict)
            or not isinstance(raw.get("model"), str)
            or not raw["model"].strip()
        ):
            raise _invalid()
        choices = raw.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise _invalid()
        choice = choices[0]
        message = choice.get("message")
        if choice.get("finish_reason") != "stop" or not isinstance(message, dict):
            raise _invalid("completion_incomplete")
        text = message.get("content")
        if message.get("tool_calls") or message.get("function_call") or message.get("refusal"):
            raise _invalid("text_response_required")
        if type(text) is not str or not text.strip():
            raise _invalid("text_response_required")
        return {
            "text": text,
            "actual_model": raw["model"],
            "input_tokens": _usage(raw, "prompt_tokens"),
            "output_tokens": _usage(raw, "completion_tokens"),
        }

    async def _generate(self, request, schema=None):
        self._task(request.task_id, request.profile_id)
        if not request.messages or any(
            set(m) != {"role", "content"}
            or m["role"] not in ("system", "user", "assistant")
            or not m["content"].strip()
            for m in request.messages
        ):
            raise ModelCallError(ErrorCode.INVALID_INPUT, "messages_invalid")
        payload = {
            "messages": request.messages,
            "schema": schema.model_json_schema() if schema else None,
        }

        def validate(raw):
            result = self._validate(raw)
            if schema:
                from .checks import validate_structured

                validate_structured(result["text"], schema)
            return result

        result, reference = await self._call(
            request.task_id,
            request.call_id,
            payload,
            request.timeout_seconds,
            lambda timeout: self.transport.chat(
                messages=request.messages, model=self.profile.model, timeout=timeout
            ),
            validate,
            remaining_required=request.remaining_required,
        )
        return ModelResponse(call_id=request.call_id, response_ref=reference, **result)

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return await self._generate(request)

    async def generate_structured(self, request: ModelRequest, schema):
        from .checks import validate_structured

        response = await self._generate(request, schema)
        return validate_structured(response.text, schema)
