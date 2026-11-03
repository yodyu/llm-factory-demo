"""Validated extraction, explicit legacy SQLite compatibility and frozen retrieval."""

import ast
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from contracts import ErrorCode
from contracts.base import strict_json_loads
from contracts.metrics_knowledge import Extraction
from factory.metrics.knowledge_store import open_knowledge as _open_knowledge
from factory.models.transport import ModelCallError
from factory.runtime.artifacts import digest
from factory.runtime.security import SecretGuard

# Kept as an import-compatible factory: production never opens SQLite implicitly.
KnowledgeStore = _open_knowledge

KINDS = {"Source", "Chunk", "Capability", "Constraint", "Implementation", "ValidationRun", "Experience", "DataContract", "Metric", "Environment"}
RELATIONS = {"DERIVED_FROM", "REQUIRES", "IMPLEMENTED_BY", "EVALUATED_BY", "LEARNED_FROM", "CONSUMES", "PRODUCES", "EVALUATED_WITH", "DEPENDS_ON", "SUPERSEDES"}

EXTRACTION_INSTRUCTIONS = (
    "metrics-extraction/3：只从本次材料抽取有原文依据的能力及约束。"
    "method_id是算法名称（如fixed_threshold、rolling_mad、ewma），不是依赖环境；"
    "metrics-py312-stdlib/1等环境名称只能放dependency_profile。一般字段、评价或限制规范用method_id=null。"
    "summary、constraints、limitations和citations可保留材料中的公式与事实，不要求构造完整算法卡片。"
    "只有材料同时明确给出version、task_type、inputs、outputs、parameters、algorithm_spec、"
    "evaluation_metrics、supported_directions且能为这八个字段分别提供field_evidence时，才填写完整规格。"
    "缺任意字段或其原文依据时，version、task_type、inputs、outputs、parameters、defaults、algorithm_spec、"
    "evaluation_metrics、supported_directions、verification_level、field_evidence全部设为null；"
    "不能从常识补版本号、JSON Schema、评价指标或公式，不能用相关但不支持字段的引用充数。"
    "quote必须是给定chunk的逐字连续子串，保留空格、不用省略号，chunk_id必须来自本次材料。"
    "symbol只能来自给定AST符号或为null。不得把材料来源校验说成实现已验证；"
    "verification_level只能为null或contract_only。不确定条件填unknown，不要猜测。"
)


class EvidenceError(ValueError):
    def __init__(self, feedback):
        self.feedback = feedback
        super().__init__(feedback["code"])


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def identity(kind, value):
    return kind.lower() + "-" + digest(canonical(value).encode())[7:]


class LegacySQLiteKnowledgeStore:
    """Explicit historical/test adapter. Production entrypoints open Neo4j only."""
    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValueError("knowledge database must not be a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            marker = db.execute("PRAGMA application_id").fetchone()[0]
            if tables and marker != 0x4D4B4E57:
                raise ValueError("refuse non-metrics knowledge database")
            db.execute("""CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS relations (
                source TEXT REFERENCES nodes(id), relation TEXT NOT NULL, target TEXT REFERENCES nodes(id),
                provenance TEXT NOT NULL, PRIMARY KEY(source,relation,target))""")
            db.execute("CREATE TABLE IF NOT EXISTS publications (id TEXT PRIMARY KEY, receipt TEXT NOT NULL)")
            db.execute("PRAGMA application_id=1296780887")

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def insert(db, nodes, relations):
        for node in nodes:
            if node["kind"] not in KINDS:
                raise ValueError("unknown knowledge node kind")
            SecretGuard().require_public(node)
            raw = canonical(node["payload"])
            old = db.execute("SELECT kind,payload FROM nodes WHERE id=?", (node["id"],)).fetchone()
            if old and tuple(old) != (node["kind"], raw):
                raise ValueError("immutable knowledge node conflict")
            db.execute("INSERT OR IGNORE INTO nodes VALUES (?,?,?)", (node["id"], node["kind"], raw))
        for relation in relations:
            if relation["relation"] not in RELATIONS:
                raise ValueError("unknown relation")
            old = db.execute("SELECT provenance FROM relations WHERE source=? AND relation=? AND target=?",
                             (relation["source"], relation["relation"], relation["target"])).fetchone()
            if old and old[0] != canonical(relation["provenance"]):
                raise ValueError("immutable relationship conflict")
            db.execute("INSERT OR IGNORE INTO relations VALUES (?,?,?,?)",
                       (relation["source"], relation["relation"], relation["target"], canonical(relation["provenance"])))

    def add(self, nodes, relations):
        with self.transaction() as db:
            self.insert(db, nodes, relations)

    def publish(self, nodes, relations, receipt):
        with self.transaction() as db:
            old = db.execute("SELECT receipt FROM publications WHERE id=?", (receipt["publication_id"],)).fetchone()
            if old:
                if json.loads(old[0]) != receipt:
                    raise ValueError("immutable publication conflict")
                return json.loads(old[0])
            self.insert(db, nodes, relations)
            db.execute("INSERT INTO publications VALUES (?,?)", (receipt["publication_id"], canonical(receipt)))
        return receipt

    def snapshot(self):
        with self.transaction() as db:
            nodes = [{"id": row["id"], "kind": row["kind"], "payload": strict_json_loads(row["payload"])}
                     for row in db.execute("SELECT * FROM nodes ORDER BY id")]
            relations = [{**dict(row), "provenance": strict_json_loads(row["provenance"])}
                         for row in db.execute("SELECT * FROM relations ORDER BY source,relation,target")]
        value = {"schema_version": snapshot_schema(nodes), "nodes": nodes, "relations": relations}
        return {**value, "snapshot_id": digest(canonical(value).encode())}


def snapshot_schema(nodes):
    return "metrics-knowledge/2" if any(n['kind'] in {'DataContract', 'Metric', 'Environment'}
        or n['payload'].get('algorithm_spec') for n in nodes) else "metrics-knowledge/1"


RELATION_PAIRS = {
    'DERIVED_FROM': {('Chunk', 'Source'), ('Capability', 'Chunk'), ('Constraint', 'Chunk')},
    'REQUIRES': {('Capability', 'Constraint')}, 'IMPLEMENTED_BY': {('Capability', 'Implementation')},
    'EVALUATED_BY': {('Implementation', 'ValidationRun')}, 'LEARNED_FROM': {('Experience', 'ValidationRun')},
    'CONSUMES': {('Capability', 'DataContract')}, 'PRODUCES': {('Capability', 'DataContract')},
    'EVALUATED_WITH': {('Capability', 'Metric')}, 'DEPENDS_ON': {('Capability', 'Environment')},
    'SUPERSEDES': {('Capability', 'Capability')},
}


def verify_snapshot(snapshot):
    payload = {key: value for key, value in snapshot.items() if key != "snapshot_id"}
    if snapshot.get("schema_version") not in {"metrics-knowledge/1", "metrics-knowledge/2"} or digest(canonical(payload).encode()) != snapshot.get("snapshot_id"):
        raise ValueError("knowledge snapshot digest/schema mismatch")
    if any(n["kind"] not in KINDS or not isinstance(n["payload"], dict) for n in snapshot["nodes"]):
        raise ValueError("invalid snapshot entity schema")
    edge_ids = {(r["source"], r["relation"], r["target"]) for r in snapshot["relations"]}
    if len(edge_ids) != len(snapshot["relations"]) or any(r["relation"] not in RELATIONS for r in snapshot["relations"]):
        raise ValueError("invalid snapshot relationship identities")
    ids = {node["id"] for node in snapshot["nodes"]}
    if len(ids) != len(snapshot["nodes"]) or any(r["source"] not in ids or r["target"] not in ids for r in snapshot["relations"]):
        raise ValueError("invalid snapshot relationship endpoints")
    if snapshot['schema_version'] == 'metrics-knowledge/2':
        by_id = {n['id']: n for n in snapshot['nodes']}
        for edge in snapshot['relations']:
            if (by_id[edge['source']]['kind'], by_id[edge['target']]['kind']) not in RELATION_PAIRS[edge['relation']]:
                raise ValueError('invalid snapshot relationship endpoint kinds')
        for node in snapshot['nodes']:
            if node['kind'] == 'Capability' and node['payload'].get('algorithm_spec'):
                payload = node['payload']
                for field, cite in (payload.get('field_evidence') or {}).items():
                    chunk = by_id.get(cite['chunk_id'])
                    if not chunk or cite['quote'] not in chunk['payload']['text']:
                        raise ValueError('capability field citation missing')
                if not all(payload.get(k) for k in ('version', 'task_type', 'inputs', 'outputs', 'parameters', 'evaluation_metrics', 'supported_directions', 'field_evidence')):
                    raise ValueError('incomplete schema v2 capability')
                if 'spec_sources' in payload:
                    from factory.metrics.spec_sources import verify_frozen_spec_sources
                    verify_frozen_spec_sources(node, by_id, edge_ids)
    return snapshot


def sources_only(snapshot):
    """Freeze extraction knowledge for paired trials, excluding all run-derived experience."""
    verify_snapshot(snapshot)
    nodes = [node for node in snapshot["nodes"] if node["kind"] in {"Source", "Chunk", "Capability", "Constraint", "DataContract", "Metric", "Environment"}]
    ids = {node["id"] for node in nodes}
    value = {"schema_version": snapshot_schema(nodes), "nodes": nodes,
             "relations": [r for r in snapshot["relations"] if r["source"] in ids and r["target"] in ids]}
    return {**value, "snapshot_id": digest(canonical(value).encode())}


def import_material(root: Path, relative: str):
    from pydantic import TypeAdapter
    from contracts.base import RelativePath

    TypeAdapter(RelativePath).validate_python(relative)
    root, path = root.resolve(), root / relative
    if not path.resolve().is_relative_to(root) or path.is_symlink() or path.suffix not in {".md", ".txt", ".py"}:
        raise ValueError("material must be a bounded Markdown/text/Python file under source root")
    with path.open("rb") as stream:
        raw = stream.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024:
        raise ValueError("material too large")
    text = raw.decode("utf-8")
    SecretGuard().require_public(text)
    source_id = identity("source", {"path": relative, "sha256": digest(raw)})
    source = {"id": source_id, "kind": "Source", "payload": {"path": relative, "sha256": digest(raw),
              "material_type": path.suffix[1:], "origin": "constructed_reference" if path.suffix == ".py" else "constructed_material"}}
    symbols, imports = [], []
    import_evidence, calls = [], []
    if path.suffix == ".py":
        tree = ast.parse(text)
        qualified = {}

        def visit(node, scope=()):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names = (*scope, child.name)
                    qualified[id(child)] = ".".join(names)
                    visit(child, names)
                else:
                    visit(child, scope)

        visit(tree)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.append({"name": node.name, "line": node.lineno, "end_line": node.end_lineno,
                                "qualified_name": qualified[id(node)],
                                "signature": ast.unparse(node.args) if hasattr(node, "args") else None,
                                "docstring": ast.get_docstring(node)})
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or '.']
                for name in names:
                    import_evidence.append({'name': name, 'line': node.lineno, 'end_line': node.end_lineno,
                        'quote': '\n'.join(text.splitlines()[node.lineno-1:node.end_lineno])})
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                calls.extend({'caller': qualified[id(node)], 'callee': ast.unparse(call.func), 'line': call.lineno}
                             for call in ast.walk(node) if isinstance(call, ast.Call))
        source['payload'].update(extraction_protocol='metrics-source/2', origin='provided_code',
                                 import_evidence=import_evidence, calls=calls)
        source_id = identity('source', {k: source['payload'][k] for k in ('path','sha256','extraction_protocol')})
        source['id'] = source_id
    source["payload"].update({"symbols": symbols, "imports": sorted({i for i in imports if i})})
    lines, chunks = text.splitlines(), []
    if path.suffix == '.py':
        spans, cursor = [], 0
        functions = sorted((n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), key=lambda n: n.lineno)
        for function in functions:
            start = min([function.lineno] + [d.lineno for d in function.decorator_list]) - 1
            if cursor == 0:
                start = 0
            elif start > cursor:
                spans.append((cursor, start))
            spans.append((start, function.end_lineno))
            cursor = max(cursor, function.end_lineno)
        if cursor < len(lines):
            spans.append((cursor, len(lines)))
    else:
        spans = [(start, min(start+32, len(lines))) for start in range(0, len(lines), 32)]
    for start, end in spans:
        fragment = "\n".join(lines[start:end])
        if not fragment.strip():
            continue
        payload = {"source_id": source_id, "start_line": start + 1, "end_line": end,
                   "text": fragment, "sha256": digest(fragment.encode())}
        chunks.append({"id": identity("chunk", payload), "kind": "Chunk", "payload": payload})
    if not chunks:
        raise ValueError("empty material")
    return source, chunks


def checked_extraction(source, chunks, extraction, *, origin, response_evidence):
    from execution.metrics_runner import IMPORTS
    by_id = {chunk["id"]: chunk for chunk in chunks}
    symbol_names = {name for symbol in source["payload"]["symbols"] for name in (symbol["name"], symbol["qualified_name"])}
    nodes, relations = [source, *chunks], []
    unsupported = [name for name in source["payload"]["imports"] if name.split(".")[0] not in IMPORTS]
    for chunk in chunks:
        relations.append({"source": chunk["id"], "relation": "DERIVED_FROM", "target": source["id"], "provenance": response_evidence})
    for cap_index, capability in enumerate(extraction.capabilities):
        if capability.verification_level not in (None, 'contract_only'):
            raise EvidenceError({'code': 'UNSUPPORTED_IMPLEMENTATION_CLAIM',
                                 'expected': 'implementation verification requires a ValidationRun'})
        if capability.algorithm_spec:
            required = {'version', 'task_type', 'inputs', 'outputs', 'parameters', 'algorithm_spec',
                        'evaluation_metrics', 'supported_directions'}
            evidence = capability.field_evidence or {}
            if not required <= set(evidence) or not all(getattr(capability, k) for k in required):
                raise EvidenceError({'code': 'MISSING_FIELD_EVIDENCE',
                    'field': f'capabilities[{cap_index}]', 'expected': sorted(required),
                    'missing_evidence': sorted(required - set(evidence)),
                    'missing_values': sorted(k for k in required if not getattr(capability, k))})
            for field, cite in evidence.items():
                if cite.chunk_id not in by_id or cite.quote not in by_id[cite.chunk_id]['payload']['text']:
                    raise EvidenceError({'code': 'QUOTE_NOT_IN_CHUNK', 'field': field})
        for cite_index, cite in enumerate(capability.citations):
            if cite.chunk_id not in by_id or cite.quote not in by_id[cite.chunk_id]["payload"]["text"]:
                raise EvidenceError({"code": "QUOTE_NOT_IN_CHUNK", "field": f"capabilities[{cap_index}].citations[{cite_index}].quote",
                                     "chunk_id": cite.chunk_id, "actual": cite.quote,
                                     "expected": "exact contiguous substring of the named chunk, including whitespace; no ellipsis"})
            if cite.symbol is not None and cite.symbol not in symbol_names:
                raise EvidenceError({"code": "UNKNOWN_CODE_SYMBOL", "field": f"capabilities[{cap_index}].citations[{cite_index}].symbol",
                                     "actual": cite.symbol, "allowed": sorted(symbol_names)})
        payload = {**capability.model_dump(mode="json"), "source_id": source["id"], "origin": origin,
                   "source_status": "source_checked", "knowledge_status": "extracted_unverified",
                   "implementation_verified": False, "response_evidence": response_evidence, "required_imports": unsupported}
        cap_id = identity("capability", payload)
        for name in unsupported:
            record = next((item for item in source['payload'].get('import_evidence', []) if item['name'] == name), None)
            chunk = next((item for item in chunks if record and item['payload']['start_line'] <= record['line']
                          and item['payload']['end_line'] >= record['end_line']), chunks[0])
            cite = {'chunk_id': chunk['id'], 'quote': record['quote'][:2000] if record else chunk['payload']['text'][:2000], 'symbol': None}
            value = {'name': name, 'definition': {'required_import': name}, 'citations': [cite], 'origin': origin}
            env_id = identity('environment', value)
            nodes.append({'id': env_id, 'kind': 'Environment', 'payload': value})
            relations.append({'source': cap_id, 'relation': 'DEPENDS_ON', 'target': env_id, 'provenance': response_evidence})
        nodes.append({"id": cap_id, "kind": "Capability", "payload": payload})
        for cite in capability.citations:
            relations.append({"source": cap_id, "relation": "DERIVED_FROM", "target": cite.chunk_id, "provenance": response_evidence})
        for description in capability.constraints:
            value = {"description": description, "citations": [c.model_dump(mode="json") for c in capability.citations],
                     "conditions_status": capability.conditions_status, "knowledge_status": "extracted_unverified"}
            constraint_id = identity("constraint", value)
            nodes.append({"id": constraint_id, "kind": "Constraint", "payload": value})
            relations.append({"source": cap_id, "relation": "REQUIRES", "target": constraint_id, "provenance": response_evidence})
    return nodes, relations


async def ingest(root, paths, knowledge, gateway, task_id, *, origin):
    # A source chunk is a content identity, independent of the extraction task.
    # Re-extraction creates new capability evidence while retaining existing immutable
    # material edges and explicitly disclosing their original provenance.
    existing = knowledge.snapshot()
    material_edges = {(r["source"], r["target"]): r for r in existing["relations"]
                      if r["relation"] == "DERIVED_FROM"}
    results = []
    for index, relative in enumerate(paths):
        source, chunks = import_material(root, relative)
        public_input = {"source": source, "chunks": chunks}
        instructions = EXTRACTION_INSTRUCTIONS
        stage = f"extract-{index}"
        for check_attempt in range(2):
            try:
                result = await gateway.ask(task_id, stage, Extraction, public_input, instructions)
            except ModelCallError as error:
                if error.code != ErrorCode.MODEL_OUTPUT_INVALID or error.reason != "structured_output_invalid":
                    raise
                # A malformed source must not erase the batch report or prevent
                # subsequent sources from being checked. Never ingest its output.
                record = {"source_id": source["id"], "path": relative, "status": "REJECTED",
                          "feedback": {"code": error.code.value, "issues": error.validation_issues},
                          "stage": stage, "check_attempt": check_attempt}
                gateway.store.register_document(task_id, record, "extraction-check-failure")
                break
            evidence = {"task_id": task_id, "stage": stage, "prompt_version": gateway.prompt_version, "extraction_protocol": "metrics-extraction/3"}
            try:
                nodes, relations = checked_extraction(source, chunks, result, origin=origin, response_evidence=evidence)
                reused_edges = []
                chunk_ids = {chunk["id"] for chunk in chunks}
                for edge in relations:
                    prior = material_edges.get((edge["source"], edge["target"]))
                    if prior and edge["source"] in chunk_ids and edge["target"] == source["id"]:
                        edge["provenance"] = prior["provenance"]
                        reused_edges.append(prior)
                knowledge.add(nodes, relations)
                record = {"source_id": source["id"], "path": relative, "status": "source_checked",
                          "capabilities": [node["id"] for node in nodes if node["kind"] == "Capability"],
                          "reused_immutable_source_edges": reused_edges}
                break
            except EvidenceError as error:
                record = {"source_id": source["id"], "path": relative, "status": "REJECTED", "feedback": error.feedback,
                          "stage": stage, "check_attempt": check_attempt}
                gateway.store.register_document(task_id, record, "extraction-check-failure")
                if check_attempt:
                    break
                stage = f"extract-{index}-citation-fix"
                public_input = {"source": source, "chunks": chunks,
                                "previous": result.model_dump(mode="json"), "feedback": error.feedback}
                instructions = EXTRACTION_INSTRUCTIONS + "修正feedback列出的字段或引用错误，返回完整Extraction实例。"
        gateway.store.register_document(task_id, record, "extraction-check")
        results.append(record)
    return {"sources": results, "snapshot": knowledge.snapshot(), "origin": origin}


ALIASES = {"内存": "memory", "CPU": "cpu", "磁盘": "disk", "延迟": "latency", "网络": "network",
           "持续": "sustained", "周期": "periodic", "缺失": "missing", "阈值": "threshold"}


def latest_versions(snapshot):
    result = {}
    for node in snapshot['nodes']:
        p = node['payload']
        if node['kind'] == 'Capability' and p.get('source_status') == 'registered_card':
            version = tuple(map(int, p['version'].split('.')))
            if version > tuple(map(int, result.get(p['method_id'], '0.0.0').split('.'))):
                result[p['method_id']] = p['version']
    return result


def retrieve(snapshot, *, requirement, metric_kind, allowed_methods, history_points, origin="llm_api", enabled=True, dependency_profile="metrics-py312-stdlib/1", metric_name=None):
    from factory.metrics.retrieval_policy import relevance_score
    from factory.metrics.experience_context import development_feedback, prioritize_experiences
    verify_snapshot(snapshot)
    by_id = {node["id"]: node for node in snapshot["nodes"]}
    query = requirement.lower()
    terms = set(query.split())
    for word, alias in ALIASES.items():
        if word.lower() in query:
            terms.update([word.lower(), alias])
    ranked, excluded = [], []
    versions = latest_versions(snapshot)
    for node in snapshot["nodes"]:
        if node["kind"] != "Capability":
            continue
        cap = node["payload"]
        reason = None
        if cap["origin"] != origin and not (cap["origin"] == "reference" and cap.get("source_status") == "registered_card"):
            reason = "provenance_mode_mismatch"
        elif cap["method_id"] is not None and cap["method_id"] not in allowed_methods:
            reason = "method_not_allowed"
        elif cap.get('source_status') == 'registered_card' and cap.get('version') != versions[cap['method_id']]:
            reason = 'superseded_capability_version'
        elif cap["conditions_status"] == "conflict":
            reason = "conflicting_conditions"
        elif cap["conditions_status"] != "unknown":
            if metric_kind not in cap["metric_kinds"]:
                reason = "metric_kind_not_supported"
            elif not cap["single_host"]:
                reason = "not_single_host"
            elif cap["min_history"] is not None and history_points < cap["min_history"]:
                reason = "insufficient_history"
        if reason is None and (cap.get('dependency_profile') != dependency_profile or cap.get('required_imports')):
            reason = 'dependency_profile_incompatible'
        if reason:
            excluded.append({"capability_id": node["id"], "reason": reason})
        else:
            text = canonical(cap).lower()
            ranked.append((sum(term in text for term in terms), node))
    score = relevance_score(requirement, [node for _, node in ranked], metric_name=metric_name)
    if score < 1:
        return {"snapshot_id": snapshot["snapshot_id"], "schema_version": snapshot["schema_version"],
                "status": "NO_RELEVANT_CAPABILITY", "relevance_score": score,
                "capabilities": [], "mode": "structured" if enabled else "none", "knowledge_ids": [],
                "chunks": [], "experiences": [], "excluded": excluded}
    if not enabled:
        return {"snapshot_id": snapshot["snapshot_id"], "schema_version": snapshot["schema_version"],
                "capabilities": [], "mode": "none", "knowledge_ids": [], "chunks": [],
                "experiences": [], "excluded": []}
    chunks, ids = [], []
    cards = [{'id': n['id'], **n['payload']} for _, n in sorted(ranked, key=lambda pair: (-pair[0], pair[1]['id']))
             if n['payload'].get('algorithm_spec')]
    for cap in cards:
        ids.append(cap['id'])
        # Every material supporting a generation specification is mandatory;
        # the optional context limit below must never truncate these quotations.
        evidence = cap.get('spec_sources') or [cap['field_evidence']['algorithm_spec']]
        for cite in evidence:
            chunk = by_id[cite['chunk_id']]
            source = by_id[chunk['payload']['source_id']]
            if chunk['id'] not in {item['id'] for item in chunks}:
                chunks.append({'id': chunk['id'], **chunk['payload'], 'source': source['payload']['path'],
                               'source_sha256': source['payload']['sha256'], 'capability_id': cap['id'],
                               'summary': cap['summary'], 'conditions_status': cap['conditions_status'],
                               'knowledge_status': 'source_checked'})
            ids.extend([chunk['id'], source['id']])
    for _, node in sorted(ranked, key=lambda pair: (-pair[0], pair[1]["id"])):
        for cite in node["payload"]["citations"]:
            if len(chunks) >= 6:
                break
            if cite["chunk_id"] not in {chunk["id"] for chunk in chunks}:
                chunk = by_id[cite["chunk_id"]]
                source = by_id[chunk["payload"]["source_id"]]
                chunks.append({"id": chunk["id"], **chunk["payload"], "source": source["payload"]["path"],
                               "source_sha256": source["payload"]["sha256"], "capability_id": node["id"],
                               "summary": node["payload"]["summary"], "conditions_status": node["payload"]["conditions_status"],
                               "knowledge_status": "extracted_unverified"})
                ids += [node["id"], chunk["id"]]
    experiences = []
    for node in snapshot["nodes"]:
        if node["kind"] == "Experience" and node["payload"].get("origin") == origin:
            value = node["payload"]
            # Method-check/1 incorrectly rejected equal string-valued evidence.
            # Keep the original audit record, but never turn that false rejection
            # into algorithm advice for another model task.
            if value.get("method_validation_protocol", "metrics-method-check/1") == "metrics-method-check/1" and any(
                check.get("difference", {}).get("code") in {"STATE_RELOAD_DIFFERENCE", "RESET_PREFIX_DIFFERENCE"}
                for check in value.get("development_feedback", [])
            ):
                excluded.append({"experience_id": node["id"], "reason": "requires_revalidation_after_method_check_v1_issue"})
                continue
            if value["method_id"] in allowed_methods and value["metric_kind"] == metric_kind:
                keys = ("method_id", "metric_kind", "origin", "implementation_id", "validation_id",
                        "reusable_implementation", "implementation_verified", "method_validation_protocol",
                        "effect_status", "acceptance_status", "issue", "action", "reuse_scope", "final_feedback_policy")
                experiences.append({"id": node["id"], **{key: value[key] for key in keys if key in value},
                                    "development_feedback": development_feedback(value.get("development_feedback", []))})
    # Explicitly bounded successful and failed risk hints. Never retrieve final values/metrics.
    # Reserve a small quota for every permitted method, so another candidate's
    # histories cannot crowd out this method before its generation context exists.
    experiences = [e for method in dict.fromkeys(allowed_methods) for reusable in (False, True)
                   for e in prioritize_experiences(
                       [e for e in experiences if e["method_id"] == method
                        and bool(e["reusable_implementation"]) == reusable], [method])[:2]]
    ids += [e["id"] for e in experiences]
    return {"snapshot_id": snapshot["snapshot_id"], "schema_version": snapshot["schema_version"],
            "status": "RETRIEVED", "relevance_score": score, "capabilities": cards, "mode": "structured", "knowledge_ids": sorted(set(ids)),
            "chunks": chunks, "experiences": experiences, "excluded": excluded,
            "conditions_notice": "extracted applicability claims are source-linked, not implementation verification"}
