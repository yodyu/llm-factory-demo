"""Read-only environment diagnostics with redacted, actionable results."""

import os
import re
import subprocess
import sys

from execution.runner import docker_command_from_env


def diagnose(*, image=None, knowledge=None, env_file=None):
    checks = []

    def record(name, ok, hint):
        checks.append({"check": name, "status": "PASSED" if ok else "UNAVAILABLE", "hint": hint})

    record("python", sys.version_info >= (3, 12), "Use Python 3.12 or later in .venv.")
    command = docker_command_from_env()

    def docker(*args):
        try:
            return subprocess.run([*command, *args], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    available = docker("info")
    record("docker", available, "Check daemon access; configure FACTORY_DOCKER_COMMAND if needed.")
    image = image or os.environ.get("FACTORY_METRICS_IMAGE", "")
    record("sandbox_image", bool(re.fullmatch(r"sha256:[0-9a-f]{64}", image))
           and available and docker("image", "inspect", image),
           "Run make sandbox; export FACTORY_METRICS_IMAGE to its full image ID.")
    backend = os.environ.get("FACTORY_KNOWLEDGE_BACKEND", "neo4j")
    try:
        if backend == "local":
            # Do not create or migrate a database during diagnosis.
            from pathlib import Path
            path = knowledge or os.environ.get("FACTORY_METRICS_KNOWLEDGE")
            ok = bool(path and Path(path).is_file())
            if ok:
                import sqlite3
                from contextlib import closing
                with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
                    ok = db.execute("PRAGMA application_id").fetchone()[0] == 0x4D4B4E57
        else:
            from factory.metrics.knowledge_store import open_knowledge
            with open_knowledge(knowledge) as store:
                store.snapshot()
            ok = True
    except Exception:
        ok = False
    record("knowledge", ok, "Initialize the explicitly selected backend; no automatic fallback.")
    # Only check presence. Never echo credentials or perform a paid request.
    try:
        from factory.models.environment import load_environment
        values = load_environment(env_file or os.environ.get("FACTORY_METRICS_MODEL_ENV"))
        model_ok = all(values.get(key) for key in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"))
    except (OSError, ValueError):
        model_ok = False
    record("model", model_ok, "Mock needs no key; API mode needs an explicit model profile/env file.")
    return {"checks": checks, "knowledge_backend": backend,
            "levels": {"L0": checks[0]["status"] == "PASSED",
                       "L1": all(c["status"] == "PASSED" for c in checks[:4]),
                       "L2": all(c["status"] == "PASSED" for c in checks)}}
