import json
import math


class Detector:
    def __init__(self, config: dict):
        self.config = {
            "method_id": "fixed_threshold",
            "direction": config.get("direction", "upper"),
            "threshold": float(config.get("threshold", 70.0)),
        }
        if self.config["direction"] not in ("upper", "lower"):
            raise ValueError("direction must be upper or lower")
        if not math.isfinite(self.config["threshold"]):
            raise ValueError("threshold must be finite")
        self._fitted = False

    def fit(self, train_points: list[dict]):
        has_valid = False
        for point in train_points:
            value = point.get("value")
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
        return None

    def score_one(self, point: dict):
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

        try:
            if isinstance(value, bool):
                raise ValueError()
            x = float(value)
            if not math.isfinite(x):
                raise ValueError()
        except (TypeError, ValueError, OverflowError):
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "invalid_input",
                "score": None,
                "evidence": {},
            }

        threshold = self.config["threshold"]
        if self.config["direction"] == "upper":
            score = x - threshold
        else:
            score = threshold - x

        return {
            "timestamp": timestamp,
            "host_id": host_id,
            "status": "ok",
            "score": score,
            "evidence": {"threshold": threshold},
        }

    def save_state(self) -> str:
        return json.dumps(
            {
                "config": dict(self.config),
                "fitted": self._fitted,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    def load_state(self, raw: str):
        state = json.loads(raw)
        config = state["config"]
        self.config = {
            "method_id": "fixed_threshold",
            "direction": str(config["direction"]),
            "threshold": float(config["threshold"]),
        }
        self._fitted = bool(state.get("fitted", False))
        self.reset()


def create_detector(config: dict):
    return Detector(config)
