import hashlib
import json
import os
import signal
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

root = Path('/path/to/llm-factory/real-web-revalidation-20261102')
demo = (root / 'demo').resolve()
proof = root / 'review-evidence'
sources = proof / 'sources'
sources.mkdir(exist_ok=True)
for p in (proof / 'runs').glob('*/audit.json'):
    record = json.loads(p.read_text())
    for candidate in record['candidates']:
        method = candidate['config']['method_id']
        for version in candidate['versions']:
            data = (p.parent / version['source_path']).read_bytes()
            target = sources / (record['label'] + '-' + method + '-v' + str(version['version']) + '.py')
            target.write_bytes(data)
            original = (p.parent / version['source_path']).with_name('model-original-v0.py')
            if original.exists():
                (sources / 'repair-model-original-v0.py').write_bytes(original.read_bytes())

stopped = []
for name in ['web-launcher.pid', 'repair-web-launcher.pid']:
    pid_path = root / 'evidence' / name
    if not pid_path.exists():
        continue
    parent = int(pid_path.read_text())
    children = subprocess.run(['pgrep', '-P', str(parent)], capture_output=True, text=True)
    for raw in children.stdout.split():
        pid = int(raw)
        proc = Path('/proc') / str(pid)
        try:
            command = (proc / 'cmdline').read_bytes()
            if (proc / 'cwd').resolve() == demo and b'streamlit' in command:
                os.kill(pid, signal.SIGTERM)
                stopped.append(pid)
        except FileNotFoundError:
            pass
    try:
        cmd = (Path('/proc') / str(parent) / 'cmdline').read_bytes()
        if b'make' in cmd and b'web' in cmd:
            os.kill(parent, signal.SIGTERM)
    except (FileNotFoundError, ProcessLookupError):
        pass

instrumentation = json.loads((root / 'evidence/repair-instrumentation.json').read_text())
path = demo / 'src/factory/metrics/creation.py'
current = path.read_bytes()
assert hashlib.sha256(current).hexdigest() == instrumentation['instrumented_sha256']
path.write_bytes((root / 'evidence/creation-original.py').read_bytes())
unchanged = 0
with tarfile.open(root.parent / 'llm-real-web-revalidation-source.tar.gz') as archive:
    for member in archive.getmembers():
        if member.isfile() and member.name.startswith(('src/', 'scripts/', 'capabilities/', 'materials/')):
            assert archive.extractfile(member).read() == (demo / member.name).read_bytes(), member.name
            unchanged += 1

expected = json.loads((root / 'evidence/environment.json').read_text())['neo4j']['id']
actual = subprocess.run(['sudo', '-n', 'docker', 'inspect', 'demo-neo4j-1', '--format', '{{.Id}}'],
                        capture_output=True, text=True, check=True).stdout.strip()
assert actual == expected
subprocess.run(['sudo', '-n', 'docker', 'stop', 'demo-neo4j-1'], check=True, capture_output=True, text=True)
existing = subprocess.run(['sudo', '-n', 'docker', 'inspect', 'llm-factory-neo4j', '--format',
                           '{{.Id}} {{.State.StartedAt}} {{.RestartCount}}'], check=True, capture_output=True, text=True).stdout
assert existing == (root / 'evidence/existing-neo4j-before.txt').read_text()
result = {'finished_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
          'web_child_pids_stopped':stopped, 'acceptance_neo4j_stopped':True,
          'data_volume_and_evidence_retained':True, 'instrumentation_restored':True,
          'baseline_source_files_unchanged_after_restore':unchanged, 'existing_neo4j_identity_unchanged':True}
(root / 'evidence/final-environment-state.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False))
