import difflib
import hashlib
import json
import os
import signal
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

from factory.metrics.budget import read_campaign
from factory.metrics.knowledge import sources_only, verify_snapshot
from factory.metrics.knowledge_store import open_knowledge

root = Path('/path/to/llm-factory/final-classic-web-20261103')
demo, repair, evidence = root / 'demo', root / 'repair-demo', root / 'evidence'
old_root = Path('/path/to/llm-factory/bugfix-revalidation-20261103').resolve()
shared_private = Path('/path/to/private-config/llm-factory-web-revalidation-20261102')
private = Path('/path/to/private-config/llm-factory-final-classic-20261103')
private.mkdir(mode=0o700, exist_ok=True)
config = json.loads((shared_private / 'knowledge.json').read_text())
config['namespace'] = 'final-classic-web-20261103'
config_path = private / 'knowledge.json'
config_path.write_text(json.dumps(config))
config_path.chmod(0o600)
seed = sources_only(json.loads((old_root / 'evidence/ingested-snapshot.json').read_text()))
verify_snapshot(seed)
assert not any(n['kind'] in {'Experience', 'Implementation', 'ValidationRun'} for n in seed['nodes'])
with open_knowledge(config_path) as knowledge:
    knowledge.initialize()
    assert not knowledge.snapshot()['nodes'], 'namespace must be new and empty'
    knowledge.add(seed['nodes'], seed['relations'])
    assert knowledge.snapshot()['snapshot_id'] == seed['snapshot_id']
(evidence / 'knowledge-seed.json').write_text(json.dumps(seed, ensure_ascii=False, indent=2))
campaign = shared_private / 'campaign.sqlite'
(evidence / 'budget-before.json').write_text(json.dumps(read_campaign(campaign), ensure_ascii=False, indent=2))
source_files = {}
with tarfile.open('/path/to/llm-factory/llm-final-classic-source.tar') as archive:
    for member in archive.getmembers():
        if member.isfile() and member.name.startswith(('src/', 'scripts/', 'capabilities/', 'materials/')):
            expected = archive.extractfile(member).read()
            assert (demo / member.name).read_bytes() == expected
            assert (repair / member.name).read_bytes() == expected
            source_files[member.name] = hashlib.sha256(expected).hexdigest()
(evidence / 'source-baseline.json').write_text(json.dumps(source_files, indent=2))
path = repair / 'src/factory/metrics/creation.py'
original = path.read_text()
assert original.count('fault_injection=False') == 1
changed = original.replace('import asyncio\n', 'import asyncio\nimport os\n', 1)
changed = changed.replace("    mode, retrieval = settings['model_mode'], 'structured'\n",
    "    mode, retrieval = settings['model_mode'], 'structured'\n"
    "    if os.environ.get('FACTORY_ACCEPTANCE_FAULT_INJECTION') == '1':\n"
    "        st.warning('验收专用：真实模型初版将注入明确标记的分数偏移错误，再由真实模型修复；不计自然错误修复率。')\n", 1)
changed = changed.replace('fault_injection=False', "fault_injection=os.environ.get('FACTORY_ACCEPTANCE_FAULT_INJECTION') == '1'", 1)
(evidence / 'creation-original.py').write_text(original)
path.write_text(changed)
(evidence / 'repair-web-instrumentation.diff').write_text(''.join(difflib.unified_diff(
    original.splitlines(keepends=True), changed.splitlines(keepends=True),
    fromfile='baseline/src/factory/metrics/creation.py', tofile='repair-acceptance/src/factory/metrics/creation.py')))
old_pid = int((old_root / 'evidence/web.pid').read_text())
proc = Path('/proc') / str(old_pid)
if proc.exists():
    assert (proc / 'cwd').resolve() == old_root / 'demo'
    assert '--server.port=18503' in (proc / 'cmdline').read_bytes().decode()
    os.kill(old_pid, signal.SIGTERM)
    for _ in range(30):
        if not proc.exists():
            break
        time.sleep(.2)
image = Path('/path/to/llm-factory/real-web-revalidation-20261102/demo/.runtime/bootstrap/image-id').read_text().strip()
env = {**os.environ, 'PYTHONPATH': 'src:.', 'FACTORY_DOCKER_COMMAND': 'sudo -n docker',
       'FACTORY_KNOWLEDGE_BACKEND': 'neo4j', 'FACTORY_METRICS_STATE': str(demo / '.runtime/final-classic'),
       'FACTORY_METRICS_KNOWLEDGE': str(config_path), 'FACTORY_METRICS_MODEL_ENV': str(shared_private / 'model.env'),
       'FACTORY_METRICS_CAMPAIGN': str(campaign), 'FACTORY_METRICS_IMAGE': image}
pids = {}
for port, directory in [(18503, demo), (18504, repair)]:
    launch_env = {**env, **({'FACTORY_ACCEPTANCE_FAULT_INJECTION': '1'} if port == 18504 else {})}
    command = [sys.executable, '-m', 'streamlit', 'run', 'streamlit_app.py',
               '--server.address=127.0.0.1', f'--server.port={port}', '--server.headless=true',
               '--browser.gatherUsageStats=false', '--server.fileWatcherType=none']
    with (evidence / f'web-{port}.txt').open('w') as log:
        process = subprocess.Popen(command, cwd=directory, env=launch_env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    pids[str(port)] = process.pid
    for _ in range(50):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/_stcore/health', timeout=2) as response:
                assert response.read() == b'ok'
            break
        except OSError:
            time.sleep(.2)
    else:
        raise RuntimeError('Web health check failed')
record = {'source_baseline': 'final-classic-source-archive',
          'source_files_verified': len(source_files), 'knowledge_seed_snapshot': seed['snapshot_id'],
          'seed_experiences': 0, 'seed_material_sources': 8, 'pids': pids,
          'namespace': config['namespace'], 'image': image,
          'repair_scope': 'separate repair-demo copy; existing fault_injection switch only; user approved',
          'normal_creation_sha256': source_files['src/factory/metrics/creation.py'],
          'instrumented_creation_sha256': hashlib.sha256(changed.encode()).hexdigest()}
(evidence / 'environment.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
print(json.dumps(record, ensure_ascii=False))
