"""Strict numeric contracts and common error/identity primitives."""
from .base import Contract, content_hash, parse_contract
from .errors import ErrorCode, FactoryError, Failure

__all__ = ["Contract", "content_hash", "parse_contract", "ErrorCode", "FactoryError", "Failure"]
