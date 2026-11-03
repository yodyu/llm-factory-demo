"""Run only on the authorized server. Installs this project's separate user service."""

import argparse
import json
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

NAME = "llm-factory-metrics.service"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8502)
    parser.add_argument("--image", required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--model-env", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, help="optional historical evidence; not a live knowledge source")
    parser.add_argument("--knowledge", type=Path, required=True, help="server-only Neo4j config for an already initialized/migrated namespace")
    parser.add_argument("--history", type=Path, action="append", default=[])
    args = parser.parse_args()
    root = args.root.resolve()
    for path in (root / ".venv/bin/python", root / "streamlit_app.py", args.campaign, args.model_env, args.knowledge):
        if not path.is_file():
            raise ValueError("missing deployment input: " + str(path))
    if not 1024 <= args.port <= 65535:
        raise ValueError("invalid unprivileged port")
    state = root / ".runtime/metrics/deployment/ui"
    state.mkdir(parents=True, exist_ok=True)
    knowledge = args.knowledge.resolve()
    from factory.metrics.knowledge_store import open_knowledge
    graph = open_knowledge(knowledge)
    try:
        graph.snapshot()  # Read-only preflight; no implicit import or namespace creation.
    finally:
        graph.close()
    # Viewing copies are independent of the sealed original and do not import runtime DBs.
    for source in args.history:
        report = json.loads((source / "report.json").read_text())
        from factory.metrics.knowledge import identity
        target = state / "runs" / identity("view", report["task"]["task_id"])
        if not target.exists():
            shutil.copytree(source, target)
    config = Path.home() / ".config/llm-factory-metrics"
    config.mkdir(parents=True, exist_ok=True, mode=0o700)
    values = {
        "PYTHONPATH": str(root / "src"),
        "PYTHONUNBUFFERED": "1",
        "FACTORY_METRICS_STATE": str(state),
        "FACTORY_METRICS_KNOWLEDGE": str(knowledge),
        "FACTORY_METRICS_SNAPSHOT": str(args.snapshot.resolve()) if args.snapshot else "",
        "FACTORY_METRICS_CAMPAIGN": str(args.campaign.resolve()),
        "FACTORY_METRICS_MODEL_ENV": str(args.model_env.resolve()),
        "FACTORY_METRICS_IMAGE": args.image,
    }
    env = config / "runtime.env"
    env.write_text("".join(key + "=" + json.dumps(value) + "\n" for key, value in values.items()))
    env.chmod(0o600)
    unit = Path.home() / ".config/systemd/user" / NAME
    unit.parent.mkdir(parents=True, exist_ok=True)
    if unit.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(unit, unit.with_suffix(".service.backup-" + stamp))
    template = (root / "deploy/llm-factory-metrics.service.in").read_text()
    unit.write_text(template.replace("@ROOT@", str(root)).replace("@PORT@", str(args.port)))
    subprocess.run(["systemd-analyze", "--user", "verify", str(unit)], check=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", NAME], check=True)
    with sqlite3.connect(args.campaign.resolve().as_uri() + "?mode=ro", uri=True) as db:
        used = db.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
    receipt = {"service": NAME, "bind": f"127.0.0.1:{args.port}", "root": str(root),
               "state": str(state), "model_calls_used": used, "history_copies": len(args.history),
               "credentials_copied": False}
    (state.parent / "deployment.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
