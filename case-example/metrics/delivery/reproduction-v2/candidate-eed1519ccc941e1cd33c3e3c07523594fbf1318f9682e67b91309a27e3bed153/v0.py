import json
import math
from collections import deque


class RollingMadDetector:
    def __init__(self, config):
        self.config = dict(config or {})
        self.window = int(self.config.get("window", 30))
        self.min_history = int(self.config.get("min_history", 15))
        self.direction = str(self.config.get("direction", "upper"))
        if self.window <= 0:
            raise ValueError("window must be positive")
        if self.min_history <= 0:
            raise ValueError("min_history must be positive")
        if self.min_history > self.window:
            raise ValueError("min_history must be <= window")
        if self.direction not in ("upper", "lower", "two_sided"):
            raise ValueError("unsupported direction")
        self.scale_floor = 1e-9
        self.fit_scale_floor = 1e-9
        self.history = None
        self.true_count = 0

    @staticmethod
    def _finite_number(value):
        if isinstance(value, bool):
            return False
        if not isinstance(value, (int, float)):
            return False
        return math.isfinite(float(value))

    @staticmethod
    def _median(values):
        if not values:
            return None
        ordered = sorted(values)
        n = len(ordered)
        mid = n // 2
        if n % 2:
            return float(ordered[mid])
        return (float(ordered[mid - 1]) + float(ordered[mid])) / 2.0

    @staticmethod
    def _linear_quantile(values, q):
        ordered = sorted(float(v) for v in values)
        n = len(ordered)
        if n == 1:
            return ordered[0]
        pos = (n - 1) * q
        lo = int(math.floor(pos))
        hi = int(math.ceil(pos))
        if lo == hi:
            return ordered[lo]
        frac = pos - lo
        return ordered[lo] * (1.0 - frac) + ordered[hi] * frac

    def fit(self, train_points):
        valid_values = []
        for point in train_points or []:
            value = point.get("value") if isinstance(point, dict) else None
            if self._finite_number(value):
                valid_values.append(float(value))
        if not valid_values:
            raise ValueError("no valid training observations")
        q1 = self._linear_quantile(valid_values, 0.25)
        q3 = self._linear_quantile(valid_values, 0.75)
        iqr = q3 - q1
        if not math.isfinite(iqr) or iqr < 0.0:
            iqr = 0.0
        self.fit_scale_floor = max(1e-9, iqr * 1e-6)
        self.scale_floor = self.fit_scale_floor
        self.reset()

    def reset(self):
        self.history = deque()
        self.true_count = 0
        self.scale_floor = getattr(self, "fit_scale_floor", 1e-9)

    @staticmethod
    def _base_result(point, status, score=None, evidence=None):
        return {
            "timestamp": point.get("timestamp"),
            "host_id": point.get("host_id"),
            "status": status,
            "score": score,
            "evidence": evidence if evidence is not None else {},
        }

    def score_one(self, point):
        current_value = point.get("value")
        original_present = bool(point.get("original_present", False))

        if current_value is None:
            result = self._base_result(point, "missing_input")
        elif not self._finite_number(current_value):
            result = self._base_result(point, "invalid_input")
        else:
            x = float(current_value)
            usable_history = [
                float(slot.get("value"))
                for slot in self.history
                if slot.get("value") is not None
                and self._finite_number(slot.get("value"))
            ]

            if self.true_count < self.min_history:
                result = self._base_result(point, "insufficient_history")
            else:
                median = self._median(usable_history)
                if median is None:
                    result = self._base_result(point, "insufficient_history")
                else:
                    mad = self._median([abs(v - median) for v in usable_history])
                    scale = max(1.4826 * mad, self.scale_floor)
                    if self.direction == "upper":
                        score = (x - median) / scale
                    elif self.direction == "lower":
                        score = (median - x) / scale
                    else:
                        score = abs(x - median) / scale
                    result = self._base_result(
                        point,
                        "ok",
                        float(score),
                        {
                            "median": float(median),
                            "mad": float(mad),
                            "scale": float(scale),
                        },
                    )

        self.history.append({
            "value": current_value,
            "original_present": original_present,
        })
        if original_present and self._finite_number(current_value):
            self.true_count += 1
        while len(self.history) > self.window:
            old = self.history.popleft()
            if old.get("original_present") and self._finite_number(old.get("value")):
                self.true_count = max(0, self.true_count - 1)

        return result

    def save_state(self):
        state = {
            "config": self.config,
            "window": self.window,
            "min_history": self.min_history,
            "direction": self.direction,
            "scale_floor": self.scale_floor,
            "fit_scale_floor": self.fit_scale_floor,
            "true_count": self.true_count,
            "history": list(self.history if self.history is not None else deque()),
        }
        return json.dumps(state, allow_nan=False, separators=(",", ":"))

    def load_state(self, raw):
        state = json.loads(raw)
        self.config = state["config"]
        self.window = int(state["window"])
        self.min_history = int(state["min_history"])
        self.direction = str(state["direction"])
        self.scale_floor = float(state["scale_floor"])
        self.fit_scale_floor = float(state["fit_scale_floor"])
        loaded_history = state.get("history", [])
        self.history = deque(loaded_history[-self.window:] if self.window > 0 else [])
        self.true_count = sum(
            1
            for slot in self.history
            if slot.get("original_present") and self._finite_number(slot.get("value"))
        )
        if int(state.get("true_count", self.true_count)) != self.true_count:
            # Keep loaded state internally consistent even for older serializations.
            pass


def create_detector(config: dict):
    return RollingMadDetector(config)
