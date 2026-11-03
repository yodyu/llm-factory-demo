"""Stable failure categories shared by all modules."""

from enum import StrEnum
from typing import Annotated

from pydantic import BeforeValidator

from .base import Contract


class ErrorCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    INPUT_CONFLICT = "INPUT_CONFLICT"
    UNKNOWN_TARGET = "UNKNOWN_TARGET"
    INVALID_TIME_RANGE = "INVALID_TIME_RANGE"
    UNSUPPORTED_TASK = "UNSUPPORTED_TASK"
    DATA_HASH_MISMATCH = "DATA_HASH_MISMATCH"
    DATA_CONTRACT_ERROR = "DATA_CONTRACT_ERROR"
    MODEL_ERROR = "MODEL_ERROR"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_OUTPUT_INVALID = "MODEL_OUTPUT_INVALID"
    RETRIEVAL_ERROR = "RETRIEVAL_ERROR"
    QUERY_TIMEOUT = "QUERY_TIMEOUT"
    CODE_CONTRACT_ERROR = "CODE_CONTRACT_ERROR"
    CODE_EXECUTION_ERROR = "CODE_EXECUTION_ERROR"
    CODE_TIMEOUT = "CODE_TIMEOUT"
    SANDBOX_UNAVAILABLE = "SANDBOX_UNAVAILABLE"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"


class Failure(Contract):
    code: Annotated[ErrorCode, BeforeValidator(lambda value: ErrorCode(value))]
    message: str
    field: str | None
    retryable: bool


class FactoryError(RuntimeError):
    """Runtime exception with a stable machine-readable code."""

    def __init__(self, code: ErrorCode, message: str):
        self.code = code
        super().__init__(message)
