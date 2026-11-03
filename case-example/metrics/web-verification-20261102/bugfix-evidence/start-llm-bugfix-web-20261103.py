import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

root = Path('/path/to/llm-factory/bugfix-revalidation-20261103')
demo, evidence = root / 'demo', root / 'evidence'
old_demo = Path('/path/to/llm-factory/real-web-revalidation-20261102/demo').resolve()
old_pid_path = old_demo.parent / 'evidence/disk-screenshot-retry-web.pid'
old_pid = int(old_pid_path.read_text().strip())
proc = Path('/proc') / str(old_pid)
if proc.exists():
    assert (proc / 'cwd').resolve() == old_demo
    command = (proc / 'cmdline').read_bytes().replace(b'\x00', b' ').decode()
    assert 'streamlit run streamlit_app.py' in command and '--server.port=18503' in command
    os.kill(old_pid, signal.SIGTERM)
    for _ in range(30):
        if not proc.exists():
            break
        time.sleep(.2)
subprocess.run(['cp', '-a', str(root / 'threshold_probe'), str(demo / 'capabilities/threshold_probe')], check=True)
private = Path('/path/to/private-config/llm-factory-web-revalidation-20261102')
image = (old_demo / '.runtime/bootstrap/image-id').read_text().strip()
env = {**os.environ, 'PYTHONPATH': 'src:.', 'FACTORY_DOCKER_COMMAND': 'sudo -n docker',
       'FACTORY_KNOWLEDGE_BACKEND': 'neo4j', 'FACTORY_METRICS_STATE': str(demo / '.runtime/bugfix'),
       'FACTORY_METRICS_KNOWLEDGE': '/path/to/private-config/llm-factory-bugfix-20261103/knowledge.json',
       'FACTORY_METRICS_MODEL_ENV': str(private / 'model.env'),
       'FACTORY_METRICS_CAMPAIGN': str(private / 'campaign.sqlite'),
       'FACTORY_METRICS_IMAGE': image}
command = [sys.executable, '-m', 'streamlit', 'run', 'streamlit_app.py',
           '--server.address=127.0.0.1', '--server.port=18503', '--server.headless=true',
           '--browser.gatherUsageStats=false', '--server.fileWatcherType=none']
with (evidence / 'web.log').open('w') as log:
    process = subprocess.Popen(command, cwd=demo, env=env, stdin=subprocess.DEVNULL,
                               stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
(evidence / 'web.pid').write_text(str(process.pid))
for _ in range(50):
    try:
        with urllib.request.urlopen('http://127.0.0.1:18503/_stcore/health', timeout=2) as response:
            assert response.read() == b'ok'
        break
    except OSError:
        time.sleep(.2)
else:
    raise RuntimeError('Web health check failed')
record = {'old_web_pid_stopped': old_pid, 'new_web_pid': process.pid, 'port': 18503,
          'new_namespace': 'bugfix-revalidation-20261103', 'test_plugin': 'threshold_probe',
          'production_service_unchanged': True}
(evidence / 'web-launch.json').write_text(json.dumps(record, indent=2))
print(json.dumps(record))
