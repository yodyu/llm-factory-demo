import json
import math


class FixedThresholdDetector:
    def __init__(self, config):
        direction = config.get("direction", "upper")
        threshold = config.get("threshold", 90.0)
        if direction not in ("upper", "lower"):
            raise ValueError("direction must be 'upper' or 'lower'")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise ValueError("threshold must be a number")
        if not math.isfinite(float(threshold)):
            raise ValueError("threshold must be finite")
        self.direction = direction
        self.threshold = float(threshold)
        self._fitted = False

    def fit(self, train_points):
        has_valid = False
        for point in train_points or []:
            value = point.get("value") if isinstance(point, dict) else None
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if math.isfinite(float(value)):
                has_valid = True
                break
        if not has_valid:
            raise ValueError("no valid training observations")
        self._fitted = True
        self.reset()

    def reset(self):
        # Fixed-threshold scoring has no fitted distribution or runtime history.
        return None

    def score_one(self, point):
        timestamp = point.get("timestamp")
        host_id = point.get("host_id")

        if not self._fitted:
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "insufficient_history",
                "score": None,
                "evidence": {},
            }

        if "value" not in point or point.get("value") is None:
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "missing_input",
                "score": None,
                "evidence": {},
            }

        value = point.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "invalid_input",
                "score": None,
                "evidence": {},
            }

        value = float(value)
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
        threshold = state["threshold"]
        direction = state["direction"]
        if direction not in ("upper", "lower") or not math.isfinite(float(threshold)):
            raise ValueError("invalid saved state")
        self.threshold = float(threshold)
        self.direction = direction
        self._fitted = bool(state.get("fitted", False))


def create_detector(config: dict):
    return FixedThresholdDetector(config)
