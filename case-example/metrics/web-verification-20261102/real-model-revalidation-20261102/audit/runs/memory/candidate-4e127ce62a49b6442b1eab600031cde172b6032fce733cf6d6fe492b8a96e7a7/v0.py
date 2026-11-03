import json
import math
from statistics import median


def _quantile(values, q):
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


class Detector:
    def __init__(self, config):
        self.config = {
            "window": 30,
            "min_history": 15,
            "direction": "upper",
            "quantile": 0.99,
        }
        if config:
            self.config.update(config)

        if not isinstance(self.config["window"], int) or isinstance(self.config["window"], bool):
            raise ValueError("window must be an integer")
        if not isinstance(self.config["min_history"], int) or isinstance(self.config["min_history"], bool):
            raise ValueError("min_history must be an integer")
        if not (1 <= self.config["window"] <= 600):
            raise ValueError("window must be in [1, 600]")
        if not (1 <= self.config["min_history"] <= 600):
            raise ValueError("min_history must be in [1, 600]")
        if self.config["min_history"] > self.config["window"]:
            raise ValueError("min_history must not exceed window")
        if self.config["direction"] not in ("upper", "lower", "two_sided"):
            raise ValueError("invalid direction")
        if not _finite_number(self.config["quantile"]) or not (0.0 < float(self.config["quantile"]) < 1.0):
            raise ValueError("quantile must be in (0, 1)")

        self.config["quantile"] = float(self.config["quantile"])
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

        if self.scale_floor is None:
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "invalid_input",
                "score": None,
                "evidence": {},
            }

        if value is None:
            status = "missing_input"
            score = None
            evidence = {}
            usable = False
            numeric_value = None
        elif not _finite_number(value):
            status = "invalid_input"
            score = None
            evidence = {}
            usable = False
            numeric_value = None
        else:
            numeric_value = float(value)
            true_history = sum(1 for slot in self.history if slot[1] is True)
            if true_history < self.config["min_history"]:
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
                    center = median(history_values)
                    mad = median(abs(v - center) for v in history_values)
                    scale = max(1.4826 * mad, self.scale_floor)
                    delta = numeric_value - center
                    if self.config["direction"] == "lower":
                        delta = -delta
                    elif self.config["direction"] == "two_sided":
                        delta = abs(delta)
                    score = delta / scale
                    status = "ok"
                    evidence = {
                        "median": float(center),
                        "mad": float(mad),
                        "scale": float(scale),
                    }
            usable = True

        if usable or value is None:
            self.history.append([numeric_value, point.get("original_present") is True])
            self.history = self.history[-self.config["window"]:]

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
            "scale_floor": self.scale_floor,
            "history": self.history,
        }, separators=(",", ":"), allow_nan=False)

    def load_state(self, raw):
        state = json.loads(raw)
        config = state["config"]
        self.config = {
            "window": int(config["window"]),
            "min_history": int(config["min_history"]),
            "direction": config["direction"],
            "quantile": float(config["quantile"]),
        }
        self.scale_floor = float(state["scale_floor"])
        self.history = [
            [None if slot[0] is None else float(slot[0]), bool(slot[1])]
            for slot in state["history"]
        ][-self.config["window"]:]


def create_detector(config: dict):
    return Detector(config)
