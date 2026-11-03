import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from factory.metrics.knowledge import retrieve
from factory.metrics.knowledge_store import open_knowledge
from factory.metrics.local_store import LocalKnowledgeStore
from factory.metrics.neo4j_store import Neo4jKnowledgeStore, snapshot_value
from tests.metrics.test_neo4j import conditions, material


@pytest.fixture(params=["local", "neo4j"])
def repository(request, tmp_path):
    if request.param == "local":
        store = LocalKnowledgeStore(tmp_path / "knowledge.sqlite")
    else:
        path = os.environ.get("FACTORY_NEO4J_CONFIG", os.environ.get("METRICS_NEO4J_CONFIG"))
        if not path:
            pytest.skip("需要设置 FACTORY_NEO4J_CONFIG 以验证 Neo4j 后端契约")
        config = json.loads(Path(path).read_text())
        store = Neo4jKnowledgeStore(config["uri"], tuple(Path(config["auth_file"]).read_text().strip().split("/", 1)),
                                    namespace="contract-" + uuid4().hex)
    store.initialize()
    yield store
    if request.param == "neo4j":
        store._execute(lambda tx: tx.run("MATCH (n) WHERE n.namespace=$ns DETACH DELETE n",
                                        ns=store.namespace).consume(), write=True)
    store.close()


def test_shared_repository_contract(repository, tmp_path):
    nodes, relations = material(tmp_path)
    repository.add(nodes, relations)
    expected = snapshot_value(nodes, relations)
    assert repository.snapshot() == expected
    frozen, found = repository.freeze(**conditions())
    assert frozen == expected
    assert found == retrieve(expected, **conditions())
    assert repository.details([n["id"] for n in nodes]) == expected["nodes"]
    graph = repository.local_graph()
    assert {n["id"] for n in graph["nodes"]} == {n["id"] for n in nodes}
    receipt = {"publication_id": "contract-test"}
    assert repository.publish([], [], receipt) == receipt
    assert repository.publish([], [], receipt) == receipt
    with pytest.raises(ValueError, match="publication conflict"):
        repository.publish([], [], {**receipt, "changed": True})
    assert repository.snapshot() == expected


def test_explicit_backend_selection_never_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_KNOWLEDGE_BACKEND", "local")
    assert isinstance(open_knowledge(tmp_path / "knowledge.sqlite"), LocalKnowledgeStore)
    monkeypatch.setenv("FACTORY_KNOWLEDGE_BACKEND", "unknown")
    with pytest.raises(ValueError):
        open_knowledge(tmp_path / "missing")
    monkeypatch.setenv("FACTORY_KNOWLEDGE_BACKEND", "neo4j")
    from factory.metrics.neo4j_store import KnowledgeUnavailable
    with pytest.raises(KnowledgeUnavailable):
        open_knowledge(tmp_path / "missing.json")
    assert not (tmp_path / "missing.json").exists()


def test_shared_v2_registered_capabilities_contract(repository, tmp_path, monkeypatch):
    from factory.metrics.capability_knowledge import register_plugins
    register_plugins(repository)
    frozen, found = repository.freeze(**conditions())
    assert frozen['schema_version'] == 'metrics-knowledge/2'
    assert found == retrieve(frozen, **conditions())
    assert len(found['capabilities']) == 2
    assert {'DataContract', 'Metric', 'Environment'} <= {n['kind'] for n in frozen['nodes']}

    import shutil
    plugins = tmp_path / 'versioned-plugins'
    shutil.copytree(Path(__file__).resolve().parents[2] / 'capabilities', plugins)
    path = plugins / 'fixed_threshold/capability.json'
    card = json.loads(path.read_text())
    card['version'] = '2.0.0'
    path.write_text(json.dumps(card, ensure_ascii=False))
    monkeypatch.setenv('FACTORY_CAPABILITIES_DIRECTORY', str(plugins))
    register_plugins(repository)
    updated, retrieved = repository.freeze(**conditions())
    assert retrieved == retrieve(updated, **conditions())
    assert next(c for c in retrieved['capabilities'] if c['method_id'] == 'fixed_threshold')['version'] == '2.0.0'
    assert any(r['reason'] == 'superseded_capability_version' for r in retrieved['excluded'])
