"""Reviewable Markdown and allowlisted digest-bound export, excluding credentials/DBs."""

import json
import zipfile
from pathlib import Path

from contracts.base import strict_json_loads
from factory.metrics.knowledge import canonical
from factory.runtime.artifacts import digest


def markdown(report):
    from factory.metrics.usage import model_usage
    from factory.metrics.ui_presentation import selection_explanation
    usage = model_usage(report)
    if report.get("data_source"):
        from factory.metrics.upload import UNKNOWN, BENCHMARK_NOTICE
        sections = [("A. 工程质量", {"model_origin": report["origin"], "dependency_profile": report["dependency_profile"],
            "image": report["bindings"].get("image_id"), "prompt_version": report.get("prompt_version"),
            "candidates": report["candidates"], "stage_status": report.get("stage_status"), "model_usage": usage,
            "workflow_runtime_seconds": report.get("workflow_runtime_seconds"), "resources": report.get("resource_measurement"),
            "peak_memory": "NOT_MEASURED; container limits are not measurements", "failure": report.get("failure")}),
            ("B. 当前检测数据", {"frozen_source": report["data_source"], "selection": report.get("selection"), "result": report.get("final"),
             "notice": UNKNOWN if report["data_source"]["type"] == "uploaded_csv" and report.get("final", {}).get("effect_status") == "NOT_EVALUATED" else None}),
            ("C. 独立模拟基准效果", {"notice": BENCHMARK_NOTICE, "result": report.get("benchmark", {"execution_status": "NOT_EVALUATED", "reason": "builtin simulation evaluated in B"})})]
        lines = ["# 数值监控验证报告", f"任务：{report['task']['task_id']}；流程：{report['status']}",
                 "工程通过、效果测量、业务达标分别记录；业务门槛以冻结需求和验收结果为准。"]
        sections.append(("D. 需求理解与业务验收", {"frozen_task": report["task"], "selection_explanation": selection_explanation(report),
            "evaluation_policy": report.get("evaluation_policy"), "requirement": report.get("requirement_understanding"),
            "acceptance": report.get("business_acceptance"), "criteria": report['task'].get('acceptance_criteria')}))
        for title, value in sections:
            lines += ["", "## " + title, "", "```json", json.dumps(value, ensure_ascii=False, indent=2), "```"]
        return "\n".join(lines) + "\n"
    lines = ["# 数值监控算法运行报告", "", f"任务：{report['task']['task_id']}",
             f"来源：{report['origin']}；流程状态：{report['status']}",
             "", "数据为模拟数据；工程通过、效果已测量及业务达标分别记录。业务门槛未定义。", "",
             "| 候选 | 方法 | 版本数 | 工程状态 | 开发事件 F1 | 覆盖率 |", "| --- | --- | --- | --- | --- | --- |"]
    for candidate in report["candidates"]:
        result = candidate.get("report", {})
        f1 = result.get("event", {}).get("f1", {}).get("value")
        coverage = result.get("coverage", {}).get("value")
        lines.append(f"| {candidate['candidate_id']} | {candidate['plan']['config']['method_id']} | {len(candidate['versions'])} | {result.get('engineering_status')} | {f1} | {coverage} |")
    lines += ["", "## 冻结与最终测试", "", "```json", json.dumps({"selection": report.get("selection"), "final": report.get("final"),
              "failure": report.get("failure"), "bindings": report["bindings"]}, ensure_ascii=False, indent=2), "```", "",
              "## 模型与知识证据", "", f"检索模式：{report['retrieval_mode']}；快照：{report['task']['knowledge_snapshot']}",
              "", f"本任务模型操作记录数：{len(report.get('model_operations', []))}（mock 操作不是真实请求）。",
              f"共享调用额度：{report.get('campaign_budget')}", "", "最终测试结果没有进入修复或重新选择。失败版本保留在候选目录中。",
              "峰值内存未测量；沙箱限制不能替代实测。", ""]
    return "\n".join(lines)


def bound_report(store, directory):
    directory = Path(directory).resolve()
    report = strict_json_loads((directory / "report.json").read_bytes())
    task_id = report["task"]["task_id"]
    # Do not let edits to the readable sidecar be mistaken for ledger evidence.
    with store._transaction() as db:
        refs = [row[0] for row in db.execute("SELECT reference FROM task_artifacts WHERE task_id=? AND role='run-report'", (task_id,))]
    if not any(store.document(ref) == report for ref in refs):
        raise ValueError("report differs from immutable ledger evidence")
    orchestration = report.get("orchestration")
    if orchestration:
        path = directory / "orchestration.json"
        if (orchestration.get("evidence_path") != "orchestration.json" or path.is_symlink()
                or digest(path.read_bytes()) != orchestration.get("evidence_sha256")):
            raise ValueError("orchestration differs from frozen report evidence")
    for candidate in report["candidates"]:
        for version in candidate["versions"]:
            path = directory / version["source_path"]
            if path.is_symlink() or not path.resolve().is_relative_to(directory) or digest(path.read_bytes()) != version["source_sha256"]:
                raise ValueError("source differs from validated digest")
    return report


def export_run(store, directory, output, *, dataset_root=None):
    directory, output = Path(directory).resolve(), Path(output)
    report = bound_report(store, directory)
    task_id = report["task"]["task_id"]
    source_refs = set()
    names = {"report.json", "task.json", "requirement-draft.json", "requirement-evidence.json", "knowledge.json", "dataset-manifest.json", "retrieval.json", "plans.json", "selection.json", "publication.json", "report.md"}
    if report.get("orchestration"):
        names.add("orchestration.json")
    names.update(p.name for p in directory.glob("publication-recovery-*.json") if p.is_file() and not p.is_symlink())
    for candidate in report["candidates"]:
        for version in candidate["versions"]:
            path = Path(version["source_path"])
            if (directory / path).is_symlink() or not (directory / path).resolve().is_relative_to(directory):
                raise ValueError("candidate export path is unsafe")
            if digest((directory / path).read_bytes()) != version["source_sha256"]:
                raise ValueError("source differs from validated digest")
            raw = (directory / path).read_bytes()
            store.guard.require_public(raw.decode())
            ref = store.artifact_store.put(raw)
            store.attach_artifact(task_id, ref, len(raw), "candidate-source")
            source_refs.add(ref)
            names.update({str(path), str(path.with_name(path.stem + "-checks.json")), str(path.parent / "candidate.json"),
                          str(path.parent / "model-original-v0.py")})
    files = {name: (directory / name).read_bytes() for name in sorted(names) if (directory / name).is_file()}
    for name in ("detection", "benchmark"):
        binding = report.get("curves", {}).get(name)
        if binding:
            from factory.metrics.upload import read_curve
            read_curve(directory, binding)
            for suffix in ("curve.json", "points.csv", "events.json"):
                filename = name + "-" + suffix
                content = (directory / filename).read_bytes()
                if suffix != "curve.json" and digest(content) != binding.get("downloads", {}).get(filename):
                    raise ValueError("curve export artifact digest mismatch")
                files[filename] = content
    with store._transaction() as db:
        artifact_refs = {row[0] for row in db.execute("SELECT reference FROM task_artifacts WHERE task_id=?", (task_id,))}
        operations = [dict(row) for row in db.execute("SELECT operation_id,resource,input_hash,status,result_ref,metadata FROM operations WHERE task_id=? ORDER BY reserved_at,operation_id", (task_id,))]
    artifact_refs.update(op["result_ref"] for op in operations if op["result_ref"])
    for ref in sorted(artifact_refs):
        raw = store.artifact_store.read(ref)
        store.guard.require_public(raw.decode())
        files["evidence/" + ref[7:] + (".py" if ref in source_refs else ".json")] = raw
    files["operations.json"] = canonical(operations).encode()
    if dataset_root is not None:
        dataset_root = Path(dataset_root)
        manifest_raw = (dataset_root / "manifest.json").read_bytes()
        if digest(manifest_raw) != report["bindings"]["manifest_sha256"]:
            raise ValueError("export dataset differs from run binding")
        manifest = strict_json_loads(manifest_raw)
        for role in ("train", "calibration", "development", "test"):
            path = dataset_root / manifest["roles"][role]["path"]
            if path.is_symlink() or not path.resolve().is_relative_to(dataset_root.resolve()):
                raise ValueError("unsafe dataset path")
            raw = path.read_bytes()
            if digest(raw) != manifest["roles"][role]["sha256"]:
                raise ValueError("dataset role digest mismatch")
            files["dataset/" + manifest["roles"][role]["path"]] = raw
        files["dataset/manifest.json"] = manifest_raw
        if "upload_sha256" in report["bindings"]:
            upload_raw = (dataset_root / "upload.json").read_bytes()
            if digest(upload_raw) != report["bindings"]["upload_sha256"]:
                raise ValueError("upload configuration binding mismatch")
            upload = strict_json_loads(upload_raw)
            observations = (dataset_root / "observations.csv").read_bytes()
            if digest(observations) != upload["sha256"]:
                raise ValueError("upload raw binding mismatch")
            files["dataset/upload.json"], files["dataset/observations.csv"] = upload_raw, observations
            if upload["labels"]:
                labels = (dataset_root / "trusted" / "user-labels.csv").read_bytes()
                if digest(labels) != upload["labels"]["sha256"]:
                    raise ValueError("user label binding mismatch")
                files["dataset/trusted/user-labels.csv"] = labels
            if upload["benchmark"]["status"] == "READY":
                from contracts.metrics import MetricsDataset
                from factory.metrics.data import load_role
                from factory.metrics.workflow import trusted_labels
                benchmark_root = dataset_root / "benchmark"
                benchmark_raw = (benchmark_root / "manifest.json").read_bytes()
                if digest(benchmark_raw) != upload["benchmark"]["manifest_sha256"] or digest((benchmark_root / "trusted/experiment.json").read_bytes()) != upload["benchmark"]["experiment_sha256"]:
                    raise ValueError("benchmark export binding mismatch")
                bm = MetricsDataset.model_validate(strict_json_loads(benchmark_raw))
                trusted_labels(benchmark_root, bm, "test")
                for role in bm.roles:
                    load_role(benchmark_root, bm, role)
                for name in ("manifest.json", "train.csv", "calibration.csv", "development.csv", "test.csv", "trusted/labels.json", "trusted/experiment.json"):
                    files["dataset/benchmark/" + name] = (dataset_root / "benchmark" / name).read_bytes()
        if "labels_sha256" in report["bindings"]:
            for name in ("labels.json", "experiment.json"):
                files["dataset/trusted/" + name] = (dataset_root / "trusted" / name).read_bytes()
            if digest(files["dataset/trusted/labels.json"]) != report["bindings"]["labels_sha256"]:
                raise ValueError("export labels differ from run binding")
    files["bundle-manifest.json"] = (canonical({"schema_version": "metrics-export/1", "task_id": task_id,
        "files": {name: {"sha256": digest(raw), "bytes": len(raw)} for name, raw in sorted(files.items())}}) + "\n").encode()
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(files.items()):
            archive.writestr(name, raw)
    return {"output": str(output), "files": len(files), "sha256": digest(output.read_bytes())}


def export_task_evidence(store, task_id, output):
    """Evidence-only package for ingestion, including rejected responses and failures."""
    task = store.task(task_id)
    if digest(store._json(strict_json_loads(task["spec"])).encode()) != task["spec_hash"]:
        raise ValueError("task spec digest mismatch")
    with store._transaction() as db:
        attachments = [dict(row) for row in db.execute("SELECT reference,role FROM task_artifacts WHERE task_id=? ORDER BY role,reference", (task_id,))]
        operations = [dict(row) for row in db.execute("SELECT operation_id,resource,input_hash,status,result_ref,metadata FROM operations WHERE task_id=? ORDER BY reserved_at", (task_id,))]
    refs = {row["reference"] for row in attachments}
    refs.update(row["result_ref"] for row in operations if row["result_ref"])
    source_refs = {row["reference"] for row in attachments if row["role"] == "candidate-source"}
    files = {"task.json": (canonical(strict_json_loads(task["spec"])) + "\n").encode(),
             "attachments.json": (canonical(attachments) + "\n").encode(),
             "operations.json": (canonical(operations) + "\n").encode()}
    for ref in refs:
        raw = store.artifact_store.read(ref)
        store.guard.require_public(raw.decode())
        files["evidence/" + ref[7:] + (".py" if ref in source_refs else ".json")] = raw
    files["bundle-manifest.json"] = (canonical({"schema_version": "metrics-evidence-export/1", "task_id": task_id,
        "files": {name: {"sha256": digest(raw), "bytes": len(raw)} for name, raw in sorted(files.items())}}) + "\n").encode()
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(files.items()):
            archive.writestr(name, raw)
    return {"output": str(output), "files": len(files), "sha256": digest(Path(output).read_bytes())}
