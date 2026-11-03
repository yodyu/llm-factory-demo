import json
import math


def _is_finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


class EwmaDetector:
    def __init__(self, config):
        method_id = config.get("method_id", "ewma")
        if method_id != "ewma":
            raise ValueError("method_id must be ewma")

        alpha = config.get("alpha", 0.3)
        min_history = config.get("min_history", 3)
        direction = config.get("direction", "upper")
        quantile = config.get("quantile", 0.99)

        if not _is_finite_number(alpha) or not (0.0 < float(alpha) <= 1.0):
            raise ValueError("alpha must be in (0, 1]")
        if isinstance(min_history, bool) or not isinstance(min_history, int):
            raise ValueError("min_history must be an integer")
        if not 1 <= min_history <= 600:
            raise ValueError("min_history must be in [1, 600]")
        if direction not in ("upper", "lower", "two_sided"):
            raise ValueError("unsupported direction")
        if not _is_finite_number(quantile) or not (0.0 < float(quantile) < 1.0):
            raise ValueError("quantile must be in (0, 1)")

        self.config = {
            "method_id": "ewma",
            "alpha": float(alpha),
            "min_history": int(min_history),
            "direction": direction,
            "quantile": float(quantile),
        }
        self.baseline = None
        self.scale = None
        self.smooth = None
        self.count = 0

    def fit(self, train_points):
        values = []
        for point in train_points:
            value = point.get("value")
            if _is_finite_number(value):
                values.append(float(value))

        if not values:
            raise ValueError("no valid training observations")

        n = len(values)
        baseline = sum(values) / n
        variance = sum((x - baseline) * (x - baseline) for x in values) / n
        self.baseline = baseline
        self.scale = max(1e-9, math.sqrt(variance))
        self.reset()

    def reset(self):
        if self.baseline is None or self.scale is None:
            raise ValueError("fit required")
        self.smooth = self.baseline
        self.count = 0

    def score_one(self, point):
        if self.baseline is None or self.scale is None or self.smooth is None:
            raise ValueError("fit required")

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

        z = (self.smooth - self.baseline) / self.scale
        direction = self.config["direction"]
        if direction == "upper":
            score = z
        elif direction == "lower":
            score = -z
        else:
            score = abs(z)

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
            },
            separators=(",", ":"),
            allow_nan=False,
        )

    def load_state(self, raw):
        state = json.loads(raw)
        config = state["config"]
        self.config = {
            "method_id": "ewma",
            "alpha": float(config["alpha"]),
            "min_history": int(config["min_history"]),
            "direction": config["direction"],
            "quantile": float(config["quantile"]),
        }
        self.baseline = None if state["baseline"] is None else float(state["baseline"])
        self.scale = None if state["scale"] is None else float(state["scale"])
        self.smooth = None if state["smooth"] is None else float(state["smooth"])
        self.count = int(state["count"])
        return self


def create_detector(config: dict):
    return EwmaDetector(config)
