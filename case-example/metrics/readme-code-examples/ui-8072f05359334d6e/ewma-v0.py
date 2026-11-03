import json
import math


class EwmaDetector:
    def __init__(self, config):
        cfg = dict(config) if config is not None else {}
        self.alpha = float(cfg.get("alpha", 0.3))
        self.min_history = int(cfg.get("min_history", 3))
        self.direction = cfg.get("direction", "upper")
        self.quantile = float(cfg.get("quantile", 0.99))

        if not (math.isfinite(self.alpha) and 0.0 < self.alpha <= 1.0):
            raise ValueError("alpha must be in (0, 1]")
        if not (1 <= self.min_history <= 600):
            raise ValueError("min_history must be in [1, 600]")
        if self.direction not in ("upper", "lower", "two_sided"):
            raise ValueError("unsupported direction")
        if not (math.isfinite(self.quantile) and 0.0 < self.quantile < 1.0):
            raise ValueError("quantile must be in (0, 1)")

        self.baseline = None
        self.scale = None
        self.smooth = None
        self.count = 0

    def fit(self, train_points):
        values = []
        for point in train_points or []:
            value = point.get("value") if isinstance(point, dict) else None
            if value is None:
                continue
            value = float(value)
            if not math.isfinite(value):
                continue
            values.append(value)

        if not values:
            raise ValueError("no valid training observations")

        n = len(values)
        mean = sum(values) / n
        variance = sum((x - mean) * (x - mean) for x in values) / n
        self.baseline = mean
        self.scale = max(1e-9, math.sqrt(variance))
        self.reset()
        return None

    def reset(self):
        self.smooth = self.baseline
        self.count = 0
        return None

    def score_one(self, point):
        timestamp = point.get("timestamp")
        host_id = point.get("host_id")
        value = point.get("value")

        def result(status, score, evidence):
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": status,
                "score": score,
                "evidence": evidence,
            }

        if self.baseline is None or self.scale is None:
            return result("invalid_input", None, {})

        if value is None:
            return result("missing_input", None, {})

        try:
            x = float(value)
        except (TypeError, ValueError, OverflowError):
            return result("invalid_input", None, {})

        if not math.isfinite(x):
            return result("invalid_input", None, {})

        self.smooth = self.alpha * x + (1.0 - self.alpha) * self.smooth
        if point.get("original_present") is True:
            self.count += 1

        if self.count < self.min_history:
            return result("insufficient_history", None, {})

        z = (self.smooth - self.baseline) / self.scale
        if self.direction == "upper":
            score = z
        elif self.direction == "lower":
            score = -z
        else:
            score = abs(z)

        if not math.isfinite(score):
            return result("invalid_input", None, {})

        evidence = {
            "ewma": self.smooth,
            "baseline": self.baseline,
            "scale": self.scale,
        }
        return result("ok", score, evidence)

    def save_state(self):
        state = {
            "config": {
                "alpha": self.alpha,
                "min_history": self.min_history,
                "direction": self.direction,
                "quantile": self.quantile,
            },
            "stats": {
                "baseline": self.baseline,
                "scale": self.scale,
            },
            "runtime": {
                "smooth": self.smooth,
                "count": self.count,
            },
        }
        return json.dumps(state, separators=(",", ":"), allow_nan=False)

    def load_state(self, raw):
        state = json.loads(raw)
        cfg = state["config"]
        stats = state["stats"]
        runtime = state["runtime"]

        self.alpha = float(cfg["alpha"])
        self.min_history = int(cfg["min_history"])
        self.direction = str(cfg["direction"])
        self.quantile = float(cfg["quantile"])
        self.baseline = None if stats["baseline"] is None else float(stats["baseline"])
        self.scale = None if stats["scale"] is None else float(stats["scale"])
        self.smooth = None if runtime["smooth"] is None else float(runtime["smooth"])
        self.count = int(runtime["count"])
        return None


def create_detector(config: dict):
    return EwmaDetector(config)
