"""Check expert specification quotations against bounded original material bytes."""

import os
from pathlib import Path

from contracts.capability import SpecSource
from factory.runtime.artifacts import digest


def material_root():
    return Path(os.environ.get('FACTORY_MATERIALS_DIRECTORY',
                               Path(__file__).resolve().parents[3] / 'materials')).resolve()


def source_path(reference, root):
    path = root / reference.path.removeprefix('materials/')
    if (not path.resolve().is_relative_to(root) or path.is_symlink()
            or not path.is_file() or path.suffix not in {'.md', '.txt', '.py'}):
        raise ValueError('spec source must be an existing bounded material file: ' + reference.path)
    return path


def checked_spec_sources(card, root=None):
    root = Path(root).resolve() if root is not None else material_root()
    if not card.spec_sources:
        raise ValueError('capability spec sources missing')
    evidence = []
    for reference in card.spec_sources:
        path = source_path(reference, root)
        with path.open('rb') as stream:
            raw = stream.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024 or digest(raw) != reference.sha256:
            raise ValueError('spec source size/hash mismatch: ' + reference.path)
        lines = raw.decode('utf-8').splitlines()
        if reference.end_line > len(lines) or '\n'.join(lines[reference.start_line - 1:reference.end_line]) != reference.quote:
            raise ValueError('spec source quote/line mismatch: ' + reference.path)
        evidence.append(reference)
    return evidence


def source_signature(cards, root):
    """Material edits/removals invalidate the live registry cache as plugin edits do."""
    return tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size)
                 for card in cards for reference in card.spec_sources
                 for path in [source_path(reference, root)])


def verify_frozen_spec_sources(capability, by_id, edges):
    """Verify the frozen chain without consulting live materials or the registry."""
    payload = capability['payload']
    references = payload.get('spec_sources')
    if not references:
        raise ValueError('capability spec sources missing')
    for item in references:
        reference = SpecSource.model_validate({k: v for k, v in item.items() if k != 'chunk_id'})
        chunk = by_id.get(item.get('chunk_id'))
        source = by_id.get(chunk['payload'].get('source_id')) if chunk else None
        if (not chunk or chunk['kind'] != 'Chunk' or not source or source['kind'] != 'Source'
                or source['payload'].get('path') != reference.path
                or source['payload'].get('sha256') != reference.sha256
                or chunk['payload'].get('text') != reference.quote
                or chunk['payload'].get('sha256') != digest(reference.quote.encode())
                or chunk['payload'].get('start_line') != reference.start_line
                or chunk['payload'].get('end_line') != reference.end_line
                or (capability['id'], 'DERIVED_FROM', chunk['id']) not in edges
                or (chunk['id'], 'DERIVED_FROM', source['id']) not in edges):
            raise ValueError('capability spec source provenance mismatch')
    if payload['field_evidence']['algorithm_spec'] != {
            'chunk_id': references[0]['chunk_id'], 'quote': references[0]['quote'], 'symbol': None}:
        raise ValueError('algorithm specification must cite its material source')
