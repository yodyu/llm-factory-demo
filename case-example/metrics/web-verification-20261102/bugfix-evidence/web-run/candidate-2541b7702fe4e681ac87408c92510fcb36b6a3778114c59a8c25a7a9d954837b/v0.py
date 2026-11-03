import json
import math


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


class ThresholdProbeDetector:
    def __init__(self, config):
        cfg = dict(config or {})
        self.direction = cfg.get("direction", "upper")
        threshold = cfg.get("threshold", 85.0)
        if self.direction not in ("upper", "lower"):
            raise ValueError("direction must be upper or lower")
        if not _is_number(threshold):
            raise ValueError("threshold must be a finite number")
        self.threshold = float(threshold)
        self.fitted = False

    def fit(self, train_points):
        has_valid = False
        for point in train_points or []:
            value = point.get("value") if isinstance(point, dict) else None
            if value is not None:
                if not _is_number(value):
                    raise ValueError("training value must be a finite number")
                has_valid = True
        if not has_valid:
            raise ValueError("no valid training observations")
        self.fitted = True
        self.reset()

    def reset(self):
        # The fixed-threshold probe has no rolling role state.
        return None

    def score_one(self, point):
        timestamp = point.get("timestamp")
        host_id = point.get("host_id")
        value = point.get("value")

        if value is None:
            status = "missing_input"
            score = None
            evidence = {}
        elif not _is_number(value):
            status = "invalid_input"
            score = None
            evidence = {}
        else:
            x = float(value)
            if self.direction == "upper":
                score = x - self.threshold
            else:
                score = self.threshold - x
            status = "ok"
            evidence = {"threshold": self.threshold}

        return {
            "timestamp": timestamp,
            "host_id": host_id,
            "status": status,
            "score": score,
            "evidence": evidence,
        }

    def save_state(self):
        return json.dumps(
            {
                "direction": self.direction,
                "threshold": self.threshold,
                "fitted": self.fitted,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    def load_state(self, raw):
        state = json.loads(raw)
        self.direction = state["direction"]
        self.threshold = float(state["threshold"])
        self.fitted = bool(state.get("fitted", False))


def create_detector(config: dict):
    return ThresholdProbeDetector(config)
