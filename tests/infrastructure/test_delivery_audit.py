"""Audit status metadata must not bypass real credential rejection."""
import importlib.util
from pathlib import Path
import pytest
from factory.runtime.security import SecretGuard


spec = importlib.util.spec_from_file_location("delivery_audit", Path(__file__).resolve().parents[2] / "scripts/metrics_verify_delivery.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_historical_status_has_one_narrowly_typed_exception():
    guard = SecretGuard()
    value = {"registered_credential_scan": "PASSED", "archives": 16}
    audit.check_document(guard, value, "checks/delivery-verification.json")
    with pytest.raises(ValueError):
        audit.check_document(guard, value, "arbitrary.json")
    with pytest.raises(ValueError):
        audit.check_document(guard, {"registered_credential_scan": "secret"}, "checks/delivery-verification.json")


def test_metadata_exception_keeps_registered_secret_and_field_checks():
    guard = SecretGuard(("controlled-provider-value",))
    for extra in ({"note": "controlled-provider-value"}, {"api_key": "value"}):
        with pytest.raises(ValueError):
            audit.check_document(guard, {"registered_credential_scan": "PASSED", **extra}, "checks/delivery-verification.json")
