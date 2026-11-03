import json
import math


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _quantile(values, q):
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def _median(values):
    return _quantile(values, 0.5)


class RollingMadDetector:
    def __init__(self, config):
        method_id = config.get("method_id", "rolling_mad")
        if method_id != "rolling_mad":
            raise ValueError("method_id must be rolling_mad")
        direction = config.get("direction", "upper")
        if direction not in ("upper", "lower", "two_sided"):
            raise ValueError("invalid direction")
        window = config.get("window", 30)
        min_history = config.get("min_history", 15)
        quantile = config.get("quantile", 0.99)
        if not isinstance(window, int) or isinstance(window, bool) or not (1 <= window <= 600):
            raise ValueError("window must be an integer in [1, 600]")
        if not isinstance(min_history, int) or isinstance(min_history, bool) or not (1 <= min_history <= 600):
            raise ValueError("min_history must be an integer in [1, 600]")
        if min_history > window:
            raise ValueError("min_history must not exceed window")
        if not _finite_number(quantile) or not (0.0 < float(quantile) < 1.0):
            raise ValueError("quantile must be in (0, 1)")
        self.config = {
            "method_id": "rolling_mad",
            "window": window,
            "min_history": min_history,
            "direction": direction,
            "quantile": float(quantile),
        }
        self.scale_floor = None
        self.history = []

    def fit(self, train_points):
        values = []
        for point in train_points:
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
            real_count = sum(1 for slot in self.history if slot[1] is True)
            if real_count < self.config["min_history"]:
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
                    if self.config["direction"] == "lower":
                        directed = -delta
                    elif self.config["direction"] == "two_sided":
                        directed = abs(delta)
                    else:
                        directed = delta
                    score = directed / scale
                    status = "ok"
                    evidence = {
                        "median": center,
                        "mad": mad,
                        "scale": scale,
                    }

        original_present = bool(point.get("original_present", value is not None))
        if value is None or not _finite_number(value):
            slot_value = None
        else:
            slot_value = float(value)
        self.history.append((slot_value, original_present))
        if len(self.history) > self.config["window"]:
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
            "history": [[slot[0], slot[1]] for slot in self.history],
        }, separators=(",", ":"), allow_nan=False)

    def load_state(self, raw):
        state = json.loads(raw)
        config = state["config"]
        detector = RollingMadDetector(config)
        self.config = detector.config
        floor = state.get("scale_floor")
        if floor is None or not _finite_number(floor) or float(floor) <= 0.0:
            raise ValueError("invalid scale_floor")
        self.scale_floor = float(floor)
        history = []
        for value, original_present in state.get("history", []):
            if value is not None:
                if not _finite_number(value):
                    raise ValueError("invalid history value")
                value = float(value)
            history.append((value, bool(original_present)))
        if len(history) > self.config["window"]:
            raise ValueError("history exceeds window")
        self.history = history


def create_detector(config: dict):
    return RollingMadDetector(config)
