import json
import math


class FixedThresholdDetector:
    def __init__(self, config):
        self.config = dict(config)
        self.direction = self.config.get("direction", "upper")
        threshold = self.config.get("threshold")
        if threshold is None or not isinstance(threshold, (int, float)):
            raise ValueError("threshold must be a number")
        if isinstance(threshold, bool) or not math.isfinite(float(threshold)):
            raise ValueError("threshold must be finite")
        if self.direction not in ("upper", "lower"):
            raise ValueError("direction must be upper or lower")
        self.threshold = float(threshold)

    def fit(self, train_points):
        self.reset()

    def reset(self):
        return None

    def score_one(self, point):
        timestamp = point.get("timestamp")
        host_id = point.get("host_id")
        value = point.get("value")

        if value is None:
            status = "missing_input"
            score = None
        else:
            try:
                numeric_value = float(value)
            except (TypeError, ValueError, OverflowError):
                numeric_value = float("nan")

            if not math.isfinite(numeric_value):
                status = "invalid_input"
                score = None
            else:
                status = "ok"
                delta = numeric_value - self.threshold
                if self.direction == "lower":
                    delta = -delta
                score = delta

        return {
            "timestamp": timestamp,
            "host_id": host_id,
            "status": status,
            "score": score,
            "evidence": {"threshold": self.threshold}
        }

    def save_state(self):
        state = {
            "method_id": "fixed_threshold",
            "threshold": self.threshold,
            "direction": self.direction
        }
        return json.dumps(state, allow_nan=False, separators=(",", ":"))

    def load_state(self, raw):
        state = json.loads(raw)
        if not isinstance(state, dict):
            raise ValueError("invalid state")
        if state.get("threshold") != self.threshold or state.get("direction") != self.direction:
            raise ValueError("state config mismatch")


def create_detector(config):
    return FixedThresholdDetector(config)
