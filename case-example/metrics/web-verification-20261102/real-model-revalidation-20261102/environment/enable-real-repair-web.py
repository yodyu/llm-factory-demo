import difflib
import hashlib
import json
from pathlib import Path

root = Path('/path/to/llm-factory/real-web-revalidation-20261102')
path = root / 'demo/src/factory/metrics/creation.py'
original = path.read_text()
assert original.count('fault_injection=False') == 1
assert 'FACTORY_ACCEPTANCE_FAULT_INJECTION' not in original
(root / 'evidence/creation-original.py').write_text(original)
changed = original.replace('import asyncio\n', 'import asyncio\nimport os\n', 1)
changed = changed.replace(
    "    mode, retrieval = settings['model_mode'], 'structured'\n",
    "    mode, retrieval = settings['model_mode'], 'structured'\n"
    "    if os.environ.get('FACTORY_ACCEPTANCE_FAULT_INJECTION') == '1':\n"
    "        st.warning('验收专用：真实模型初版将注入明确标记的分数偏移错误，再由真实模型修复；不计自然错误修复率。')\n", 1)
changed = changed.replace('fault_injection=False', "fault_injection=os.environ.get('FACTORY_ACCEPTANCE_FAULT_INJECTION') == '1'", 1)
temporary = path.with_suffix('.acceptance-tmp')
temporary.write_text(changed)
temporary.replace(path)
(root / 'evidence/repair-web-instrumentation.diff').write_text(''.join(difflib.unified_diff(
    original.splitlines(keepends=True), changed.splitlines(keepends=True),
    fromfile='baseline/src/factory/metrics/creation.py', tofile='acceptance/src/factory/metrics/creation.py')))
record = {'purpose': 'User-authorized Web invocation of existing fault_injection switch',
          'baseline_sha256': hashlib.sha256(original.encode()).hexdigest(),
          'instrumented_sha256': hashlib.sha256(changed.encode()).hexdigest(),
          'scope': 'isolated server checkout only; port 18504 process enables flag; port 18503 keeps existing module',
          'injection_implementation': 'existing orchestration/candidate.py and execution_ops.FAULT unchanged',
          'real_model': True, 'authorization': 'user explicitly allowed fault injection on 2026-11-02'}
(root / 'evidence/repair-instrumentation.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(record, ensure_ascii=False))
