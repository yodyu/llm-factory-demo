import json
import os
import subprocess
import sys
from pathlib import Path

from factory.metrics.budget import read_campaign

root = Path('/path/to/llm-factory/bugfix-revalidation-20261103')
demo, evidence = root / 'demo', root / 'evidence'
previous_private = Path('/path/to/private-config/llm-factory-web-revalidation-20261102')
private = Path('/path/to/private-config/llm-factory-bugfix-20261103')
private.mkdir(mode=0o700, exist_ok=True)
config = json.loads((previous_private / 'knowledge.json').read_text())
config['namespace'] = 'bugfix-revalidation-20261103'
config_path = private / 'knowledge.json'
config_path.write_text(json.dumps(config))
config_path.chmod(0o600)
campaign = previous_private / 'campaign.sqlite'
(evidence / 'budget-before.json').write_text(json.dumps(read_campaign(campaign), indent=2))
env = {**os.environ, 'PYTHONPATH': 'src:.', 'FACTORY_KNOWLEDGE_BACKEND': 'neo4j',
       'FACTORY_DOCKER_COMMAND': 'sudo -n docker'}
initialize = [sys.executable, '-m', 'factory', 'metrics-knowledge-init', '--knowledge', str(config_path)]
with (evidence / 'knowledge-init.txt').open('w') as output:
    subprocess.run(initialize, cwd=demo, env=env, stdout=output, stderr=subprocess.STDOUT, check=True)
command = [sys.executable, '-m', 'factory', 'metrics-ingest', '--state', str(demo / '.runtime/bugfix'),
           '--mode', 'api', '--campaign', str(campaign), '--env-file', str(previous_private / 'model.env'),
           '--knowledge', str(config_path), '--root', 'materials/metrics',
           '--task-id', 'ingest-bugfix-20261103-1', '--output', str(private / 'ingested.json')]
with (evidence / 'real-ingest.json').open('w') as output, (evidence / 'real-ingest.stderr').open('w') as errors:
    process = subprocess.run(command, cwd=demo, env=env, stdout=output, stderr=errors)
(evidence / 'budget-after.json').write_text(json.dumps(read_campaign(campaign), indent=2))
report = private / 'ingested.ingest.json'
if report.is_file():
    value = json.loads(report.read_text())
    (evidence / 'ingest-report.json').write_text(json.dumps(value, ensure_ascii=False, indent=2))
    (evidence / 'ingested-snapshot.json').write_bytes((private / 'ingested.json').read_bytes())
    print(json.dumps({'exit_code': process.returncode, 'status': value['status'],
                      'sources': value['sources'], 'budget': value['budget']}, ensure_ascii=False))
else:
    print(json.dumps({'exit_code': process.returncode, 'report_written': False}))
