import json
import math


def _is_finite_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


class FixedThresholdDetector:
    def __init__(self, config):
        config = config or {}
        threshold = config.get("threshold", 85.0)
        direction = config.get("direction", "upper")
        if not _is_finite_number(threshold):
            raise ValueError("threshold must be a finite number")
        if direction not in ("upper", "lower"):
            raise ValueError("direction must be upper or lower")
        self.threshold = float(threshold)
        self.direction = direction
        self._fitted = False

    def fit(self, train_points):
        valid = False
        for point in train_points or []:
            if not isinstance(point, dict):
                raise ValueError("training point must be a dict")
            value = point.get("value")
            if value is not None:
                if not _is_finite_number(value):
                    raise ValueError("training value must be a finite number or null")
                valid = True
        if not valid:
            raise ValueError("no valid training observations")
        self._fitted = True
        self.reset()

    def reset(self):
        return None

    def score_one(self, point):
        if not isinstance(point, dict):
            return {
                "timestamp": None,
                "host_id": None,
                "status": "invalid_input",
                "score": None,
                "evidence": {},
            }

        timestamp = point.get("timestamp")
        host_id = point.get("host_id")
        value = point.get("value")

        if value is None:
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "missing_input",
                "score": None,
                "evidence": {},
            }

        if not _is_finite_number(value):
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "invalid_input",
                "score": None,
                "evidence": {},
            }

        numeric_value = float(value)
        if self.direction == "upper":
            score = numeric_value - self.threshold
        else:
            score = self.threshold - numeric_value

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
        if not _is_finite_number(threshold) or direction not in ("upper", "lower"):
            raise ValueError("invalid saved state")
        self.threshold = float(threshold)
        self.direction = direction
        self._fitted = bool(state.get("fitted", False))
        self.reset()


def create_detector(config: dict):
    return FixedThresholdDetector(config)
