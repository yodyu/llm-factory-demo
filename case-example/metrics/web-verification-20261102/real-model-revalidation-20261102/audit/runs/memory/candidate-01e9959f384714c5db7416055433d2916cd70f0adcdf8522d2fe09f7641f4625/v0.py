import json
import math


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


class FixedThresholdDetector:
    def __init__(self, config):
        if not isinstance(config, dict):
            raise ValueError("config must be a dict")
        threshold = config.get("threshold", 70.0)
        direction = config.get("direction", "upper")
        if not _finite_number(threshold):
            raise ValueError("threshold must be a finite number")
        if direction not in ("upper", "lower"):
            raise ValueError("direction must be upper or lower")
        self.config = {"threshold": float(threshold), "direction": direction}
        self.fitted = False

    def fit(self, train_points):
        if not isinstance(train_points, list) or not any(
            isinstance(point, dict) and point.get("value") is not None and _finite_number(point.get("value"))
            for point in train_points
        ):
            raise ValueError("no valid training observations")
        self.fitted = True
        self.reset()

    def reset(self):
        return None

    def score_one(self, point):
        if not isinstance(point, dict):
            raise ValueError("point must be a dict")
        timestamp = point.get("timestamp")
        host_id = point.get("host_id")
        value = point.get("value")

        if value is None:
            status = "missing_input"
            score = None
            evidence = {}
        elif not _finite_number(value):
            status = "invalid_input"
            score = None
            evidence = {}
        elif not self.fitted:
            status = "insufficient_history"
            score = None
            evidence = {}
        else:
            x = float(value)
            threshold = self.config["threshold"]
            if self.config["direction"] == "upper":
                score = x - threshold
            else:
                score = threshold - x
            status = "ok"
            evidence = {"threshold": threshold}

        return {
            "timestamp": timestamp,
            "host_id": host_id,
            "status": status,
            "score": score,
            "evidence": evidence,
        }

    def save_state(self):
        return json.dumps({"config": self.config, "fitted": self.fitted}, separators=(",", ":"), sort_keys=True)

    def load_state(self, raw):
        state = json.loads(raw)
        if not isinstance(state, dict):
            raise ValueError("invalid state")
        config = state.get("config")
        if not isinstance(config, dict) or not _finite_number(config.get("threshold")) or config.get("direction") not in ("upper", "lower"):
            raise ValueError("invalid config state")
        self.config = {"threshold": float(config["threshold"]), "direction": config["direction"]}
        self.fitted = bool(state.get("fitted", False))


def create_detector(config: dict):
    return FixedThresholdDetector(config if isinstance(config, dict) else {})
