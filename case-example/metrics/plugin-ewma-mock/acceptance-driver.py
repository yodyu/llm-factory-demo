"""Controlled mock acceptance at the plugin-only commit; no model API access."""
import asyncio
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

from factory.metrics.service import ingest_command, run_command
from factory.metrics.requirements import build_draft, controlled_extract, binding_for, request_from_draft
from factory.metrics.synthetic import generate, write_dataset
from factory.metrics.execution_ops import write_json
from factory.metrics.local_store import LocalKnowledgeStore
from factory.metrics.runtime import MetricsStore

root = Path.cwd()
output = root / '.runtime/ewma-acceptance'
output.mkdir(parents=True, exist_ok=False)
os.environ['FACTORY_KNOWLEDGE_BACKEND'] = 'local'
knowledge = output / 'knowledge.sqlite'
state = output / 'state'
ingest = SimpleNamespace(knowledge=knowledge, state=state, mode='mock', campaign=None, env_file=None,
                        task_id='ewma-plugin-ingest', root=root / 'materials/metrics', sources=None, output=output / 'knowledge.json')
result = asyncio.run(ingest_command(ingest))
assert result['status'] == 'SUCCEEDED', result
text = '比较固定阈值、滚动MAD和EWMA检测模拟内存持续升高，固定阈值85%，连续两点告警'
draft = build_draft([text], [controlled_extract(text)], binding=binding_for([text]))
request = request_from_draft(draft, current_binding=draft.binding)
assert set(request.allowed_methods) == {'fixed_threshold', 'rolling_mad', 'ewma'}
assert request.budgets.candidates == 3
write_json(output / 'request.json', request.model_dump(mode='json'))
write_dataset(output / 'dataset', generate('memory_shift'))
args = SimpleNamespace(knowledge=knowledge, state=state, mode='mock', campaign=None, env_file=None,
                       task_id='ewma-three-candidates', task=output / 'request.json', dataset=output / 'dataset',
                       image=os.environ['FACTORY_METRICS_IMAGE'], retrieval='structured', fault_injection=False)
result = asyncio.run(run_command(args))
assert result['status'] == 'COMPLETED', result
assert result['publication']['status'] == 'PUBLISHED'
directory = Path(result['directory'])
report = json.loads((directory / 'report.json').read_text())
assert report['generation_protocol'] == 'capability-generation/2'
assert report['origin'] == 'mock'
assert len(report['candidates']) == 3
assert all(c['versions'][-1]['validation']['passed'] for c in report['candidates'])
assert all(c['versions'][-1]['validation']['verification_level'] == 'reference_verified' for c in report['candidates'])
assert all(c['versions'][-1]['specification_sha256'] for c in report['candidates'])
store = LocalKnowledgeStore(knowledge)
snapshot = store.snapshot()
assert any(n['kind'] == 'Implementation' and n['payload']['config']['method_id'] == 'ewma' for n in snapshot['nodes'])
assert any(n['kind'] == 'ValidationRun' and n['payload']['method_checks']['config']['method_id'] == 'ewma' for n in snapshot['nodes'])
# Model inputs contain no role registries, final labels, injection seeds or test values.
runtime = MetricsStore(state / 'runtime.sqlite')
with runtime._transaction() as db:
    prompts = [runtime.document(row[0]) for row in db.execute("SELECT reference FROM task_artifacts WHERE role='model-prompt'")]
for prompt in prompts:
    for message in prompt['messages']:
        if message['role'] != 'user':
            continue
        data = json.loads(message['content'])['input']
        if 'task' in data:
            assert not {'roles', 'labels', 'seed', 'injection', 'test'} & set(data['task'])
receipt = {'origin': 'mock', 'real_model_requests': 0,
           'status': 'PASSED', 'task': text, 'candidates': [c['plan']['config']['method_id'] for c in report['candidates']],
           'generation_protocol': report['generation_protocol'], 'publication': result['publication']['status'],
           'all_reference_verified': True, 'new_plugin_commit_changes_src': False,
           'limitations': ['expert references copied by mock', 'synthetic data and low event count', 'real API not verified']}
target = root / 'case-example/metrics/plugin-ewma-mock'
target.mkdir(parents=True, exist_ok=False)
shutil.copytree(directory, target / 'run')
for name in ('request.json', 'knowledge.json'):
    shutil.copy2(output / name, target / name)
write_json(target / 'published-knowledge.json', snapshot)
write_json(target / 'acceptance.json', receipt)
print(json.dumps(receipt, ensure_ascii=False))
