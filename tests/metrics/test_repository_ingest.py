from factory.metrics.knowledge import import_material, checked_extraction, retrieve
from factory.metrics.local_store import LocalKnowledgeStore
from factory.metrics.repository_ingest import repository_sources
from tests.metrics.test_knowledge import extracted


def test_repository_ast_chunks_dependencies_are_retained_then_filtered(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / '__init__.py').write_text('')
    (repo / 'a.py').write_text('import numpy as np\ndef normalize(x):\n    """Vector normalization."""\n    return np.asarray(x)\n')
    (repo / 'b.py').write_text('from a import normalize\ndef detect(x):\n    return normalize(x)\n')
    (repo / 'c.py').write_text('def passthrough(x):\n    return x\n')
    (repo / 'tests').mkdir()
    (repo / 'tests/test_hidden.py').write_text('raise RuntimeError("MUST NOT EXECUTE")')
    (repo / '.venv').mkdir()
    (repo / '.venv/hidden.py').write_text('raise RuntimeError("MUST NOT EXECUTE")')
    paths = repository_sources(repo)
    assert paths == ['a.py', 'b.py', 'c.py']
    store = LocalKnowledgeStore(tmp_path / 'knowledge.sqlite')
    for path in paths:
        source, chunks = import_material(repo, path)
        assert source['payload']['symbols'][0]['signature'] == 'x'
        if path == 'a.py':
            assert source['payload']['calls'][0]['callee'] == 'np.asarray'
            assert chunks[0]['payload']['end_line'] == 4
        store.add(*checked_extraction(source, chunks, extracted(source, chunks), origin='mock', response_evidence={}))
    snapshot = store.snapshot()
    assert len([n for n in snapshot['nodes'] if n['kind'] == 'Source']) == 3
    assert any(n['kind'] == 'Environment' and n['payload']['name'] == 'numpy' for n in snapshot['nodes'])
    assert any(r['relation'] == 'DEPENDS_ON' for r in snapshot['relations'])
    found = retrieve(snapshot, requirement='memory', metric_kind='gauge', allowed_methods=['rolling_mad'], history_points=60, origin='mock')
    assert len([r for r in found['excluded'] if r['reason'] == 'dependency_profile_incompatible']) == 2
