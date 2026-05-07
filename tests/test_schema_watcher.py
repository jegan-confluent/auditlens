"""Phase 3: schema-watcher must never write Python source files.

The schema-watcher container previously rewrote ``src/classification/methods.py``
at runtime — a code-injection vector if the upstream Confluent docs page or
Schema Registry is ever poisoned. The Phase 3 hardening:

* the watcher only writes to a JSON data file under its writeable volume.
* methods.py reads that data file at startup and unions the entries with
  hard-coded defaults.

These tests guard the boundary.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_WATCHER_PATH = _REPO_ROOT / "schema-watcher" / "watcher.py"


@pytest.fixture()
def watcher_module():
    """Import schema-watcher/watcher.py without putting it on sys.path permanently."""
    spec = importlib.util.spec_from_file_location("schema_watcher_module", _WATCHER_PATH)
    if spec is None or spec.loader is None:
        pytest.skip("schema-watcher source not present")
    module = importlib.util.module_from_spec(spec)
    sys.modules["schema_watcher_module"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("schema_watcher_module", None)


def test_watcher_refuses_python_data_file(watcher_module, tmp_path):
    """Constructor rejects a .py path defensively."""
    versions = tmp_path / "versions.json"
    with pytest.raises(ValueError, match="must not be a Python source file"):
        watcher_module.ConfluentSchemaWatcher(
            data_file=tmp_path / "methods.py",
            versions_file=versions,
        )


def test_watcher_writes_json_not_python(watcher_module, tmp_path):
    """update_methods_data_file writes only to schema_methods.json."""
    data_file = tmp_path / "schema_methods.json"
    versions = tmp_path / "versions.json"
    watcher = watcher_module.ConfluentSchemaWatcher(
        data_file=data_file,
        versions_file=versions,
    )

    new_methods = {
        "CRITICAL": ["DeleteAuditLog"],
        "HIGH": ["RotateApiKey"],
        "MEDIUM": ["UpdateNetworkLink"],
        "LOW": ["GetAuditLog"],
    }

    updated = watcher.update_methods_data_file(new_methods)
    assert updated is True

    # Sanity: the JSON file is the only thing the watcher created in tmp_path.
    files_created = sorted(p for p in tmp_path.iterdir() if p.is_file())
    assert files_created == [data_file]
    assert data_file.suffix == ".json"

    payload = json.loads(data_file.read_text())
    assert "DeleteAuditLog" in payload["methods_by_level"]["CRITICAL"]
    assert "RotateApiKey" in payload["methods_by_level"]["HIGH"]
    assert "UpdateNetworkLink" in payload["methods_by_level"]["MEDIUM"]
    assert "GetAuditLog" in payload["methods_by_level"]["LOW"]
    # change_log records the addition with a timestamp.
    assert payload["change_log"], "expected at least one change_log entry"


def test_watcher_update_is_idempotent(watcher_module, tmp_path):
    """Calling update twice with the same methods doesn't double-add or write a .py file."""
    data_file = tmp_path / "schema_methods.json"
    versions = tmp_path / "versions.json"
    watcher = watcher_module.ConfluentSchemaWatcher(
        data_file=data_file,
        versions_file=versions,
    )
    new_methods = {"CRITICAL": ["DeleteAuditLog"]}
    watcher.update_methods_data_file(new_methods)
    watcher.update_methods_data_file(new_methods)

    payload = json.loads(data_file.read_text())
    assert payload["methods_by_level"]["CRITICAL"] == ["DeleteAuditLog"]
    # Still only the JSON file exists; never any .py file.
    files = sorted(p.name for p in tmp_path.iterdir())
    assert all(name.endswith(".json") or name.endswith(".tmp") is False for name in files)
    assert not any(name.endswith(".py") for name in files)


def test_methods_module_merges_data_file(monkeypatch, tmp_path):
    """methods.py should union schema-watcher additions into _get_methods()."""
    import importlib

    data_file = tmp_path / "schema_methods.json"
    data_file.write_text(json.dumps({
        "methods_by_level": {
            "CRITICAL": ["FabricatedDeleteOperation"],
            "HIGH": ["FabricatedRotateOperation"],
        }
    }))
    monkeypatch.setenv("SCHEMA_METHODS_DATA_FILE", str(data_file))

    # Force a true re-import: dropping sys.modules alone is not enough because
    # ``src.classification.__init__`` re-binds ``CRITICAL_METHODS`` from the
    # original module. ``importlib.reload`` runs the module body again with
    # the env var set, then we re-read the frozenset off the reloaded module.
    import src.classification.methods as methods_module  # noqa: WPS433
    methods_module = importlib.reload(methods_module)

    assert "FabricatedDeleteOperation" in methods_module.CRITICAL_METHODS
    assert "FabricatedRotateOperation" in methods_module.HIGH_METHODS
