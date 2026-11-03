import json
import math


class FixedThresholdDetector:
    def __init__(self, config):
        if not isinstance(config, dict):
            raise ValueError("config must be a dict")
        threshold = config.get("threshold", 85.0)
        direction = config.get("direction", "upper")
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
            raise ValueError("threshold must be a finite number")
        threshold = float(threshold)
        if not math.isfinite(threshold):
            raise ValueError("threshold must be finite")
        if direction not in ("upper", "lower"):
            raise ValueError("direction must be upper or lower")
        self.threshold = threshold
        self.direction = direction
        self._fitted = False

    def fit(self, train_points):
        if not isinstance(train_points, (list, tuple)):
            raise ValueError("train_points must be a list")
        has_valid = False
        for point in train_points:
            value = point.get("value") if isinstance(point, dict) else None
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            value = float(value)
            if math.isfinite(value):
                has_valid = True
                break
        if not has_valid:
            raise ValueError("no valid training observations")
        self._fitted = True
        self.reset()

    def reset(self):
        return None

    def score_one(self, point):
        timestamp = point.get("timestamp") if isinstance(point, dict) else None
        host_id = point.get("host_id") if isinstance(point, dict) else None

        if not self._fitted:
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "insufficient_history",
                "score": None,
                "evidence": {},
            }

        value = point.get("value") if isinstance(point, dict) else None
        if value is None:
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "missing_input",
                "score": None,
                "evidence": {},
            }

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "invalid_input",
                "score": None,
                "evidence": {},
            }

        value = float(value)
        if not math.isfinite(value):
            return {
                "timestamp": timestamp,
                "host_id": host_id,
                "status": "invalid_input",
                "score": None,
                "evidence": {},
            }

        score = value - self.threshold if self.direction == "upper" else self.threshold - value
        return {
            "timestamp": timestamp,
            "host_id": host_id,
            "status": "ok",
            "score": score,
            "evidence": {
                "threshold": self.threshold,
                "direction": self.direction,
            },
        }

    def save_state(self):
        return json.dumps(
            {
                "threshold": self.threshold,
                "direction": self.direction,
                "fitted": self._fitted,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    def load_state(self, raw):
        state = json.loads(raw)
        threshold = float(state["threshold"])
        direction = state["direction"]
        if not math.isfinite(threshold) or direction not in ("upper", "lower"):
            raise ValueError("invalid saved state")
        self.threshold = threshold
        self.direction = direction
        self._fitted = bool(state.get("fitted", False))
        self.reset()


def create_detector(config: dict):
    return FixedThresholdDetector(config)

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
