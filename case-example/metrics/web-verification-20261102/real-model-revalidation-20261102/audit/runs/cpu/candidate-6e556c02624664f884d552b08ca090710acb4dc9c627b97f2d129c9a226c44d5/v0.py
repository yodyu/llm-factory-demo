import json
import math


def _is_finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


class FixedThresholdDetector:
    def __init__(self, config):
        threshold = config.get("threshold", 90.0)
        direction = config.get("direction", "upper")
        if not _is_finite_number(threshold):
            raise ValueError("threshold must be a finite number")
        if direction not in ("upper", "lower"):
            raise ValueError("direction must be 'upper' or 'lower'")
        self.threshold = float(threshold)
        self.direction = direction
        self._fitted = False

    def fit(self, train_points):
        valid = False
        if isinstance(train_points, list):
            for point in train_points:
                if isinstance(point, dict) and _is_finite_number(point.get("value")):
                    valid = True
                    break
        if not valid:
            raise ValueError("no valid training observations")
        self._fitted = True
        self.reset()

    def reset(self):
        return None

    def score_one(self, point):
        timestamp = point.get("timestamp")
        host_id = point.get("host_id")
        value = point.get("value")

        if value is None:
            status = "missing_input"
        elif not _is_finite_number(value):
            status = "invalid_input"
        elif not self._fitted:
            status = "insufficient_history"
        else:
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

        return {
            "timestamp": timestamp,
            "host_id": host_id,
            "status": status,
            "score": None,
            "evidence": {}
        }

    def save_state(self):
        return json.dumps({
            "threshold": self.threshold,
            "direction": self.direction,
            "fitted": self._fitted
        }, separators=(",", ":"), sort_keys=True)

    def load_state(self, raw):
        state = json.loads(raw)
        threshold = state.get("threshold")
        direction = state.get("direction")
        if not _is_finite_number(threshold) or direction not in ("upper", "lower"):
            raise ValueError("invalid saved state")
        self.threshold = float(threshold)
        self.direction = direction
        self._fitted = bool(state.get("fitted", False))


def create_detector(config: dict):
    return FixedThresholdDetector(config if isinstance(config, dict) else {})
