import json
import math


def _quantile(values, q):
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _median(values):
    return _quantile(values, 0.5)


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


class Detector:
    def __init__(self, config):
        self.window = int(config.get("window", 30))
        self.min_history = int(config.get("min_history", 15))
        self.direction = config.get("direction", "upper")
        self.quantile = float(config.get("quantile", 0.99))
        if self.window < 1 or self.window > 600:
            raise ValueError("window out of range")
        if self.min_history < 1 or self.min_history > self.window:
            raise ValueError("min_history out of range")
        if self.direction not in ("upper", "lower", "two_sided"):
            raise ValueError("invalid direction")
        if not (0.0 < self.quantile <= 1.0):
            raise ValueError("invalid quantile")
        self.scale_floor = 1e-9
        self.history = []

    def fit(self, train_points):
        values = []
        for point in train_points:
            value = point.get("value") if isinstance(point, dict) else None
            if _finite_number(value):
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

        status = "ok"
        score = None
        evidence = {}

        if value is None:
            status = "missing_input"
        elif not _finite_number(value):
            status = "invalid_input"
        elif sum(1 for slot in self.history if slot[1]) < self.min_history:
            status = "insufficient_history"
        else:
            values = [slot[0] for slot in self.history if slot[0] is not None]
            if not values:
                status = "insufficient_history"
            else:
                center = _median(values)
                mad = _median([abs(x - center) for x in values])
                scale = max(1.4826 * mad, self.scale_floor)
                numeric_value = float(value)
                if self.direction == "upper":
                    score = (numeric_value - center) / scale
                elif self.direction == "lower":
                    score = (center - numeric_value) / scale
                else:
                    score = abs(numeric_value - center) / scale
                evidence = {"median": center, "mad": mad, "scale": scale}

        stored_value = None if value is None else float(value)
        self.history.append((stored_value, original_present))
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
            "window": self.window,
            "min_history": self.min_history,
            "direction": self.direction,
            "quantile": self.quantile,
            "scale_floor": self.scale_floor,
            "history": [[value, original] for value, original in self.history],
        }, separators=(",", ":"), allow_nan=False)

    def load_state(self, raw):
        state = json.loads(raw)
        self.window = int(state["window"])
        self.min_history = int(state["min_history"])
        self.direction = state["direction"]
        self.quantile = float(state["quantile"])
        self.scale_floor = float(state["scale_floor"])
        self.history = [(None if slot[0] is None else float(slot[0]), bool(slot[1])) for slot in state["history"]][-self.window:]


def create_detector(config):
    return Detector(config)
