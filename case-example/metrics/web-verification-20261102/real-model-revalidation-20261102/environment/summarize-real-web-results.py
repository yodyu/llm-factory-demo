import json
from pathlib import Path

root = Path('/path/to/llm-factory/real-web-revalidation-20261102/review-evidence')
summary = {}
for path in (root / 'runs').glob('*/audit.json'):
    r = json.loads(path.read_text())
    final = r.get('final') or {}
    point, event = final.get('point') or {}, final.get('event') or {}
    value = lambda group, key: (group.get(key) or {}).get('value')
    result = {'task_id':r['task_id'], 'status':r['status'], 'origin':r['origin'],
              'point_precision':value(point,'precision'), 'point_recall':value(point,'recall'),
              'point_f1':value(point,'f1'), 'event_f1':value(event,'f1'),
              'point_counts':{k:point.get(k) for k in ['tp','fp','fn','tn','total']},
              'event_counts':{k:event.get(k) for k in ['tp','fp','fn']},
              'delay_median':(final.get('matched_delay_seconds') or {}).get('median'),
              'normal_false_alarms_per_hour':value(final,'normal_false_alarms_per_host_hour'),
              'coverage':value(final,'coverage'), 'model_usage':r['usage'],
              'runtime_seconds':r['workflow_runtime_seconds'], 'selected':(r.get('selection') or {}).get('selected'),
              'provided_knowledge':len(r['knowledge_usage']['supplied']),
              'cited_knowledge':len(r['knowledge_usage']['cited']),
              'provided_experiences':len(r['knowledge_usage']['supplied_experiences']),
              'cited_experiences':len(r['knowledge_usage']['cited_experiences']),
              'publication_nodes':len(r['publication'].get('node_ids',[])), 'candidates':[]}
    for c in r['candidates']:
        dev = c.get('development') or {}
        point = dev.get('point') or {}
        beta = (r.get('selection') or {}).get('beta',1)
        tp,fp,fn = (point.get(k,0) for k in ['tp','fp','fn'])
        denominator = (1+beta*beta)*tp+beta*beta*fn+fp
        result['candidates'].append({'method':c['config']['method_id'], 'candidate_id':c['candidate_id'],
            'source_paths':[v['source_path'] for v in c['versions']],
            'checks_per_version':[len(v['checks']) for v in c['versions']],
            'passed_per_version':[v['passed'] for v in c['versions']],
            'dev_precision':value(point,'precision'), 'dev_recall':value(point,'recall'),
            'dev_f1':value(point,'f1'), 'dev_fbeta':((1+beta*beta)*tp/denominator if denominator else None),
            'beta':beta, 'source_sha256':[v['source_sha256'] for v in c['versions']]})
    summary[r['label']]=result
checks=json.loads((root/'extraction-checks.json').read_text())
sources=sorted((root.parent/'demo/materials/metrics').iterdir())
source_results={p.name:{'source_checked':any(c.get('path')==p.name and c.get('status')=='source_checked' for c in checks),
                          'checks':[c.get('status') for c in checks if c.get('path')==p.name]}
                for p in sources if p.suffix in {'.txt','.py','.md'}}
output={'experiments':summary, 'material_sources':source_results}
(root/'results-summary.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(output,ensure_ascii=False,indent=2))
