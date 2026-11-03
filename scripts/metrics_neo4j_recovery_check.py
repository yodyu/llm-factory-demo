"""Zero-API recovery acceptance. Stop/start only an explicitly authorized test Neo4j externally.

freeze -> operator stops test Neo4j -> continue -> operator starts/waits for ready
-> recover -> operator stops -> offline-replay -> operator starts.
Use a new --state. Does not administer Docker/Neo4j or touch a campaign budget.
"""
import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from factory.metrics.knowledge_store import open_knowledge
from factory.metrics.runtime import MetricsStore
from factory.metrics.model import make_gateway
from factory.metrics.workflow import run
from factory.metrics.publication import publish_pending
from factory.metrics.service import run_command
from factory.metrics.synthetic import generate,write_dataset
from factory.metrics.reports import bound_report,export_run
from factory.metrics.replay import replay_bundle
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--phase',choices=['freeze','continue','recover','offline-replay'],required=True)
parser.add_argument('--state',type=Path,required=True)
parser.add_argument('--knowledge',type=Path,required=True)
parser.add_argument('--image',required=True)
args=parser.parse_args()
state=args.state.resolve()
config=args.knowledge.resolve()
request={'requirement':'检测内存持续升高 memory MAD','anomaly_target':'upper','explicit_constraints':{'threshold':85.0}}
c=dict(requirement=request['requirement'],metric_kind='gauge',allowed_methods=['fixed_threshold','rolling_mad'],history_points=60,origin='mock')
image=args.image
if args.phase=='freeze':
 state.mkdir(mode=0o700)
 write_dataset(state/'data',generate('memory_shift'))
 (state/'request.json').write_text(json.dumps(request))
 with open_knowledge(config) as graph:
     snapshot,retrieval=graph.freeze(**c)
 (state/'frozen.json').write_text(json.dumps({'snapshot':snapshot,'retrieval':retrieval}))
 print('Frozen graph before real container shutdown.')
elif args.phase=='continue':
 args=SimpleNamespace(knowledge=config,task=state/'request.json',dataset=state/'data',state=state/'new-task',mode='mock',retrieval='structured',campaign=None,env_file=None,image=image,task_id='must-not-start',fault_injection=False)
 failed=False
 try:
     asyncio.run(run_command(args))
 except RuntimeError:
     failed=True
 assert failed and not (state/'new-task').exists()
 frozen=json.loads((state/'frozen.json').read_text())
 store=MetricsStore(state/'runtime.sqlite')
 gateway=make_gateway(store,mode='mock')
 graph=open_knowledge(config)
 try:
  result=asyncio.run(run(store,gateway,state=state,task_input=request,dataset_root=state/'data',snapshot=frozen['snapshot'],frozen_retrieval=frozen['retrieval'],knowledge=graph,image=image,task_id='neo4j-recovery-check'))
 finally:
     graph.close()
 assert result['status']=='COMPLETED' and result['publication']['status']=='PENDING_RETRY',result
 with store._transaction() as db:
     operations=db.execute('SELECT COUNT(*) FROM operations').fetchone()[0]
 (state/'continue-result.json').write_text(json.dumps({'new_task_failed_before_runtime':True,'result':result,'operations_before_retry':operations}))
 print('Real stopped Neo4j: new task rejected; frozen task completed; publication PENDING_RETRY.')
elif args.phase=='recover':
 outcome=json.loads((state/'continue-result.json').read_text())
 store=MetricsStore(state/'runtime.sqlite')
 directory=Path(outcome['result']['directory'])
 report=bound_report(store,directory)
 with open_knowledge(config) as graph:
  first=publish_pending(store,graph,report)
  snap=graph.snapshot()
  second=publish_pending(store,graph,report)
  assert first==second and graph.snapshot()==snap and first['status']=='PUBLISHED'
 with store._transaction() as db:
     operations=db.execute('SELECT COUNT(*) FROM operations').fetchone()[0]
 assert operations==outcome['operations_before_retry']
 export=export_run(store,directory,state/'bundle.zip',dataset_root=state/'data')
 result={'new_task_failed_before_runtime':True,'frozen_task_status':outcome['result']['status'],'during_outage':'PENDING_RETRY','recovered':first['status'],'duplicate_retry_equal':True,'operations_added_by_retry':0,'real_api_calls':0,'bundle':export,'snapshot_id':report['task']['knowledge_snapshot']}
 (state/'outage-report.json').write_text(json.dumps(result,indent=2))
 print(json.dumps(result))
elif args.phase=='offline-replay':
 outcome=json.loads((state/'outage-report.json').read_text())
 replay=replay_bundle(state/'bundle.zip',outcome['bundle']['sha256'],state=state/'offline-replay',image=image)
 assert replay['model_calls']==0 and replay['effect_matches_recorded']
 (state/'offline-replay-report.json').write_text(json.dumps(replay,indent=2))
 print('Replay while Neo4j stopped: COMPLETED; zero model; effects match.')
