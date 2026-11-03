import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image
from factory.models.environment import load_environment

demo = Path('/path/to/llm-factory/bugfix-revalidation-20261103/demo')
folder = demo / 'case-example/metrics/web-verification-20261102'
proof = folder / 'bugfix-evidence'
audit = json.loads((proof / 'audit-summary.json').read_text())
assert audit['real_sources_checked'] == audit['real_source_total'] == 8
assert audit['complete_algorithm_specs'] == 0
assert len(audit['web_runs']) == 1
assert audit['web_runs'][0]['candidate_count'] == 4
assert '498 passed, 71 skipped' in (proof / 'full-tests-final.txt').read_text()
for name, expected in json.loads((proof / 'source-files.json').read_text()).items():
    assert hashlib.sha256((demo / name).read_bytes()).hexdigest() == expected, name
(proof / 'manifest.sha256').touch(exist_ok=True)
(proof / 'report-checks.json').touch(exist_ok=True)
links = 0
for doc in [demo / 'README.md', demo / 'docs/getting-started.md', *folder.glob('*.md')]:
    for raw in re.findall(r'\]\(([^)]+)\)', doc.read_text()):
        if raw.startswith(('http:', 'https:', '#')):
            continue
        assert (doc.parent / raw.split('#')[0]).exists(), (str(doc), raw)
        links += 1
screenshots = sorted((proof / 'screenshots').glob('*.jpg'))
assert len(screenshots) >= 4
for path in screenshots:
    with Image.open(path) as image:
        assert image.format == 'JPEG'
        image.verify()
key = load_environment(Path('/path/to/private-config/llm-factory-web-revalidation-20261102/model.env'))['LLM_API_KEY'].encode()
for path in proof.rglob('*'):
    if path.is_file():
        assert key not in path.read_bytes(), 'credential content in exported artifact'
result = {'checked_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), 'status': 'PASSED',
          'links_checked': links, 'screenshots_verified': len(screenshots), 'real_material_sources_checked': 8,
          'real_web_candidates_passed': 4, 'source_files_verified': 9, 'credential_content_matches': 0}
(proof / 'report-checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
def manifest(base):
    target = base / 'manifest.sha256'
    files = sorted(p for p in base.rglob('*') if p.is_file() and p != target
                   and not p.name.startswith('._') and '__pycache__' not in p.parts)
    target.write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + str(p.relative_to(base)) + '\n'
                              for p in files))
    for line in target.read_text().splitlines():
        expected, name = line.split('  ', 1)
        assert hashlib.sha256((base / name).read_bytes()).hexdigest() == expected
    return len(files)
result['evidence_files'] = manifest(proof)
result['report_directory_files'] = manifest(folder)
print(json.dumps(result, ensure_ascii=False))
