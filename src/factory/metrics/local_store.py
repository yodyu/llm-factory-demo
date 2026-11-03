"""Explicit local knowledge repository; generated code still requires Docker."""

from factory.metrics.knowledge import LegacySQLiteKnowledgeStore, identity, retrieve


class LocalKnowledgeStore(LegacySQLiteKnowledgeStore):
    namespace = "local"

    def initialize(self):
        # Tables are initialized transactionally by the base constructor.
        return None

    def close(self):
        # Every operation owns and closes its connection.
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @staticmethod
    def insert(db, nodes, relations):
        from factory.metrics.neo4j_store import validate_records
        from factory.metrics.knowledge import verify_snapshot
        from factory.metrics.neo4j_store import snapshot_value
        import json

        validate_records(nodes, relations)
        LegacySQLiteKnowledgeStore.insert(db, nodes, relations)
        # Validate the complete graph in the same transaction, so bad citations
        # and endpoint kinds roll back just as they do in the Neo4j repository.
        records = [dict(r) for r in db.execute("SELECT * FROM nodes ORDER BY id")]
        records = [{**r, "payload": json.loads(r["payload"])} for r in records]
        edges = [dict(r) for r in db.execute("SELECT * FROM relations")]
        edges = [{**r, "provenance": json.loads(r["provenance"])} for r in edges]
        verify_snapshot(snapshot_value(records, edges))
        by_id = {n["id"]: n for n in records}
        from factory.metrics.knowledge import RELATION_PAIRS
        pairs = RELATION_PAIRS
        links = {(r["source"], r["relation"], r["target"]) for r in edges}
        for edge in edges:
            if (by_id[edge["source"]]["kind"], by_id[edge["target"]]["kind"]) not in pairs[edge["relation"]]:
                raise ValueError("invalid relationship endpoint kinds")
        for node in nodes:
            if node["kind"] != "Capability":
                continue
            for cite in node["payload"]["citations"]:
                chunk = by_id.get(cite["chunk_id"])
                if (not chunk or chunk["kind"] != "Chunk"
                    or cite["quote"] not in chunk["payload"]["text"]
                    or (node["id"], "DERIVED_FROM", chunk["id"]) not in links):
                    raise ValueError("capability citation or graph provenance invalid")
                source = by_id[chunk["payload"]["source_id"]]
                if (chunk["id"], "DERIVED_FROM", source["id"]) not in links:
                    raise ValueError("capability graph provenance invalid")
                symbols = {s[k] for s in source["payload"].get("symbols", [])
                           for k in ("name", "qualified_name") if k in s}
                if cite.get("symbol") is not None and cite["symbol"] not in symbols:
                    raise ValueError("unknown source AST symbol")

    def freeze(self, **conditions):
        snapshot = self.snapshot()
        return snapshot, retrieve(snapshot, **conditions)

    def details(self, ids):
        if len(ids) > 128:
            raise ValueError("node detail limit exceeded")
        return [n for n in self.snapshot()["nodes"] if n["id"] in ids]

    def local_graph(self, *, search="", method="", origin="", status="", source="", limit=60):
        from factory.metrics.neo4j_store import properties

        limit = max(1, min(int(limit), 100))
        snapshot = self.snapshot()
        nodes, edges = snapshot["nodes"], snapshot["relations"]
        roots = []
        for node in nodes:
            p = properties(node)
            if ((not search or search in node["id"] or p.get("task_id") == search
                 or search in p.get("path", ""))
                and (not method or p.get("method_id") == method)
                and (not origin or p.get("origin") == origin)
                and (not status or status in (p.get("verification_status"), p.get("effect_status")))
                and (not source or source in (p.get("source_id"), node["id"], p.get("path")))):
                roots.append(node["id"])
        roots = roots[:min(limit, 3 if not search and not method and not source else 10)]
        if not any((search, method, origin, status, source)):
            first = {}
            for node in nodes:
                first.setdefault(node["kind"], node["id"])
            roots = [first[k] for k in sorted(first)]
        distance = {root: 0 for root in roots}
        for depth in range(1, 4):
            reached = set(distance)
            for edge in edges:
                if edge["source"] in reached:
                    distance.setdefault(edge["target"], depth)
                if edge["target"] in reached:
                    distance.setdefault(edge["source"], depth)
        ids = set(sorted(distance, key=lambda key: (distance[key], key))[:limit])
        return {"nodes": [n for n in nodes if n["id"] in ids],
                "relations": [{**r, "id": identity("relation", {
                    k: r[k] for k in ("source", "relation", "target")})}
                    for r in edges if r["source"] in ids and r["target"] in ids],
                "roots": roots, "limit": limit, "scope": "live_local_graph"}
