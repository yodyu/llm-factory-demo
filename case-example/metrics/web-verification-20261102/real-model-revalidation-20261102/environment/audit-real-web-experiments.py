import hashlib
import json
import shutil
import sqlite3
import tarfile
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from factory.metrics.budget import read_campaign
from factory.metrics.knowledge_store import open_knowledge
from factory.metrics.review import knowledge_usage
from factory.metrics.runtime import MetricsStore
from factory.models.checks import validate_structured
from factory.models.transport import ModelCallError
from contracts.metrics_knowledge import Extraction

root = Path('/path/to/llm-factory/real-web-revalidation-20261102')
demo = root / 'demo'
state = demo / '.runtime/poc'
private = Path('/path/to/private-config/llm-factory-web-revalidation-20261102')
output = root / 'review-evidence'
output.mkdir(exist_ok=True)
def read(path):
    return json.loads(path.read_text())
def sha(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()
def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

known = {'ui-34a756c1b4ac490b': 'cpu', 'ui-15e8770de18747f7': 'memory',
         'ui-e6121958cd5a44b7': 'disk-timeout', 'ui-da4c1f50a3504008': 'disk',
         'ui-74cc4a21520a4e1b': 'repair'}
store = MetricsStore(state / 'runtime.sqlite')
with sqlite3.connect((state / 'runtime.sqlite').resolve().as_uri() + '?mode=ro', uri=True) as db:
    db.row_factory = sqlite3.Row
    operations = [dict(r) for r in db.execute('SELECT operation_id,task_id,resource,status,metadata,result_ref FROM operations ORDER BY reserved_at')]
    tasks = [dict(r) for r in db.execute('SELECT task_id,status,phase,started_at FROM tasks ORDER BY started_at')]
    artifacts = [dict(r) for r in db.execute('SELECT task_id,reference,role FROM task_artifacts')]

with open_knowledge(private / 'knowledge.json') as knowledge:
    graph = knowledge.snapshot()
by_id = {n['id']: n for n in graph['nodes']}
save(output / 'knowledge-after.json', graph)

records = []
for path in sorted((state / 'runs').glob('*/report.json')):
    report = read(path)
    task_id = report['task']['task_id']
    assert task_id in known, task_id
    label = known[task_id]
    downloaded = root / 'browser-downloads' / (label + '-report.json')
    download_checked = label != 'disk'
    if download_checked:
        assert read(downloaded) == report, (label, 'download differs from server report')
    assert report['task']['model_mode'] == 'api'
    assert report['model_usage']['requests'] > 0
    if label == 'disk-timeout':
        assert report['status'] == 'FAILED' and report['failure']['code'] == 'MODEL_TIMEOUT'
        assert not report['candidates']
    else:
        assert report['status'] == 'COMPLETED', (label, report.get('failure'))
    assert report['origin'] == ('fault_injection' if label == 'repair' else 'llm_api')
    folder = output / 'runs' / label
    folder.mkdir(parents=True, exist_ok=True)
    for name in ['report.json', 'report.md', 'task.json', 'plans.json', 'selection.json', 'publication.json',
                 'retrieval.json', 'dataset-manifest.json', 'requirement-draft.json', 'requirement-evidence.json',
                 'orchestration.json', 'export.json', 'detection-events.json', 'detection-points.csv']:
        if (path.parent / name).is_file():
            shutil.copyfile(path.parent / name, folder / name)
    receipt = read(path.parent / 'publication.json')
    assert receipt['status'] == 'PUBLISHED'
    usage = knowledge_usage(report)
    candidate_records = []
    for candidate in report['candidates']:
        versions = candidate['versions']
        assert versions[-1]['validation']['passed']
        version_records = []
        for index, version in enumerate(versions):
            source = (path.parent / version['source_path']).read_bytes()
            assert sha(source) == version['source_sha256']
            validation = version['validation']
            assert validation['protocol'] == 'metrics-method-check/3'
            assert validation['source_sha256'] == version['source_sha256']
            if index:
                assert version['parent_source_sha256'] == versions[index-1]['source_sha256']
            if label == 'repair' and index == 0:
                assert version['origin'] == 'fault_injection' and not validation['passed']
            else:
                assert version['origin'] == 'llm_api'
                assert validation['passed'] and all(c['passed'] for c in validation['checks'])
                assert validation['verification_level'] == 'reference_verified'
            method = candidate['plan']['config']['method_id']
            for name, expected in version['plugin_hashes'].items():
                assert sha((demo / 'capabilities' / method / name).read_bytes()) == expected
            capability = by_id[version['capability_id']]['payload']
            assert capability['origin'] == 'reference' and capability['source_status'] == 'registered_card'
            assert capability['version'] == version['capability_version']
            assert sha(capability['algorithm_spec'].encode()) == version['specification_sha256']
            target = folder / version['source_path']
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source)
            check_file = target.with_name('v' + str(version['version']) + '-checks.json')
            save(check_file, validation)
            original = (path.parent / version['source_path']).with_name('model-original-v0.py')
            if original.is_file() and index == 0:
                shutil.copyfile(original, target.with_name('model-original-v0.py'))
                assert b'Deliberate test-only fault injection' not in original.read_bytes()
                assert b'Deliberate test-only fault injection' in source
            implementations = [n for n in graph['nodes'] if n['kind'] == 'Implementation'
                               and n['payload'].get('task_id') == task_id
                               and n['payload'].get('candidate_id') == candidate['candidate_id']
                               and n['payload'].get('version') == version['version']]
            assert implementations
            assert any(e['relation'] == 'IMPLEMENTED_BY' and e['source'] == version['capability_id']
                       and e['target'] == implementations[0]['id'] for e in graph['relations'])
            assert any(e['relation'] == 'EVALUATED_BY' and e['source'] == implementations[0]['id'] for e in graph['relations'])
            version_records.append({**{k:version.get(k) for k in ['version','origin','source_path','source_sha256',
                'parent_source_sha256','capability_id','capability_version','specification_sha256','knowledge_ids']},
                'passed': validation['passed'], 'verification_level': validation['verification_level'],
                'checks': validation['checks'], 'implementation_ids': [n['id'] for n in implementations]})
        candidate_records.append({'candidate_id':candidate['candidate_id'], 'config':candidate['plan']['config'],
                                  'development':candidate.get('report'), 'versions':version_records})
    if label == 'repair':
        assert len(report['candidates']) == 1 and len(report['candidates'][0]['versions']) >= 2
    prompts = []
    for entry in artifacts:
        if entry['task_id'] != task_id or entry['role'] != 'model-prompt':
            continue
        document = store.document(entry['reference'])
        request = json.loads(document['messages'][1]['content'])
        inputs = request['input']
        experiences = ((inputs.get('task') or {}).get('knowledge') or inputs.get('knowledge') or {}).get('experiences', [])
        prompts.append({'call_id':document['call_id'], 'prompt_sha256':entry['reference'],
                        'provided_experience_ids':[e['id'] for e in experiences],
                        'has_previous_source':'previous_source' in inputs,
                        'has_development_feedback':'development_feedback' in inputs})
    op_records = [{**{k:op[k] for k in ['operation_id','resource','status']}, 'metadata':json.loads(op['metadata'])}
                  for op in operations if op['task_id'] == task_id]
    job = read(state / 'jobs' / task_id / 'job.json')
    assert bool(job['args']['fault_injection']) == (label == 'repair')
    record = {'label':label, 'task_id':task_id, 'status':report['status'], 'origin':report['origin'],
              'requirement':report['task']['requirement'], 'task':report['task'],
              'usage':report['model_usage'], 'knowledge_usage':usage, 'prompts':prompts,
              'operations':op_records, 'candidates':candidate_records, 'selection':report.get('selection'),
              'final':report.get('final'), 'publication':receipt, 'failure':report.get('failure'),
              'workflow_runtime_seconds':report.get('workflow_runtime_seconds'),
              'browser_download_checked':download_checked,
              'download_matches_server':True if download_checked else None,
              'page_capture_limitation':'Saved browser permission blocked final disk page capture' if label == 'disk' else None}
    save(folder / 'audit.json', record)
    records.append(record)
assert set(r['label'] for r in records) == set(known.values())

disk = next(r for r in records if r['label'] == 'disk')
memory = next(r for r in records if r['label'] == 'memory')
memory_experiences = [n['id'] for n in graph['nodes'] if n['kind'] == 'Experience' and n['payload'].get('task_id') == memory['task_id']]
supplied = set(disk['knowledge_usage']['supplied_experiences'])
cited = set(disk['knowledge_usage']['cited_experiences'])
chain = {'memory_task_id':memory['task_id'], 'disk_task_id':disk['task_id'],
         'memory_experience_ids':memory_experiences,
         'memory_experiences_provided_to_disk':sorted(supplied.intersection(memory_experiences)),
         'memory_experiences_cited_by_disk':sorted(cited.intersection(memory_experiences)),
         'disk_code_prompts': [p for p in disk['prompts'] if ':code-' in p['call_id']]}
save(output / 'experience-chain.json', chain)

extraction_checks, extraction_schema_errors = [], []
for item in artifacts:
    if item['role'] in {'extraction-check', 'extraction-check-failure'}:
        extraction_checks.append(store.document(item['reference']))
for op in operations:
    if not op['task_id'].startswith('ingest-') or not op['result_ref']:
        continue
    response = store.document(op['result_ref']).get('response') or {}
    if response.get('text'):
        try:
            validate_structured(response['text'], Extraction)
        except ModelCallError as error:
            extraction_schema_errors.append({'operation_id':op['operation_id'], 'issues':error.validation_issues})
save(output / 'extraction-checks.json', extraction_checks)
save(output / 'extraction-schema-errors.json', extraction_schema_errors)
save(output / 'task-ledger.json', tasks)
save(output / 'budget-after.json', read_campaign(private / 'campaign.sqlite'))

zip_check = {}
zip_path = root / 'browser-downloads/cpu-delivery.zip'
cpu_path = next(p for p in (state / 'runs').glob('*/report.json') if read(p)['task']['task_id'] == 'ui-34a756c1b4ac490b')
assert zip_path.read_bytes() == (cpu_path.parent / 'delivery.zip').read_bytes()
with zipfile.ZipFile(zip_path) as archive:
    assert archive.testzip() is None
    zip_check = {'byte_equal_to_server':True, 'entries':len(archive.infolist()), 'sha256':sha(zip_path.read_bytes())}
save(output / 'cpu-delivery-check.json', zip_check)
save(output / 'audit-summary.json', {'checked_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
    'source_baseline':'real-web-source-archive', 'run_labels':known, 'checks_passed':True, 'experience_chain':chain,
    'zip_check':zip_check, 'completed':sum(r['status']=='COMPLETED' for r in records),
    'retained_failed_runs':sum(r['status']=='FAILED' for r in records)})
print(json.dumps({'checks_passed':True,'runs':[(r['label'],r['status']) for r in records],
                  'experience_chain':chain},ensure_ascii=False))
