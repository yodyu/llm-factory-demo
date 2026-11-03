"""Trusted reference facade; new capability validation reads plugin reference files."""
from factory.metrics.legacy_reference import (
    ReferenceDetector, DetectorState, HistorySlot, linear_quantile,
)
from contracts.metrics import FixedConfig, MADConfig, Score


__all__ = ["ReferenceDetector", "DetectorState", "HistorySlot", "linear_quantile", "create_detector"]


def create_detector(config):
    if isinstance(config, (FixedConfig, MADConfig)):
        return ReferenceDetector(config)
    from factory.metrics.capability_registry import registry
    detector = registry().module(config.method_id, "reference").create_detector(config.model_dump())
    class Adapter:
        def fit(self, points):
            detector.fit([p.model_dump(mode="json") for p in points])
        def reset(self):
            detector.reset()
        def score_one(self, point):
            return Score.model_validate(detector.score_one(point.model_dump(mode="json")))
        def save_state(self):
            return detector.save_state()
        def load_state(self, raw):
            return detector.load_state(raw)
    return Adapter()
