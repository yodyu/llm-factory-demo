"""Idempotent evidence publication. Retrieval summaries exclude final measurements."""

from factory.metrics.knowledge import canonical, identity
from factory.metrics.knowledge_store import KnowledgeRepository


def publication_key(report):
    """Pure identity calculation shared by publication and read-only review."""
    return identity("publication", {"task_id": report["task"]["task_id"], "report_hash": identity("report", report),
                                    "protocol": report["task"]["validation_protocol"]})


def publication_payload(report):
    key = publication_key(report)
    nodes, relations = [], []
    selected_id = report.get("selection", {}).get("selected")
    final = report.get("final", {})
    origin = report["origin"]
    for candidate in report.get("candidates", []):
        for version in candidate["versions"]:
            if "source_sha256" not in version:
                continue
            implementation = {"task_id": report["task"]["task_id"], "candidate_id": candidate["candidate_id"],
                              "version": version["version"], "source_sha256": version["source_sha256"],
                              "source_ref": version.get("source_ref", version["source_sha256"]),
                              "config": candidate["plan"]["config"], "origin": version["origin"],
                              "parent_source_sha256": version.get("parent_source_sha256"),
                              "dependency_profile": report["dependency_profile"],
                              **{k: version.get(k) for k in ('capability_id', 'capability_version', 'specification_sha256')},
                              "verification_level": version.get('validation', {}).get('verification_level', 'contract_only')}
            impl_id = identity("implementation", implementation)
            validation = {"implementation_id": impl_id, "method_checks": version.get("validation"),
                          "development": candidate.get("report") if version is candidate["versions"][-1] else None,
                          "final": final if candidate["candidate_id"] == selected_id and version is candidate["versions"][-1] else None,
                          "bindings": report["bindings"], "protocol": report["task"]["validation_protocol"]}
            val_id = identity("validation", validation)
            checks_passed = version.get("validation", {}).get("passed", False)
            reusable = bool(checks_passed and candidate["candidate_id"] == selected_id
                            and version is candidate["versions"][-1]
                            and final.get("execution_status") == "SUCCEEDED"
                            and final.get("engineering_status") == "PASSED")
            experience = {"task_id": report["task"]["task_id"], "method_id": candidate["plan"]["config"]["method_id"],
                          "metric_kind": report["dataset_public"]["metric_kind"], "origin": origin,
                          "implementation_id": impl_id, "validation_id": val_id,
                          "reusable_implementation": reusable, "implementation_verified": checks_passed,
                          "method_validation_protocol": version.get("validation", {}).get("protocol"),
                          "effect_status": final.get("effect_status", "NOT_MEASURED") if reusable else "NOT_QUALIFIED_FOR_REUSE",
                          "acceptance_status": (report.get("business_acceptance", {}).get("status")
                              if reusable and report.get("business_acceptance", {}).get("status") not in {None, "NOT_DEFINED"}
                              else "MEASURED_NO_ACCEPTANCE_THRESHOLD" if reusable and final.get("effect_status") == "MEASURED"
                              else "NOT_EVALUATED" if reusable else "NOT_CLAIMED"),
                          "issue": "method_check_failure" if not checks_passed else "verified_method_requires_new_input_evaluation",
                          "action": "development_difference_repair" if version["version"] else "initial_generation",
                          "development_feedback": [check for check in version.get("validation", {}).get("checks", []) if not check["passed"]],
                          "reuse_scope": "single host and metric; revalidate code, calibration and effect on new data",
                          "final_feedback_policy": "final values, labels and metrics omitted from retrieval summary"}
            exp_id = identity("experience", experience)
            nodes += [{"id": impl_id, "kind": "Implementation", "payload": implementation},
                      {"id": val_id, "kind": "ValidationRun", "payload": validation},
                      {"id": exp_id, "kind": "Experience", "payload": experience}]
            relations += [{"source": impl_id, "relation": "EVALUATED_BY", "target": val_id, "provenance": {"publication": key}},
                          {"source": exp_id, "relation": "LEARNED_FROM", "target": val_id, "provenance": {"publication": key}}]
            by_id = {n["id"]: n for n in report["knowledge_snapshot"]["nodes"]}
            for knowledge_id in candidate["plan"]["knowledge_ids"]:
                node = by_id.get(knowledge_id)
                if node and node["kind"] == "Capability":
                    relations.append({"source": knowledge_id, "relation": "IMPLEMENTED_BY", "target": impl_id, "provenance": {"publication": key}})
    if not nodes:
        value = {"task_id": report["task"]["task_id"], "method_id": report["task"]["allowed_methods"][0],
                 "metric_kind": report["dataset_public"]["metric_kind"], "origin": origin,
                 "reusable_implementation": False, "implementation_verified": False,
                 "issue": report.get("failure", {}).get("code", "task_failed_before_implementation"),
                 "action": "retain_failure", "reuse_scope": "risk hint only", "development_feedback": []}
        nodes.append({"id": identity("experience", value), "kind": "Experience", "payload": value})
    receipt = {"publication_id": key, "node_ids": sorted(n["id"] for n in nodes), "status": "PUBLISHED"}
    return {"nodes": report["knowledge_snapshot"]["nodes"] + nodes,
            "relations": report["knowledge_snapshot"]["relations"] + relations, "receipt": receipt}


def publish(knowledge: KnowledgeRepository, report):
    payload = publication_payload(report)
    return knowledge.publish(**payload)


def publish_pending(store, knowledge: KnowledgeRepository, report):
    """Durable SQLite operation + immutable payload, followed by idempotent graph transaction.

    Does not migrate ledger schema, claim a distributed transaction, or call a model.
    A graph commit followed by receipt failure is recovered with the same publication ID.
    """
    from factory.runtime.artifacts import digest
    task_id = report["task"]["task_id"]
    key = publication_key(report)
    operation_id = task_id + ":knowledge:" + key
    with store._transaction() as db:
        row = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        old = dict(row) if row else None
    if old:
        import json
        metadata = json.loads(old["metadata"])
        ref = metadata["payload_ref"]
        payload = store.document(ref)
        if (old["input_hash"] != digest(canonical(payload).encode())
                or payload["receipt"]["publication_id"] != key):
            raise ValueError("pending publication binding mismatch")
        if old["status"] == "SUCCEEDED":
            receipt = store.document(old["result_ref"])
            if receipt != payload["receipt"]:
                raise ValueError("publication receipt binding mismatch")
            return receipt
    else:
        payload = publication_payload(report)
        ref = store.register_document(task_id, payload, "knowledge-publication-payload")
        with store._transaction() as db:
            row = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
            if row and row["input_hash"] != digest(canonical(payload).encode()):
                raise ValueError("publication payload conflict")
            if not row:
                now = store.clock()
                db.execute("""INSERT INTO operations(operation_id,task_id,resource,input_hash,reserved_at,deadline,status,metadata)
                              VALUES (?,?,?,?,?,?,?,?)""", (operation_id,task_id,"knowledge-publication",digest(canonical(payload).encode()),
                              now,now,"PENDING_RETRY",canonical({"payload_ref":ref,"publication_id":key})))
    try:
        receipt = knowledge.publish(**payload)
        receipt_ref = store.register_document(task_id, receipt, "knowledge-publication-receipt")
        with store._transaction() as db:
            db.execute("UPDATE operations SET status='SUCCEEDED',result_ref=? WHERE operation_id=?", (receipt_ref,operation_id))
        return receipt
    except Exception as error:
        # Persist pending status even if Neo4j committed but local receipt completion failed.
        with store._transaction() as db:
            db.execute("UPDATE operations SET status='PENDING_RETRY' WHERE operation_id=? AND status!='SUCCEEDED'", (operation_id,))
        return {"status":"PENDING_RETRY", "publication_id":key, "payload_ref":ref,
                "failure":{"code":type(error).__name__,"message":"knowledge publication pending; retry without model or algorithm execution"}}
