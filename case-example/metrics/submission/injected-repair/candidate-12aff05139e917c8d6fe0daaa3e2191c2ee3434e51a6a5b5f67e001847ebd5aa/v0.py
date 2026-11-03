"""Constructed human reference (origin=reference), never an LLM-generated result.

Upper score=x-T, lower score=T-x. Equality is not an alert. The trusted driver
owns preprocessing, persistence and labels; the detector only emits scores.
"""
import json


class Detector:
    def __init__(self, config):
        self.config = dict(config)

    def fit(self, train_points):
        if not any(point["value"] is not None for point in train_points):
            raise ValueError("no valid training observations")
        self.reset()

    def reset(self):
        pass

    def score_one(self, point):
        value = point["value"]
        delta = None if value is None else value - self.config["threshold"]
        if delta is not None and self.config["direction"] == "lower":
            delta = -delta
        return {"timestamp": point["timestamp"], "host_id": point["host_id"],
                "status": "missing_input" if value is None else "ok", "score": delta,
                "evidence": {"threshold": self.config["threshold"]}}

    def save_state(self):
        return json.dumps({"config": self.config}, allow_nan=False)

    def load_state(self, raw):
        if json.loads(raw) != {"config": self.config}:
            raise ValueError("state config mismatch")


def create_detector(config):
    return Detector(config)

# Deliberate test-only fault injection: do not count as a natural model failure.
_fault_original_factory = create_detector
def create_detector(config):
    original = _fault_original_factory(config)
    class FaultProxy:
        def fit(self, points): return original.fit(points)
        def reset(self): return original.reset()
        def save_state(self): return original.save_state()
        def load_state(self, raw): return original.load_state(raw)
        def score_one(self, point):
            result = original.score_one(point)
            if result['status'] == 'ok': result['score'] += 1.0
            return result
    return FaultProxy()
