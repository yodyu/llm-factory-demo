import hashlib
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from factory.metrics.budget import read_campaign
from factory.metrics.knowledge import checked_extraction, import_material, verify_snapshot
from factory.metrics.knowledge_store import open_knowledge
from factory.metrics.reports import bound_report
from factory.metrics.runtime import MetricsStore
from factory.models.environment import load_environment
from contracts.metrics_knowledge import ExtractedCapability, Extraction

root = Path('/path/to/llm-factory/bugfix-revalidation-20261103')
demo, evidence = root / 'demo', root / 'evidence'
state = demo / '.runtime/bugfix'
store = MetricsStore(state / 'runtime.sqlite')
private = Path('/path/to/private-config/llm-factory-web-revalidation-20261102')

def save(name, value):
    (evidence / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

with sqlite3.connect(state / 'runtime.sqlite') as db:
    db.row_factory = sqlite3.Row
    operations = [dict(r) for r in db.execute('SELECT operation_id,task_id,resource,status,metadata,result_ref FROM operations ORDER BY reserved_at')]
    artifacts = [dict(r) for r in db.execute('SELECT task_id,reference,role FROM task_artifacts')]
    tasks = [dict(r) for r in db.execute('SELECT task_id,status,phase,spec_hash FROM tasks')]
documents = {}
for row in artifacts:
    if row['task_id'].startswith('ingest-') and row['role'] in {
        'model-prompt', 'model-output', 'extraction-check', 'extraction-check-failure', 'ingest-report'}:
        documents.setdefault(row['role'], []).append(store.document(row['reference']))
save('ingest-documents.json', documents)
corrections = []
for prompt in documents.get('model-prompt', []):
    if prompt['call_id'].endswith(':format-1'):
        feedback = prompt['messages'][-1]['content'].split('检查差异：', 1)[1]
        corrections.append({'call_id': prompt['call_id'], 'issues': json.loads(feedback)})
save('format-corrections.json', corrections)
save('model-operations.json', operations)
save('task-status.json', tasks)
ingest_report = json.loads((evidence / 'ingest-report.json').read_text())
snapshot = json.loads((evidence / 'ingested-snapshot.json').read_text())
verify_snapshot(snapshot)
checked = []
for row in ingest_report['sources']:
    assert row['status'] == 'source_checked', row
    source, chunks = import_material(demo / 'materials/metrics', row['path'])
    nodes = [n for n in snapshot['nodes'] if n['id'] in row['capabilities']]
    assert nodes and all(n['payload']['origin'] == 'llm_api' for n in nodes)
    replay = Extraction.model_validate({'capabilities': [
        {k: n['payload'][k] for k in ExtractedCapability.model_fields}
        for n in nodes]})
    checked_extraction(source, chunks, replay, origin='llm_api', response_evidence={})
    assert all(not n['payload']['implementation_verified'] for n in nodes)
    checked.append({'path': row['path'], 'capabilities': len(nodes),
                    'complete_algorithm_specs': sum(bool(n['payload']['algorithm_spec']) for n in nodes),
                    'all_origins_llm_api': True, 'source_and_citations_rechecked': True})
assert len(checked) == 8
save('source-checks.json', checked)
web = []
with open_knowledge('/path/to/private-config/llm-factory-bugfix-20261103/knowledge.json') as knowledge:
    graph = knowledge.snapshot()
verify_snapshot(graph)
save('knowledge-after.json', graph)
graph_ids = {n['id'] for n in graph['nodes']}
for path in (state / 'runs').glob('*/report.json'):
    report = bound_report(store, path.parent)
    downloaded = evidence / 'web-report-download.json'
    assert downloaded.is_file() and json.loads(downloaded.read_text()) == report
    assert report['status'] == 'COMPLETED'
    assert report['origin'] == 'llm_api'
    assert {c['plan']['config']['method_id'] for c in report['candidates']} == {
        'ewma', 'fixed_threshold', 'rolling_mad', 'threshold_probe'}
    for candidate in report['candidates']:
        version = candidate['versions'][-1]
        assert version['origin'] == 'llm_api' and version['validation']['passed']
        source = (path.parent / version['source_path']).read_bytes()
        assert 'sha256:' + hashlib.sha256(source).hexdigest() == version['source_sha256']
        method = candidate['plan']['config']['method_id']
        for name, expected in version['plugin_hashes'].items():
            assert 'sha256:' + hashlib.sha256((demo / 'capabilities' / method / name).read_bytes()).hexdigest() == expected
    publication = json.loads((path.parent / 'publication.json').read_text())
    assert publication['status'] == 'PUBLISHED'
    assert set(publication['node_ids']) <= graph_ids
    output = evidence / 'web-run'
    output.mkdir(exist_ok=True)
    for name in ['report.json', 'report.md', 'task.json', 'plans.json', 'selection.json',
                 'publication.json', 'retrieval.json', 'requirement-draft.json', 'requirement-evidence.json']:
        if (path.parent / name).is_file():
            shutil.copyfile(path.parent / name, output / name)
    for candidate in report['candidates']:
        for version in candidate['versions']:
            destination = output / version['source_path']
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path.parent / version['source_path'], destination)
    web.append({'task_id': report['task']['task_id'], 'status': report['status'],
                'origin': report['origin'], 'candidate_count': len(report['candidates']),
                'methods': [c['plan']['config']['method_id'] for c in report['candidates']],
                'browser_download_matches_server': True,
                'selected': report['selection']['selected'],
                'final': report['final'],
                'all_versions': [[{'origin': v['origin'], 'passed': v['validation']['passed'],
                                  'checks': len(v['validation']['checks'])} for v in c['versions']]
                                 for c in report['candidates']],
                'model_usage': report['model_usage'], 'publication': publication})
save('web-checks.json', web)
budget = read_campaign(private / 'campaign.sqlite')
save('budget-final.json', budget)
changed_files = ['src/contracts/metrics_knowledge.py', 'src/factory/metrics/knowledge.py',
                 'src/factory/metrics/model.py', 'src/factory/metrics/requirements.py',
                 'src/factory/models/checks.py', 'src/factory/models/transport.py',
                 'tests/metrics/test_plugin_generation.py', 'tests/metrics/test_ingest_regressions.py',
                 'tests/models/test_structured_feedback.py']
save('source-files.json', {name: hashlib.sha256((demo / name).read_bytes()).hexdigest() for name in changed_files})
key = load_environment(private / 'model.env')['LLM_API_KEY'].encode()
assert all(key not in path.read_bytes() for path in evidence.rglob('*') if path.is_file())
save('audit-summary.json', {'checked_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                           'real_sources_checked': len(checked), 'real_source_total': 8,
                           'complete_algorithm_specs': sum(r['complete_algorithm_specs'] for r in checked),
                           'format_corrections': corrections,
                           'source_checked_is_not_implementation_verified': True,
                           'web_runs': web, 'credential_content_matches': 0,
                           'campaign_lifetime_reserved': budget['lifetime_reserved']})
print(json.dumps({'sources_checked': len(checked), 'web_runs': len(web),
                  'lifetime_requests': budget['lifetime_reserved']}))
