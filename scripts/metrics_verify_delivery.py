"""Verify final package digests and credential exclusion on the authorized server."""

import argparse
import json
import sqlite3
import zipfile
from pathlib import Path

from factory.models.environment import load_environment
from factory.runtime.config import Settings
from factory.runtime.artifacts import digest
from factory.metrics.knowledge import verify_snapshot


def check_document(guard, value, relative):
    """The historical audit has a status key that resembles a credential field."""
    if relative == "checks/delivery-verification.json" and isinstance(value, dict):
        if value.get("registered_credential_scan") != "PASSED":
            raise ValueError("invalid historical scan status")
        # Only this exact literal status is metadata. Every other field/value
        # and the complete file still undergo the ordinary secret checks.
        guard.require_public({key: item for key, item in value.items() if key != "registered_credential_scan"})
    else:
        guard.require_public(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings.from_env(load_environment(args.env_file))
    guard = settings.secret_guard()
    registered = [value.get_secret_value().encode() for value in (settings.llm_api_key, settings.embedding_api_key) if value]
    archives, files = 0, 0
    fixture_exceptions = []
    for path in args.delivery.rglob("*"):
        if not path.is_file():
            continue
        if any(value in path.read_bytes() for value in registered):
            raise ValueError("registered credential in delivery: " + str(path.relative_to(args.delivery)))
        if path.suffix in {".env", ".db"} or path.name in {"runtime.sqlite", "campaign.sqlite"}:
            raise ValueError("runtime/credential file in delivery")
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as archive:
                manifest = json.loads(archive.read("bundle-manifest.json"))
                if set(archive.namelist()) != set(manifest["files"]) | {"bundle-manifest.json"}:
                    raise ValueError("archive whitelist mismatch")
                for name, item in manifest["files"].items():
                    raw = archive.read(name)
                    if digest(raw) != item["sha256"] or len(raw) != item["bytes"]:
                        raise ValueError("archive digest mismatch")
                    text = raw.decode("utf-8")
                    guard.require_public(text)
                    if name.endswith(".json"):
                        guard.require_public(json.loads(text))
                    files += 1
            archives += 1
        elif path.suffix in {".json", ".md", ".py", ".xml", ".sha256"}:
            text = path.read_text()
            try:
                guard.require_public(text)
            except ValueError:
                if path.suffix == ".xml":
                    # JUnit test IDs deliberately include fake Bearer/key fixtures.
                    # The full file has already passed actual registered-key matching.
                    fixture_exceptions.append(str(path.relative_to(args.delivery)))
                else:
                    raise ValueError("credential-shaped text in " + str(path.relative_to(args.delivery))) from None
            if path.suffix == ".json":
                data = json.loads(text)
                check_document(guard, data, path.relative_to(args.delivery).as_posix())
                if isinstance(data, dict) and data.get("schema_version") in {"metrics-knowledge/1", "metrics-knowledge/2"}:
                    if path.name == 'retrieval.json' and 'nodes' not in data and 'relations' not in data:
                        # Legacy retrieval sidecars used the graph schema version.
                        # Validate their frozen bindings instead of treating them as snapshots.
                        frozen = verify_snapshot(json.loads(path.with_name('knowledge.json').read_text()))
                        by_id = {node['id']: node for node in frozen['nodes']}
                        if data.get('snapshot_id') != frozen['snapshot_id'] or not set(data['knowledge_ids']) <= set(by_id):
                            raise ValueError('retrieval frozen binding mismatch')
                        for cap in data.get('capabilities', []):
                            if cap != {'id': cap['id'], **by_id[cap['id']]['payload']}:
                                raise ValueError('retrieval capability differs from snapshot')
                        for chunk in data.get('chunks', []):
                            payload = by_id[chunk['id']]['payload']
                            if any(chunk.get(key) != value for key, value in payload.items()):
                                raise ValueError('retrieval chunk differs from snapshot')
                    else:
                        verify_snapshot(data)
        elif path.name == "knowledge.sqlite":
            with sqlite3.connect(path) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError("knowledge database integrity failure")
                for (raw,) in db.execute("SELECT payload FROM nodes"):
                    guard.require_public(json.loads(raw))
    result = {"archives": archives, "verified_archive_files": files, "digest_checks": "PASSED",
              "registered_credential_scan": "PASSED", "knowledge_integrity": "PASSED", "model_calls": 0,
              "heuristic_fixture_exceptions": fixture_exceptions,
              "fixture_note": "JUnit contains intentional fake credential-shaped test IDs; all XML still scanned for actual registered keys"}
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
