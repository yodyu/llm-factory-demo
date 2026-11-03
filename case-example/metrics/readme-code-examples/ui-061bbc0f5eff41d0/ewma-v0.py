import json
import math


class EWMADetector:
    def __init__(self, config=None):
        supplied = dict(config or {})
        self.config = {
            "alpha": 0.2,
            "min_history": 3,
            "direction": "upper",
            "quantile": 0.99,
        }
        self.config.update(supplied)

        alpha = self.config.get("alpha")
        min_history = self.config.get("min_history")
        direction = self.config.get("direction")
        quantile = self.config.get("quantile")

        if not isinstance(alpha, (int, float)) or isinstance(alpha, bool):
            raise ValueError("alpha must be a finite number in (0, 1]")
        alpha = float(alpha)
        if not math.isfinite(alpha) or alpha <= 0.0 or alpha > 1.0:
            raise ValueError("alpha must be a finite number in (0, 1]")

        if not isinstance(min_history, int) or isinstance(min_history, bool):
            raise ValueError("min_history must be an integer in [1, 600]")
        if min_history < 1 or min_history > 600:
            raise ValueError("min_history must be an integer in [1, 600]")

        if direction not in ("upper", "lower", "two_sided"):
            raise ValueError("direction must be upper, lower, or two_sided")

        if not isinstance(quantile, (int, float)) or isinstance(quantile, bool):
            raise ValueError("quantile must be a finite number in (0, 1)")
        quantile = float(quantile)
        if not math.isfinite(quantile) or quantile <= 0.0 or quantile >= 1.0:
            raise ValueError("quantile must be a finite number in (0, 1)")

        self.config["alpha"] = alpha
        self.config["quantile"] = quantile

        self.baseline = None
        self.scale = None
        self.smooth = None
        self.count = 0
        self.fitted = False

    @staticmethod
    def _finite_number(value):
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )

    def fit(self, train_points):
        if not isinstance(train_points, (list, tuple)):
            raise ValueError("train_points must be a list")

        values = []
        for point in train_points:
            if not isinstance(point, dict):
                continue
            value = point.get("value")
            if value is None:
                continue
            if not self._finite_number(value):
                raise ValueError("training values must be finite numbers or null")
            values.append(float(value))

        if not values:
            raise ValueError("at least one valid training observation is required")

        n = len(values)
        baseline = sum(values) / n
        variance = sum((x - baseline) * (x - baseline) for x in values) / n
        self.baseline = baseline
        self.scale = max(1e-9, math.sqrt(variance))
        self.fitted = True
        self.reset()
        return None

    def reset(self):
        if not self.fitted:
            self.smooth = None
            self.count = 0
            return None
        self.smooth = self.baseline
        self.count = 0
        return None

    def score_one(self, point):
        if not isinstance(point, dict):
            raise ValueError("point must be a dictionary")

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

        if not self.fitted:
            return result("invalid_input", None, {})

        if value is None:
            return result("missing_input", None, {})

        if not self._finite_number(value):
            return result("invalid_input", None, {})

        x = float(value)
        alpha = float(self.config["alpha"])
        self.smooth = alpha * x + (1.0 - alpha) * self.smooth

        if point.get("original_present", True) is True:
            self.count += 1

        if self.count < int(self.config["min_history"]):
            return result("insufficient_history", None, {})

        normalized = (self.smooth - self.baseline) / self.scale
        direction = self.config["direction"]
        if direction == "upper":
            score = normalized
        elif direction == "lower":
            score = -normalized
        else:
            score = abs(normalized)

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
            "config": self.config,
            "fitted": self.fitted,
            "baseline": self.baseline,
            "scale": self.scale,
            "smooth": self.smooth,
            "count": self.count,
        }
        return json.dumps(state, separators=(",", ":"), allow_nan=False)

    def load_state(self, raw):
        state = json.loads(raw)
        if not isinstance(state, dict):
            raise ValueError("saved state must be a JSON object")

        config = state.get("config")
        if not isinstance(config, dict):
            raise ValueError("saved config must be an object")

        detector = EWMADetector(config)
        self.config = detector.config

        fitted = bool(state.get("fitted", False))
        self.fitted = fitted
        self.baseline = state.get("baseline")
        self.scale = state.get("scale")
        self.smooth = state.get("smooth")
        count = state.get("count", 0)

        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("saved count must be a nonnegative integer")
        self.count = count

        if fitted:
            for name in ("baseline", "scale", "smooth"):
                number = getattr(self, name)
                if not self._finite_number(number):
                    raise ValueError("saved statistics must be finite numbers")
                setattr(self, name, float(number))
            if self.scale < 1e-9:
                raise ValueError("saved scale is invalid")
        else:
            self.baseline = None
            self.scale = None
            self.smooth = None
            self.count = 0

        return None


def create_detector(config: dict):
    return EWMADetector(config)
