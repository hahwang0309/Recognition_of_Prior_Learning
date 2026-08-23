"""전문가 검토 5단계 — 보완 항목 병합과 인정 계산.

여기서 확인하는 것은 둘이다.
  ① 같은 항목이 여러 요소에 걸려도 한 번만 묻는가
  ② 「인정됐다」가 무엇 때문인지 항상 말할 수 있는가
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.review.stages import (
    Item, collect_items, item_key, next_open_stage, outcomes, stage_states,
)


def _el(eid, unit, name, rems, **payload):
    return {"element_id": eid, "recommendation": payload.pop("rec", "R2"),
            "payload": {"unit_name": unit, "element_name": name,
                        "remediation": rems, **payload}}


def _rem(method, item, ksa, **kw):
    return {"method": method, "item": item, "ksa_refs": ksa, "reason": "이유", **kw}


SAFETY = "산업안전보건 교육 이수확인서"


# ── 병합 ──────────────────────────────────────────────────────────

def test_same_item_across_elements_is_asked_once():
    """「안전보건교육 이수확인서」 한 건이 여러 요소를 한꺼번에 푼다.

    요소마다 따로 물으면 같은 서류를 열다섯 번 확인하는 꼴이 된다.
    """
    els = [
        _el("A_1v1.1", "가", "가1", [_rem("추가서류", SAFETY, ["태도1"])]),
        _el("A_1v1.2", "가", "가2", [_rem("추가서류", SAFETY, ["태도2"])]),
        _el("B_1v1.1", "나", "나1", [_rem("추가서류", SAFETY, ["태도1", "태도3"])]),
    ]
    items = collect_items(els)
    docs = items["추가서류"]
    assert len(docs) == 1
    it = docs[0]
    assert it.n_elements == 3 and it.n_units == 2 and it.n_ksa == 4
    assert it.units == ["가", "나"]


def test_item_key_is_stable_and_method_scoped():
    assert item_key("면접", " x ") == item_key("면접", "x")
    assert item_key("면접", "x") != item_key("실기", "x")


def test_alt_document_and_questions_are_gathered():
    """대체서류·구술 질문은 어느 요소에 붙어 있든 항목 하나로 모인다."""
    els = [
        _el("A_1v1.1", "가", "가1", [_rem("면접", "면접 항목", ["태도1"],
                                          oral_check=["질문 하나"])]),
        _el("A_1v1.2", "가", "가2", [_rem("면접", "면접 항목", ["태도2"],
                                          oral_check=["질문 둘", "질문 하나"],
                                          alt_document="교육 수료증")]),
    ]
    it = collect_items(els)["면접"][0]
    assert it.oral_check == ["질문 하나", "질문 둘"]     # 중복 없이 순서대로
    assert it.alt_document == "교육 수료증"


def test_unnamed_or_malformed_remediation_is_skipped():
    els = [_el("A_1v1.1", "가", "가1",
               ["문자열", {"method": "면접"}, {"item": "방법 없음"},
                _rem("면접", "제대로 된 항목", ["태도1"])])]
    assert len(collect_items(els)["면접"]) == 1


# ── 인정 계산 ─────────────────────────────────────────────────────

def _one(rems, decision, results=None):
    els = [_el("A_1v1.1", "가", "가1", rems)]
    items = collect_items(els)
    for group in items.values():
        for it in group:
            if results and it.item in results:
                it.result = results[it.item]
                it.decided_at = datetime(2026, 8, 23, tzinfo=timezone.utc)
    rv = {"A_1v1.1": {"decision": decision}} if decision else {}
    return outcomes(els, rv, items)[0]


def test_expert_decision_stands_on_its_own():
    for d, expect in (("인정", "인정"), ("불인정", "미인정")):
        o = _one([_rem("면접", "면접 항목", ["태도1"])], d)
        assert o.decision == expect
        assert o.basis == [f"전문가 판단 — {d}"]


def test_unjudged_element_waits():
    o = _one([_rem("면접", "면접 항목", ["태도1"])], None)
    assert o.decision == "대기" and "아직 판단" in o.basis[0]


def test_conditional_waits_until_the_item_is_decided():
    o = _one([_rem("면접", "면접 항목", ["태도1"])], "조건부인정")
    assert o.decision == "대기"
    assert "결과 대기" in o.basis[0]


def test_conditional_becomes_recognized_when_the_item_passes():
    o = _one([_rem("면접", "면접 항목", ["태도1"])], "조건부인정",
             {"면접 항목": "통과"})
    assert o.decision == "인정"
    assert "통과" in o.basis[0] and "2026-08-23" in o.basis[0]


def test_one_failure_is_enough_to_deny():
    """면접·실기가 둘 다 걸렸으면 둘 다 통과해야 한다."""
    o = _one([_rem("면접", "면접 항목", ["태도1"]),
              _rem("실기", "실기 과제", ["기술1"])], "조건부인정",
             {"면접 항목": "통과", "실기 과제": "미통과"})
    assert o.decision == "미인정"
    assert any("미통과" in b for b in o.basis)


def test_training_cannot_be_cleared_by_checking():
    """훈련은 확인이 아니라 배우는 절차다. 통과를 찍을 대상이 아니다."""
    o = _one([_rem("훈련", "비파괴검사 기초 교육 이수", ["지식4"])], "조건부인정")
    assert o.decision == "미인정"
    assert "훈련 이수 필요" in o.basis[0]


def test_conditional_with_nothing_left_is_recognized():
    o = _one([], "조건부인정")
    assert o.decision == "인정"


def test_every_outcome_says_why():
    """「인정됐다」가 무엇 때문인지 항상 말할 수 있어야 한다."""
    cases = [
        ([_rem("면접", "x", ["태도1"])], "인정", None),
        ([_rem("면접", "x", ["태도1"])], "조건부인정", {"x": "통과"}),
        ([_rem("면접", "x", ["태도1"])], "조건부인정", {"x": "미통과"}),
        ([_rem("훈련", "y", ["지식1"])], "조건부인정", None),
        ([], None, None),
    ]
    for rems, d, res in cases:
        o = _one(rems, d, res)
        assert o.basis and all(b.strip() for b in o.basis), (rems, d, res)


# ── 단계 진척 ─────────────────────────────────────────────────────

def _items(**counts) -> dict[str, list[Item]]:
    return {m: [Item(key=f"{m}{i}", method=m, item=f"{m}{i}") for i in range(n)]
            for m, n in counts.items()}


def test_stage_with_nothing_to_do_is_skipped():
    st = stage_states(3, 0, _items(추가서류=2, 실기=1))
    by_n = {x.n: x for x in st}
    assert by_n[3].skipped and by_n[3].total == 0     # 면접 항목이 없다
    assert not by_n[2].skipped


def test_next_stage_walks_forward():
    items = _items(추가서류=1, 면접=1)
    assert next_open_stage(stage_states(3, 0, items)) == 1     # 1단계 미완
    assert next_open_stage(stage_states(3, 3, items)) == 2     # 1단계 끝 → 2

    items["추가서류"][0].result = "통과"
    assert next_open_stage(stage_states(3, 3, items)) == 3     # 2단계 끝 → 3

    items["면접"][0].result = "미통과"
    assert next_open_stage(stage_states(3, 3, items)) == 5     # 다 끝 → 최종


def test_a_case_with_no_judgment_needed_starts_at_the_next_open_stage():
    """판단할 요소가 없으면 1단계는 건너뛴다."""
    st = stage_states(0, 0, _items(면접=1))
    assert st[0].skipped
    assert next_open_stage(st) == 3


def test_skipped_stage_counts_as_complete():
    st = stage_states(0, 0, {})
    assert all(x.complete for x in st if x.n < 5)
    assert next_open_stage(st) == 5


@pytest.mark.parametrize("bad", ["통과함", "", "pass", None])
def test_unknown_result_is_refused(bad):
    from services.review.stages import save_result
    with pytest.raises(ValueError):
        save_result(None, 1, "k", "면접", "i", bad)
