"""Trusted reproducible simulations. Injection schedules define labels independently.

    The returned experiment (including seeds/labels) is evaluator-only. Never
    include it or the test role in model prompts or container mounts.
"""

import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from contracts.metrics import MetricPoint, MetricsDataset, RoleFile
from factory.metrics.data import encode_csv
from factory.runtime.artifacts import digest

GENERATOR_VERSION = "metrics-synthetic/1"
ROLES = ("train", "calibration", "development", "test")
SCENARIOS = {
    "cpu_spike": ("cpu_utilization", "percent", 35.0, 100.0),
    "memory_shift": ("memory_utilization", "percent", 45.0, 100.0),
    "memory_drift": ("memory_utilization", "percent", 40.0, 100.0),
    "disk_peaks": ("disk_latency", "ms", 10.0, 1000.0),
    "network_missing": ("network_rate", "bytes/s", 1000.0, 100000.0),
    "periodic": ("cpu_utilization", "percent", 45.0, 100.0),
}


def generate(scenario: str, *, seed: int = 20261031, direction: str = "upper", prefix_points: int = 60,
             scoring_points: int = 240) -> dict:
    if scenario not in SCENARIOS:
        raise ValueError("unsupported synthetic scenario")
    if direction not in {"upper", "lower", "two_sided"}:
        raise ValueError("unsupported synthetic direction")
    if (type(seed) is not int or type(prefix_points) is not int or type(scoring_points) is not int
            or not 0 <= prefix_points <= 600 or not 220 <= scoring_points <= 10000):
        raise ValueError("invalid simulation sizes/seed")
    metric, unit, baseline, upper = SCENARIOS[scenario]
    host_id = "sim-host-a"
    files, labels_by_role, role_files, schedules, seeds = {}, {}, {}, {}, {}
    for role_index, role in enumerate(ROLES):
        role_seed = seed + role_index * 100003
        seeds[role] = role_seed
        rng = random.Random(role_seed)
        # Each role uses independent initialization and an independent time interval.
        start = datetime(2026, 1, 1 + role_index, tzinfo=timezone.utc)
        schedule = []
        if role in ("development", "test"):
            schedule = {"cpu_spike": [(35, 38), (120, 121), (180, 185)],
                        "memory_shift": [(100, 160)], "memory_drift": [(90, 200)],
                        "disk_peaks": [(100, 110), (180, 190)],
                        "network_missing": [(120, 145)], "periodic": [(150, 175)]}[scenario]
        schedules[role] = schedule
        points, labels = [], []
        for index in range(prefix_points + scoring_points):
            offset = index - prefix_points
            injected = any(a <= offset < b for a, b in schedule)
            value = baseline + rng.gauss(0, baseline * 0.025)
            if scenario == "periodic":
                value += 22 * math.sin(index * 2 * math.pi / 60)
            if scenario == "disk_peaks" and offset >= 0 and 40 <= offset % 90 < 48:
                value += 45  # legitimate business peaks, explicitly negative labels
            if scenario == "network_missing" and 80 <= offset < 120:
                value = baseline  # zero MAD does not imply an anomaly
            if injected:
                sign = -1 if direction == "lower" or (direction == "two_sided" and offset < 150) else 1
                if scenario == "memory_drift":
                    value += sign * (offset - 90) * 0.4
                else:
                    value += sign * {"cpu_spike": 60, "memory_shift": 45, "disk_peaks": 45,
                              "network_missing": 2000, "periodic": 25}[scenario]
            value = round(max(0, min(upper, value)), 6)
            # Missing slots stay on the grid. Labels still follow the injection schedule.
            if (scenario == "network_missing" and (20 <= offset < 23 or 50 <= offset < 65)) or offset == 132:
                value = None
            points.append(MetricPoint(timestamp=start + timedelta(seconds=index * 60), host_id=host_id, value=value))
            labels.append(injected)
        raw = encode_csv(points)
        files[f"{role}.csv"] = raw
        labels_by_role[role] = labels
        role_files[role] = RoleFile(path=f"{role}.csv", sha256=digest(raw), prefix_points=prefix_points)
    manifest = MetricsDataset(dataset_id=f"sim-{scenario}-v1", host_id=host_id, metric=metric, unit=unit,
                              metric_kind="rate" if scenario == "network_missing" else "gauge",
                              sampling_seconds=60, valid_range=[0.0, upper], roles=role_files)
    label_bytes = json.dumps(labels_by_role, sort_keys=True, separators=(",", ":")).encode()
    experiment = {"generator_version": GENERATOR_VERSION, "scenario": scenario, "seeds": seeds,
                  "direction": direction,
                  "injection_intervals_scoring_offsets": schedules, "labels_path": "trusted/labels.json",
                  "labels_sha256": digest(label_bytes), "prefix_points": prefix_points,
                  "scoring_points": scoring_points, "normal_prefix_assumption": True,
                  "calibration_normal_reference_assumption": True,
                  "origin": "synthetic_injection", "dataset": manifest.model_dump(mode="json")}
    return {"manifest": manifest, "observations": files, "labels": label_bytes, "experiment": experiment}


def write_dataset(destination: Path, bundle: dict):
    """Writes a new trusted dataset; refuses to replace any existing directory."""
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    (destination / "trusted").mkdir(mode=0o700)
    for name, raw in bundle["observations"].items():
        if name not in {f"{role}.csv" for role in ROLES}:
            raise ValueError("unexpected observation filename")
        (destination / name).write_bytes(raw)
    (destination / "trusted" / "labels.json").write_bytes(bundle["labels"])
    (destination / "trusted" / "experiment.json").write_text(json.dumps(bundle["experiment"], indent=2) + "\n")
    (destination / "manifest.json").write_text(bundle["manifest"].model_dump_json(indent=2) + "\n")
