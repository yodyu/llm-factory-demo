"""Trusted CSV validation and causal preprocessing, shared by all candidates."""

import csv
import io
import math
from datetime import timedelta
from pathlib import Path
from collections.abc import Sequence

from contracts.metrics import MetricPoint, MetricsDataset, ProcessedPoint, Role
from factory.runtime.artifacts import digest

MAX_CSV_BYTES = 16 * 1024 * 1024


def validate_grid(points: Sequence[MetricPoint], *, host_id: str, sampling_seconds: int):
    if not points or type(sampling_seconds) is not int or sampling_seconds <= 0:
        raise ValueError("nonempty observations and positive sampling_seconds required")
    previous = None
    for index, point in enumerate(points):
        if point.host_id != host_id:
            raise ValueError(f"row {index + 2}: host_id mismatch")
        if previous is not None and point.timestamp - previous != timedelta(seconds=sampling_seconds):
            raise ValueError(f"row {index + 2}: duplicate, unordered or missing time slot")
        previous = point.timestamp


def read_csv(data: bytes, *, host_id: str, sampling_seconds: int,
             valid_range: tuple[float, float]) -> list[MetricPoint]:
    if len(data) > MAX_CSV_BYTES:
        raise ValueError("CSV exceeds byte limit")
    if (len(valid_range) != 2 or not all(math.isfinite(x) for x in valid_range)
            or valid_range[0] >= valid_range[1]):
        raise ValueError("invalid physical range")
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""))
    if reader.fieldnames != ["timestamp", "host_id", "value"]:
        raise ValueError("CSV header must be timestamp,host_id,value")
    points = []
    for row in reader:
        line = reader.line_num
        if None in row or any(v is None for v in row.values()):
            raise ValueError(f"row {line}: column count mismatch")
        try:
            value = float(row["value"]) if row["value"].strip() else None
            if value is not None and (not math.isfinite(value) or not valid_range[0] <= value <= valid_range[1]):
                raise ValueError("value outside physical range")
            points.append(MetricPoint(timestamp=row["timestamp"], host_id=row["host_id"], value=value))
        except (ValueError, TypeError):
            raise ValueError(f"row {line}: invalid timestamp, host_id or numeric value") from None
    validate_grid(points, host_id=host_id, sampling_seconds=sampling_seconds)
    return points


def encode_csv(points: Sequence[MetricPoint]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["timestamp", "host_id", "value"])
    for p in points:
        writer.writerow([p.timestamp.isoformat().replace("+00:00", "Z"), p.host_id,
                         "" if p.value is None else repr(p.value)])
    return stream.getvalue().encode("utf-8")


def load_role(root: Path, manifest: MetricsDataset, role: Role) -> list[MetricPoint]:
    """Caller grants a single role. No other role/label file is read here."""
    entry = manifest.roles[role]
    root = root.resolve()
    path = root / entry.path
    if not path.resolve().is_relative_to(root) or path.is_symlink():
        raise ValueError("role path escapes dataset root or is a symlink")
    with path.open("rb") as stream:
        raw = stream.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES or digest(raw) != entry.sha256:
        raise ValueError("role content digest/size mismatch")
    points = read_csv(raw, host_id=manifest.host_id, sampling_seconds=manifest.sampling_seconds,
                      valid_range=manifest.valid_range)
    if entry.prefix_points >= len(points):
        raise ValueError("role has no scoring points")
    return points


class CausalPreprocessor:
    """At most three forward fills; no future observation is held by this object."""

    def __init__(self):
        self.last_value = None
        self.missing_streak = 0

    def step(self, point: MetricPoint) -> ProcessedPoint:
        if point.value is not None:
            self.last_value = point.value
            self.missing_streak = 0
            imputation = "none"
            value = point.value
        else:
            self.missing_streak += 1
            value = self.last_value if self.missing_streak <= 3 else None
            imputation = "forward_fill" if value is not None else "unavailable"
        return ProcessedPoint(timestamp=point.timestamp, host_id=point.host_id, value=value,
                              original_present=point.value is not None, imputation=imputation,
                              missing_streak=self.missing_streak)
