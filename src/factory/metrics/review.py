"""Read-only projections of recorded evidence; no models, runners or publication."""

import math
import re
import sqlite3
from pathlib import Path

from pydantic import TypeAdapter

from contracts.base import RelativePath, strict_json_loads
from factory.metrics.knowledge import identity
from factory.metrics.publication import publication_key
from factory.runtime.artifacts import digest


def read_bytes(directory, relative, *, limit=8 * 1024 * 1024):
    TypeAdapter(RelativePath).validate_python(relative)
    root = Path(directory).resolve()
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("artifact path leaves the selected run")
    # Reject links in intermediate directories, too.
    if any(parent.is_symlink() for parent in path.parents if parent != root and parent.is_relative_to(root)):
        raise ValueError("artifact directory must not be a symlink")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("recorded artifact exceeds review size limit")
    return raw


def read_json(directory, relative):
    value = strict_json_loads(read_bytes(directory, relative))
    if not isinstance(value, dict):
        raise ValueError("recorded object required")
    return value


def source_bytes(directory, version):
    raw = read_bytes(directory, version["source_path"], limit=256 * 1024)
    if digest(raw) != version["source_sha256"]:
        raise ValueError("源码摘要与验证记录不一致，已停止提供该文件。")
    return raw


def metric_text(value, *, percent=False):
    if not isinstance(value, dict):
        return "未记录（not_recorded）"
    number = value.get("value")
    if number is None:
        return "未定义（" + str(value.get("null_reason") or "not_recorded") + "）"
    if type(number) not in (int, float) or not math.isfinite(number):
        return "未定义（invalid_metric）"
    return f"{number:.1%}" if percent else f"{number:.4f}"


def result_outcome(report):
    """Conservative display projection of frozen statuses, never evaluates data."""
    final = report.get("final") or {}
    source = report.get("data_source") or {}
    selected = (report.get("selection") or {}).get("selected")
    candidate = next((c for c in report.get("candidates") or [] if c.get("candidate_id") == selected), {})
    failure = report.get("failure") or final.get("failure")
    stages = report.get("stage_status") or {}
    status = report.get("completion_status") or report.get("status") or "未记录"
    succeeded = final.get("execution_status") == "SUCCEEDED" and report.get("final_test_executed") is not False
    failed = final.get("execution_status") == "FAILED" or stages.get("detection") == "FAILED" or report.get("status") == "FAILED" or stages.get("engineering") == "FAILED"
    succeeded = (succeeded and not failed and not failure and bool(selected)
                 and status not in {'RUNNING', 'QUEUED', 'PENDING', 'PLAN_ONLY'}
                 and not report.get('proposal'))
    no_labels = source.get("type") == "uploaded_csv" and "labels" in source and source["labels"] is None
    measured = succeeded and bool(selected) and final.get("effect_status") == "MEASURED" and not no_labels
    if report.get('proposal', {}).get('status') == 'PLAN_ONLY':
        summary = report['proposal']['notice']
        level = 'warning'
    elif failed or failure:
        phase = "检测" if final.get("execution_status") == "FAILED" or stages.get("detection") == "FAILED" else "工程验证" if stages.get("engineering") == "FAILED" else "任务流程（阶段未记录）"
        reason = failure or next((c.get("failure") for c in report.get("candidates") or [] if c.get("failure")), {})
        reason = reason.get("message") or reason.get("code") or "失败原因未记录，请查看验证过程。"
        summary = f"任务失败 · {phase}：{reason}"
        level = "error"
    elif succeeded:
        summary = "检测已完成"
        business_unmet = (report.get('business_acceptance') or {}).get('status') == 'FAILED'
        if no_labels:
            summary += "；无标签，可查看检测结果，但无法评价准确性。"
        elif measured:
            missed = (final.get("matched_delay_seconds") or {}).get("missed_events")
            if missed is not None:
                summary += f"；已记录漏检事件 {missed} 个。"
            if final.get("acceptance_status") == "MEASURED_NO_ACCEPTANCE_THRESHOLD":
                summary += " 效果已测量，未定义业务验收门槛。"
        else:
            summary += "；效果未评估或未记录，不能据此判断准确性。"
        engineering_issue = final.get("engineering_status") not in {None, "PASSED"}
        if engineering_issue:
            summary += " 工程状态：" + str(final["engineering_status"]) + "。"
        if business_unmet:
            summary += ' 验收目标未满足，当前展示最佳可运行方案。'
        if status == "PARTIAL_SUCCESS" or stages.get("benchmark") == "FAILED":
            summary += " 独立模拟基准失败，请查看基准记录。"
        level = "warning" if business_unmet or no_labels or not measured or engineering_issue or status == "PARTIAL_SUCCESS" or stages.get("benchmark") == "FAILED" else "success"
    else:
        summary, level = f"任务状态：{status}；检测尚未完成或未记录最终执行结果。", "warning"
    reason = "无标签" if no_labels else "最终检测未成功或未执行" if not succeeded else "未记录冻结采用方案" if not selected else "效果未评估或未记录"
    return {"summary": summary, "level": level, "selected": selected, "candidate": candidate,
            "succeeded": succeeded, "measured": measured, "metric_reason": reason, "no_labels": no_labels}


def recorded_repairs(report):
    """Only explicit source-version records, excluding an initial v0 record."""
    return [v for c in report.get("candidates") or [] for v in c.get("versions") or []
            if type(v.get("version")) is int and v["version"] > 0]


def conflicting_upper_terms(requirement):
    """Only flag explicit contrary phrases; this is not general NLU validation."""
    pattern = (r"(?:检测|监测|识别|发现)[^，。；;\n]{0,12}(?:下降|降低)|"
               r"(?:下降|降低)[^，。；;\n]{0,8}(?:告警|报警)|低于|下界|双侧|双向异常|\b(?:lower|two[_ -]sided)\b")
    result = []
    for match in re.finditer(pattern, requirement, re.I):
        prefix = requirement[max(0, match.start() - 4):match.start()]
        if re.search(r"(?:不|无需|不要|不做|不采用)\s*$", prefix):
            continue
        result.append(match.group())
    return sorted(set(result))


def knowledge_usage(report):
    retrieval = report.get("retrieval") or {}
    supplied = set(retrieval.get("knowledge_ids") or [])
    references = []
    for candidate in report.get("candidates") or []:
        references.append({"候选": candidate.get("candidate_id", "未记录"), "阶段": "方案",
                           "知识ID": (candidate.get("plan") or {}).get("knowledge_ids") or []})
        for version in candidate.get("versions") or []:
            references.append({"候选": candidate.get("candidate_id", "未记录"), "阶段": f"代码 v{version.get('version', '未记录')}",
                               "知识ID": version.get("knowledge_ids") or []})
    cited = {value for row in references for value in row["知识ID"]}
    experiences = {e["id"] for e in retrieval.get("experiences") or []}
    return {"supplied": sorted(supplied), "cited": sorted(cited), "references": references,
            "unprovided_citations": sorted(cited - supplied),
            "supplied_experiences": sorted(experiences), "cited_experiences": sorted(cited & experiences)}


def old_validator_affected(version):
    validation = version.get("validation") or {}
    return validation.get("protocol") == "metrics-method-check/1" and any(
        check.get("difference", {}).get("code") in {"STATE_RELOAD_DIFFERENCE", "RESET_PREFIX_DIFFERENCE"}
        for check in validation.get("checks") or []
    )


def publication_evidence(directory, report, knowledge_path):
    """Read receipt and its exact nodes using SQLite mode=ro; never creates a DB."""
    try:
        receipt = read_json(directory, "publication.json")
    except FileNotFoundError:
        return {"receipt": {"status": "NOT_RECORDED"}, "nodes": [], "notes": ["没有回写回执；未推断为已发布。"]}
    if receipt.get("status") != "PUBLISHED":
        recovered = sorted(Path(directory).glob("publication-recovery-*.json"))
        if recovered:
            receipt = read_json(directory, recovered[-1].name)
    if receipt.get("status") != "PUBLISHED":
        return {"receipt": receipt, "nodes": [], "notes": ["回执未记录发布成功；页面不会自动重试。"]}
    if receipt.get("publication_id") != publication_key(report):
        raise ValueError("publication 回执与当前报告不绑定，停止展示为已核实回写")
    ids = receipt.get("node_ids", [])
    if not ids or len(ids) > 128 or not all(isinstance(value, str) for value in ids):
        raise ValueError("invalid publication node list")
    if hasattr(knowledge_path, "details"):
        nodes = knowledge_path.details(ids)
    elif Path(knowledge_path).suffix not in {".sqlite", ".db"}:
        from factory.metrics.knowledge_store import open_knowledge
        graph = open_knowledge(knowledge_path)
        try:
            nodes = graph.details(ids)
        finally:
            graph.close()
    else:
        # Explicit historical compatibility for old review packages; never a write target.
        path = Path(knowledge_path)
        if not path.is_file() or path.is_symlink():
            return {"receipt": receipt, "nodes": [], "notes": ["回执记录已发布，但当前只读知识库不可用，节点尚未核实。"]}
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        try:
            rows = db.execute("SELECT id,kind,payload FROM nodes WHERE id IN (" + ",".join("?" for _ in ids) + ")", ids).fetchall()
        finally:
            db.close()
        nodes = [{"id": row[0], "kind": row[1], "payload": strict_json_loads(row[2])} for row in rows]
    kinds = {"Implementation": "implementation", "ValidationRun": "validation", "Experience": "experience"}
    for node in nodes:
        payload = node["payload"]
        if node["kind"] not in kinds or identity(kinds[node["kind"]], payload) != node["id"]:
            raise ValueError("publication 节点摘要不匹配")
        if node["kind"] in {"Implementation", "Experience"} and payload.get("task_id") != report["task"]["task_id"]:
            raise ValueError("publication 节点属于其他任务")
    implementations = {n["id"] for n in nodes if n["kind"] == "Implementation"}
    if any(n["payload"].get("implementation_id") not in implementations for n in nodes if n["kind"] == "ValidationRun"):
        raise ValueError("验证节点缺少当前任务实现关联")
    notes = []
    if len(nodes) != len(ids):
        notes.append(f"回执节点 {len(ids)} 个，当前只读库找到 {len(nodes)} 个；未找到的节点未核实，页面不会补写。")
    return {"receipt": receipt, "nodes": nodes, "notes": notes}
