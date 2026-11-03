import json
import math


class FixedThresholdDetector:
    def __init__(self, config):
        if not isinstance(config, dict):
            raise ValueError("config must be a dict")
        threshold = config.get("threshold", 70.0)
        direction = config.get("direction", "upper")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise ValueError("threshold must be a finite number")
        threshold = float(threshold)
        if not math.isfinite(threshold):
            raise ValueError("threshold must be finite")
        if direction not in ("upper", "lower"):
            raise ValueError("direction must be upper or lower")
        self.config = {"threshold": threshold, "direction": direction}
        self.fitted = False

    def fit(self, train_points):
        if not isinstance(train_points, (list, tuple)):
            raise ValueError("train_points must be a list")
        has_valid = False
        for point in train_points:
            if not isinstance(point, dict):
                continue
            value = point.get("value")
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            value = float(value)
            if math.isfinite(value):
                has_valid = True
                break
        if not has_valid:
            raise ValueError("no valid training observations")
        self.fitted = True
        self.reset()

    def reset(self):
        pass

    def score_one(self, point):
        timestamp = point.get("timestamp")
        host_id = point.get("host_id")
        value = point.get("value")

        if value is None:
            status = "missing_input"
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            status = "invalid_input"
        elif not self.fitted:
            status = "insufficient_history"
        else:
            x = float(value)
            threshold = self.config["threshold"]
            if self.config["direction"] == "upper":
                score = x - threshold
            else:
                score = threshold - x
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "ok",
                "score": float(score),
                "evidence": {"threshold": threshold},
            }

        return {
            "timestamp": timestamp,
            "host_id": host_id,
            "status": status,
            "score": None,
            "evidence": {},
        }

    def save_state(self):
        return json.dumps({
            "config": self.config,
            "fitted": self.fitted,
        }, separators=(",", ":"), sort_keys=True)

    def load_state(self, raw):
        state = json.loads(raw)
        if not isinstance(state, dict):
            raise ValueError("invalid state")
        config = state.get("config")
        fitted = state.get("fitted")
        if not isinstance(config, dict) or not isinstance(fitted, bool):
            raise ValueError("invalid state")
        threshold = config.get("threshold")
        direction = config.get("direction")
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
            raise ValueError("invalid state")
        threshold = float(threshold)
        if not math.isfinite(threshold) or direction not in ("upper", "lower"):
            raise ValueError("invalid state")
        self.config = {"threshold": threshold, "direction": direction}
        self.fitted = fitted


def create_detector(config: dict):
    return FixedThresholdDetector(config)
