"""Track A 판정 엔진 — 경계값·신뢰도·집계 검증."""
import pytest

from krpl_core.config import get_rubric
from krpl_rules.track_a import HeldUnit, RequiredUnit, assess_track_a


@pytest.fixture
def rb():
    return get_rubric()


def _req(code="1000000001", req=40):
    return RequiredUnit(code, f"단위{code[-1]}", req, round(req * 0.5))


def _run(rb, req_hours, held_hours, held_min=None):
    r = _req(req=req_hours)
    held = [] if held_hours is None else [HeldUnit(r.unit_code, held_hours, held_min, "자격X")]
    return assess_track_a("종목_L2", req_hours, [r], held, rb).elements[0]


# ── 경계값 ──────────────────────────────────────────────
@pytest.mark.parametrize("held,expect,rec", [
    (60, "완전충족", "R0"),      # 초과
    (40, "완전충족", "R0"),      # 정확히 100% — 경계
    (39, "조정범위내", "R0"),
    (20, "조정범위내", "R0"),    # 정확히 50% — 경계
    (19, "시간부족", "R2"),
    (1,  "시간부족", "R2"),
    (None, "미이수", "R5"),
])
def test_boundaries(rb, held, expect, rec):
    e = _run(rb, 40, held)
    assert (e.verdict, e.recommendation) == (expect, rec)


def test_absent_has_no_ratio(rb):
    e = _run(rb, 40, None)
    assert e.ratio is None and e.completed_hours is None and e.evidence == []


def test_evidence_records_source(rb):
    e = _run(rb, 40, 45, 36)
    assert e.evidence[0]["source"] == "자격X"
    assert e.evidence[0]["composed_hours"] == 45


# ── 신뢰도 ──────────────────────────────────────────────
def test_confidence_stable_when_floor_keeps_verdict(rb):
    """편성 하한(80%)으로도 완전충족이면 확정."""
    e = _run(rb, 40, 60, 48)          # 48/40 = 1.2 → 여전히 완전충족
    assert e.confidence == "확정"


def test_confidence_unstable_when_floor_flips_verdict(rb):
    """하한에서 판정이 바뀌면 추정 — 이수증명서를 받아야 한다."""
    e = _run(rb, 40, 45, 36)          # 45/40=1.13 완전충족 / 36/40=0.9 조정범위내
    assert e.verdict == "완전충족"
    assert e.confidence.startswith("추정")


def test_confidence_stable_without_range(rb):
    e = _run(rb, 40, 45, None)
    assert e.confidence == "확정"


# ── 집계 ────────────────────────────────────────────────
def test_aggregation(rb):
    req = [RequiredUnit("U1", "a", 40, 20), RequiredUnit("U2", "b", 30, 15),
           RequiredUnit("U3", "c", 20, 10), RequiredUnit("U4", "d", 10, 5)]
    held = [HeldUnit("U1", 45, None, "Q"), HeldUnit("U2", 20, None, "Q"),
            HeldUnit("U3", 5, None, "Q")]                       # U4 미보유
    r = assess_track_a("P", 100, req, held, rb)

    assert r.by_verdict == {"완전충족": 1, "조정범위내": 1, "시간부족": 1, "미이수": 1}
    assert r.hours == {"완전충족": 40, "조정범위내": 30, "시간부족": 20, "미이수": 10}
    assert r.unit_coverage_rate == 0.75                          # 4개 중 3개 보유
    assert r.credit_rate_strict == 0.40                          # 40/100
    assert r.credit_rate_adjusted == 0.70                        # (40+30)/100
    assert r.remaining_hours == 30                               # 20+10
    assert sum(r.hours.values()) == r.total_hours                # 배분 합 = 총시간


def test_summary_records_rubric_version(rb):
    s = assess_track_a("P", 40, [_req()], [], rb).summary()
    assert s["rubric_version"] == rb.version                     # 재현성 요건


def test_coverage_high_but_credit_low(rb):
    """v3에서 발견한 함정 — 능력단위는 다 겹치는데 시간이 전부 부족한 경우."""
    req = [RequiredUnit(f"U{i}", f"n{i}", 50, 25) for i in range(4)]
    held = [HeldUnit(f"U{i}", 5, None, "Q") for i in range(4)]
    r = assess_track_a("P", 200, req, held, rb)
    assert r.unit_coverage_rate == 1.0        # 커버리지 100%
    assert r.credit_rate_strict == 0.0        # 확정 인정률 0%
    assert r.remaining_hours == 200
