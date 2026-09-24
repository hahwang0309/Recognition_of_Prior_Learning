"""부족한 능력단위의 시간 셈 — 인정선을 넘었나가 전부다.

인정시간(이수 + 위원 추가 인정)이 요구시간의 50% 이상이면 그 능력단위가
**인정 능력단위**가 되고, 요구시간 **전체**가 면제된다. 미만이면 0 이다.
훈련기준의 「−50%까지 조정 가능」 조항을 최종 인정시간에 적용한 것이다.

합산이 아니라 게이트다. 45h 를 인정했다고 45h 가 면제되는 것이 아니다.
"""
from __future__ import annotations

import pytest

from services.review.unit_hours import UnitGap, compute_gaps

# (element_id, evidence_level, payload) — 기록 확인 판정이 남기는 모양 그대로
ROWS = [
    ("2001020231", "완전충족", {"unit_name": "프로그래밍 언어 활용", "required_hours": 50,
                             "completed_hours": 60, "ratio": 1.2, "min_hours": 25}),
    ("2001020225", "미이수", {"unit_name": "화면 구현", "required_hours": 48,
                           "completed_hours": None, "ratio": None, "min_hours": 24}),
    ("2001020232", "시간부족", {"unit_name": "응용SW 기초", "required_hours": 40,
                             "completed_hours": 8, "ratio": 0.2, "min_hours": 20}),
    ("2001020233", "보류", {"unit_name": "설계도서 작성", "required_hours": 80,
                          "completed_hours": 20, "ratio": 0.25, "min_hours": 40}),
    ("2001020234", "조정범위내", {"unit_name": "개발환경 구축", "required_hours": 60,
                               "completed_hours": 33, "ratio": 0.55, "min_hours": 30}),
]


def gaps(granted=None):
    return {g.unit_code: g for g in compute_gaps(ROWS, granted or {})}


def test_only_units_below_the_line_need_a_decision():
    """50% 이상은 규칙이 이미 요구시간 전체를 인정했다 — 위원이 볼 것이 없다."""
    assert list(gaps()) == ["2001020225", "2001020232", "2001020233"]


# ── 게이트 ────────────────────────────────────────────────────────

def test_crossing_the_line_exempts_the_whole_unit():
    """요구 80 · 이수 20 · 위원 25 → 45h(56%) → 면제는 45h 가 아니라 80h 다."""
    g = gaps({"2001020233": 25})["2001020233"]
    assert g.counted == 45
    assert g.ratio_final == pytest.approx(0.5625)
    assert g.credited == 80, "인정선을 넘으면 요구시간 전체가 면제된다"


def test_below_the_line_exempts_nothing():
    """요구 80 · 이수 0 · 위원 20 → 25% → 면제 0h. 넣은 20h 는 면제가 아니다."""
    g = gaps({"2001020225": 20})["2001020225"]
    assert g.counted == 20
    assert g.credited == 0


def test_exactly_on_the_line_counts_as_in():
    """50% 는 포함이다 — 기준서의 `ratio_gte: 0.5`."""
    g = gaps({"2001020225": 24})["2001020225"]      # 요구 48 · 이수 0 · 위원 24
    assert g.ratio_final == 0.5
    assert g.credited == 48


def test_the_record_alone_can_never_pass_here():
    """이 표에 오는 단위는 정의상 이수만으로 50% 미만이다."""
    for g in gaps().values():
        assert g.credited == 0, f"{g.unit_name} 이 위원 입력 없이 인정됐다"


# ── 인정선까지 얼마가 필요한가 ────────────────────────────────────

def test_it_says_how_many_hours_reach_the_line():
    g = gaps()
    assert g["2001020233"].to_pass == 20, "요구 80 의 절반 40, 이수 20 → 20h 더"
    assert g["2001020225"].to_pass == 24, "요구 48 · 이수 0 → 24h"
    assert g["2001020232"].to_pass == 12, "요구 40 의 절반 20, 이수 8 → 12h"


def test_the_line_is_rounded_up():
    """요구 45h 의 절반은 22.5h — 22h 로는 못 넘는다."""
    rows = [("X", "미이수", {"unit_name": "홀수", "required_hours": 45,
                           "completed_hours": 0, "ratio": None})]
    g = {x.unit_code: x for x in compute_gaps(rows, {})}["X"]
    assert g.to_pass == 23
    assert {x.unit_code: x for x in compute_gaps(rows, {"X": 22})}["X"].credited == 0
    assert {x.unit_code: x for x in compute_gaps(rows, {"X": 23})}["X"].credited == 45


# ── 입력값 다루기 ────────────────────────────────────────────────

def test_input_is_capped_at_the_shortfall():
    g = gaps({"2001020233": 999})["2001020233"]
    assert g.granted == 60, "부족분(80−20)으로 잘린다"
    assert g.counted == 80 and g.ratio_final == 1.0
    assert g.credited == 80


def test_negative_input_is_zero():
    assert gaps({"2001020225": -5})["2001020225"].granted == 0


@pytest.mark.parametrize("hours,want", [(0, 0), (10, 10), (48, 48)])
def test_within_range_is_kept_as_is(hours, want):
    assert gaps({"2001020225": hours})["2001020225"].granted == want


def test_a_unit_with_no_required_hours_does_not_divide_by_zero():
    rows = [("Z", "미이수", {"unit_name": "빈 단위", "required_hours": 0,
                          "completed_hours": 0, "ratio": None})]
    g = {x.unit_code: x for x in compute_gaps(rows, {"Z": 5})}["Z"]
    assert (g.ratio_final, g.credited, g.to_pass) == (0.0, 0, 0)


def test_the_gate_comes_from_the_rubric_not_the_code():
    """기준을 코드에 박으면 기준서를 고쳐도 화면이 안 따라온다."""
    from services.review.unit_hours import credit_floor
    assert credit_floor() == 0.5
    tight = {x.unit_code: x for x in compute_gaps(ROWS, {"2001020233": 25}, floor=0.6)}
    assert tight["2001020233"].credited == 0, "기준이 60% 면 56% 는 못 넘는다"


def test_a_gap_is_a_plain_value():
    g = compute_gaps(ROWS, {})[0]
    assert isinstance(g, UnitGap)
    assert g.unit_name and g.verdict
