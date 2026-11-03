"""Explicit knowledge backend selection; connection failures never trigger fallback."""
import os
from typing import Protocol


class KnowledgeRepository(Protocol):
    namespace: str
    def initialize(self): ...
    def close(self): ...
    def add(self, nodes: list, relations: list): ...
    def snapshot(self) -> dict: ...
    def freeze(self, **conditions) -> tuple[dict, dict]: ...
    def publish(self, nodes: list, relations: list, receipt: dict) -> dict: ...
    def details(self, ids: list[str]) -> list[dict]: ...
    def local_graph(self, **filters) -> dict: ...


def open_knowledge(config=None) -> KnowledgeRepository:
    backend = os.environ.get("FACTORY_KNOWLEDGE_BACKEND", "neo4j")
    if backend == "local":
        from factory.metrics.local_store import LocalKnowledgeStore
        path = config or os.environ.get("FACTORY_METRICS_KNOWLEDGE")
        if not path:
            raise ValueError("LOCAL_NOT_CONFIGURED: explicit knowledge database path required")
        return LocalKnowledgeStore(path)
    if backend != "neo4j":
        raise ValueError("FACTORY_KNOWLEDGE_BACKEND must be neo4j or local")
    from factory.metrics.neo4j_store import Neo4jKnowledgeStore
    return Neo4jKnowledgeStore.from_config(config)
