import hashlib
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image
from factory.metrics.reports import bound_report
from factory.metrics.runtime import MetricsStore
from factory.models.environment import load_environment

root = Path('/path/to/llm-factory/final-classic-web-20261103')
demo = root / 'demo'
folder = demo / 'case-example/metrics/web-verification-20261102'
proof = folder / 'final-classics-20261103'
removed = (root / 'removed-human-reports.txt').read_text().splitlines()
for relative in removed:
    path = demo / relative
    assert path.resolve().is_relative_to(folder.resolve())
    assert path.name.endswith('.md') or path.name == 'manifest-before-revalidation.sha256'
    path.unlink(missing_ok=True)
assert len(removed) == 10
assert not list((folder / 'real-model-revalidation-20261102/prior-reports').glob('*'))
assert not list((folder / 'real-model-revalidation-20261102/audit/runs').glob('*/report.md'))
assert not list((proof / 'runs').glob('*/report.md'))
for name in ['manifest.sha256', 'report-checks.json']:
    (proof / name).touch(exist_ok=True)
audit = json.loads((proof / 'audit-summary.json').read_text())
summary = json.loads((proof / 'results-summary.json').read_text())
chain = json.loads((proof / 'experience-chain.json').read_text())
assert audit['completed'] == 4 and audit['checks_passed']
assert not audit['other_runs']
assert len(chain['provided']) == len(chain['cited']) == 2
assert set(chain['cited']) <= set(chain['provided'])
store = MetricsStore(demo / '.runtime/final-classic/runtime.sqlite')
bound = {}
for path in (demo / '.runtime/final-classic/runs').glob('*/report.json'):
    report = bound_report(store, path.parent)
    assert report['task']['task_id'] in audit['runs'].values()
    bound[report['task']['task_id']] = report
assert len(bound) == 4
files = {'cpu': 'cpu-report.md', 'memory': 'memory-report.md',
         'disk': 'disk-report.md', 'repair': 'history-repair-report.md'}
for label, name in files.items():
    report = bound[audit['runs'][label]]
    text = (folder / name).read_text()
    assert report['task']['task_id'] in text and report['task']['requirement'] in text
    assert '最终报告' in text and '文件 SHA-256' in text and 'current-source-comparison.json' in text
    assert f"{report['final']['point']['f1']['value']:.4f}" in text
    assert json.loads((proof / 'downloads' / (label + '-report.json')).read_text()) == report
    for candidate in report['candidates']:
        for version in candidate['versions']:
            source = proof / 'runs' / label / version['source_path']
            assert 'sha256:' + hashlib.sha256(source.read_bytes()).hexdigest() == version['source_sha256']
    if label == 'repair':
        versions = report['candidates'][0]['versions']
        assert len(versions) == 2 and not versions[0]['validation']['passed'] and versions[1]['validation']['passed']
        assert versions[1]['parent_source_sha256'] == versions[0]['source_sha256']
budget = json.loads((proof / 'budget-after.json').read_text())
assert budget['round'] == 3 and budget['used'] == budget['sent'] == 18
assert budget['lifetime_reserved'] == 75 and budget['remaining'] == 42
baseline = json.loads((proof / 'environment/source-baseline.json').read_text())
for name, expected in baseline.items():
    assert hashlib.sha256((demo / name).read_bytes()).hexdigest() == expected
    assert hashlib.sha256((root / 'repair-demo' / name).read_bytes()).hexdigest() == expected
comparison = json.loads((proof / 'environment/current-source-comparison.json').read_text())
assert comparison['source_files_byte_equal'] == len(baseline) == 116
links = 0
for doc in [demo / 'README.md', demo / 'docs/getting-started.md', *folder.glob('*.md')]:
    for raw in re.findall(r'\]\(([^)]+)\)', doc.read_text()):
        if raw.startswith(('http:', 'https:', '#')):
            continue
        assert (doc.parent / raw.split('#')[0]).exists(), (str(doc), raw)
        links += 1
section = (demo / 'README.md').read_text().split('## 8.')[1].split('## 9.')[0]
assert '0.9130' in section and '0.9545' in section
assert '0.8879' not in section and '0.9364' not in section
for name in files.values():
    assert section.count('/' + name + ')') == 1
screenshots = sorted((proof / 'screenshots').glob('*.jpg'))
assert len(screenshots) == 36
for path in screenshots:
    with Image.open(path) as image:
        assert image.format == 'JPEG'
        image.verify()
observations = json.loads((proof / 'web-observations.json').read_text())
assert observations['all_four_submitted_via_web']
assert {s['file'] for s in observations['screenshots']} | {'01-real-model-budget.jpg'} == {p.name for p in screenshots}
private = Path('/path/to/private-config/llm-factory-web-revalidation-20261102')
key = load_environment(private / 'model.env')['LLM_API_KEY'].encode()
for path in proof.rglob('*'):
    if path.is_file():
        assert key not in path.read_bytes(), 'credential content found in exported artifact'
        if path.suffix == '.zip':
            with zipfile.ZipFile(path) as archive:
                assert all(key not in archive.read(name) for name in archive.namelist())
result = {'checked_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), 'status': 'PASSED',
          'completed_real_web_tasks': 4, 'browser_report_downloads_verified': 4,
          'screenshots_verified': len(screenshots), 'links_checked': links,
          'memory_experiences_provided_and_cited_by_disk': 2,
          'source_files_verified_in_both_copies': 116, 'real_requests_added': 18,
          'old_human_report_files_removed': len(removed), 'credential_content_matches': 0}
(proof / 'report-checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
def manifest(base):
    target = base / 'manifest.sha256'
    paths = sorted(p for p in base.rglob('*') if p.is_file() and p != target
                   and not p.name.startswith('._') and '__pycache__' not in p.parts)
    target.write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + str(p.relative_to(base)) + '\n'
                              for p in paths))
    for line in target.read_text().splitlines():
        expected, name = line.split('  ', 1)
        assert hashlib.sha256((base / name).read_bytes()).hexdigest() == expected
    return len(paths)
result['evidence_files'] = manifest(proof)
result['retained_old_evidence_files'] = manifest(folder / 'real-model-revalidation-20261102')
result['report_directory_files'] = manifest(folder)
local_files = (root / 'local-report-files.txt').read_text().splitlines()
local = {str(Path(p).relative_to(folder.relative_to(demo))) for p in local_files
         if not Path(p).name.startswith('._') and '__pycache__' not in Path(p).parts}
remote = {str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file()
          and not p.name.startswith('._') and '__pycache__' not in p.parts}
assert local | {'final-classics-20261103/manifest.sha256', 'final-classics-20261103/report-checks.json'} == remote
print(json.dumps(result, ensure_ascii=False))
