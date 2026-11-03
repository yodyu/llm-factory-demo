import json
import os
import subprocess
import sys
from pathlib import Path

root = Path('/path/to/llm-factory/real-web-revalidation-20261102')
demo = root / 'demo'
private = Path('/path/to/private-config/llm-factory-web-revalidation-20261102')
env = {**os.environ, 'PYTHONPATH': 'src:.', 'FACTORY_KNOWLEDGE_BACKEND': 'neo4j',
       'FACTORY_DOCKER_COMMAND': 'sudo -n docker'}
results = []
for source in ['03-rolling-mad.txt', '04-evaluation.txt', '05-limitations.txt', '06-ewma.txt',
               'reference_fixed.py', 'reference_mad.py']:
    for attempt in range(1, 3):
        label = source.replace('.', '-') + '-' + str(attempt)
        output = private / ('recover-' + label + '.json')
        stdout = root / 'evidence' / ('recover-' + label + '.json')
        stderr = stdout.with_suffix('.stderr')
        command = [sys.executable, '-m', 'factory', 'metrics-ingest', '--state', str(demo / '.runtime/poc'),
                   '--mode', 'api', '--campaign', str(private / 'campaign.sqlite'),
                   '--env-file', str(private / 'model.env'), '--knowledge', str(private / 'knowledge.json'),
                   '--root', 'materials/metrics', '--sources', source, '--output', str(output)]
        with stdout.open('w') as out, stderr.open('w') as err:
            process = subprocess.run(command, cwd=demo, env=env, stdout=out, stderr=err)
        value = {}
        if process.returncode == 0:
            try:
                value = json.loads(stdout.read_text())
            except ValueError:
                pass
        result = {'source': source, 'attempt': attempt, 'exit_code': process.returncode,
                  'status': value.get('status', 'FAILED'), 'task_id': value.get('task_id'),
                  'sources': value.get('sources', [])}
        results.append(result)
        (root / 'evidence/material-recovery.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
        if result['status'] == 'SUCCEEDED':
            break
print(json.dumps(results, ensure_ascii=False))
