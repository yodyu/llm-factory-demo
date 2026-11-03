"""Numeric candidate adapter over the public hardened JSON stream interface."""

import ast
from contextlib import contextmanager
from pathlib import Path
from pydantic import ValidationError

from contracts import FactoryError
from contracts.metrics import Score, MAX_UPLOAD_POINTS
from execution.runner import LocalSandboxRunner, StreamBudget, OUTPUT_LIMIT
from execution.validation import _check_source

DEPENDENCY_PROFILE = "metrics-py312-stdlib/1"
IMPORTS = {"math", "statistics", "collections", "json", "datetime", "typing", "bisect", "__future__"}


def role_budget(point_count, fit_count):
    """Allocate from trusted role lengths, including warmup; no code-controlled quotas."""
    if any(type(n) is not int or not 0 <= n <= MAX_UPLOAD_POINTS for n in (point_count, fit_count)):
        raise ValueError("role exceeds 50000 point limit")
    # Allow escaped 256-character identifiers and ordinary evidence, while
    # repeated oversized evidence still exhausts the cumulative allocation.
    # A fit request may contain nearly the entire bounded 16-MiB CSV.
    return StreamBudget(output_bytes=OUTPUT_LIMIT + point_count * 4096,
        input_bytes=2 * 1024 * 1024 + (point_count + fit_count) * 4096,
        request_bytes=32 * 1024 * 1024, seconds=10 + point_count * .004)


class CandidateFailure(ValueError):
    def __init__(self, feedback):
        self.feedback = feedback
        super().__init__(feedback["code"])


def check_source(source: str):
    raw = source.encode()
    if len(raw) > 256 * 1024:
        raise CandidateFailure({"code": "SOURCE_SIZE_LIMIT", "line": None, "message": "source exceeds 256KiB"})
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            names = [item.name for item in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) else []
            if any(name.split(".")[0] not in IMPORTS for name in names):
                raise CandidateFailure({"code": "UNAPPROVED_IMPORT", "line": node.lineno,
                                        "message": "metrics profile permits only approved standard library modules"})
        _check_source(raw)
        if not any(isinstance(node, ast.FunctionDef) and node.name == "create_detector" for node in tree.body):
            raise CandidateFailure({"code": "MISSING_ENTRYPOINT", "line": None, "message": "define create_detector(config)"})
    except FactoryError as error:
        raise CandidateFailure({"code": error.code.value, "line": None, "message": str(error)}) from None
    except SyntaxError as error:
        raise CandidateFailure({"code": "SYNTAX_ERROR", "line": error.lineno, "message": error.msg}) from None


class DetectorSession:
    def __init__(self, stream):
        self.stream = stream

    def call(self, op, **fields):
        answer = self.stream.request({"op": op, **fields})
        if not isinstance(answer, dict) or answer.get("ok") is not True:
            error = answer.get("error") if isinstance(answer, dict) else None
            if not isinstance(error, dict):
                error = {"code": "WORKER_PROTOCOL_ERROR", "line": None, "message": "invalid worker envelope"}
            raise CandidateFailure(error)
        return answer["result"]

    def fit(self, config, points):
        self.call("fit", config=config.model_dump(mode="json"), points=[p.model_dump(mode="json") for p in points])

    def reset(self):
        self.call("reset")

    def score_one(self, point):
        raw = self.call("step", point=point.model_dump(mode="json"))
        try:
            result = Score.model_validate(raw)
        except ValidationError as error:
            raise CandidateFailure({"code": "OUTPUT_SCHEMA", "line": None,
                                    "actual": raw,
                                    "issues": [{"field": list(item["loc"]), "type": item["type"], "expected": item["msg"]}
                                               for item in error.errors(include_input=False, include_context=False, include_url=False)],
                                    "expected_schema": Score.model_json_schema(),
                                    "message": "evidence must be an object (use {} for non-ok); score is null exactly when non-ok"}) from None
        if (result.timestamp, result.host_id) != (point.timestamp, point.host_id):
            raise CandidateFailure({"code": "POINT_ALIGNMENT", "line": None, "message": "timestamp/host differ from current point"})
        return result


class MetricsRunner(LocalSandboxRunner):
    managed_label = "llm-factory.managed=metrics-v1"
    container_prefix = "llmf-metrics-"

    @contextmanager
    def detector(self, task_id, source, *, point_count=None, fit_count=0):
        budget = role_budget(point_count, fit_count) if point_count is not None else None
        check_source(source)
        files = {"algorithm.py": source.encode(),
                 "worker.py": Path(__file__).with_name("metrics_worker.py").read_bytes()}
        with self.open_json_stream(task_id, files, budget=budget) as stream:
            yield DetectorSession(stream)
