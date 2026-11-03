"""Backward-compatible configuration names for frozen two-method reports."""
from typing import Literal

from pydantic import Field
from .metrics import DetectorConfig


class FixedConfig(DetectorConfig):
    method_id: Literal['fixed_threshold'] = 'fixed_threshold'
    threshold: float
    direction: Literal['upper', 'lower'] = 'upper'


class MADConfig(DetectorConfig):
    method_id: Literal['rolling_mad'] = 'rolling_mad'
    window: int = Field(default=30, ge=1, le=600)
    min_history: int = Field(default=15, ge=1)
    direction: Literal['upper', 'lower', 'two_sided'] = 'upper'
    quantile: float = Field(default=.99, gt=0, le=1)
