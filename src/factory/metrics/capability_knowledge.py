"""Source-linked expert plugin cards. These nodes never claim model extraction."""
import json
import re

from contracts.metrics_knowledge import ExtractedCapability
from factory.metrics.capability_registry import registry
from factory.metrics.knowledge import identity
from factory.metrics.spec_sources import checked_spec_sources
from factory.runtime.artifacts import digest

FIELDS = {'version': 'version', 'task_type': 'task_type', 'inputs': 'inputs', 'outputs': 'outputs',
          'parameters': 'config_schema', 'defaults': 'defaults', 'algorithm_spec': 'algorithm_spec',
          'evaluation_metrics': 'evaluation_metrics', 'supported_directions': 'supported_directions',
          'dependency_profile': 'dependency_profile', 'metric_kinds': 'metric_kinds', 'min_history': 'min_history'}


def plugin_records(card, directory, *, materials=None):
    path = directory / 'capability.json'
    text = path.read_text()
    raw = json.loads(text)
    if raw.get('spec_sources') != [reference.model_dump(mode='json') for reference in card.spec_sources]:
        raise ValueError('manifest field evidence mismatch')
    source_id = identity('source', {'path': 'capabilities/' + card.method_id + '/capability.json',
                                    'sha256': digest(text.encode())})
    source = {'id': source_id, 'kind': 'Source', 'payload': {
        'path': 'capabilities/' + card.method_id + '/capability.json', 'sha256': digest(text.encode()),
        'material_type': 'json', 'origin': 'reference_plugin', 'symbols': [], 'imports': []}}
    chunks, citations = [], {}
    for field, key in FIELDS.items():
        match = re.search(r'"' + re.escape(key) + r'"\s*:\s*', text)
        value, length = json.JSONDecoder().raw_decode(text[match.end():])
        if value != raw[key] or value != getattr(card, key):
            raise ValueError('manifest field evidence mismatch')
        fragment = text[match.start():match.end() + length]
        payload = {'source_id': source_id, 'start_line': text[:match.start()].count('\n') + 1,
                   'end_line': text[:match.end() + length].count('\n') + 1,
                   'text': fragment, 'sha256': digest(fragment.encode())}
        chunk = {'id': identity('chunk', payload), 'kind': 'Chunk', 'payload': payload}
        chunks.append(chunk)
        citations[field] = {'chunk_id': chunk['id'], 'quote': fragment[:2000], 'symbol': None}
    manifest_citations = dict(citations)
    material_sources, material_chunks, spec_sources = {}, [], []
    for reference in checked_spec_sources(card, materials):
        material_id = identity('source', {'path': reference.path, 'sha256': reference.sha256})
        material_sources[material_id] = {'id': material_id, 'kind': 'Source', 'payload': {
            'path': reference.path, 'sha256': reference.sha256, 'material_type': reference.path.rsplit('.', 1)[-1],
            'origin': 'reference_material', 'symbols': [], 'imports': []}}
        p = {'source_id': material_id, 'start_line': reference.start_line, 'end_line': reference.end_line,
             'text': reference.quote, 'sha256': digest(reference.quote.encode())}
        chunk = {'id': identity('chunk', p), 'kind': 'Chunk', 'payload': p}
        material_chunks.append(chunk)
        spec_sources.append({**reference.model_dump(mode='json'), 'chunk_id': chunk['id']})
    material_citations = [{'chunk_id': ref['chunk_id'], 'quote': ref['quote'], 'symbol': None} for ref in spec_sources]
    citations['algorithm_spec'] = material_citations[0]
    payload = ExtractedCapability(local_id=card.method_id, name=card.display_name, method_id=card.method_id,
        summary=card.display_name + '；' + '；'.join(card.assumptions), metric_kinds=card.metric_kinds,
        single_host=True, min_history=card.min_history, dependency_profile=card.dependency_profile,
        conditions_status='evidenced', constraints=card.assumptions, limitations=['expert authored plugin card; not model extraction'],
        citations=[*manifest_citations.values(), *material_citations], version=card.version, task_type=card.task_type, inputs=card.inputs,
        outputs=card.outputs, parameters=card.config_schema, defaults=card.defaults, algorithm_spec=card.algorithm_spec,
        evaluation_metrics=card.evaluation_metrics, supported_directions=card.supported_directions,
        verification_level='contract_only', field_evidence=citations).model_dump(mode='json')
    payload.update(source_id=source_id, origin='reference', source_status='registered_card',
                   knowledge_status='source_checked', implementation_verified=False,
                   specification_sha256=digest(card.algorithm_spec.encode()), verification=card.verification,
                   response_evidence={'origin': 'reference', 'source_sha256': source['payload']['sha256']})
    payload['plugin_hashes'] = {p.name: digest(p.read_bytes()) for p in directory.iterdir() if p.suffix in ('.py', '.json')}
    payload.update(spec_sources=spec_sources, manifest_field_evidence=manifest_citations)
    cap = {'id': identity('capability', payload), 'kind': 'Capability', 'payload': payload}
    chunks += material_chunks
    nodes = [source, *material_sources.values(), *chunks, cap]
    edges = [{'source': c['id'], 'relation': 'DERIVED_FROM', 'target': c['payload']['source_id'],
              'provenance': {'origin': 'reference'}} for c in chunks]
    edges += [{'source': cap['id'], 'relation': 'DERIVED_FROM', 'target': c['id'],
               'provenance': {'origin': 'reference'}} for c in chunks]
    entities = [('DataContract', 'input', card.inputs, 'CONSUMES', 'inputs'),
                ('DataContract', 'output', card.outputs, 'PRODUCES', 'outputs'),
                ('Environment', card.dependency_profile, {'profile': card.dependency_profile}, 'DEPENDS_ON', 'dependency_profile')]
    entities += [('Metric', name, {'name': name}, 'EVALUATED_WITH', 'evaluation_metrics') for name in card.evaluation_metrics]
    for kind, name, value, relation, field in entities:
        p = {'name': name, 'definition': value, 'citations': [citations[field]], 'origin': 'reference'}
        node = {'id': identity(kind.lower(), p), 'kind': kind, 'payload': p}
        nodes.append(node)
        edges.append({'source': cap['id'], 'relation': relation, 'target': node['id'],
                      'provenance': {'source_id': source_id, 'field': field}})
    # Constraint evidence is its own original JSON field, never an unrelated formula quote.
    match = re.search(r'"assumptions"\s*:\s*', text)
    if card.assumptions:
        _, length = json.JSONDecoder().raw_decode(text[match.end():])
        fragment = text[match.start():match.end()+length]
        p = {'source_id': source_id, 'start_line': text[:match.start()].count('\n')+1,
             'end_line': text[:match.end()+length].count('\n')+1,
             'text': fragment, 'sha256': digest(fragment.encode())}
        constraint_chunk = {'id': identity('chunk', p), 'kind': 'Chunk', 'payload': p}
        nodes.append(constraint_chunk)
        edges.append({'source': constraint_chunk['id'], 'relation': 'DERIVED_FROM', 'target': source_id,
                      'provenance': {'origin': 'reference'}})
        constraint_cite = {'chunk_id': constraint_chunk['id'], 'quote': fragment[:2000], 'symbol': None}
    for description in card.assumptions:
        p = {'description': description, 'conditions_status': 'evidenced',
             'citations': [constraint_cite], 'knowledge_status': 'source_checked'}
        node = {'id': identity('constraint', p), 'kind': 'Constraint', 'payload': p}
        nodes.append(node)
        edges.append({'source': cap['id'], 'relation': 'REQUIRES', 'target': node['id'], 'provenance': {'origin': 'reference'}})
        edges.append({'source': node['id'], 'relation': 'DERIVED_FROM', 'target': constraint_chunk['id'], 'provenance': {'origin': 'reference'}})
    return nodes, edges, cap


def register_plugins(knowledge):
    plugins = registry()
    old = knowledge.snapshot()['nodes']
    for method, card in plugins.cards.items():
        nodes, edges, cap = plugin_records(card, plugins.directories[method], materials=plugins.materials)
        for node in old:
            p = node['payload']
            if node['kind'] != 'Capability' or p.get('source_status') != 'registered_card' or p.get('method_id') != method:
                continue
            if tuple(map(int, p['version'].split('.'))) > tuple(map(int, card.version.split('.'))):
                raise ValueError('cannot register an older capability version')
            if p['version'] == card.version and node['id'] != cap['id']:
                raise ValueError('capability version is immutable; increment version before changing card')
            if tuple(map(int, p['version'].split('.'))) < tuple(map(int, card.version.split('.'))):
                edges.append({'source': cap['id'], 'relation': 'SUPERSEDES', 'target': node['id'],
                              'provenance': {'source_id': cap['payload']['source_id']}})
        knowledge.add(nodes, edges)
