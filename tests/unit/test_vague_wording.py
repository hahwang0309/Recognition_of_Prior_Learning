"""정도(程度)는 말이 아니라 숫자로 적는다.

「요구시간 48시간의 50%를 크게 상회하므로」 — 「크게」가 몇 %인지 읽는 사람이
되짚을 수 없다. 심사는 시간을 다투는 일이라 이런 문장은 근거가 되지 못한다.
프롬프트로 시키되, 지켜졌는지는 기계가 본다.
"""
from __future__ import annotations

import pytest

from krpl_rules.track_b import VAGUE

OK = [
    "요구 48시간 대비 140시간 이수(292%)로 하한 50%를 넘어 기이수 인정검토 대상이다",
    "KSA 16개 중 11개(69%)가 확인된다",
    "이수 시간이 요구의 절반에 못 미친다",
    "요구 70시간 대비 120시간 이수(171%)하고 내부평가 합격 기록이 있다",
    "근거가 닿지 않은 항목이 14개 남는다",
]

BAD = [
    "요구시간 48시간의 50%를 크게 상회하므로 기이수 인정검토 대상이다",
    "요구 시간을 훨씬 넘는 이수 실적이 있다",
    "KSA 가 대부분 확인된다",
    "관련 지식이 상당히 부족하다",
    "이수시간이 기준을 크게 웃돈다",
    "요구시간을 대폭 넘어선다",
    "현저히 모자란다",
]


@pytest.mark.parametrize("text", OK)
def test_numeric_wording_passes(text):
    assert not VAGUE.search(text), f"숫자로 쓴 문장을 잡았다: {text}"


@pytest.mark.parametrize("text", BAD)
def test_vague_wording_is_caught(text):
    assert VAGUE.search(text), f"모호한 문장을 놓쳤다: {text}"


def test_validator_reports_it_as_a_warning():
    """오류가 아니라 경고다 — 뜻이 틀린 것은 아니고 표현이 성기다."""
    from krpl_core.config import get_rubric
    from krpl_rules.track_b import validate_track_b

    # 검증기는 패키지의 요소 목록을 기준으로 돈다. 비워 두면 그냥 건너뛴다.
    pkg = {"fragments": [], "ncs": {"units": [{
        "unit_code": "X", "unit_name": "시험 단위", "required_hours": 10,
        "elements": [{"element_id": "X_1v1.1",
                      "ksa": [{"ref": "기술1"}]}]}]}}
    out = {"elements": [{
        "element_id": "X_1v1.1", "recommendation": "R0",
        "evidence": [{"ksa_ref": "기술1", "quote": "", "why": "x",
                      "grade": "B", "fids": []}],
        "uncovered_ksa": [], "remediation": [], "conflicts": [],
        "negative_statements": [], "negative_grades": [], "source_grades": [],
        "evidence_level": "충분", "verification_method": "불필요",
        "proven_dimensions": [], "missing_dimensions": [],
        "period_backing": {"fids": [], "grades": [], "note": "x"},
        "recommendation_reason": "요구시간 48시간의 50%를 크게 상회한다",
        "qualitative_note": "이수 기록이 남아 있어 다시 확인하지 않는다. 충분하다.",
    }]}
    rep = validate_track_b(pkg, out, get_rubric())
    hits = [i for i in rep.issues if i.code == "정도표현_모호"]
    assert hits, "검증기가 잡지 못했다"
    assert all(i.severity == "warn" for i in hits)
    assert "크게 상회" in hits[0].detail


def test_prompt_tells_the_model_to_use_numbers():
    """규칙은 프롬프트에도 있어야 한다 — 검증기는 뒤늦게 잡을 뿐이다."""
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "config/prompts/trackb_v5.md"
    t = p.read_text(encoding="utf-8")
    assert "정도(程度)는 말이 아니라 숫자로 적는다" in t
    assert "크게 상회" in t and "292%" in t
