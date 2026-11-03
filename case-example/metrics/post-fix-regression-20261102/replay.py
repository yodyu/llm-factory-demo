"""Post-fix development-only replay. Run only on the authorized server."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from contracts.metrics import MetricsTask
from factory.metrics.orchestration.nodes import task_actions
from factory.metrics.ui_presentation import selection_explanation

parser = argparse.ArgumentParser()
parser.add_argument('--source-state', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--web-state', type=Path, required=True)
args = parser.parse_args()
ids = {'ui-b0c4acdd29bc47d9', 'ui-a25079152c7940fa'}
web_ids = ids | {'ui-ac5fa8e7cab64a6d', 'ui-96ad0eca55c14f59'}
results = []
for path in sorted(args.source_state.glob('runs/*/report.json')):
    raw = path.read_bytes()
    report = json.loads(raw)
    task_id = report['task']['task_id']
    if task_id in web_ids or ('cpu' in report['task'].get('metric', '').lower()):
        dest = args.web_state/'runs'/path.parent.name
        if not dest.exists():
            shutil.copytree(path.parent, dest)
    if task_id not in ids:
        continue
    task = MetricsTask.model_validate(report['task'])
    # The actual orchestration adapter sees development records only. No final
    # evaluation, model, sandbox, publication or history write is invoked.
    ctx = SimpleNamespace(task=task, legacy_upload=False,
        report={'task':task.model_dump(mode='json'), 'candidates':report['candidates']})
    task_actions(ctx, None)['select_candidate']({})
    results.append({'kind':'post_fix_development_replay', 'task_id':task_id,
        'source_report_sha256':hashlib.sha256(raw).hexdigest(),
        'frozen_objective':task.evaluation_objective, 'frozen_policy':task.selection_policy,
        'original_selection':report['selection'], 'replayed_selection':ctx.report['selection'],
        'selection_explanation':selection_explanation(ctx.report),
        'source_unchanged':path.read_bytes()==raw, 'model_calls':0, 'final_test_executed':False})
assert len(results) == 2
args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2)+'\n')
print(json.dumps([{k:r[k] for k in ('task_id','frozen_objective','replayed_selection','source_unchanged')} for r in results], ensure_ascii=False, indent=2))
