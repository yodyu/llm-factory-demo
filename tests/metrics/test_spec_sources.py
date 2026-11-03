"""Expert material evidence must survive registration, freezing and generation."""

import asyncio
import copy
import json
import os
from pathlib import Path
import shutil

import pytest

from contracts.capability import CapabilityCard
from contracts.metrics import CandidatePlan, DetectorConfig
from factory.metrics.capability_knowledge import plugin_records, register_plugins
from factory.metrics.capability_registry import CapabilityRegistry, registry
from factory.metrics.generation import generate
from factory.metrics.knowledge import identity, retrieve, verify_snapshot
from factory.metrics.neo4j_store import snapshot_value
from factory.metrics.planning import public_context
from tests.metrics.test_knowledge_backends import repository as repository_fixture
from tests.metrics.test_plugin_generation import ControlledGateway
from tests.metrics.test_runtime import task

ROOT = Path(__file__).resolve().parents[2]
repository = repository_fixture


def copied_sources(tmp_path, monkeypatch):
    plugins, materials = tmp_path / 'plugins', tmp_path / 'materials'
    shutil.copytree(ROOT / 'capabilities', plugins)
    shutil.copytree(ROOT / 'materials', materials)
    monkeypatch.setenv('FACTORY_CAPABILITIES_DIRECTORY', str(plugins))
    monkeypatch.setenv('FACTORY_MATERIALS_DIRECTORY', str(materials))
    return plugins, materials


@pytest.mark.parametrize('damage', ['missing', 'hash', 'quote', 'lines', 'escape'])
def test_registry_rejects_invalid_material_evidence(tmp_path, monkeypatch, damage):
    plugins, materials = copied_sources(tmp_path, monkeypatch)
    path = plugins / 'ewma/capability.json'
    card = json.loads(path.read_text())
    ref = card['spec_sources'][0]
    material = materials / ref['path'].removeprefix('materials/')
    if damage == 'missing':
        material.unlink()
    elif damage == 'hash':
        material.write_text(material.read_text() + '\nchanged material\n')
    elif damage == 'quote':
        ref['quote'] += ' fabricated claim'
    elif damage == 'lines':
        ref['start_line'] += 1
    else:
        outside = tmp_path / 'outside.txt'
        outside.write_bytes(material.read_bytes())
        material.unlink()
        material.symlink_to(outside)
    path.write_text(json.dumps(card, ensure_ascii=False))
    with pytest.raises(ValueError, match='spec source'):
        CapabilityRegistry(plugins, materials=materials)


@pytest.mark.parametrize('path', ['../materials/a.txt', 'materials/../a.txt', '/materials/a.txt', 'capabilities/a.json'])
def test_manifest_requires_a_safe_material_path(path):
    card = json.loads((ROOT / 'capabilities/ewma/capability.json').read_text())
    card['spec_sources'][0]['path'] = path
    with pytest.raises(ValueError):
        CapabilityCard.model_validate(card)


def test_cached_registry_and_direct_registration_recheck_materials(tmp_path, monkeypatch):
    plugins, materials = copied_sources(tmp_path, monkeypatch)
    live = registry()
    card = live.get('ewma')
    material = materials / 'metrics/06-ewma.txt'
    material.write_text(material.read_text() + '\nchanged material\n')
    with pytest.raises(ValueError, match='spec source size/hash'):
        registry()
    with pytest.raises(ValueError, match='spec source size/hash'):
        plugin_records(card, plugins / 'ewma', materials=materials)


def test_material_edges_and_quotes_reach_generation_on_both_backends(repository, tmp_path, monkeypatch):
    copied_sources(tmp_path, monkeypatch)
    register_plugins(repository)
    conditions = dict(requirement='用 EWMA 检测主机负载', metric_kind='gauge',
                      allowed_methods=['fixed_threshold', 'rolling_mad', 'ewma'], history_points=60, origin='mock')
    frozen, found = repository.freeze(**conditions)
    assert found == retrieve(frozen, **conditions)
    by_id = {node['id']: node for node in frozen['nodes']}
    edges = {(edge['source'], edge['relation'], edge['target']) for edge in frozen['relations']}
    for cap in found['capabilities']:
        assert cap['origin'] == 'reference' and cap['source_status'] == 'registered_card'
        assert cap['field_evidence']['algorithm_spec']['chunk_id'] == cap['spec_sources'][0]['chunk_id']
        assert cap['manifest_field_evidence']['algorithm_spec'] != cap['field_evidence']['algorithm_spec']
        for ref in cap['spec_sources']:
            chunk = by_id[ref['chunk_id']]
            source = by_id[chunk['payload']['source_id']]
            assert source['payload']['path'] == ref['path']
            assert source['payload']['sha256'] == ref['sha256']
            assert (cap['id'], 'DERIVED_FROM', chunk['id']) in edges
            assert (chunk['id'], 'DERIVED_FROM', source['id']) in edges
            assert ref['chunk_id'] in found['knowledge_ids'] and source['id'] in found['knowledge_ids']
            assert any(item['id'] == ref['chunk_id'] and item['text'] == ref['quote'] for item in found['chunks'])

    from factory.metrics.synthetic import generate as synthetic
    manifest = synthetic('memory_shift')['manifest']
    spec = task(allowed_methods=conditions['allowed_methods'])
    context = public_context(spec, manifest, [], found)
    cap = next(cap for cap in found['capabilities'] if cap['method_id'] == 'ewma')
    candidate = CandidatePlan(candidate_id='material-ewma', config=DetectorConfig(method_id='ewma'),
        capability_id=cap['id'], knowledge_ids=[cap['id']], parameter_sources={}, limitations=[], selection_reason='material evidence')
    expected = copy.deepcopy(context)
    # Generation and retrieval must continue from the frozen evidence, even when
    # the live material becomes unavailable after the freeze.
    (tmp_path / 'materials/metrics/06-ewma.txt').unlink()
    assert retrieve(frozen, **conditions) == found
    gateway = ControlledGateway()
    asyncio.run(generate(gateway, spec, candidate, context, version=0))
    provided = gateway.calls[0][3]
    assert provided['capability']['spec_sources'] == cap['spec_sources']
    assert all(any(chunk['id'] == ref['chunk_id'] and chunk['text'] == ref['quote']
                   for chunk in provided['task']['knowledge']['chunks']) for ref in cap['spec_sources'])
    assert context == expected


@pytest.mark.parametrize('damage', ['edge', 'hash', 'line', 'field'])
def test_frozen_material_evidence_cannot_lose_its_provenance(damage):
    plugins = registry()
    nodes, relations, cap = plugin_records(plugins.get('ewma'), plugins.directories['ewma'])
    ref = cap['payload']['spec_sources'][0]
    if damage == 'edge':
        relations = [edge for edge in relations if (edge['source'], edge['target']) != (cap['id'], ref['chunk_id'])]
    elif damage == 'hash':
        ref['sha256'] = 'sha256:' + '0' * 64
    elif damage == 'line':
        ref['start_line'] += 1
    else:
        cap['payload']['field_evidence']['algorithm_spec'] = cap['payload']['manifest_field_evidence']['algorithm_spec']
    with pytest.raises(ValueError, match='spec source|specification must cite'):
        verify_snapshot(snapshot_value(nodes, relations))


def test_existing_manifest_only_card_is_superseded_without_rewriting_its_snapshot(repository):
    plugins = registry()
    nodes, relations, cap = plugin_records(plugins.get('ewma'), plugins.directories['ewma'])
    old = copy.deepcopy(cap)
    old['payload'].pop('spec_sources')
    old['payload']['field_evidence'] = old['payload'].pop('manifest_field_evidence')
    old['payload']['version'] = '1.0.0'
    old['id'] = identity('capability', old['payload'])
    relations = [{**edge, 'source': old['id'] if edge['source'] == cap['id'] else edge['source']}
                 for edge in relations]
    repository.add([old if node['id'] == cap['id'] else node for node in nodes], relations)
    original = repository.snapshot()
    register_plugins(repository)
    register_plugins(repository)
    updated = repository.snapshot()
    assert verify_snapshot(original) == original
    assert any(edge['source'] != old['id'] and edge['relation'] == 'SUPERSEDES' and edge['target'] == old['id']
               for edge in updated['relations'])
    assert next(node for node in updated['nodes'] if node['id'] == old['id']) == old


def test_material_linked_ewma_runs_in_sandbox_and_publishes(tmp_path):
    image = os.environ.get('FACTORY_METRICS_IMAGE')
    if not image:
        pytest.skip('需要设置 FACTORY_METRICS_IMAGE 以验证材料溯源后的真实沙箱闭环')
    from factory.metrics.local_store import LocalKnowledgeStore
    from factory.metrics.model import make_gateway
    from factory.metrics.runtime import MetricsStore
    from factory.metrics.synthetic import generate as synthetic, write_dataset
    from factory.metrics.workflow import run

    knowledge = LocalKnowledgeStore(tmp_path / 'knowledge.sqlite')
    register_plugins(knowledge)
    data = tmp_path / 'data'
    write_dataset(data, synthetic('memory_shift'))
    state = tmp_path / 'state'
    store = MetricsStore(state / 'runtime.sqlite')
    result = asyncio.run(run(store, make_gateway(store, mode='mock'), state=state,
        dataset_root=data, knowledge=knowledge, image=image, task_id='material-ewma',
        task_input={'requirement': '用 EWMA 检测内存持续升高', 'anomaly_target': 'upper',
                    'allowed_methods': ['ewma'], 'explicit_constraints': {}}))
    report = json.loads((Path(result['directory']) / 'report.json').read_text())
    assert result['status'] == 'COMPLETED' and result['publication']['status'] == 'PUBLISHED'
    cap = report['retrieval']['capabilities'][0]
    assert cap['version'] == '1.1.0' and cap['spec_sources'][0]['path'] == 'materials/metrics/06-ewma.txt'
    assert report['final']['engineering_status'] == 'PASSED'
    assert all(candidate['versions'][-1]['capability_id'] == cap['id'] for candidate in report['candidates'])
    assert any(edge['source'] == cap['id'] and edge['relation'] == 'IMPLEMENTED_BY'
               for edge in knowledge.snapshot()['relations'])
