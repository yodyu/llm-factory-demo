import json
import math


class EWMADetector:
    def __init__(self, config):
        cfg = dict(config or {})
        self.alpha = float(cfg.get("alpha", 0.3))
        self.min_history = int(cfg.get("min_history", 3))
        self.direction = cfg.get("direction", "upper")
        self.quantile = float(cfg.get("quantile", 0.99))
        self.method_id = cfg.get("method_id", "ewma")

        if not math.isfinite(self.alpha) or not (0.0 < self.alpha <= 1.0):
            raise ValueError("alpha must be finite and in (0, 1]")
        if not isinstance(self.min_history, int) or not (1 <= self.min_history <= 600):
            raise ValueError("min_history must be an integer in [1, 600]")
        if self.direction not in ("upper", "lower", "two_sided"):
            raise ValueError("direction must be upper, lower, or two_sided")
        if not math.isfinite(self.quantile) or not (0.0 < self.quantile < 1.0):
            raise ValueError("quantile must be finite and in (0, 1)")

        self.baseline = None
        self.scale = None
        self.smooth = None
        self.count = 0
        self.fitted = False

    def _config_dict(self):
        return {
            "method_id": self.method_id,
            "alpha": self.alpha,
            "min_history": self.min_history,
            "direction": self.direction,
            "quantile": self.quantile,
        }

    def fit(self, train_points):
        values = []
        for point in train_points or []:
            value = point.get("value") if isinstance(point, dict) else None
            if value is None:
                continue
            value = float(value)
            if math.isfinite(value):
                values.append(value)

        if not values:
            raise ValueError("at least one finite training value is required")

        n = len(values)
        baseline = sum(values) / n
        variance = sum((x - baseline) * (x - baseline) for x in values) / n
        scale = max(1e-9, math.sqrt(max(0.0, variance)))

        self.baseline = baseline
        self.scale = scale
        self.fitted = True
        self.reset()

    def reset(self):
        if not self.fitted:
            self.smooth = None
            self.count = 0
            return
        self.smooth = self.baseline
        self.count = 0

    @staticmethod
    def _is_real_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))

    def score_one(self, point):
        timestamp = point.get("timestamp")
        host_id = point.get("host_id")
        value = point.get("value")
        original_present = bool(point.get("original_present", False))

        def result(status, score, evidence):
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": status,
                "score": score,
                "evidence": evidence,
            }

        if not self.fitted or self.baseline is None or self.scale is None:
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

        if original_present:
            self.count += 1

        if self.count < self.min_history:
            return result("insufficient_history", None, {})

        standardized = (self.smooth - self.baseline) / self.scale
        if self.direction == "lower":
            score = -standardized
        elif self.direction == "two_sided":
            score = abs(standardized)
        else:
            score = standardized

        return result(
            "ok",
            float(score),
            {
                "ewma": float(self.smooth),
                "baseline": float(self.baseline),
                "scale": float(self.scale),
            },
        )

    def save_state(self):
        return json.dumps(
            {
                "config": self._config_dict(),
                "fitted": self.fitted,
                "baseline": self.baseline,
                "scale": self.scale,
                "smooth": self.smooth,
                "count": self.count,
            },
            separators=(",", ":"),
            allow_nan=False,
            sort_keys=True,
        )

    def load_state(self, raw):
        state = json.loads(raw)
        cfg = state.get("config", {})
        self.__init__(cfg)
        self.fitted = bool(state.get("fitted", False))
        self.baseline = state.get("baseline")
        self.scale = state.get("scale")
        self.smooth = state.get("smooth")
        self.count = int(state.get("count", 0))

        if self.fitted:
            if not self._is_real_number(self.baseline) or not self._is_real_number(self.scale):
                raise ValueError("invalid fitted statistics")
            self.baseline = float(self.baseline)
            self.scale = float(self.scale)
            if self.smooth is None or not self._is_real_number(self.smooth):
                raise ValueError("invalid smooth state")
            self.smooth = float(self.smooth)
            if self.count < 0:
                raise ValueError("invalid count")
        return self


def create_detector(config):
    return EWMADetector(config)
