"""Reproducible setup commands; credentials stay outside the repository."""

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

from execution.runner import docker_command_from_env

ROOT = Path(__file__).resolve().parents[1]


def command(*args, capture=False, env=None):
    return subprocess.run(args, cwd=ROOT, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None, env=env)


def sandbox():
    docker = docker_command_from_env()
    command(*docker, "build", "-f", "Dockerfile.sandbox", "-t", "llm-factory-metrics-sandbox", ".")
    image = command(*docker, "image", "inspect", "--format", "{{.Id}}",
                    "llm-factory-metrics-sandbox", capture=True).stdout.strip()
    directory = ROOT / ".runtime/bootstrap"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "image-id").write_text(image + "\n")
    print(image)


def demo():
    from factory.metrics.knowledge_store import open_knowledge

    started = time.monotonic()
    output = ROOT / "demo-output" / (time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3))
    output.mkdir(parents=True)
    knowledge = output / "knowledge.sqlite"
    image = (ROOT / ".runtime/bootstrap/image-id").read_text().strip()
    env = {**os.environ, "FACTORY_KNOWLEDGE_BACKEND": "local"}
    with open_knowledge(knowledge) as store:
        store.initialize()
    common = ["--state", str(output / "state"), "--mode", "mock", "--knowledge", str(knowledge)]
    command(sys.executable, "-m", "factory", "metrics-ingest", *common,
            "--root", str(ROOT / "materials/metrics"), "--output", str(output / "knowledge.json"), env=env)
    command(sys.executable, "-m", "factory.metrics", "simulate", "--scenario", "memory_shift",
            "--output", str(output / "dataset"), env=env)
    command(sys.executable, "-m", "factory", "metrics-run", *common,
            "--task", str(ROOT / "examples/metrics/tasks/memory-shift.json"),
            "--dataset", str(output / "dataset"), "--image", image, env=env)
    reports = list((output / "state/runs").glob("*/report.json"))
    if len(reports) != 1:
        raise RuntimeError("expected one task report")
    report = json.loads(reports[0].read_text())
    publication = json.loads((reports[0].parent / "publication.json").read_text())
    if report["status"] != "COMPLETED" or publication.get("status") != "PUBLISHED":
        raise RuntimeError("demo did not complete; inspect " + str(reports[0]))
    print(json.dumps({"report": str(reports[0].with_suffix(".md")),
                      "elapsed_seconds": round(time.monotonic() - started, 2), "origin": "mock"}))


def neo4j():
    directory = Path(os.environ.get("FACTORY_SECRET_DIR", Path.home() / ".config/llm-factory"))
    directory = directory.expanduser().resolve()
    if directory.is_relative_to(ROOT.resolve()):
        raise ValueError("FACTORY_SECRET_DIR must be outside repository")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    auth_file = directory / "neo4j-auth"
    if not auth_file.exists():
        fd = os.open(auth_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write("neo4j/" + secrets.token_urlsafe(32))
    env = {**os.environ, "FACTORY_NEO4J_AUTH_FILE": str(auth_file),
           "FACTORY_NEO4J_UID": str(os.getuid()), "FACTORY_NEO4J_GID": str(os.getgid())}
    if os.getuid() == 0:
        raise ValueError("run bootstrap as a non-root user with Docker access")
    # sudo may discard environment variables. Compose reads only non-secret
    # paths/ports from this private file, rather than requiring sudo -E.
    compose_env = directory / "compose.env"
    compose_env.write_text("\n".join(f"{key}={env[key]}" for key in (
        "FACTORY_NEO4J_AUTH_FILE", "FACTORY_NEO4J_HTTP_PORT", "FACTORY_NEO4J_BOLT_PORT",
        "FACTORY_NEO4J_UID", "FACTORY_NEO4J_GID")
        if key in env) + "\n")
    compose_env.chmod(0o600)
    command(*docker_command_from_env(), "compose", "--env-file", str(compose_env),
            "-f", "docker-compose.yml", "up", "-d", "--wait", env=env)
    config = directory / "knowledge.json"
    config.write_text(json.dumps({"uri": "bolt://127.0.0.1:" + env.get("FACTORY_NEO4J_BOLT_PORT", "7688"),
                                  "auth_file": str(auth_file), "namespace": "factory-demo"}) + "\n")
    config.chmod(0o600)
    print("Initialize with: factory metrics-knowledge-init --knowledge " + str(config))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["sandbox", "demo", "neo4j"])
    {"sandbox": sandbox, "demo": demo, "neo4j": neo4j}[parser.parse_args().action]()
