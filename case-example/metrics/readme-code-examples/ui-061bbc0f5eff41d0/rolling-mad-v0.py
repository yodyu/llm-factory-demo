import json
import math


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _quantile(values, q):
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return float(ordered[mid])
    return (float(ordered[mid - 1]) + float(ordered[mid])) / 2.0


class Detector:
    def __init__(self, config):
        self.config = dict(config)
        self.window = int(self.config.get("window", 30))
        self.min_history = int(self.config.get("min_history", 15))
        self.direction = self.config.get("direction", "upper")
        self.quantile = float(self.config.get("quantile", 0.99))
        if self.window < 1 or self.window > 600:
            raise ValueError("window must be in [1, 600]")
        if self.min_history < 1 or self.min_history > 600 or self.min_history > self.window:
            raise ValueError("min_history must be in [1, window]")
        if self.direction not in ("upper", "lower", "two_sided"):
            raise ValueError("invalid direction")
        if not (0.0 < self.quantile < 1.0):
            raise ValueError("quantile must be in (0, 1)")
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
        elif self.scale_floor is None:
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
                history_values = [slot[0] for slot in self.history if slot[0] is not None]
                if not history_values:
                    status = "insufficient_history"
                    score = None
                    evidence = {}
                else:
                    center = _median(history_values)
                    mad = _median([abs(v - center) for v in history_values])
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
                        "median": center,
                        "mad": mad,
                        "scale": scale
                    }

        usable_value = None if value is None or not _finite_number(value) else float(value)
        self.history.append([usable_value, original_present])
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
            "config": self.config,
            "scale_floor": self.scale_floor,
            "history": self.history
        }, separators=(",", ":"), allow_nan=False)

    def load_state(self, raw):
        state = json.loads(raw)
        loaded = Detector(state.get("config", {}))
        floor = state.get("scale_floor")
        if floor is not None and not _finite_number(floor):
            raise ValueError("invalid scale_floor")
        loaded.scale_floor = None if floor is None else float(floor)
        history = state.get("history", [])
        normalized = []
        for slot in history:
            value, original_present = slot[0], bool(slot[1])
            if value is not None:
                if not _finite_number(value):
                    raise ValueError("invalid history value")
                value = float(value)
            normalized.append([value, original_present])
        loaded.history = normalized[-loaded.window:]
        self.config = loaded.config
        self.window = loaded.window
        self.min_history = loaded.min_history
        self.direction = loaded.direction
        self.quantile = loaded.quantile
        self.scale_floor = loaded.scale_floor
        self.history = loaded.history


def create_detector(config: dict):
    return Detector(config)
