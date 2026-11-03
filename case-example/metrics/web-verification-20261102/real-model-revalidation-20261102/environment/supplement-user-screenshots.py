import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image
from factory.metrics.budget import read_campaign

root = Path('/path/to/llm-factory/real-web-revalidation-20261102')
proof = root / 'demo/case-example/metrics/web-verification-20261102/real-model-revalidation-20261102'
report = json.loads((proof / 'audit/runs/disk/report.json').read_text())
assert report['task']['task_id'] == 'ui-da4c1f50a3504008'
assert report['status'] == 'COMPLETED'
assert abs(report['final']['point']['f1']['value'] - 0.3333) < 0.00005
assert report['final']['normal_false_alarms_per_host_hour']['value'] == 0
assert report['final']['matched_delay_seconds']['median'] == 480
assert report['final']['coverage']['value'] == 1
audit = json.loads((proof / 'audit/runs/disk/audit.json').read_text())
usage = audit['knowledge_usage']
assert [len(usage[k]) for k in ['supplied','cited','supplied_experiences','cited_experiences']] == [14,8,3,3]

images = []
for name, original, page in [
    ('37-disk-result-user.png','codex-clipboard-23e13a71-8449-423d-9a4c-081cdda0e035.png','result_overview'),
    ('38-disk-knowledge-user.png','codex-clipboard-77487005-3ff4-4511-b0a2-398b29165c21.png','knowledge_basis'),
]:
    path = proof / 'screenshots' / name
    with Image.open(path) as image:
        assert image.format == 'PNG'
        dimensions = list(image.size)
        image.verify()
    images.append({'original_filename':original, 'stored_path':'screenshots/' + name,
                   'source':'user attachment', 'page':page, 'image_format':'PNG',
                   'dimensions':dimensions, 'bytes':path.stat().st_size,
                   'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                   'processing':'file copy only; no cropping, compositing or image edits'})
record = {'recorded_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
          'task_id':report['task']['task_id'], 'source':'two screenshots supplied by the user in this chat',
          'task_selector_visible_prefix':'ui-da4c1f5',
          'visible_values_match_server_report':True,
          'comparison_method':'assistant visual inspection of supplied images; visible values independently checked against audited JSON',
          'visible_values':{'status':'completed','effect':'measured','selected_method':'EWMA','persistence_points':2,
              'point_f1_display':'0.3333','normal_false_alarms_display':'0.0000',
              'delay_seconds_display':'480.0000','coverage_display':'100.0%',
              'provided_knowledge':14,'cited_knowledge':8,'provided_experiences':3,'cited_experiences':3},
          'not_shown_in_supplied_images':['full task ID','candidate comparison','expanded experience IDs','publication receipt'],
          'images':images,
          'campaign_snapshot_at_supplement':read_campaign(Path('/path/to/private-config/llm-factory-web-revalidation-20261102/campaign.sqlite'))}
(proof / 'user-screenshot-evidence.json').write_text(json.dumps(record,ensure_ascii=False,indent=2) + '\n')
print(json.dumps({'task_id':record['task_id'],'user_images':len(images),
                  'visible_values_match_server_report':True,
                  'lifetime_model_requests':record['campaign_snapshot_at_supplement']['lifetime_reserved']},ensure_ascii=False))
