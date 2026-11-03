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

root = Path('/path/to/llm-factory/real-web-revalidation-20261102')
demo = root / 'demo'
folder = demo / 'case-example/metrics/web-verification-20261102'
proof = folder / 'real-model-revalidation-20261102'
private = Path('/path/to/private-config/llm-factory-web-revalidation-20261102')
summary = json.loads((proof / 'audit/results-summary.json').read_text())
assert sum(x['source_checked'] for x in summary['material_sources'].values()) == 2
assert len(summary['material_sources']) == 8
assert all(summary['experiments'][k]['status'] == 'COMPLETED' for k in ['cpu','memory','disk','repair'])
assert summary['experiments']['disk-timeout']['status'] == 'FAILED'
assert summary['experiments']['repair']['candidates'][0]['passed_per_version'] == [False, True]
chain = json.loads((proof / 'audit/experience-chain.json').read_text())
assert len(chain['memory_experiences_cited_by_disk']) == 2
assert len(chain['memory_experiences_provided_to_disk']) == 2
assert any(p['provided_experience_ids'] for p in chain['disk_code_prompts'])
repair = json.loads((proof / 'audit/runs/repair/audit.json').read_text())
assert any(p['has_previous_source'] and p['has_development_feedback'] for p in repair['prompts'])

store = MetricsStore(demo / '.runtime/poc/runtime.sqlite')
bound = []
for path in (demo / '.runtime/poc/runs').glob('*/report.json'):
    report = bound_report(store, path.parent)
    bound.append(report['task']['task_id'])
assert len(bound) == 5

manifest = proof / 'manifest.sha256'
manifest.touch(exist_ok=True)
root_manifest = folder / 'manifest.sha256'
root_manifest.touch(exist_ok=True)
docs = [demo / 'README.md', demo / 'docs/getting-started.md', folder / 'REPORT.md',
        *[folder / name for name in ['cpu-report.md','memory-report.md','disk-report.md','history-repair-report.md','getting-started-report.md']]]
links = []
for doc in docs:
    for raw in re.findall(r'\]\(([^)]+)\)', doc.read_text()):
        if raw.startswith(('http:', 'https:', '#')):
            continue
        target = doc.parent / raw.split('#')[0]
        assert target.exists(), (doc, raw)
        links.append(str(target.relative_to(demo)))
agent_images = [p for p in (proof / 'screenshots').glob('*.jpg') if not p.name.startswith('._')]
user_images = [proof / 'screenshots' / name for name in ['37-disk-result-user.png','38-disk-knowledge-user.png']]
assert len(agent_images) == 36
assert all(p.is_file() for p in user_images)
images = agent_images + user_images
for path in images:
    with Image.open(path) as image:
        assert image.format == ('PNG' if path.suffix == '.png' else 'JPEG')
        image.verify()
supplement = json.loads((proof / 'user-screenshot-evidence.json').read_text())
assert supplement['task_id'] == 'ui-da4c1f50a3504008'
assert supplement['visible_values_match_server_report']
for item in supplement['images']:
    assert hashlib.sha256((proof / item['stored_path']).read_bytes()).hexdigest() == item['sha256']

key = load_environment(private / 'model.env').get('LLM_API_KEY')
assert key and len(key) > 8
for path in proof.rglob('*'):
    if not path.is_file() or path.name.startswith('._'):
        continue
    assert key.encode() not in path.read_bytes(), 'credential content found in exported artifact'
    if path.suffix == '.zip':
        with zipfile.ZipFile(path) as archive:
            assert all(key.encode() not in archive.read(item) for item in archive.namelist()), 'credential content found in delivery ZIP'

result = {'checked_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), 'status':'PASSED',
          'local_links_checked':len(links), 'jpeg_screenshots_verified':len(agent_images),
          'user_png_screenshots_verified':len(user_images), 'screenshots_verified_total':len(images),
          'immutable_ledger_reports_verified':bound, 'real_material_sources_passed':2,
          'real_material_sources_total':8, 'memory_experiences_cited_by_disk':2,
          'credential_content_matches':0, 'browser_limitations_preserved':True,
          'disk_success_visual_evidence_supplemented_by_user':True}
(proof / 'report-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')

def write_manifest(base, target):
    files = sorted(p for p in base.rglob('*') if p.is_file() and p != target
                   and '__pycache__' not in p.parts and not p.name.startswith('._'))
    text = ''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+str(p.relative_to(base))+'\n' for p in files)
    target.write_text(text)
    for line in text.splitlines():
        digest, name = line.split('  ',1)
        assert hashlib.sha256((base / name).read_bytes()).hexdigest() == digest
    return len(files)

counts = {'new_artifact_files':write_manifest(proof,manifest),
          'current_report_directory_files':write_manifest(folder,root_manifest)}
print(json.dumps({**result, **counts},ensure_ascii=False))
