import hashlib
import json
import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from factory.metrics.budget import read_campaign
from factory.metrics.knowledge import verify_snapshot
from factory.metrics.knowledge_store import open_knowledge
from factory.metrics.reports import bound_report
from factory.metrics.review import knowledge_usage
from factory.metrics.runtime import MetricsStore
from factory.models.environment import load_environment

root = Path('/path/to/llm-factory/final-classic-web-20261103')
demo, state = root / 'demo', root / 'demo/.runtime/final-classic'
output = root / 'final-evidence'
output.mkdir(exist_ok=True)
known = json.loads((root / 'evidence/run-map.json').read_text())
store = MetricsStore(state / 'runtime.sqlite')
private = Path('/path/to/private-config/llm-factory-web-revalidation-20261102')

def read(path):
    return json.loads(path.read_text())

def sha(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

with store._transaction() as db:
    operations = [dict(r) for r in db.execute('SELECT operation_id,task_id,resource,status,metadata,result_ref FROM operations ORDER BY reserved_at')]
    artifacts = [dict(r) for r in db.execute('SELECT task_id,reference,role FROM task_artifacts')]
    tasks = [dict(r) for r in db.execute('SELECT task_id,status,phase,spec_hash,started_at FROM tasks ORDER BY started_at')]
with open_knowledge('/path/to/private-config/llm-factory-final-classic-20261103/knowledge.json') as knowledge:
    graph = knowledge.snapshot()
verify_snapshot(graph)
save(output / 'knowledge-after.json', graph)
by_id = {n['id']: n for n in graph['nodes']}
reports = {read(p)['task']['task_id']: p for p in (state / 'runs').glob('*/report.json')}
records = []
for label, task_id in known.items():
    path = reports[task_id]
    report = bound_report(store, path.parent)
    assert report['status'] == 'COMPLETED', (label, report.get('failure'))
    assert report['task']['model_mode'] == 'api'
    assert report['origin'] == ('fault_injection' if label == 'repair' else 'llm_api')
    assert report['model_usage']['requests'] > 0
    assert read(root / 'browser-downloads' / (label + '-report.json')) == report
    receipt = read(path.parent / 'publication.json')
    assert receipt['status'] == 'PUBLISHED' and set(receipt['node_ids']) <= set(by_id)
    job = read(state / 'jobs' / task_id / 'job.json')
    assert bool(job['args']['fault_injection']) == (label == 'repair')
    folder = output / 'runs' / label
    folder.mkdir(parents=True, exist_ok=True)
    for name in ['report.json', 'task.json', 'plans.json', 'selection.json', 'publication.json',
                 'retrieval.json', 'dataset-manifest.json', 'requirement-draft.json', 'requirement-evidence.json',
                 'orchestration.json', 'export.json', 'detection-events.json', 'detection-points.csv']:
        if (path.parent / name).is_file():
            shutil.copyfile(path.parent / name, folder / name)
    candidates = []
    for candidate in report['candidates']:
        versions = candidate['versions']
        assert versions[-1]['validation']['passed']
        audited_versions = []
        for index, version in enumerate(versions):
            source = (path.parent / version['source_path']).read_bytes()
            validation = version['validation']
            assert sha(source) == version['source_sha256'] == validation['source_sha256']
            assert validation['protocol'] == 'metrics-method-check/3'
            if index:
                assert version['parent_source_sha256'] == versions[index - 1]['source_sha256']
            if label == 'repair' and index == 0:
                assert version['origin'] == 'fault_injection' and not validation['passed']
            else:
                assert version['origin'] == 'llm_api'
            method = candidate['plan']['config']['method_id']
            for name, expected in version['plugin_hashes'].items():
                assert sha((demo / 'capabilities' / method / name).read_bytes()) == expected
            capability = by_id[version['capability_id']]['payload']
            assert capability['origin'] == 'reference' and capability['source_status'] == 'registered_card'
            assert capability['version'] == version['capability_version']
            assert sha(capability['algorithm_spec'].encode()) == version['specification_sha256']
            implementations = [n for n in graph['nodes'] if n['kind'] == 'Implementation'
                               and n['payload'].get('task_id') == task_id
                               and n['payload'].get('candidate_id') == candidate['candidate_id']
                               and n['payload'].get('version') == version['version']]
            assert len(implementations) == 1
            implementation_id = implementations[0]['id']
            assert any(e['relation'] == 'IMPLEMENTED_BY' and e['source'] == version['capability_id']
                       and e['target'] == implementation_id for e in graph['relations'])
            assert any(e['relation'] == 'EVALUATED_BY' and e['source'] == implementation_id for e in graph['relations'])
            target = folder / version['source_path']
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source)
            save(target.with_name(f'v{version["version"]}-checks.json'), validation)
            original = (path.parent / version['source_path']).with_name('model-original-v0.py')
            if label == 'repair' and index == 0:
                assert original.is_file()
                shutil.copyfile(original, target.with_name('model-original-v0.py'))
            audited_versions.append({**version, 'passed': validation['passed'],
                                     'implementation_id': implementation_id})
        candidates.append({'candidate_id': candidate['candidate_id'], 'config': candidate['plan']['config'],
                           'development': candidate.get('report'), 'versions': audited_versions})
    prompts = []
    for entry in artifacts:
        if entry['task_id'] != task_id or entry['role'] != 'model-prompt':
            continue
        document = store.document(entry['reference'])
        request = json.loads(document['messages'][1]['content'])
        inputs = request['input']
        experiences = ((inputs.get('task') or {}).get('knowledge') or inputs.get('knowledge') or {}).get('experiences', [])
        prompts.append({'call_id': document['call_id'], 'prompt_sha256': entry['reference'],
                        'provided_experience_ids': [e['id'] for e in experiences],
                        'has_previous_source': 'previous_source' in inputs,
                        'has_development_feedback': 'development_feedback' in inputs})
    record = {'label': label, 'task_id': task_id, 'status': report['status'], 'origin': report['origin'],
              'task': report['task'], 'requirement': report['task']['requirement'],
              'usage': report['model_usage'], 'knowledge_usage': knowledge_usage(report),
              'prompts': prompts, 'candidates': candidates, 'selection': report['selection'],
              'final': report['final'], 'publication': receipt,
              'workflow_runtime_seconds': report['workflow_runtime_seconds'],
              'operations': [{**{k: op[k] for k in ['operation_id', 'resource', 'status']},
                              'metadata': json.loads(op['metadata'])} for op in operations if op['task_id'] == task_id],
              'browser_download_matches_server': True}
    assert not record['knowledge_usage']['unprovided_citations']
    save(folder / 'audit.json', record)
    records.append(record)
assert set(known) == {'cpu', 'memory', 'disk', 'repair'}
repair_record = next(r for r in records if r['label'] == 'repair')
assert len(repair_record['candidates']) == 1
assert len(repair_record['candidates'][0]['versions']) >= 2
assert any(p['has_previous_source'] and p['has_development_feedback'] for p in repair_record['prompts'])
memory = next(r for r in records if r['label'] == 'memory')
disk = next(r for r in records if r['label'] == 'disk')
memory_ids = {n['id'] for n in graph['nodes'] if n['kind'] == 'Experience' and n['payload'].get('task_id') == memory['task_id']}
provided = memory_ids.intersection(disk['knowledge_usage']['supplied_experiences'])
cited = memory_ids.intersection(disk['knowledge_usage']['cited_experiences'])
assert provided and cited
code_prompts = [p for p in disk['prompts'] if ':code-' in p['call_id']]
assert all(p['provided_experience_ids'] for p in code_prompts)
chain = {'memory_task_id': memory['task_id'], 'disk_task_id': disk['task_id'],
         'memory_experience_ids': sorted(memory_ids), 'provided': sorted(provided), 'cited': sorted(cited),
         'disk_code_prompts': code_prompts}
save(output / 'experience-chain.json', chain)
save(output / 'task-ledger.json', tasks)
save(output / 'budget-after.json', read_campaign(private / 'campaign.sqlite'))
failures = [{'task_id': task_id, 'status': read(path)['status'], 'failure': read(path).get('failure')}
            for task_id, path in reports.items() if task_id not in known.values()]
save(output / 'other-run-records.json', failures)
cpu_zip = root / 'browser-downloads/cpu-delivery.zip'
cpu_server = reports[known['cpu']].parent / 'delivery.zip'
assert cpu_zip.read_bytes() == cpu_server.read_bytes()
with zipfile.ZipFile(cpu_zip) as archive:
    assert archive.testzip() is None
    zip_check = {'byte_equal_to_server': True, 'entries': len(archive.infolist()), 'sha256': sha(cpu_zip.read_bytes())}
save(output / 'cpu-delivery-check.json', zip_check)
save(output / 'audit-summary.json', {'checked_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
     'source_baseline': 'final-classic-source-archive', 'completed': len(records), 'runs': known, 'checks_passed': True,
     'experience_chain': chain, 'zip_check': zip_check, 'other_runs': failures})
key = load_environment(private / 'model.env')['LLM_API_KEY'].encode()
assert all(key not in p.read_bytes() for p in output.rglob('*') if p.is_file())
print(json.dumps({'completed': len(records), 'memory_experiences_cited_by_disk': len(cited),
                  'other_runs': failures}, ensure_ascii=False))
