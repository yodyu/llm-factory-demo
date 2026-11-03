import json
import math


class FixedThresholdDetector:
    def __init__(self, config):
        self.config = dict(config)
        self.direction = self.config.get("direction", "upper")
        self.threshold = float(self.config.get("threshold", 85.0))
        valid_range = self.config.get("valid_range", (0.0, 100.0))
        if valid_range is None:
            self.valid_range = None
        else:
            self.valid_range = (float(valid_range[0]), float(valid_range[1]))
        if self.direction not in ("upper", "lower"):
            raise ValueError("direction must be upper or lower")
        if not math.isfinite(self.threshold):
            raise ValueError("threshold must be finite")

    def fit(self, train_points):
        has_valid = False
        for point in train_points:
            value = point.get("value")
            if self._is_finite_number(value) and self._in_valid_range(float(value)):
                has_valid = True
        if not has_valid:
            raise ValueError("no valid training observations")
        self.reset()

    def reset(self):
        pass

    @staticmethod
    def _is_finite_number(value):
        return (
            value is not None
            and not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
        )

    def _in_valid_range(self, value):
        if self.valid_range is None:
            return True
        low, high = self.valid_range
        return low <= value <= high

    def score_one(self, point):
        timestamp = point.get("timestamp")
        host_id = point.get("host_id")
        value = point.get("value")

        if value is None:
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "missing_input",
                "score": None,
                "evidence": {}
            }

        if not self._is_finite_number(value):
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "invalid_input",
                "score": None,
                "evidence": {}
            }

        numeric_value = float(value)
        if not self._in_valid_range(numeric_value):
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "invalid_input",
                "score": None,
                "evidence": {}
            }

        if self.direction == "upper":
            score = numeric_value - self.threshold
        else:
            score = self.threshold - numeric_value

        return {
            "timestamp": timestamp,
            "host_id": host_id,
            "status": "ok",
            "score": score,
            "evidence": {"threshold": self.threshold}
        }

    def save_state(self):
        return json.dumps(
            {
                "method_id": "fixed_threshold",
                "threshold": self.threshold,
                "direction": self.direction
            },
            allow_nan=False,
            separators=(",", ":")
        )

    def load_state(self, raw):
        state = json.loads(raw)
        threshold = float(state["threshold"])
        direction = state["direction"]
        if not math.isfinite(threshold) or direction not in ("upper", "lower"):
            raise ValueError("invalid detector state")
        self.threshold = threshold
        self.direction = direction
        self.config["threshold"] = threshold
        self.config["direction"] = direction


def create_detector(config: dict):
    return FixedThresholdDetector(config)
