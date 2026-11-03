import json
import math


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


class Detector:
    def __init__(self, config):
        self.config = dict(config)
        self.alpha = float(self.config.get("alpha", 0.3))
        self.min_history = int(self.config.get("min_history", 3))
        self.direction = self.config.get("direction", "upper")
        self.quantile = float(self.config.get("quantile", 0.99))
        self.baseline = None
        self.scale = None
        self.smooth = None
        self.count = 0
        self._validate_params()

    def _validate_params(self):
        if not (0.0 < self.alpha <= 1.0):
            raise ValueError("alpha must be in (0, 1]")
        if not (1 <= self.min_history <= 600):
            raise ValueError("min_history must be between 1 and 600")
        if self.direction not in ("upper", "lower", "two_sided"):
            raise ValueError("unsupported direction")
        if not (0.0 < self.quantile <= 1.0):
            raise ValueError("quantile must be in (0, 1]")

    def fit(self, train_points):
        values = []
        for point in train_points:
            value = point.get("value")
            if value is not None and _finite_number(value):
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

        if not _finite_number(value):
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "invalid_input",
                "score": None,
                "evidence": {},
            }

        x = float(value)
        self.smooth = self.alpha * x + (1.0 - self.alpha) * self.smooth
        if bool(point.get("original_present", False)):
            self.count += 1

        if self.count < self.min_history:
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "insufficient_history",
                "score": None,
                "evidence": {},
            }

        signed_score = (self.smooth - self.baseline) / self.scale
        if self.direction == "lower":
            score = -signed_score
        elif self.direction == "two_sided":
            score = abs(signed_score)
        else:
            score = signed_score

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
            sort_keys=True,
            allow_nan=False,
        )

    def load_state(self, raw):
        state = json.loads(raw)
        self.config = dict(state["config"])
        self.alpha = float(self.config.get("alpha", 0.3))
        self.min_history = int(self.config.get("min_history", 3))
        self.direction = self.config.get("direction", "upper")
        self.quantile = float(self.config.get("quantile", 0.99))
        self._validate_params()
        self.baseline = float(state["baseline"])
        self.scale = float(state["scale"])
        self.smooth = float(state["smooth"])
        self.count = int(state["count"])
        if not all(math.isfinite(v) for v in (self.baseline, self.scale, self.smooth)):
            raise ValueError("invalid restored state")
        if self.count < 0:
            raise ValueError("invalid restored count")


def create_detector(config: dict):
    return Detector(config)
