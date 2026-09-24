"""받지 못한 서류가 맡던 것을 면접·실기로 넘긴다.

AI 는 요소마다 「비어 있는 KSA」를 서류·면접·실기로 **쪼개서** 배정한다.
실측 5건에서 (요소, KSA) 겹침이 0이었다 — 셋은 서로 다른 것을 맡고, 셋 다
통과해야 요소가 인정된다.

문제는 서류가 안 들어왔을 때였다. 요소의 60~75%가 서류에 걸려 있는데
「못 받음」 한 번에 그 요소가 곧바로 미인정이 됐다. 면접으로 대신 확인할
길이 없었다.
"""
from __future__ import annotations

import pytest

from datetime import datetime, timedelta

from services.review.stages import (
    Item, carry_over, item_key, outcomes, stage_states,
)

T0 = datetime(2026, 8, 24, 8, 40)


def item(method: str, txt: str, *targets, result=None) -> Item:
    """targets: (element_id, [ksa…])"""
    return Item(key=item_key(method, txt), method=method, item=txt, result=result,
                targets=[{"eid": e, "unit_code": e.split("_")[0], "unit": "단위",
                          "element": e, "ksa": list(k)} for e, k in targets])


def els(*ids):
    return [{"element_id": i, "payload": {"recommendation": "R2"}} for i in ids]


def cond(*ids):
    return {i: {"decision": "조건부인정"} for i in ids}


# ── 넘긴다 ────────────────────────────────────────────────────────

def test_a_missing_document_hands_its_ksa_to_the_interview():
    doc = item("추가서류", "성취수준 확인서", ("A_1", ["지식2", "지식3"]), result="미통과")
    oral = item("면접", "메뉴 개선 사례 확인", ("A_1", ["태도1"]))
    items = {"추가서류": [doc], "면접": [oral]}
    carry_over(items)
    assert doc.superseded, "넘겼다고 표시되지 않았다"
    assert len(oral.carried) == 1
    assert oral.carried[0]["ksa"] == ["지식2", "지식3"]
    assert oral.carried[0]["from"] == "성취수준 확인서"


def test_it_lands_on_the_practical_when_there_is_no_interview():
    doc = item("추가서류", "확인서", ("A_1", ["지식2"]), result="미통과")
    prac = item("실기", "통합 실기", ("A_1", ["기술1"]))
    items = {"추가서류": [doc], "실기": [prac]}
    carry_over(items)
    assert len(prac.carried) == 1


def test_an_already_decided_host_is_not_used():
    """이미 찍은 항목에 얹으면 그 KSA 는 영영 확인되지 않는다."""
    doc = item("추가서류", "확인서", ("A_1", ["지식2"]), result="미통과")
    done = item("면접", "이미 본 면접", ("A_1", ["태도1"]), result="통과")
    items = {"추가서류": [doc], "면접": [done]}
    carry_over(items)
    assert not done.carried
    fresh = [i for i in items["면접"] if i is not done]
    assert len(fresh) == 1 and fresh[0].from_missing_document == "확인서"


def test_a_new_interview_item_is_made_when_nothing_can_host_it():
    doc = item("추가서류", "급식경영론 성취수준 확인서",
               ("A_1", ["지식2", "지식3"]), result="미통과")
    items = {"추가서류": [doc]}
    carry_over(items)
    made = items["면접"]
    assert len(made) == 1
    it = made[0]
    assert it.from_missing_document == "급식경영론 성취수준 확인서"
    assert "서류를 받지 못해 면접으로 확인" in it.item
    assert it.reason and "받지 못했습니다" in it.reason
    assert it.carried[0]["ksa"] == ["지식2", "지식3"]
    # 열쇠는 글에서 나오므로 다시 열어도 같아야 한다 — 결과가 붙어 있어야 한다
    assert it.key == item_key("면접", it.item)


def test_two_elements_of_one_document_both_move():
    doc = item("추가서류", "확인서", ("A_1", ["지식2"]), ("A_2", ["지식3"]),
               result="미통과")
    oral = item("면접", "면접", ("A_1", ["태도1"]))
    items = {"추가서류": [doc], "면접": [oral]}
    carry_over(items)
    assert len(oral.carried) == 1                       # A_1 은 기존 항목이 받고
    assert len(items["면접"]) == 2                       # A_2 는 새 항목이 받는다


@pytest.mark.parametrize("result", ["미통과", "미실시"])
def test_both_unfilled_results_move(result):
    """「미실시」도 확인되지 않은 것이다."""
    doc = item("추가서류", "확인서", ("A_1", ["지식2"]), result=result)
    items = {"추가서류": [doc]}
    carry_over(items)
    assert doc.superseded and items.get("면접")


def test_a_received_document_moves_nothing():
    doc = item("추가서류", "확인서", ("A_1", ["지식2"]), result="통과")
    items = {"추가서류": [doc]}
    carry_over(items)
    assert not doc.superseded and "면접" not in items


def test_nothing_happens_before_anyone_marks_it():
    doc = item("추가서류", "확인서", ("A_1", ["지식2"]))
    items = {"추가서류": [doc]}
    carry_over(items)
    assert not doc.superseded


# ── 판정 ──────────────────────────────────────────────────────────

def test_the_element_survives_a_missing_document():
    """이것이 그 결함이다 — 서류 하나에 요소가 곧바로 죽었다."""
    doc = item("추가서류", "확인서", ("A_1", ["지식2"]), result="미통과")
    oral = item("면접", "면접", ("A_1", ["태도1"]))
    items = {"추가서류": [doc], "면접": [oral]}
    carry_over(items)
    o = outcomes(els("A_1"), cond("A_1"), items)[0]
    assert o.decision == "대기", o.basis
    assert any("면접·실기로 넘겼" in b for b in o.basis), o.basis


def test_it_is_recognised_when_the_interview_passes():
    """넘겨받은 뒤에 면접을 봤으면 인정이다."""
    doc = item("추가서류", "확인서", ("A_1", ["지식2"]), result="미통과")
    oral = item("면접", "면접", ("A_1", ["태도1"]))
    items = {"추가서류": [doc], "면접": [oral]}
    carry_over(items)                    # 넘긴 뒤에
    oral.result = "통과"                  # 면접을 본다
    assert outcomes(els("A_1"), cond("A_1"), items)[0].decision == "인정"


def test_an_interview_already_held_does_not_cover_what_came_later():
    """넘기기 **전에** 이미 끝난 면접은 그 KSA 를 확인한 적이 없다.
    거기에 얹으면 확인되지 않은 것이 확인된 것으로 둔갑한다."""
    doc = item("추가서류", "확인서", ("A_1", ["지식2"]), result="미통과")
    oral = item("면접", "이미 본 면접", ("A_1", ["태도1"]), result="통과")
    items = {"추가서류": [doc], "면접": [oral]}
    carry_over(items)
    assert not oral.carried
    o = outcomes(els("A_1"), cond("A_1"), items)[0]
    assert o.decision == "대기", "새로 만든 면접 항목을 기다려야 한다"


def test_it_is_not_recognised_when_the_interview_fails_too():
    doc = item("추가서류", "확인서", ("A_1", ["지식2"]), result="미통과")
    oral = item("면접", "면접", ("A_1", ["태도1"]), result="미통과")
    items = {"추가서류": [doc], "면접": [oral]}
    carry_over(items)
    assert outcomes(els("A_1"), cond("A_1"), items)[0].decision == "미인정"


def test_not_doing_the_interview_is_not_a_pass():
    """「미실시」를 통과처럼 세면 아무것도 안 하고 인정이 된다 —
    실제로 그렇게 계산되고 있었다."""
    oral = item("면접", "면접", ("A_1", ["태도1"]), result="미실시")
    assert outcomes(els("A_1"), cond("A_1"), {"면접": [oral]})[0].decision == "미인정"


def test_an_expert_denial_still_wins():
    """1단계에서 불인정으로 정했으면 서류가 없어도 그대로다."""
    doc = item("추가서류", "확인서", ("A_1", ["지식2"]), result="미통과")
    items = {"추가서류": [doc]}
    carry_over(items)
    o = outcomes(els("A_1"), {"A_1": {"decision": "불인정"}}, items)[0]
    assert o.decision == "미인정"


# ── 단계 진척 ────────────────────────────────────────────────────

def test_the_new_item_shows_up_in_the_interview_stage():
    doc = item("추가서류", "확인서", ("A_1", ["지식2"]), result="미통과")
    items = {"추가서류": [doc]}
    carry_over(items)
    st = {x.n: x for x in stage_states(1, 1, items, {"A_1": "대기"})}
    assert st[3].total == 1 and not st[3].complete


# ── 찍은 순서를 본다 ──────────────────────────────────────────────

def test_a_host_decided_after_the_hand_off_keeps_it():
    """서류를 못 받는다고 정한 **뒤에** 통과시킨 실기는 이미 넘겨받은
    상태로 본 것이다. 그것을 못 보고 새 항목을 만들었더니, 통과한 실기가
    헛것이 되고 능력단위 시간이 안 붙었다 (실측 R2026-9010 윤활장치 50시간).
    """
    doc = item("추가서류", "확인서", ("A_1", ["지식2"]), result="미통과")
    doc.decided_at = T0
    prac = item("실기", "통합 실기", ("A_1", ["기술1"]), result="통과")
    prac.decided_at = T0 + timedelta(minutes=5)
    items = {"추가서류": [doc], "실기": [prac]}
    carry_over(items)
    assert prac.carried, "넘겨받은 것으로 치지 않았다"
    assert "면접" not in items, "쓸데없이 면접 항목을 새로 만들었다"
    assert outcomes(els("A_1"), cond("A_1"), items)[0].decision == "인정"


def test_a_host_decided_before_the_hand_off_does_not_count():
    """서류보다 먼저 끝난 실기는 그 KSA 를 본 적이 없다."""
    doc = item("추가서류", "확인서", ("A_1", ["지식2"]), result="미통과")
    doc.decided_at = T0
    prac = item("실기", "통합 실기", ("A_1", ["기술1"]), result="통과")
    prac.decided_at = T0 - timedelta(minutes=5)
    items = {"추가서류": [doc], "실기": [prac]}
    carry_over(items)
    assert not prac.carried
    assert items.get("면접"), "확인할 자리를 만들지 않았다"
    assert outcomes(els("A_1"), cond("A_1"), items)[0].decision == "대기"


def test_an_undecided_host_still_wins_over_a_decided_one():
    """아직 안 찍은 자리가 있으면 거기로 간다 — 확인할 기회가 남아 있다."""
    doc = item("추가서류", "확인서", ("A_1", ["지식2"]), result="미통과")
    doc.decided_at = T0
    done = item("면접", "끝난 면접", ("A_1", ["태도1"]), result="통과")
    done.decided_at = T0 + timedelta(minutes=1)
    open_ = item("실기", "남은 실기", ("A_1", ["기술1"]))
    items = {"추가서류": [doc], "면접": [done], "실기": [open_]}
    carry_over(items)
    assert open_.carried and not done.carried
