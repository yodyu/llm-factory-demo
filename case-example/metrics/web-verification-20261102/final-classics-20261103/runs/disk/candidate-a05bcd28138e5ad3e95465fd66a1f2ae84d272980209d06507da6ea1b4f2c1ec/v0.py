import json
import math


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _quantile(values, q):
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


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
        if not (0.0 < self.quantile < 1.0):
            raise ValueError("quantile must be in (0, 1)")

        self.scale_floor = None
        self.history = []

    def fit(self, train_points):
        values = []
        for point in train_points or []:
            value = point.get("value") if isinstance(point, dict) else None
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

        if value is None:
            status = "missing_input"
        elif not _finite_number(value):
            status = "invalid_input"
            value = None
        elif self.scale_floor is None:
            status = "invalid_input"
            value = None
        else:
            value = float(value)
            real_history = 0
            available_history = []
            for slot in self.history[-self.window:]:
                slot_value = slot[0]
                original_present = bool(slot[1])
                if original_present:
                    real_history += 1
                if slot_value is not None and _finite_number(slot_value):
                    available_history.append(float(slot_value))

            if real_history < self.min_history:
                status = "insufficient_history"
            elif not available_history:
                status = "insufficient_history"
            else:
                center = _median(available_history)
                mad = _median([abs(x - center) for x in available_history])
                scale = max(1.4826 * mad, self.scale_floor)
                delta = value - center
                if self.direction == "lower":
                    score_value = (center - value) / scale
                elif self.direction == "two_sided":
                    score_value = abs(delta) / scale
                else:
                    score_value = delta / scale
                result = {
                    "timestamp": timestamp,
                    "host_id": host_id,
                    "status": "ok",
                    "score": score_value,
                    "evidence": {
                        "median": center,
                        "mad": mad,
                        "scale": scale
                    }
                }
                self._append(value, point)
                return result

        self._append(value, point)
        return {
            "timestamp": timestamp,
            "host_id": host_id,
            "status": status,
            "score": None,
            "evidence": {}
        }

    def _append(self, value, point):
        original_present = bool(point.get("original_present", False))
        self.history.append([value, original_present])
        if len(self.history) > self.window:
            self.history = self.history[-self.window:]

    def save_state(self):
        return json.dumps({
            "config": {
                "window": self.window,
                "min_history": self.min_history,
                "direction": self.direction,
                "quantile": self.quantile
            },
            "scale_floor": self.scale_floor,
            "history": self.history
        }, separators=(",", ":"), allow_nan=False)

    def load_state(self, raw):
        state = json.loads(raw)
        config = state.get("config", {})
        self.window = int(config["window"])
        self.min_history = int(config["min_history"])
        self.direction = config["direction"]
        self.quantile = float(config["quantile"])
        self.scale_floor = (None if state.get("scale_floor") is None
                            else float(state["scale_floor"]))
        self.history = []
        for slot in state.get("history", []):
            slot_value = slot[0]
            if slot_value is not None:
                slot_value = float(slot_value)
            self.history.append([slot_value, bool(slot[1])])


def create_detector(config: dict):
    return Detector(config)
