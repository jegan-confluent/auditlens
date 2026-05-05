from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_postgres_product_script_fails_when_api_ready_never_succeeds():
    source = (REPO_ROOT / "scripts" / "run_postgres_product.sh").read_text(encoding="utf-8")
    assert "api_ready=0" in source
    assert "exit 1" in source
    assert "readiness did not become ready" in source
    assert "scripts/health_check.sh || true" not in source


def test_health_check_treats_pipeline_readiness_as_degraded_not_api_failure():
    source = (REPO_ROOT / "scripts" / "health_check.sh").read_text(encoding="utf-8")
    assert 'check_http "API /ready"' in source
    assert 'check_optional_http "Pipeline /pipeline/ready"' in source
