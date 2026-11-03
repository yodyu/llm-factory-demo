from __future__ import annotations

import json
import math
from statistics import median
from typing import Any


_METHOD = "rolling_mad"


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _quantile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("no valid training observations")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = (len(ordered) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(ordered[lo])
    frac = pos - lo
    return float(ordered[lo] * (1.0 - frac) + ordered[hi] * frac)


class RollingMadDetector:
    def __init__(self, config: dict):
        method = config.get("method_id", _METHOD)
        if method != _METHOD:
            raise ValueError("unsupported method")

        window = int(config.get("window", 30))
        min_history = int(config.get("min_history", 15))
        if window <= 0 or min_history <= 0 or min_history > window:
            raise ValueError("invalid window or min_history")

        direction = config.get("direction", "two_sided")
        if direction not in ("upper", "lower", "two_sided"):
            raise ValueError("invalid direction")

        self.config = {
            "method_id": _METHOD,
            "window": window,
            "min_history": min_history,
            "direction": direction,
        }
        self._scale_floor = 1e-9
        self._fitted = False
        self.reset()

    def fit(self, train_points: list[dict]) -> None:
        valid_raw: list[float] = []
        for point in train_points:
            value = point.get("value")
            if value is None:
                continue
            if not _finite_number(value):
                continue
            valid_raw.append(float(value))

        if not valid_raw:
            raise ValueError("no valid training observations")

        q1 = _quantile(valid_raw, 0.25)
        q3 = _quantile(valid_raw, 0.75)
        iqr = q3 - q1
        self._scale_floor = max(1e-9, iqr * 1e-6)
        self._fitted = True
        self.reset()

    def reset(self) -> None:
        self._history: list[list[Any]] = []
        self._real_count = 0

    def _append_history(self, point: dict, usable_value: float | None) -> None:
        original_present = bool(point.get("original_present", False))
        self._history.append([usable_value, original_present])
        if original_present:
            self._real_count += 1

        if len(self._history) > self.config["window"]:
            removed = self._history.pop(0)
            if removed[1]:
                self._real_count -= 1

    def score_one(self, point: dict) -> dict:
        timestamp = point.get("timestamp")
        host_id = point.get("host_id")
        value = point.get("value")

        def result(status: str, score: float | None, evidence: dict | None = None) -> dict:
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": status,
                "score": score,
                "evidence": evidence,
            }

        if value is None:
            self._append_history(point, None)
            return result("missing_input", None)

        if not _finite_number(value):
            self._append_history(point, None)
            return result("invalid_input", None)

        x = float(value)
        usable_value = x

        if not bool(point.get("original_present", True)):
            imputed = point.get("imputation")
            if imputed is not None and _finite_number(imputed):
                usable_value = float(imputed)

        historical_values = [float(slot[0]) for slot in self._history if slot[0] is not None]

        score = None
        evidence = None
        if self._real_count < self.config["min_history"] or not historical_values:
            status = "insufficient_history"
        else:
            m = float(median(historical_values))
            mad = float(median(abs(v - m) for v in historical_values))
            scale = max(1.4826 * mad, self._scale_floor)
            direction = self.config["direction"]
            if direction == "upper":
                score = (x - m) / scale
            elif direction == "lower":
                score = (m - x) / scale
            else:
                score = abs(x - m) / scale
            status = "ok"
            evidence = {
                "method": _METHOD,
                "direction": direction,
                "window": self.config["window"],
                "min_history": self.config["min_history"],
                "history_size": len(self._history),
                "real_history": self._real_count,
                "usable_history": len(historical_values),
                "median": m,
                "mad": mad,
                "scale": scale,
                "scale_floor": self._scale_floor,
            }

        self._append_history(point, usable_value)
        return result(status, score, evidence)

    def save_state(self) -> str:
        state = {
            "config": self.config,
            "scale_floor": self._scale_floor,
            "fitted": self._fitted,
            "history": self._history,
            "real_count": self._real_count,
        }
        return json.dumps(state, allow_nan=False, separators=(",", ":"))

    def load_state(self, raw: str) -> None:
        state = json.loads(raw)
        if state.get("config") != self.config:
            raise ValueError("state config mismatch")
        self._scale_floor = float(state.get("scale_floor", 1e-9))
        self._fitted = bool(state.get("fitted", False))
        history = state.get("history", [])
        if not isinstance(history, list):
            raise ValueError("invalid history state")
        normalized: list[list[Any]] = []
        real_count = 0
        for slot in history:
            if not isinstance(slot, list) or len(slot) != 2:
                raise ValueError("invalid history slot")
            val, was_real = slot
            if val is not None:
                if not _finite_number(val):
                    raise ValueError("invalid history value")
                val = float(val)
            if not isinstance(was_real, bool):
                raise ValueError("invalid history flag")
            if was_real:
                real_count += 1
            normalized.append([val, was_real])
        if len(normalized) > self.config["window"] or real_count != int(state.get("real_count", -1)):
            raise ValueError("inconsistent history state")
        self._history = normalized
        self._real_count = real_count


def create_detector(config: dict) -> RollingMadDetector:
    return RollingMadDetector(config)
