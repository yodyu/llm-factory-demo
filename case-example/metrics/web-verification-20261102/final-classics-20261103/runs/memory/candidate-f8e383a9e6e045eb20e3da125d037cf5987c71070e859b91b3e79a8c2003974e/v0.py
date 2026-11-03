import json
import math


_DEFAULTS = {
    "alpha": 0.2,
    "direction": "upper",
    "min_history": 3,
    "quantile": 0.99,
}


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


class EwmaDetector:
    def __init__(self, config):
        cfg = dict(_DEFAULTS)
        if isinstance(config, dict):
            cfg.update(config)
        self.config = {
            "alpha": float(cfg["alpha"]),
            "direction": str(cfg["direction"]),
            "min_history": int(cfg["min_history"]),
            "quantile": float(cfg["quantile"]),
        }
        if not (0.0 < self.config["alpha"] <= 1.0):
            raise ValueError("alpha must be in (0, 1]")
        if self.config["direction"] not in ("upper", "lower", "two_sided"):
            raise ValueError("unsupported direction")
        if not (1 <= self.config["min_history"] <= 600):
            raise ValueError("min_history must be in [1, 600]")
        if not (0.0 < self.config["quantile"] < 1.0):
            raise ValueError("quantile must be in (0, 1)")
        self.baseline = None
        self.scale = None
        self.smooth = None
        self.count = 0

    def fit(self, train_points):
        values = []
        for point in train_points or []:
            value = point.get("value") if isinstance(point, dict) else None
            if value is not None and _finite_number(value):
                values.append(float(value))
        if not values:
            raise ValueError("no valid training observations")
        n = len(values)
        baseline = sum(values) / n
        variance = sum((value - baseline) * (value - baseline) for value in values) / n
        self.baseline = baseline
        self.scale = max(1e-9, math.sqrt(variance))
        self.reset()

    def reset(self):
        if self.baseline is None:
            self.smooth = None
            self.count = 0
        else:
            self.smooth = self.baseline
            self.count = 0

    def score_one(self, point):
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
        elif self.baseline is None or self.scale is None or self.smooth is None:
            status = "insufficient_history"
            score = None
            evidence = {}
        else:
            x = float(value)
            alpha = self.config["alpha"]
            self.smooth = alpha * x + (1.0 - alpha) * self.smooth
            if point.get("original_present") is True:
                self.count += 1

            if self.count < self.config["min_history"]:
                status = "insufficient_history"
                score = None
                evidence = {}
            else:
                normalized = (self.smooth - self.baseline) / self.scale
                direction = self.config["direction"]
                if direction == "upper":
                    score = normalized
                elif direction == "lower":
                    score = -normalized
                else:
                    score = abs(normalized)
                status = "ok"
                evidence = {
                    "ewma": self.smooth,
                    "baseline": self.baseline,
                    "scale": self.scale,
                }

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
        self.config = {
            "alpha": float(state["config"]["alpha"]),
            "direction": str(state["config"]["direction"]),
            "min_history": int(state["config"]["min_history"]),
            "quantile": float(state["config"]["quantile"]),
        }
        self.baseline = None if state["baseline"] is None else float(state["baseline"])
        self.scale = None if state["scale"] is None else float(state["scale"])
        self.smooth = None if state["smooth"] is None else float(state["smooth"])
        self.count = int(state["count"])


def create_detector(config: dict):
    return EwmaDetector(config)
