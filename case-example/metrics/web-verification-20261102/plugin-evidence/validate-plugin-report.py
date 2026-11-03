import hashlib
import json
import re
from pathlib import Path

from PIL import Image

root = Path('/path/to/llm-factory/plugin-web-verification-20261102/demo').resolve()
folder = root / 'case-example/metrics/web-verification-20261102'
evidence = folder / 'plugin-evidence'
manifest_path = evidence / 'manifest.sha256'
manifest_path.touch(exist_ok=True)
checked = []
for doc in (root / 'README.md', folder / 'REPORT.md', folder / 'plugin-report.md'):
    for raw in re.findall(r'\]\(([^)]+)\)', doc.read_text()):
        if raw.startswith(('http:', 'https:', '#')):
            continue
        target = doc.parent / raw.split('#')[0]
        assert target.exists(), (doc, raw)
        checked.append(str(target.relative_to(root)))
images = [p for p in (evidence / 'screenshots').glob('*.jpg') if not p.name.startswith('._')]
for path in images:
    with Image.open(path) as im:
        assert im.format == 'JPEG'
        im.verify()
summary = {'links_checked': len(checked), 'jpeg_screenshots_verified': len(images), 'status': 'PASSED'}
(evidence / 'report-checks.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
files = sorted(p for p in evidence.rglob('*') if p.is_file() and p.name != 'manifest.sha256'
               and '__pycache__' not in p.parts and not p.name.startswith('._'))
manifest = ''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + str(p.relative_to(evidence)) + '\n'
                   for p in files)
manifest_path.write_text(manifest)
for line in manifest.splitlines():
    expected, name = line.split('  ', 1)
    assert hashlib.sha256((evidence / name).read_bytes()).hexdigest() == expected
print(json.dumps({**summary, 'manifest_files': len(files)}, ensure_ascii=False))
