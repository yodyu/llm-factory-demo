"""Server-only, mock + real Docker, three reproducible review cases. No API budget use."""
import argparse
import asyncio
import csv
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from contracts.metrics import MetricPoint
from factory.metrics.data import encode_csv
from factory.metrics.knowledge import KnowledgeStore
from factory.metrics.service import ingest_command, run_command
from factory.metrics.synthetic import generate, write_dataset
from factory.metrics.upload import prepare_legacy_upload as prepare_upload


async def main(args):
    args.state.mkdir(parents=True, exist_ok=False)
    knowledge = KnowledgeStore(args.knowledge)
    knowledge.initialize()
    knowledge.close()
    common = dict(state=args.state.resolve(), mode="mock", campaign=None, env_file=None, knowledge=args.knowledge,
                  image=args.image, retrieval="structured", fault_injection=False, snapshot=None)
    await ingest_command(SimpleNamespace(**common, task_id="upload-review-ingest", root=Path("materials/metrics"),
        sources=None, output=args.state / "snapshot.json"))
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    results = []
    for name in ("builtin", "upload-unlabelled", "upload-labelled"):
        inputs = args.state / "inputs" / name
        inputs.mkdir(parents=True)
        dataset = inputs / "dataset"
        if name == "builtin":
            write_dataset(dataset, generate("memory_shift"))
        else:
            # Explicit controlled injection is the source of these demo labels.
            points = [MetricPoint(timestamp=start+timedelta(minutes=i), host_id="customer-host-7",
                value=None if 230 <= i < 234 else float(91 if 250 <= i < 270 else 40+(i%7)*0.1)) for i in range(360)]
            raw = encode_csv(points)
            labels = None
            if name == "upload-labelled":
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(["timestamp", "host_id", "is_anomaly"])
                for i, p in enumerate(points[200:], 200):
                    writer.writerow([p.timestamp.isoformat(), p.host_id, int(250 <= i < 270)])
                labels = output.getvalue().encode()
            prepare_upload(dataset, raw, display_name=name+".csv", host_id="customer-host-7", metric="memory_utilization",
                unit="percent", metric_kind="gauge", sampling_seconds=60, valid_range=(0,100), fit_points=60,
                history_points=200, method="fixed_threshold", labels=labels, label_source="用户提供标签；本案例为独立受控注入")
        task = inputs / "request.json"
        task.write_text(json.dumps({"requirement": "检测内存持续升高，明确业务阈值85，连续两点告警", "expected_metric": "memory_utilization",
            "anomaly_target": "upper", "explicit_constraints": {"threshold": 85.0, "direction": "upper", "persistence_points": 2.0}}, ensure_ascii=False))
        result = await run_command(SimpleNamespace(**common, task_id=name, task=task, dataset=dataset))
        results.append(result)
    (args.state / "acceptance.json").write_text(json.dumps({"model_mode": "mock", "real_api_calls": 0, "runs": results}, indent=2))
    print(json.dumps({"runs": [{"task_id": r["task_id"], "status": r["status"]} for r in results], "real_api_calls": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--knowledge", type=Path, required=True, help="explicit independent Neo4j namespace config")
    parser.add_argument("--image", required=True)
    asyncio.run(main(parser.parse_args()))
