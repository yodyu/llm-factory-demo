import json
import math


class FixedThresholdDetector:
    def __init__(self, config):
        if not isinstance(config, dict):
            raise ValueError("config must be a dict")
        threshold = config.get("threshold", 85.0)
        direction = config.get("direction", "upper")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise ValueError("threshold must be a finite number")
        threshold = float(threshold)
        if not math.isfinite(threshold):
            raise ValueError("threshold must be finite")
        if direction not in ("upper", "lower"):
            raise ValueError("direction must be upper or lower")
        self.threshold = threshold
        self.direction = direction
        self._fitted = False

    def fit(self, train_points):
        if not isinstance(train_points, (list, tuple)):
            raise ValueError("train_points must be a list")
        has_valid = False
        for point in train_points:
            if not isinstance(point, dict):
                continue
            value = point.get("value")
            if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            value = float(value)
            if math.isfinite(value):
                has_valid = True
                break
        if not has_valid:
            raise ValueError("no valid training observations")
        self._fitted = True
        self.reset()

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
                "evidence": {},
            }

        if not isinstance(point, dict):
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "invalid_input",
                "score": None,
                "evidence": {},
            }

        value = point.get("value")
        if value is None:
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "missing_input",
                "score": None,
                "evidence": {},
            }

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "invalid_input",
                "score": None,
                "evidence": {},
            }

        value = float(value)
        if not math.isfinite(value):
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "invalid_input",
                "score": None,
                "evidence": {},
            }

        if self.direction == "upper":
            score = value - self.threshold
        else:
            score = self.threshold - value

        return {
            "timestamp": timestamp,
            "host_id": host_id,
            "status": "ok",
            "score": float(score),
            "evidence": {
                "threshold": self.threshold,
                "direction": self.direction,
            },
        }

    def save_state(self):
        return json.dumps(
            {
                "threshold": self.threshold,
                "direction": self.direction,
                "fitted": self._fitted,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    def load_state(self, raw):
        state = json.loads(raw)
        if not isinstance(state, dict):
            raise ValueError("invalid saved state")
        threshold = state.get("threshold")
        direction = state.get("direction")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise ValueError("invalid saved state")
        threshold = float(threshold)
        if not math.isfinite(threshold) or direction not in ("upper", "lower"):
            raise ValueError("invalid saved state")
        self.threshold = threshold
        self.direction = direction
        self._fitted = bool(state.get("fitted", False))
        self.reset()


def create_detector(config: dict):
    return FixedThresholdDetector(config)
