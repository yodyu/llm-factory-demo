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
        self.config = dict(config or {})
        self.window = int(self.config.get("window", 30))
        self.min_history = int(self.config.get("min_history", 15))
        self.direction = self.config.get("direction", "upper")
        self.quantile = float(self.config.get("quantile", 0.99))
        if self.window < 1 or self.window > 600:
            raise ValueError("window out of range")
        if self.min_history < 1 or self.min_history > 600 or self.min_history > self.window:
            raise ValueError("min_history out of range")
        if self.direction not in ("upper", "lower", "two_sided"):
            raise ValueError("invalid direction")
        if not (0.0 < self.quantile < 1.0):
            raise ValueError("invalid quantile")
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
        q75 = _quantile(values, 0.75)
        q25 = _quantile(values, 0.25)
        self.scale_floor = max(1e-9, (q75 - q25) * 1e-6)
        self.reset()

    def reset(self):
        self.history = []

    def score_one(self, point):
        timestamp = point.get("timestamp")
        host_id = point.get("host_id")
        value = point.get("value")
        original_present = bool(point.get("original_present", False))

        if self.scale_floor is None:
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "invalid_input",
                "score": None,
                "evidence": {},
            }

        status = "ok"
        score = None
        evidence = {}

        if value is None:
            status = "missing_input"
        elif not _finite_number(value):
            status = "invalid_input"
        else:
            x = float(value)
            real_count = sum(1 for slot in self.history if slot[1])
            if real_count < self.min_history:
                status = "insufficient_history"
            else:
                values = [slot[0] for slot in self.history if slot[0] is not None]
                if not values:
                    status = "insufficient_history"
                else:
                    center = float(median(values))
                    mad_value = float(median([abs(v - center) for v in values]))
                    scale = max(1.4826 * mad_value, self.scale_floor)
                    delta = x - center
                    if self.direction == "lower":
                        score = (center - x) / scale
                    elif self.direction == "two_sided":
                        score = abs(delta) / scale
                    else:
                        score = delta / scale
                    evidence = {
                        "median": center,
                        "mad": mad_value,
                        "scale": scale,
                    }

        stored_value = None if value is None else float(value) if _finite_number(value) else None
        self.history.append([stored_value, original_present])
        if len(self.history) > self.window:
            self.history = self.history[-self.window:]

        return {
            "timestamp": timestamp,
            "host_id": host_id,
            "status": status,
            "score": score,
            "evidence": evidence,
        }

    def save_state(self):
        return json.dumps({
            "config": self.config,
            "window": self.window,
            "min_history": self.min_history,
            "direction": self.direction,
            "quantile": self.quantile,
            "scale_floor": self.scale_floor,
            "history": self.history,
        }, separators=(",", ":"), allow_nan=False)

    def load_state(self, raw):
        state = json.loads(raw)
        self.config = state["config"]
        self.window = int(state["window"])
        self.min_history = int(state["min_history"])
        self.direction = state["direction"]
        self.quantile = float(state["quantile"])
        self.scale_floor = None if state["scale_floor"] is None else float(state["scale_floor"])
        self.history = []
        for value, original_present in state["history"]:
            self.history.append([None if value is None else float(value), bool(original_present)])


def create_detector(config: dict):
    return Detector(config)
