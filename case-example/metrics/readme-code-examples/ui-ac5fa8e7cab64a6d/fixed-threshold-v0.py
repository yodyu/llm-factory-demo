import json
import math


class FixedThresholdDetector:
    def __init__(self, config):
        if not isinstance(config, dict):
            raise ValueError("config must be a dict")
        threshold = config.get("threshold")
        direction = config.get("direction")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise ValueError("threshold must be a number")
        if not math.isfinite(float(threshold)):
            raise ValueError("threshold must be finite")
        if direction not in ("upper", "lower"):
            raise ValueError("direction must be upper or lower")
        self.threshold = float(threshold)
        self.direction = direction
        self._fitted = False

    def fit(self, train_points):
        valid = False
        if isinstance(train_points, list):
            for point in train_points:
                if isinstance(point, dict):
                    value = point.get("value")
                    if value is not None and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
                        valid = True
                        break
        if not valid:
            raise ValueError("no valid training observations")
        self._fitted = True

    def reset(self):
        return None

    def score_one(self, point):
        timestamp = point.get("timestamp") if isinstance(point, dict) else None
        host_id = point.get("host_id") if isinstance(point, dict) else None

        if not self._fitted:
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "insufficient_history",
                "score": None,
                "evidence": {}
            }

        value = point.get("value") if isinstance(point, dict) else None
        if value is None:
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "missing_input",
                "score": None,
                "evidence": {}
            }

        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "invalid_input",
                "score": None,
                "evidence": {}
            }

        x = float(value)
        if self.direction == "upper":
            score = x - self.threshold
        else:
            score = self.threshold - x

        return {
            "timestamp": timestamp,
            "host_id": host_id,
            "status": "ok",
            "score": score,
            "evidence": {
                "threshold": self.threshold,
                "direction": self.direction
            }
        }

    def save_state(self):
        return json.dumps({
            "threshold": self.threshold,
            "direction": self.direction,
            "fitted": self._fitted
        }, separators=(",", ":"), sort_keys=True)

    def load_state(self, raw):
        state = json.loads(raw)
        threshold = state["threshold"]
        direction = state["direction"]
        if not math.isfinite(float(threshold)) or direction not in ("upper", "lower"):
            raise ValueError("invalid saved state")
        self.threshold = float(threshold)
        self.direction = direction
        self._fitted = bool(state.get("fitted", False))


def create_detector(config: dict):
    return FixedThresholdDetector(config)
