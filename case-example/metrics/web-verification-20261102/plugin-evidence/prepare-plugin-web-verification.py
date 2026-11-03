import hashlib
import json
import shutil
from pathlib import Path

root = Path('/path/to/llm-factory/plugin-web-verification-20261102')
demo = root / 'demo'
evidence = root / 'evidence'
def hashes(paths):
    return {str(p.relative_to(demo)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths) if p.is_file() and '__pycache__' not in p.parts}
before = hashes((demo / 'src').rglob('*'))
original = sorted(p.parent.name for p in (demo / 'capabilities').glob('*/capability.json'))
plugin = demo / 'capabilities/threshold_probe'
shutil.copytree(demo / 'capabilities/fixed_threshold', plugin)
card = json.loads((plugin / 'capability.json').read_text())
card.update(method_id='threshold_probe', version='1.0.0', display_name='阈值探针',
            aliases=['阈值探针', 'threshold_probe'], candidate_name='probe', default_candidate=False)
card['config_schema']['properties']['threshold'].update(minimum=0, maximum=100)
(plugin / 'capability.json').write_text(json.dumps(card, ensure_ascii=False, indent=2) + '\n')
after = hashes((demo / 'src').rglob('*'))
assert before == after
record = {'original_methods': original,
          'installed_methods': sorted(p.parent.name for p in (demo / 'capabilities').glob('*/capability.json')),
          'src_unchanged': before == after, 'src_sha256': after,
          'plugin_files': hashes(plugin.rglob('*')),
          'purpose': 'registration and Web extension probe, reuses fixed-threshold reference algorithm',
          'new_constraint': '0 <= threshold <= 100'}
(evidence / 'installation.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({k:v for k,v in record.items() if k != 'src_sha256'}, ensure_ascii=False, indent=2))
