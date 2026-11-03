import hashlib
import json
import os
import shutil
import tarfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from factory.metrics.local_store import LocalKnowledgeStore

root = Path('/path/to/llm-factory/plugin-web-verification-20261102')
demo = root / 'demo'
evidence = root / 'evidence'
# Supply the original source archive explicitly; its digest is recorded below.
source_archive = Path(os.environ['PLUGIN_SOURCE_ARCHIVE'])
def sha(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()
def read(path):
    return json.loads(path.read_text())

unchanged = []
with tarfile.open(source_archive) as archive:
    for member in archive.getmembers():
        if member.isfile() and member.name.startswith(('src/', 'scripts/', 'capabilities/', 'materials/')):
            assert archive.extractfile(member).read() == (demo / member.name).read_bytes(), member.name
            unchanged.append(member.name)

knowledge = LocalKnowledgeStore(root / 'state/knowledge.sqlite')
snapshot = knowledge.snapshot()
knowledge.close()
by_id = {n['id']: n for n in snapshot['nodes']}
runs = []
expected = {'ui-99ff30ac3e4b45e4': ['threshold_probe'],
            'ui-b505fafc4eff48d3': ['ewma', 'fixed_threshold', 'rolling_mad', 'threshold_probe']}
downloads = {'ui-99ff30ac3e4b45e4': 'web-plugin-report.json',
             'ui-b505fafc4eff48d3': 'web-four-plugins-report.json'}
for path in sorted((root / 'state/ui/runs').glob('*/report.json')):
    report = read(path)
    task_id = report['task']['task_id']
    assert task_id in expected
    assert report == read(evidence / downloads[task_id])
    assert report['status'] == 'COMPLETED'
    assert report['origin'] == 'mock'
    assert report['generation_protocol'] == 'capability-generation/2'
    assert report['model_usage']['requests'] == 0 and report['model_usage']['total_tokens'] == 0
    assert sorted(c['plan']['config']['method_id'] for c in report['candidates']) == expected[task_id]
    publication = read(path.parent / 'publication.json')
    assert publication['status'] == 'PUBLISHED'
    summaries = []
    for candidate in report['candidates']:
        version = candidate['versions'][-1]
        validation = version['validation']
        method = candidate['plan']['config']['method_id']
        assert validation['passed'] and all(c['passed'] for c in validation['checks'])
        assert validation['verification_level'] == 'reference_verified'
        assert validation['protocol'] == 'metrics-method-check/3'
        source = (path.parent / version['source_path']).read_bytes()
        assert sha(source) == version['source_sha256'] == validation['source_sha256']
        assert version['plugin_hashes'] == validation['plugin_hashes']
        for name, digest in version['plugin_hashes'].items():
            assert sha((demo / 'capabilities' / method / name).read_bytes()) == digest
        card = by_id[version['capability_id']]
        assert card['payload']['version'] == version['capability_version']
        assert sha(card['payload']['algorithm_spec'].encode()) == version['specification_sha256']
        assert card['payload']['origin'] == 'reference'
        implementations = [by_id[e['target']] for e in snapshot['relations']
                           if e['source'] == version['capability_id'] and e['relation'] == 'IMPLEMENTED_BY'
                           and by_id[e['target']]['payload'].get('task_id') == task_id]
        assert implementations, (task_id, method, 'missing implementation')
        validations = [by_id[e['target']] for impl in implementations for e in snapshot['relations']
                       if e['source'] == impl['id'] and e['relation'] == 'EVALUATED_BY']
        assert validations, (task_id, method, 'missing validation')
        summaries.append({'method_id': method, 'candidate_id': candidate['candidate_id'],
                          'capability_id': version['capability_id'], 'capability_version': version['capability_version'],
                          'source_sha256': version['source_sha256'], 'specification_sha256': version['specification_sha256'],
                          'plugin_hashes': version['plugin_hashes'], 'verification_level': validation['verification_level'],
                          'checks': validation['checks'], 'graph_path_verified': True})
        folder = evidence / task_id
        folder.mkdir(exist_ok=True)
        (folder / (candidate['candidate_id'] + '-v0.py')).write_bytes(source)
    shutil.copyfile(path.parent / 'publication.json', evidence / task_id / 'publication.json')
    runs.append({'task_id': task_id, 'requirement': report['task']['requirement'],
                 'status': report['status'], 'origin': report['origin'], 'download_matches_server': True,
                 'publication_status': publication['status'], 'model_usage': report['model_usage'],
                 'candidates': summaries, 'selected': report['selection']['selected'],
                 'final': report['final'], 'workflow_runtime_seconds': report['workflow_runtime_seconds']})
assert len(runs) == 2
graph = read(evidence / 'web-plugin-graph.json')
assert any(n['kind'] == 'Capability' and n['payload'].get('method_id') == 'threshold_probe' for n in graph['nodes'])
assert any(e['relation'] == 'IMPLEMENTED_BY' for e in graph['relations'])
assert any(e['relation'] == 'EVALUATED_BY' for e in graph['relations'])
result = {'checked_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
          'source_archive_sha256': sha((source_archive).read_bytes()),
          'original_source_files_unchanged': len(unchanged), 'installation': read(evidence / 'installation.json'),
          'runs': runs, 'graph_download': {'nodes': len(graph['nodes']), 'relations': len(graph['relations'])},
          'checks_passed': True}
(evidence / 'evidence-checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'checks_passed': True, 'tasks': [r['task_id'] for r in runs],
                  'original_source_files_unchanged': len(unchanged)}, ensure_ascii=False))
