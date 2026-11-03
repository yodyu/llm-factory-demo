import json
import math


def _is_finite_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))


class Detector:
    def __init__(self, config):
        self.config = {
            "alpha": float(config.get("alpha", 0.3)),
            "min_history": int(config.get("min_history", 3)),
            "direction": config.get("direction", "upper"),
            "quantile": float(config.get("quantile", 0.99)),
        }
        if not (0.0 < self.config["alpha"] <= 1.0):
            raise ValueError("alpha must be in (0, 1]")
        if not (1 <= self.config["min_history"] <= 600):
            raise ValueError("min_history must be in [1, 600]")
        if self.config["direction"] not in ("upper", "lower", "two_sided"):
            raise ValueError("unsupported direction")
        if not (0.0 < self.config["quantile"] < 1.0):
            raise ValueError("quantile must be in (0, 1)")
        self.baseline = None
        self.scale = None
        self.smooth = None
        self.count = 0
        self.fitted = False

    def fit(self, train_points):
        values = []
        for point in train_points:
            value = point.get("value")
            if value is not None and _is_finite_number(value):
                values.append(float(value))
        if not values:
            raise ValueError("no valid training observations")
        n = len(values)
        baseline = sum(values) / n
        variance = sum((x - baseline) * (x - baseline) for x in values) / n
        scale = max(1e-9, math.sqrt(variance))
        self.baseline = baseline
        self.scale = scale
        self.fitted = True
        self.reset()

    def reset(self):
        if not self.fitted:
            raise ValueError("fit required")
        self.smooth = self.baseline
        self.count = 0

    def score_one(self, point):
        timestamp = point.get("timestamp")
        host_id = point.get("host_id")
        value = point.get("value")

        if not self.fitted:
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "invalid_input",
                "score": None,
                "evidence": {},
            }

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

        x = float(value)
        alpha = self.config["alpha"]
        self.smooth = alpha * x + (1.0 - alpha) * self.smooth

        if point.get("original_present") is True:
            self.count += 1

        if self.count < self.config["min_history"]:
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "insufficient_history",
                "score": None,
                "evidence": {},
            }

        normalized = (self.smooth - self.baseline) / self.scale
        direction = self.config["direction"]
        if direction == "upper":
            score = normalized
        elif direction == "lower":
            score = -normalized
        else:
            score = abs(normalized)

        return {
            "timestamp": timestamp,
            "host_id": host_id,
            "status": "ok",
            "score": score,
            "evidence": {
                "ewma": self.smooth,
                "baseline": self.baseline,
                "scale": self.scale,
            },
        }

    def save_state(self):
        return json.dumps(
            {
                "config": self.config,
                "baseline": self.baseline,
                "scale": self.scale,
                "smooth": self.smooth,
                "count": self.count,
                "fitted": self.fitted,
            },
            separators=(",", ":"),
            allow_nan=False,
        )

    def load_state(self, raw):
        state = json.loads(raw)
        self.config = {
            "alpha": float(state["config"]["alpha"]),
            "min_history": int(state["config"]["min_history"]),
            "direction": state["config"]["direction"],
            "quantile": float(state["config"]["quantile"]),
        }
        self.baseline = None if state["baseline"] is None else float(state["baseline"])
        self.scale = None if state["scale"] is None else float(state["scale"])
        self.smooth = None if state["smooth"] is None else float(state["smooth"])
        self.count = int(state["count"])
        self.fitted = bool(state["fitted"])


def create_detector(config: dict):
    return Detector(config)
