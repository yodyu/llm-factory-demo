import hashlib
import json
import os
import shutil
import signal
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from factory.metrics.budget import read_campaign
from factory.metrics.runtime import MetricsStore

root = Path('/path/to/llm-factory/final-classic-web-20261103')
demo, repair, evidence = root / 'demo', root / 'repair-demo', root / 'evidence'
output = root / 'final-evidence'
mapping = json.loads((evidence / 'run-map.json').read_text())
store = MetricsStore(demo / '.runtime/final-classic/runtime.sqlite')
assert all(store.task(task_id)['status'] == 'SUCCEEDED' for task_id in mapping.values())
environment = json.loads((evidence / 'environment.json').read_text())
pid = environment['pids']['18504']
proc = Path('/proc') / str(pid)
if proc.exists():
    assert (proc / 'cwd').resolve() == repair.resolve()
    assert '--server.port=18504' in (proc / 'cmdline').read_bytes().decode()
    os.kill(pid, signal.SIGTERM)
(repair / 'src/factory/metrics/creation.py').write_bytes((evidence / 'creation-original.py').read_bytes())
baseline = json.loads((evidence / 'source-baseline.json').read_text())
for name, expected in baseline.items():
    assert hashlib.sha256((demo / name).read_bytes()).hexdigest() == expected, name
    assert hashlib.sha256((repair / name).read_bytes()).hexdigest() == expected, name
normal_pid = environment['pids']['18503']
assert (Path('/proc') / str(normal_pid) / 'cwd').resolve() == demo.resolve()
budget = read_campaign(Path('/path/to/private-config/llm-factory-web-revalidation-20261102/campaign.sqlite'))
before = json.loads((evidence / 'budget-before.json').read_text())
record = {'checked_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
          'source_baseline': 'final-classic-source-archive', 'normal_web_kept_for_review': 18503,
          'repair_web_stopped': 18504, 'repair_source_restored': True,
          'source_files_equal_to_commit_in_both_copies': len(baseline),
          'requests_added': budget['lifetime_reserved'] - before['lifetime_reserved'],
          'lifetime_requests': budget['lifetime_reserved'], 'current_round': budget['round'],
          'current_round_remaining': budget['remaining'], 'production_8501_unchanged_by_this_run': True}
dest = output / 'environment'
dest.mkdir(exist_ok=True)
for name in ['environment.json', 'source-baseline.json', 'budget-before.json', 'run-map.json',
             'knowledge-seed.json', 'repair-web-instrumentation.diff', 'creation-original.py',
             'start-final-classic-web-20261103.py', 'audit-final-classics-20261103.py',
             'write-final-classic-reports-20261103.py', 'finalize-final-classics-20261103.py']:
    shutil.copyfile(evidence / name, dest / name)
downloads = output / 'downloads'
downloads.mkdir(exist_ok=True)
for path in (root / 'browser-downloads').iterdir():
    if path.is_file():
        shutil.copyfile(path, downloads / path.name)
for label in mapping:
    (output / 'runs' / label / 'report.md').unlink(missing_ok=True)
(dest / 'final-state.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(record, ensure_ascii=False))
