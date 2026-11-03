import json
import math


class FixedThresholdDetector:
    def __init__(self, config):
        self.config = dict(config)
        self.direction = self.config.get("direction", "upper")
        self.threshold = float(self.config.get("threshold", 85.0))
        self.valid_range = self.config.get("valid_range", (0.0, 100.0))
        if self.direction not in ("upper", "lower"):
            raise ValueError("direction must be upper or lower")
        if not math.isfinite(self.threshold):
            raise ValueError("threshold must be finite")

    def fit(self, train_points):
        has_valid = False
        for point in train_points:
            value = point.get("value")
            if value is not None and isinstance(value, (int, float)) and math.isfinite(value):
                if self._in_valid_range(value):
                    has_valid = True
        if not has_valid:
            raise ValueError("no valid training observations")
        self.reset()

    def reset(self):
        pass

    def _in_valid_range(self, value):
        try:
            low = float(self.valid_range[0])
            high = float(self.valid_range[1])
        except Exception:
            return True
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

        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or not self._in_valid_range(float(value)):
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "invalid_input",
                "score": None,
                "evidence": {}
            }

        if self.direction == "upper":
            score = float(value) - self.threshold
        else:
            score = self.threshold - float(value)

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
        self.threshold = float(state["threshold"])
        self.direction = state["direction"]
        self.config["threshold"] = self.threshold
        self.config["direction"] = self.direction


def create_detector(config: dict):
    return FixedThresholdDetector(config)
