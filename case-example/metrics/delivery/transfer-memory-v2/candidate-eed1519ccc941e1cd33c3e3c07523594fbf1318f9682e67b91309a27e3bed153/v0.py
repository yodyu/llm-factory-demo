import json
import math
from statistics import median


class RollingMadDetector:
    def __init__(self, config):
        self.config = dict(config or {})
        self.window = int(self.config.get("window", 30))
        self.min_history = int(self.config.get("min_history", 15))
        if self.window <= 0:
            raise ValueError("window must be positive")
        if self.min_history <= 0 or self.min_history > self.window:
            raise ValueError("min_history must be in (0, window]")
        self.scale_floor = 1e-9
        self._slots = []
        self._real_count = 0

    @staticmethod
    def _finite_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))

    @staticmethod
    def _quantile(values, q):
        data = sorted(float(v) for v in values)
        n = len(data)
        if n == 1:
            return data[0]
        pos = (n - 1) * q
        lo = int(math.floor(pos))
        hi = int(math.ceil(pos))
        if lo == hi:
            return data[lo]
        return data[lo] * (hi - pos) + data[hi] * (pos - lo)

    def fit(self, train_points):
        valid = []
        for point in train_points or []:
            value = point.get("value") if isinstance(point, dict) else None
            if self._finite_number(value):
                valid.append(float(value))
        if not valid:
            raise ValueError("no valid training observations")
        q1 = self._quantile(valid, 0.25)
        q3 = self._quantile(valid, 0.75)
        iqr = q3 - q1
        if not math.isfinite(iqr) or iqr < 0:
            iqr = 0.0
        self.scale_floor = max(1e-9, iqr * 1e-6)
        self.reset()

    def reset(self):
        self._slots = []
        self._real_count = 0

    def _result(self, point, status, score, evidence):
        return {
            "timestamp": point.get("timestamp"),
            "host_id": point.get("host_id"),
            "status": status,
            "score": score,
            "evidence": evidence,
        }

    def score_one(self, point):
        raw_value = point.get("value")
        original_present = bool(point.get("original_present", False))

        if raw_value is None:
            scored = self._result(point, "missing_input", None, {})
            self._append(None, False)
            return scored

        if not self._finite_number(raw_value):
            scored = self._result(point, "invalid_input", None, {})
            self._append(None, False)
            return scored

        value = float(raw_value)

        if self._real_count < self.min_history:
            scored = self._result(point, "insufficient_history", None, {})
            self._append(value, original_present)
            return scored

        history = [slot_value for _, slot_value, _ in self._slots if slot_value is not None]
        med = float(median(history))
        mad = float(median(abs(v - med) for v in history))
        scale = max(1.4826 * mad, self.scale_floor)
        score = (value - med) / scale

        evidence = {
            "median": med,
            "mad": mad,
            "scale": scale,
        }
        scored = self._result(point, "ok", float(score), evidence)
        self._append(value, original_present)
        return scored

    def _append(self, value, original_present):
        self._slots.append((None, value, bool(original_present)))
        if value is not None and original_present:
            self._real_count += 1
        while len(self._slots) > self.window:
            _, old_value, old_original = self._slots.pop(0)
            if old_value is not None and old_original:
                self._real_count -= 1

    def save_state(self):
        state = {
            "window": self.window,
            "min_history": self.min_history,
            "scale_floor": self.scale_floor,
            "slots": [self._slot_to_json(slot) for slot in self._slots],
            "real_count": self._real_count,
        }
        return json.dumps(state, allow_nan=False, separators=(",", ":"))

    @staticmethod
    def _slot_to_json(slot):
        _, value, original_present = slot
        return {"v": value, "r": bool(original_present)}

    def load_state(self, raw):
        state = json.loads(raw)
        window = int(state["window"])
        min_history = int(state["min_history"])
        if window != self.window or min_history != self.min_history:
            raise ValueError("state config mismatch")
        scale_floor = float(state["scale_floor"])
        if not math.isfinite(scale_floor) or scale_floor < 1e-9:
            raise ValueError("invalid scale floor")

        slots = []
        real_count = 0
        raw_slots = state.get("slots", [])
        if not isinstance(raw_slots, list) or len(raw_slots) > self.window:
            raise ValueError("invalid slots")
        for item in raw_slots:
            if not isinstance(item, dict):
                raise ValueError("invalid slot")
            value = item.get("v")
            original_present = bool(item.get("r", False))
            if value is not None:
                if not self._finite_number(value):
                    raise ValueError("invalid slot value")
                value = float(value)
                if original_present:
                    real_count += 1
            slots.append((None, value, original_present))

        if int(state.get("real_count", -1)) != real_count:
            raise ValueError("real count mismatch")
        self.scale_floor = scale_floor
        self._slots = slots
        self._real_count = real_count


def create_detector(config):
    return RollingMadDetector(config)
