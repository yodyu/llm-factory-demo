"""Constructed human reference (origin=reference), not generated model code.

Use previous W time slots. Only original observations count for min_history;
forward-filled values may affect median/MAD. Update history AFTER scoring.
The training R7 IQR sets the numerical floor; no labels are used.
"""
import json
from statistics import median


def quantile(values, q):
    values = sorted(values)
    pos = (len(values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


class Detector:
    def __init__(self, config):
        self.config = dict(config)
        self.floor = None
        self.history = []

    def fit(self, train_points):
        values = [p["value"] for p in train_points if p["value"] is not None]
        if not values:
            raise ValueError("no valid training observations")
        self.floor = max(1e-9, (quantile(values, 0.75) - quantile(values, 0.25)) * 1e-6)
        self.reset()

    def reset(self):
        self.history = []

    def score_one(self, point):
        if self.floor is None:
            raise ValueError("fit required")
        value, evidence = point["value"], {}
        score, status = None, "ok"
        if value is None:
            status = "missing_input"
        elif sum(slot[1] for slot in self.history) < self.config["min_history"]:
            status = "insufficient_history"
        else:
            values = [slot[0] for slot in self.history if slot[0] is not None]
            center = median(values)
            mad = median([abs(x - center) for x in values])
            scale = max(1.4826 * mad, self.floor)
            delta = value - center
            if self.config["direction"] == "lower":
                delta = -delta
            elif self.config["direction"] == "two_sided":
                delta = abs(delta)
            score = delta / scale
            evidence = {"median": center, "mad": mad, "scale": scale}
        self.history.append([value, point["original_present"]])
        self.history = self.history[-self.config["window"]:]
        return {"timestamp": point["timestamp"], "host_id": point["host_id"],
                "status": status, "score": score, "evidence": evidence}

    def save_state(self):
        return json.dumps({"config": self.config, "floor": self.floor, "history": self.history}, allow_nan=False)

    def load_state(self, raw):
        state = json.loads(raw)
        if state["config"] != self.config or len(state["history"]) > self.config["window"]:
            raise ValueError("state config/history mismatch")
        self.floor, self.history = state["floor"], state["history"]


def create_detector(config):
    return Detector(config)
