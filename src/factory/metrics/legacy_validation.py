# Compatibility validator for frozen metrics-method-check/2 only.
"""Method-specific development checks; never inspect final observations or labels."""

import math
from datetime import datetime, timedelta, timezone

from contracts import FactoryError
from contracts.metrics import FixedConfig, MADConfig, MetricPoint
from execution.metrics_runner import CandidateFailure, check_source, DEPENDENCY_PROFILE
from factory.metrics.data import CausalPreprocessor
from factory.metrics.reference import create_detector
from factory.runtime.artifacts import digest


def _points(values):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [MetricPoint(timestamp=start + timedelta(minutes=index), host_id="validation-host", value=value)
            for index, value in enumerate(values)]


def _same(expected, actual):
    if expected.status != actual.status:
        return False
    if expected.score is None:
        return actual.score is None
    if actual.score is None or not math.isclose(expected.score, actual.score, rel_tol=1e-8, abs_tol=1e-9):
        return False
    for key, value in expected.evidence.items():
        if key not in actual.evidence:
            return False
        if isinstance(value, (int, float)):
            if not isinstance(actual.evidence[key], (int, float)) or not math.isclose(
                value, actual.evidence[key], rel_tol=1e-8, abs_tol=1e-9
            ):
                return False
        elif actual.evidence[key] != value:
            return False
    return True


def validate_candidate(runner, task_id, source, config, *, candidate_id, version, origin) -> dict:
    """Compare method semantics to human reference, never to effect labels.

    The reference is trusted host code. Generated source is transmitted only to
    Docker. Each feedback record names the check, index, development input and
    expected/actual difference. Sandbox/infrastructure failures are not repairable.
    """
    if not isinstance(config, (FixedConfig, MADConfig)):
        model = FixedConfig if config.method_id == "fixed_threshold" else MADConfig
        config = model.model_validate(config.model_dump())
    report = {"protocol": "metrics-method-check/2", "candidate_id": candidate_id, "version": version,
              "origin": origin, "source_sha256": digest(source.encode()),
              "config": config.model_dump(mode="json"), "dependency_profile": DEPENDENCY_PROFILE,
              "checks": [], "passed": False, "repairable": True}
    check, current_points, index = "static_profile", [], None
    try:
        check_source(source)
        report["checks"].append({"check": check, "passed": True})
        train = _points([0.0, 1.0, 2.0, 3.0])
        if isinstance(config, FixedConfig):
            threshold = config.threshold
            cases = {"fixed_strict_boundary": [threshold - 1, threshold, threshold + 1],
                     "fixed_missing": [threshold + 1, None, None, None, None, threshold]}
        else:
            history = [float(1 + i % 3) for i in range(config.min_history)]
            cases = {"mad_past_only": history + [1000.0, 2.0],
                     "mad_zero_scale": [1.0] * (config.window + 2) + [5.0],
                     "mad_missing_slots": history + [None] * (config.window + 4) + [2.0],
                     "mad_imputed_not_original": [1.0, None, 2.0, None] + history}
        with runner.detector(task_id, source) as detector:
            for check, values in cases.items():
                current_points = _points(values)
                detector.fit(config, train)
                detector.reset()
                reference = create_detector(config)
                reference.fit(train)
                prep, expected, actual = CausalPreprocessor(), [], []
                for index, point in enumerate(current_points):
                    processed = prep.step(point)
                    expected.append(reference.score_one(processed))
                    actual.append(detector.score_one(processed))
                    if not _same(expected[-1], actual[-1]):
                        raise CandidateFailure({"code": "METHOD_DIFFERENCE", "line": None,
                                                "expected": expected[-1].model_dump(mode="json"),
                                                "actual": actual[-1].model_dump(mode="json"),
                                                "message": "method status, score or baseline evidence differs"})
                report["checks"].append({"check": check, "passed": True, "points": len(values)})
            check = "state_reload"
            state = detector.call("save")
            # A fresh current point is the only additional observation supplied.
            point = CausalPreprocessor().step(_points([0.0] * len(current_points) + [7.0])[-1])
            expected = detector.score_one(point)
            detector.call("load", state=state)
            actual = detector.score_one(point)
            if not _same(expected, actual):
                raise CandidateFailure({"code": "STATE_RELOAD_DIFFERENCE", "line": None,
                                        "expected": expected.model_dump(mode="json"),
                                        "actual": actual.model_dump(mode="json"), "message": "save/load changed score"})
            report["checks"].append({"check": check, "passed": True})
            # Repeat the same prefix, then change only future data, in independent resets.
            check = "reset_repeat_future_invariance"
            values = list(cases.values())[0]
            outputs = []
            for future in (100.0, -100.0):
                detector.reset()
                prep = CausalPreprocessor()
                outputs.append([detector.score_one(prep.step(p)) for p in _points(values + [future])])
            if any(not _same(a, b) for a, b in zip(outputs[0][:-1], outputs[1][:-1])):
                raise CandidateFailure({"code": "RESET_PREFIX_DIFFERENCE", "line": None,
                                        "message": "repeated past prefix changed after reset"})
            report["checks"].append({"check": check, "passed": True})
        report["passed"] = True
    except CandidateFailure as error:
        report["checks"].append({"check": check, "passed": False, "point_index": index,
                                  "development_input": [p.model_dump(mode="json") for p in current_points[:(index + 1) if index is not None else 0]],
                                  "difference": error.feedback,
                                  "allowed_changes": "candidate source only; keep frozen config and interface"})
    except FactoryError as error:
        report["repairable"] = False
        report["checks"].append({"check": check, "passed": False, "difference": {"code": error.code.value,
                                  "message": str(error)}})
    return report
