"""Offline tests for the enterprise-readiness stubs: RBAC no-ops + export-format warning."""

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO))  # so `import app` (repo-root module) resolves

import app  # noqa: E402
from protocol_to_data import rbac  # noqa: E402


def test_export_warning_only_for_edc_targets():
    assert app._export_warning(app.EXPORT_SDTM) == ""
    for edc in ("CDASH (ODM XML) - Medidata Rave", "CDASH (ODM XML) - Veeva Vault EDC"):
        w = app._export_warning(edc)
        assert "v2 roadmap" in w and "SDTM analytics export" in w


def test_export_formats_default_is_sdtm():
    assert app.EXPORT_FORMATS[0] == app.EXPORT_SDTM  # first == default in the dropdown


def test_rbac_stubs_are_noops():
    assert rbac.require_write() is None
    assert rbac.require_read() is None
    assert rbac.current_role() is rbac.Role.CLINICAL_DATA_MANAGER
    assert {r.value for r in rbac.Role} == {"clinical_data_manager", "statistician"}
