import subprocess
from types import SimpleNamespace

import pytest

from execution.runner import docker_command_from_env
from factory.metrics.doctor import diagnose


def test_docker_command_default_quoted_arguments_and_invalid_values(monkeypatch):
    monkeypatch.delenv("FACTORY_DOCKER_COMMAND", raising=False)
    assert docker_command_from_env() == ("docker",)
    monkeypatch.setenv("FACTORY_DOCKER_COMMAND", 'sudo -n docker --context "a b"')
    assert docker_command_from_env() == ("sudo", "-n", "docker", "--context", "a b")
    for value in ("", "  ", 'docker "'):
        monkeypatch.setenv("FACTORY_DOCKER_COMMAND", value)
        with pytest.raises(ValueError):
            docker_command_from_env()


def test_doctor_reports_missing_dependencies_without_creating_local_database(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_KNOWLEDGE_BACKEND", "local")
    monkeypatch.setenv("LLM_API_KEY", "secret-do-not-display")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    def missing(*args, **kwargs):
        raise FileNotFoundError()
    monkeypatch.setattr(subprocess, "run", missing)
    path = tmp_path / "absent.sqlite"
    result = diagnose(knowledge=path)
    assert not path.exists()
    assert result["levels"] == {"L0": True, "L1": False, "L2": False}
    assert "secret-do-not-display" not in str(result)


def test_doctor_uses_configured_command_and_checks_image(tmp_path, monkeypatch):
    from factory.metrics.local_store import LocalKnowledgeStore
    path = tmp_path / "knowledge.sqlite"
    LocalKnowledgeStore(path)
    monkeypatch.setenv("FACTORY_KNOWLEDGE_BACKEND", "local")
    monkeypatch.setenv("FACTORY_DOCKER_COMMAND", "docker --context test")
    calls = []
    def available(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, "run", available)
    result = diagnose(image="sha256:" + "a" * 64, knowledge=path)
    assert result["levels"]["L1"]
    assert calls == [["docker", "--context", "test", "info"],
                     ["docker", "--context", "test", "image", "inspect", "sha256:" + "a" * 64]]


def test_doctor_checks_explicit_model_file_without_echoing_values(tmp_path, monkeypatch):
    path = tmp_path / "model.env"
    path.write_text("LLM_BASE_URL=https://private.invalid/v1\nLLM_API_KEY=private-token\nLLM_MODEL=test-model\n")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1))
    result = diagnose(env_file=path)
    assert next(c for c in result["checks"] if c["check"] == "model")["status"] == "PASSED"
    assert "private-token" not in str(result) and "private.invalid" not in str(result)
