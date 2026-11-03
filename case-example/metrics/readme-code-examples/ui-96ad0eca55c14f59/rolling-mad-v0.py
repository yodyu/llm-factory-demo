from __future__ import annotations

import json
import math
from statistics import median
from typing import Any


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


class RollingMadUpperDetector:
    def __init__(self, config: dict) -> None:
        self.method_config = dict(config or {})
        self.window = int(self.method_config.get("window", 30))
        self.min_history = int(self.method_config.get("min_history", 15))
        if self.window < 1:
            raise ValueError("window must be positive")
        if self.min_history < 1 or self.min_history > self.window:
            raise ValueError("min_history must be in [1, window]")
        self.scale_floor: float | None = None
        self._fit_floor: float | None = None
        self.history: list[dict[str, Any]] = []

    def fit(self, train_points: list[dict]) -> None:
        values: list[float] = []
        for point in train_points or []:
            value = point.get("value")
            if value is not None and _finite_number(value):
                values.append(float(value))
        if not values:
            raise ValueError("at least one finite training value is required")
        q75 = _quantile(values, 0.75)
        q25 = _quantile(values, 0.25)
        self._fit_floor = max(1e-9, (q75 - q25) * 1e-6)
        self.scale_floor = self._fit_floor
        self.reset()

    def reset(self) -> None:
        if self._fit_floor is None:
            raise ValueError("fit required before reset")
        self.scale_floor = self._fit_floor
        self.history = []

    def score_one(self, point: dict) -> dict:
        timestamp = point.get("timestamp")
        host_id = point.get("host_id")
        if self.scale_floor is None:
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "insufficient_history",
                "score": None,
                "evidence": {},
            }

        raw_value = point.get("value")
        original_present = bool(point.get("original_present", False))

        if raw_value is None:
            status = "missing_input"
        elif not _finite_number(raw_value):
            status = "invalid_input"
        else:
            status = ""

        effective_value: float | None = None
        if status == "":
            effective_value = float(raw_value)
        elif status == "missing_input":
            imputation = point.get("imputation")
            if imputation is not None and _finite_number(imputation):
                effective_value = float(imputation)

        score = None
        evidence: dict[str, Any] = {}

        if not status:
            real_count = sum(1 for slot in self.history if slot.get("original_present") is True)
            if real_count < self.min_history:
                status = "insufficient_history"
            else:
                values = [
                    float(slot["value"])
                    for slot in self.history
                    if slot.get("value") is not None
                ]
                if not values:
                    status = "insufficient_history"
                else:
                    center = median(values)
                    mad = median(abs(x - center) for x in values)
                    scale = max(1.4826 * mad, self.scale_floor)
                    score = (effective_value - center) / scale
                    if not math.isfinite(score):
                        status = "invalid_input"
                        score = None
                    else:
                        evidence = {
                            "median": float(center),
                            "mad": float(mad),
                            "scale": float(scale),
                        }

        self.history.append({
            "timestamp": timestamp,
            "value": effective_value,
            "original_present": original_present,
        })
        if len(self.history) > self.window:
            self.history = self.history[-self.window:]

        return {
            "timestamp": timestamp,
            "host_id": host_id,
            "status": status,
            "score": score,
            "evidence": evidence,
        }

    def save_state(self) -> str:
        if self.scale_floor is None or self._fit_floor is None:
            raise ValueError("fit required before save")
        state = {
            "window": self.window,
            "min_history": self.min_history,
            "fit_floor": self._fit_floor,
            "scale_floor": self.scale_floor,
            "history": self.history,
        }
        raw = json.dumps(state, separators=(",", ":"), allow_nan=False)
        if len(raw.encode("utf-8")) > 128 * 1024:
            raise ValueError("state exceeds 128 KiB")
        return raw

    def load_state(self, raw: str) -> None:
        state = json.loads(raw)
        self.window = int(state["window"])
        self.min_history = int(state["min_history"])
        self._fit_floor = float(state["fit_floor"])
        self.scale_floor = float(state["scale_floor"])
        loaded_history = state.get("history", [])
        if not isinstance(loaded_history, list):
            raise ValueError("invalid history state")
        self.history = loaded_history[-self.window:]


def create_detector(config: dict):
    return RollingMadUpperDetector(config)
