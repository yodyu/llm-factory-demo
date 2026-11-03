import hashlib
import json
import os
import platform
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

root = Path('/path/to/llm-factory/real-web-revalidation-20261102')
demo = root / 'demo'
private = Path('/path/to/private-config/llm-factory-web-revalidation-20261102')
def digest(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()
source_files = {}
with tarfile.open(root.parent / 'llm-real-web-revalidation-source.tar.gz') as archive:
    for member in archive.getmembers():
        if member.isfile() and member.name.startswith(('src/', 'scripts/', 'capabilities/', 'materials/')):
            current = (demo / member.name).read_bytes()
            assert current == archive.extractfile(member).read(), member.name
            source_files[member.name] = digest(current)
model = {}
for line in (private / 'model.env').read_text().splitlines():
    key, separator, value = line.partition('=')
    if separator and key in {'LLM_MODEL', 'LLM_TRANSPORT'}:
        model[key] = value.strip().strip('"').strip("'")
config = json.loads((private / 'knowledge.json').read_text())
assert config['uri'] == 'bolt://127.0.0.1:17688'
permissions = {name: oct((private / name).stat().st_mode & 0o777)
               for name in ['model.env', 'knowledge.json', 'neo4j-auth']}
assert set(permissions.values()) == {'0o600'}
inspection = subprocess.run(['sudo', '-n', 'docker', 'inspect', 'demo-neo4j-1'],
                            check=True, capture_output=True, text=True)
container = json.loads(inspection.stdout)[0]
ports = container['NetworkSettings']['Ports']
assert all(binding['HostIp'] == '127.0.0.1' for bindings in ports.values() if bindings for binding in bindings)
result = {'checked_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
          'source_baseline': 'real-web-source-archive', 'source_archive_sha256': digest((root.parent / 'llm-real-web-revalidation-source.tar.gz').read_bytes()),
          'guide_sha256': digest((demo / 'docs/getting-started.md').read_bytes()),
          'python': platform.python_version(), 'os_release': Path('/etc/os-release').read_text(),
          'model': model, 'secret_file_modes': permissions,
          'knowledge_uri': config['uri'], 'namespace': config['namespace'],
          'sandbox_before': (root / 'evidence/sandbox-before.txt').read_text().strip(),
          'sandbox_after': (demo / '.runtime/bootstrap/image-id').read_text().strip(),
          'neo4j': {'id': container['Id'], 'name': container['Name'],
                    'state': container['State']['Status'], 'health': container['State']['Health']['Status'], 'ports': ports},
          'source_files': source_files, 'source_files_unchanged': len(source_files)}
assert result['sandbox_before'] == result['sandbox_after']
(root / 'evidence/environment.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({key: result[key] for key in ['checked_at', 'python', 'model', 'knowledge_uri', 'source_files_unchanged']}, ensure_ascii=False))
