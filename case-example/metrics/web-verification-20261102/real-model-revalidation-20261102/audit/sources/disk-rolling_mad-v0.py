import json
import math
from statistics import median


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _quantile(values, q):
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


class Detector:
    def __init__(self, config):
        cfg = dict(config or {})
        self.window = int(cfg.get("window", 30))
        self.min_history = int(cfg.get("min_history", 15))
        self.direction = cfg.get("direction", "upper")
        self.quantile = float(cfg.get("quantile", 0.99))

        if self.window < 1 or self.window > 600:
            raise ValueError("window must be between 1 and 600")
        if self.min_history < 1 or self.min_history > 600:
            raise ValueError("min_history must be between 1 and 600")
        if self.min_history > self.window:
            raise ValueError("min_history must not exceed window")
        if self.direction not in ("upper", "lower", "two_sided"):
            raise ValueError("invalid direction")
        if not 0.0 < self.quantile < 1.0:
            raise ValueError("quantile must be between 0 and 1")

        self.scale_floor = None
        self.history = []

    def fit(self, train_points):
        values = []
        for point in train_points or []:
            value = point.get("value")
            if value is not None and _finite_number(value):
                values.append(float(value))
        if not values:
            raise ValueError("no valid training observations")
        iqr = _quantile(values, 0.75) - _quantile(values, 0.25)
        self.scale_floor = max(1e-9, iqr * 1e-6)
        self.reset()

    def reset(self):
        self.history = []

    def score_one(self, point):
        timestamp = point.get("timestamp")
        host_id = point.get("host_id")
        value = point.get("value")
        original_present = bool(point.get("original_present", False))

        if value is None:
            status = "missing_input"
            score = None
            evidence = {}
        elif not _finite_number(value):
            status = "invalid_input"
            score = None
            evidence = {}
        else:
            x = float(value)
            real_count = sum(1 for slot in self.history if slot[1])
            if real_count < self.min_history:
                status = "insufficient_history"
                score = None
                evidence = {}
            else:
                values = [slot[0] for slot in self.history if slot[0] is not None]
                if not values:
                    status = "insufficient_history"
                    score = None
                    evidence = {}
                else:
                    center = median(values)
                    mad = median([abs(v - center) for v in values])
                    scale = max(1.4826 * mad, self.scale_floor)
                    delta = x - center
                    if self.direction == "lower":
                        score = (center - x) / scale
                    elif self.direction == "two_sided":
                        score = abs(delta) / scale
                    else:
                        score = delta / scale
                    status = "ok"
                    evidence = {
                        "median": float(center),
                        "mad": float(mad),
                        "scale": float(scale)
                    }

        slot_value = None if value is None or not _finite_number(value) else float(value)
        self.history.append((slot_value, original_present))
        if len(self.history) > self.window:
            self.history = self.history[-self.window:]

        return {
            "timestamp": timestamp,
            "host_id": host_id,
            "status": status,
            "score": score,
            "evidence": evidence
        }

    def save_state(self):
        return json.dumps({
            "config": {
                "window": self.window,
                "min_history": self.min_history,
                "direction": self.direction,
                "quantile": self.quantile
            },
            "scale_floor": self.scale_floor,
            "history": [[v, p] for v, p in self.history]
        }, separators=(",", ":"), allow_nan=False)

    def load_state(self, raw):
        state = json.loads(raw)
        cfg = state.get("config", {})
        self.window = int(cfg["window"])
        self.min_history = int(cfg["min_history"])
        self.direction = cfg["direction"]
        self.quantile = float(cfg["quantile"])
        scale_floor = state.get("scale_floor")
        self.scale_floor = None if scale_floor is None else float(scale_floor)
        self.history = []
        for slot in state.get("history", []):
            value, present = slot
            self.history.append((None if value is None else float(value), bool(present)))
        self.history = self.history[-self.window:]


def create_detector(config):
    return Detector(config)
