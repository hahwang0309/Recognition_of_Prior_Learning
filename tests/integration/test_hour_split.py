"""시간이 지금 어디에 놓여 있나 — 개요의 막대가 대는 값.

개요 화면은 **기록 확인 결과만** 읽고 있었다. 그래서 전문가가 100시간을 더
인정한 뒤에도 「아직 확인되지 않은 시간」이 그대로였다.

    실측 R2026-9002 — 총 450시간
      기록 확인   150시간
      전문가 판단 100시간
      화면        「아직 확인되지 않은 시간 300시간」   ← 틀렸다. 200시간이다.

여기서 보는 것은 셋이다.
  ① 다섯 칸의 합이 언제나 총 필수 시간인가
  ② 「기록」 칸이 Track A 기록 확인과 같은 값인가
  ③ 1단계에서 이미 정해진 요소에 붙은 면접·실기 항목이 단계를 막지 않는가
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from krpl_core.db import session_scope
from services.assess.case_state import case_state
from services.review import load as review_ctx
from services.review import save_element_review
from services.review.stages import Item, is_live, stage_states

CASE = "R2026-0002"


@pytest.fixture(scope="module", autouse=True)
def demo_data():
    with session_scope() as s:
        if s.execute(text("SELECT 1 FROM submission WHERE case_number=:c"),
                     {"c": CASE}).first() is None:
            sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
            try:
                import load_demo
                load_demo.load()
            except FileNotFoundError as ex:
                pytest.skip(f"실사례 원본 없음: {ex}")


@pytest.fixture(scope="module")
def ids():
    with session_scope() as s:
        r = s.execute(text("""SELECT a.submission_id, a.id FROM assessment a
            JOIN submission s ON s.id=a.submission_id
            WHERE s.case_number=:c AND a.kind='evidence' AND a.status='done'
            ORDER BY a.id DESC LIMIT 1"""), {"c": CASE}).first()
    if r is None:
        pytest.skip("근거 분석 결과 없음")
    return r[0], r[1]


@pytest.fixture
def clean(ids):
    def wipe():
        with session_scope() as s:
            s.execute(text("DELETE FROM element_review WHERE assessment_id=:a"),
                      {"a": ids[1]})
            s.execute(text("DELETE FROM remediation_result WHERE assessment_id=:a"),
                      {"a": ids[1]})
    wipe()
    yield ids
    wipe()


# ── ① 합 ──────────────────────────────────────────────────────────

def test_the_five_buckets_add_up_to_the_required_hours(clean):
    """한 시간도 사라지거나 두 번 세어지면 안 된다."""
    _, aid = clean
    with session_scope() as s:
        sp = review_ctx(s, aid).hour_split()
    total = sp.record + sp.expert + sp.unjudged + sp.pending + sp.training
    assert total == sp.total, (
        f"합 {total} ≠ 총 필수 {sp.total} "
        f"(기록 {sp.record}/전문가 {sp.expert}/미판단 {sp.unjudged}/"
        f"대기 {sp.pending}/훈련 {sp.training})")
    assert sp.credited + sp.open == sp.total


def test_nothing_is_credited_before_anyone_judges(clean):
    """아무도 보지 않았는데 「전문가 판단으로 인정」이 붙으면 안 된다."""
    _, aid = clean
    with session_scope() as s:
        sp = review_ctx(s, aid).hour_split()
    assert sp.expert == 0
    assert sp.pending == 0, "판단 전에는 확인 대기가 아니라 미판단이다"


# ── ② 기록 칸은 Track A 와 같아야 한다 ───────────────────────────

def test_the_record_bucket_matches_track_a(clean):
    """두 계산이 갈리면 어느 쪽을 믿을지 알 수 없다.

    실측 R2026-9010(과정평가형 자격 보유) — 개요 한 화면에서 막대는
    「기록 확인 100시간」, ① 칸은 「320시간이 확인됐습니다」라고 했다.
    막대가 요소에서 다시 세느라 자격 편성시간을 못 봤기 때문이다.
    """
    sid, aid = clean
    with session_scope() as s:
        st = case_state(s, sid)
        sp = review_ctx(s, aid).hour_split()
    assert sp.record == st.credited_hours, (
        f"기록 칸 {sp.record}시간 ≠ 기록 확인 {st.credited_hours}시간")


def test_the_overview_counts_what_the_expert_recognised(clean):
    """이것이 그 결함이다 — 전문가가 인정한 시간이 개요에 반영돼야 한다."""
    sid, aid = clean
    with session_scope() as s:
        before = case_state(s, sid)
        ctx = review_ctx(s, aid)
        # 아직 안 정해진 요소를 전부 인정으로 찍는다
        for x in ctx.judge_pool:
            save_element_review(s, aid, x["element_id"], "인정", reviewer="시험")
    with session_scope() as s:
        after = case_state(s, sid)

    assert after.recognized_hours > before.recognized_hours, (
        "전부 인정으로 찍었는데 개요의 인정 시간이 그대로다")
    assert after.expert_hours == after.recognized_hours - after.split.record
    # 남은 시간은 그만큼 줄어야 한다 — 늘 300시간이라고 적혀 있던 자리
    assert after.unresolved_hours == after.total_hours - after.recognized_hours
    assert after.unresolved_hours < before.unresolved_hours


def test_before_review_it_falls_back_to_the_record(ids):
    """검토 전에는 기록 확인이 남긴 것만 말할 수 있다."""
    sid, _ = ids
    with session_scope() as s:
        st = case_state(s, sid)
    if st.split is None:
        assert st.recognized_hours == st.credited_hours
        assert st.unresolved_hours == st.open_hours


# ── ③ 결과를 바꾸지 못하는 항목은 단계를 막지 않는다 ─────────────

def _item(*eids: str) -> Item:
    return Item(key="k", method="면접", item="질문",
                targets=[{"eid": i, "unit_code": i.split("_")[0],
                          "unit": "단위", "element": i, "ksa": []} for i in eids])


def test_an_item_on_a_settled_element_is_not_live():
    """1단계에서 불인정으로 정해진 요소에 붙은 면접 항목 — 무엇을 찍어도
    인정 시간이 달라지지 않는다."""
    it = _item("A_1", "A_2")
    assert is_live(it, {"A_1": "미인정", "A_2": "인정"}) is False
    assert is_live(it, {"A_1": "대기", "A_2": "인정"}) is True
    # 볼 재료가 없으면 살아 있다고 본다 — 지레 감추는 편이 더 나쁘다
    assert is_live(it, None) is True


def test_a_stage_full_of_moot_items_is_skipped_not_stuck():
    """실측 R2026-9002 — 면접 1건·실기 4건이 남았다고 나와 「최종」으로
    넘어갈 수 없었다. 그 다섯 건은 전부 이미 정해진 요소에 붙어 있었다."""
    items = {"면접": [_item("A_1")], "실기": [_item("B_1")]}
    got = {"A_1": "미인정", "B_1": "인정"}
    states = {x.n: x for x in stage_states(3, 3, items, got)}
    assert states[3].total == 0 and states[3].skipped and states[3].complete
    assert states[3].moot == 1, "왜 안 세는지 화면이 말할 수 있어야 한다"
    assert states[4].complete


def test_a_decided_item_stays_counted():
    """이미 찍은 것이 진척에서 사라지면 되돌아간 것처럼 보인다."""
    it = _item("A_1")
    it.result = "통과"
    states = {x.n: x for x in stage_states(1, 1, {"면접": [it]}, {"A_1": "인정"})}
    assert states[3].total == 1 and states[3].done == 1 and states[3].moot == 0


def test_without_outcomes_every_item_is_counted():
    """판단 재료가 없으면 예전처럼 전부 센다."""
    states = {x.n: x for x in stage_states(1, 0, {"면접": [_item("A_1")]})}
    assert states[3].total == 1 and not states[3].skipped


def test_a_qualification_credited_unit_counts_as_record(clean):
    """과정평가형 자격으로 갈음된 단위는 「기록」이다.

    Track B 는 그 단위의 요소를 다시 판단 대상으로 올린다(자격은 R0 가
    아니다). 그것을 그대로 세면 자격 보유자의 인정 시간이 3분의 1로 준다.
    """
    sid, aid = clean
    with session_scope() as s:
        st = case_state(s, sid)
        ctx = review_ctx(s, aid)
        credited = ctx.credited_units
    if not credited:
        pytest.skip("기록 확인이 갈음한 단위가 없다")
    assert sum(credited.values()) == st.credited_hours
    sp = ctx.hour_split()
    assert sp.record >= sum(credited.values())


def test_recognised_hours_never_drop_below_the_record(clean):
    """검토를 아무것도 안 해도 기록으로 확인된 시간은 남아 있어야 한다."""
    _, aid = clean
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        got, tot = ctx.recognized_hours()
        assert got >= sum(ctx.credited_units.values())
        assert got == ctx.hour_split().credited
