import json
import math


class FixedThresholdDetector:
    def __init__(self, config):
        self.config = dict(config)
        self.threshold = float(config["threshold"])
        self.direction = config.get("direction", "upper")
        if self.direction not in ("upper", "lower"):
            raise ValueError("direction must be upper or lower")
        if not math.isfinite(self.threshold):
            raise ValueError("threshold must be finite")

    def fit(self, train_points):
        # The fixed-threshold method needs no fitted baseline.  Training points are
        # validated only for presence of at least one usable finite observation.
        has_valid = False
        for point in train_points:
            value = point.get("value")
            if value is not None:
                value = float(value)
                if math.isfinite(value):
                    has_valid = True
                    break
        if not has_valid:
            raise ValueError("no valid training observations")
        self.reset()

    def reset(self):
        # No rolling detector state.  Persistence is handled by the trusted layer.
        return None

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

        try:
            numeric_value = float(value)
        except (TypeError, ValueError, OverflowError):
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "invalid_input",
                "score": None,
                "evidence": {}
            }

        if not math.isfinite(numeric_value):
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "invalid_input",
                "score": None,
                "evidence": {}
            }

        delta = numeric_value - self.threshold
        if self.direction == "lower":
            delta = -delta

        return {
            "timestamp": timestamp,
            "host_id": host_id,
            "status": "ok",
            "score": delta,
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
        if not isinstance(state, dict):
            raise ValueError("invalid state")
        threshold = float(state.get("threshold"))
        direction = state.get("direction")
        if not math.isfinite(threshold) or direction not in ("upper", "lower"):
            raise ValueError("invalid state")
        self.threshold = threshold
        self.direction = direction
        self.config["threshold"] = threshold
        self.config["direction"] = direction


def create_detector(config: dict):
    return FixedThresholdDetector(config)
