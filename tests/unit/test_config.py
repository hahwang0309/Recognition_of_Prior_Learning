"""설정 체계 안전장치 검증."""
import pytest
from krpl_core.config import Rubric, get_rubric, get_settings, _load_yaml, CONFIG_DIR


def _base() -> dict:
    return _load_yaml(CONFIG_DIR / "rubric" / "v0.2.yaml")


def test_rubric_loads():
    r = get_rubric()
    assert r.version == "0.2"
    assert set(r.grade_order) == set(r.grades)


def test_pending_decisions_indexed():
    r = get_rubric()
    keys = {p.key for p in r.pending_decisions}
    assert "recommendations.R1.requires.ksa_coverage_min" in keys
    assert len(r.critical_pending) >= 1


def test_is_decided():
    r = get_rubric()
    assert r.is_decided("recommendations.R1.requires.ksa_coverage_min") is False
    assert r.is_decided("training_hours.adjustment_floor") is True


def test_unknown_grade_rejected():
    d = _base()
    d["document_types"]["경력증명서"]["grade"] = "Z"
    with pytest.raises(ValueError, match="등급 'Z'"):
        Rubric(**d)


def test_unknown_dimension_rejected():
    d = _base()
    d["document_types"]["경력증명서"]["proves"]["존재하지않는차원"] = "full"
    with pytest.raises(ValueError, match="차원"):
        Rubric(**d)


def test_r1_period_backing_grade_validated():
    d = _base()
    d["recommendations"]["R1"]["requires"]["period_backing_grades"] = ["A", "Q"]
    with pytest.raises(ValueError, match="'Q'"):
        Rubric(**d)


def test_prod_refuses_start_with_pending(monkeypatch):
    """운영 환경에서는 미확정 항목이 있으면 기동을 거부한다."""
    get_settings.cache_clear(); get_rubric.cache_clear()
    monkeypatch.setenv("KRPL_ENV", "prod")
    with pytest.raises(RuntimeError, match="미확정 기준 항목"):
        get_rubric()
    get_settings.cache_clear(); get_rubric.cache_clear()


@pytest.mark.parametrize("env,level", [("local", "DEBUG"), ("test", "WARNING")])
def test_env_overlay(env, level, monkeypatch):
    """환경별 파일이 공통 기본값을 덮어쓰되, 건드리지 않은 값은 그대로 남는가."""
    monkeypatch.setenv("KRPL_ENV", env)
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.logging["level"] == level         # environments/{env}.yaml 이 덮어씀
        assert s.storage.max_upload_mb == 50       # settings.yaml 기본값 유지
        assert s.rubric.active_version == "0.2"
    finally:
        get_settings.cache_clear()


def test_test_env_uses_separate_storage(monkeypatch):
    """시험이 운영 감사 보관함을 더럽히면 안 된다."""
    monkeypatch.setenv("KRPL_ENV", "test")
    get_settings.cache_clear()
    try:
        assert get_settings().storage.local_path.endswith("_test")
    finally:
        get_settings.cache_clear()
