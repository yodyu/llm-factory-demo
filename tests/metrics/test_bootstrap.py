import json

import pytest

from scripts import metrics_bootstrap as bootstrap


def test_neo4j_bootstrap_keeps_private_auth_and_passes_compose_config(tmp_path, monkeypatch):
    private = tmp_path / "private"
    monkeypatch.setattr(bootstrap, "ROOT", tmp_path / "repo")
    monkeypatch.setenv("FACTORY_SECRET_DIR", str(private))
    monkeypatch.setenv("FACTORY_DOCKER_COMMAND", "docker")
    monkeypatch.setenv("FACTORY_NEO4J_BOLT_PORT", "17688")
    monkeypatch.setattr(bootstrap.os, "getuid", lambda: 1001)
    monkeypatch.setattr(bootstrap.os, "getgid", lambda: 1001)
    calls = []
    monkeypatch.setattr(bootstrap, "command", lambda *args, **kwargs: calls.append(args))
    bootstrap.neo4j()
    original = (private / "neo4j-auth").read_bytes()
    assert (private / "neo4j-auth").stat().st_mode & 0o777 == 0o600
    assert (private.stat().st_mode & 0o777) == 0o700
    assert json.loads((private / "knowledge.json").read_text())["uri"] == "bolt://127.0.0.1:17688"
    compose = (private / "compose.env").read_text()
    assert "FACTORY_NEO4J_UID=1001" in compose
    assert "FACTORY_NEO4J_GID=1001" in compose
    assert original.decode() not in compose
    assert calls[0][:4] == ("docker", "compose", "--env-file", str(private / "compose.env"))
    bootstrap.neo4j()
    assert (private / "neo4j-auth").read_bytes() == original


def test_neo4j_bootstrap_rejects_repository_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "ROOT", tmp_path)
    monkeypatch.setenv("FACTORY_SECRET_DIR", str(tmp_path / "secrets"))
    with pytest.raises(ValueError, match="outside repository"):
        bootstrap.neo4j()
    assert not (tmp_path / "secrets").exists()
