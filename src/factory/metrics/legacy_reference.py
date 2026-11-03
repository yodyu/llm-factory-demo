# Backward compatibility for frozen reference/evaluation protocol v1.
"""Human reference detectors ONLY. Never an import available to generated code.

These implementations check framework semantics; their outputs are not labels
and are never presented as LLM-generated algorithms.
"""

import math
from collections import deque
from collections.abc import Sequence
from statistics import median

from pydantic import Field, SerializeAsAny

from contracts.base import Contract, strict_json_loads
from contracts.metrics import DetectorConfig, FixedConfig, MADConfig, MetricPoint, ProcessedPoint, Score

ORIGIN = "reference"


def linear_quantile(values: Sequence[float], q: float) -> float:
    if not values or not 0 <= q <= 1:
        raise ValueError("nonempty values and q in [0,1] required")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lo, hi = math.floor(position), math.ceil(position)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)


class HistorySlot(Contract):
    value: float | None
    original: bool


class DetectorState(Contract):
    schema_version: str = Field(pattern=r"^metrics-reference-state/1$")
    config: SerializeAsAny[DetectorConfig]
    scale_floor: float = Field(ge=1e-9)
    history: list[HistorySlot]


class ReferenceDetector:
    origin = ORIGIN

    def __init__(self, config: FixedConfig | MADConfig):
        self.config = config
        self.scale_floor = None
        self.history = deque(maxlen=config.window if isinstance(config, MADConfig) else 1)

    def fit(self, train_points: Sequence[MetricPoint]):
        values = [point.value for point in train_points if point.value is not None]
        if not values:
            raise ValueError("no valid training observations")
        iqr = linear_quantile(values, 0.75) - linear_quantile(values, 0.25)
        self.scale_floor = max(1e-9, iqr * 1e-6)
        self.reset()

    def reset(self):
        if self.scale_floor is None:
            raise ValueError("fit required before reset")
        self.history.clear()

    def score_one(self, point: ProcessedPoint) -> Score:
        if self.scale_floor is None:
            raise ValueError("fit required before scoring")
        status, score, evidence = "ok", None, {}
        if point.value is None:
            status = "missing_input"
        elif isinstance(self.config, FixedConfig):
            delta = point.value - self.config.threshold
            score = delta if self.config.direction == "upper" else -delta
            evidence = {"threshold": self.config.threshold}
        elif sum(slot.original for slot in self.history) < self.config.min_history:
            status = "insufficient_history"
        else:
            # Inspect history BEFORE appending this point, including unavailable slots.
            values = [slot.value for slot in self.history if slot.value is not None]
            center = median(values)
            mad = median([abs(value - center) for value in values])
            scale = max(1.4826 * mad, self.scale_floor)
            delta = point.value - center
            if self.config.direction == "lower":
                delta = -delta
            elif self.config.direction == "two_sided":
                delta = abs(delta)
            score = delta / scale
            evidence = {"median": center, "mad": mad, "scale": scale}
        if score is not None and not math.isfinite(score):
            status, score = "invalid_input", None
        self.history.append(HistorySlot(value=point.value, original=point.original_present))
        return Score(timestamp=point.timestamp, host_id=point.host_id,
                     status=status, score=score, evidence=evidence)

    def save_state(self) -> str:
        if self.scale_floor is None:
            raise ValueError("fit required before saving")
        return DetectorState(schema_version="metrics-reference-state/1", config=self.config,
                             scale_floor=self.scale_floor, history=list(self.history)).model_dump_json()

    def load_state(self, raw: str):
        if len(raw.encode()) > 128 * 1024:
            raise ValueError("state exceeds size limit")
        state = DetectorState.model_validate(strict_json_loads(raw))
        if state.config.model_dump() != self.config.model_dump() or len(state.history) > self.history.maxlen:
            raise ValueError("state config/history mismatch")
        if any(slot.original and slot.value is None for slot in state.history):
            raise ValueError("invalid original history slot")
        self.scale_floor = state.scale_floor
        self.history.clear()
        self.history.extend(state.history)


def create_detector(config: FixedConfig | MADConfig) -> ReferenceDetector:
    return ReferenceDetector(config)
