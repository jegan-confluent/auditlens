from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_postgres_product_script_fails_when_api_ready_never_succeeds():
    source = (REPO_ROOT / "scripts" / "run_postgres_product.sh").read_text(encoding="utf-8")
    assert "api_ready=0" in source
    assert "exit 1" in source
    assert "readiness did not become ready" in source
    assert "scripts/health_check.sh || true" not in source
    assert 'export DATABASE_URL="${DATABASE_URL_POSTGRES:-postgresql://auditlens:auditlens@postgres:5432/auditlens}"' in source
    assert 'export FORWARDER_DATABASE_URL="${FORWARDER_DATABASE_URL_POSTGRES:-postgresql://auditlens:auditlens@postgres:5432/auditlens}"' in source
    assert "Postgres product mode" in source
    assert "Backfill:   PYTHONPATH=. ./.venv/bin/python scripts/backfill_event_fields.py --source-fields --dry-run" in source


def test_health_check_treats_pipeline_readiness_as_degraded_not_api_failure():
    source = (REPO_ROOT / "scripts" / "health_check.sh").read_text(encoding="utf-8")
    assert 'check_http "API /ready"' in source
    assert 'check_optional_http "Pipeline /pipeline/ready"' in source


def test_db_status_script_exists():
    source = (REPO_ROOT / "scripts" / "db_status.sh").read_text(encoding="utf-8")
    assert "backend.app.services.db_status_service" in source


def test_resource_backfill_script_exposes_safe_flags():
    source = (REPO_ROOT / "scripts" / "backfill_resource_intelligence.py").read_text(encoding="utf-8")
    assert "--dry-run" in source
    assert "--limit" in source
    assert "--hours" in source
    assert "--since" in source
    assert "--until" in source
    assert "--batch-size" in source
    assert "--force" in source
