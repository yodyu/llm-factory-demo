"""Explicit, read-only legacy export followed by verified Neo4j import."""
from factory.metrics.capability_registry import default_methods
import json
import shutil
import sqlite3
from pathlib import Path

from factory.metrics.knowledge import retrieve, verify_snapshot
from factory.metrics.neo4j_store import snapshot_value, validate_records
from factory.runtime.artifacts import digest


def export_legacy(source, backup):
    source, backup = Path(source), Path(backup)
    if not source.is_file() or source.is_symlink():
        raise ValueError('regular legacy SQLite/JSON source required')
    backup.mkdir(parents=True, exist_ok=False, mode=0o700)
    before = digest(source.read_bytes())
    if source.suffix in {'.sqlite', '.db'}:
        # mode=ro plus backup API includes committed WAL contents, without checkpointing source.
        with sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True) as db:
            db.execute('PRAGMA query_only=ON')
            if db.execute('PRAGMA application_id').fetchone()[0] != 0x4D4B4E57:
                raise ValueError('not a metrics knowledge SQLite source')
            with sqlite3.connect(backup/'knowledge.sqlite') as target:
                db.backup(target)
        with sqlite3.connect(backup/'knowledge.sqlite') as db:
            nodes = [{'id':r[0],'kind':r[1],'payload':json.loads(r[2])} for r in db.execute('SELECT id,kind,payload FROM nodes ORDER BY id')]
            relations = [{'source':r[0],'relation':r[1],'target':r[2],'provenance':json.loads(r[3])} for r in db.execute('SELECT source,relation,target,provenance FROM relations ORDER BY source,relation,target')]
            receipts = [json.loads(r[0]) for r in db.execute('SELECT receipt FROM publications ORDER BY id')]
        snapshot = snapshot_value(nodes,relations)
    else:
        shutil.copyfile(source,backup/'original.json')
        snapshot = verify_snapshot(json.loads((backup/'original.json').read_text()))
        receipts=[]
    validate_records(snapshot['nodes'],snapshot['relations'])
    verify_snapshot(snapshot)
    if digest(source.read_bytes()) != before:
        raise ValueError('source changed during backup; stop migration and retry')
    (backup/'snapshot.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n')
    return snapshot, receipts, before


def migrate(source, backup, knowledge):
    snapshot, receipts, before = export_legacy(source,backup)
    # No schema/namespace creation as a side effect. Operator must explicitly initialize target.
    target_before=knowledge.snapshot()
    existing={n['id'] for n in target_before['nodes']}
    knowledge.add(snapshot['nodes'],snapshot['relations'])
    for receipt in receipts:
        knowledge.publish([],[],receipt)
    target=knowledge.snapshot()
    by_id={n['id']:n for n in target['nodes']}
    edges={(r['source'],r['relation'],r['target']):r for r in target['relations']}
    if not all(by_id.get(n['id'])==n for n in snapshot['nodes']):
        raise ValueError('migration entity/property verification failed')
    if not all(edges.get((r['source'],r['relation'],r['target']))==r for r in snapshot['relations']):
        raise ValueError('migration relationship/provenance verification failed')
    comparisons=[]
    for origin in sorted({n['payload'].get('origin') for n in snapshot['nodes'] if n['kind']=='Capability'}):
        for metric in ('gauge','rate'):
            for history in (5,60):
                conditions=dict(requirement='内存持续 MAD 缺失 memory',metric_kind=metric,allowed_methods=default_methods(),history_points=history,origin=origin)
                old=retrieve(snapshot,**conditions)
                _,new=knowledge.freeze(**conditions)
                # Empty target is required for exact query parity; additive imports compare source subset separately.
                equal=all(old[k]==new[k] for k in ('knowledge_ids','chunks','excluded','experiences'))
                comparisons.append({'conditions':conditions,'equal':equal,'legacy_knowledge_ids':old['knowledge_ids'],
                                    'neo4j_knowledge_ids':new['knowledge_ids'],'legacy_excluded':old['excluded'],'neo4j_excluded':new['excluded']})
    result={'schema_version':'metrics-migration/1','source_sha256':before,'source_snapshot_id':snapshot['snapshot_id'],
            'target_snapshot_id':target['snapshot_id'],'nodes':len(snapshot['nodes']),'relations':len(snapshot['relations']),
            'nodes_added':len({n['id'] for n in snapshot['nodes']}-existing),'endpoint_property_provenance_check':'PASSED',
            'source_unchanged':digest(Path(source).read_bytes())==before,'id_mapping':'identity; original payload and IDs preserved',
            'typed_properties':'Neo4j projection; canonical payload unchanged','comparisons':comparisons,
            'all_queries_equal':all(c['equal'] for c in comparisons)}
    result['status'] = 'VERIFIED' if result['all_queries_equal'] else 'REVIEW_REQUIRED'
    Path(backup,'migration-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result
