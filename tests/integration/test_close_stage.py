"""단계 마감 — 손대지 않은 것을 기본값으로 확정한다.

## 왜

항목마다 「받음/못 받음」을 찍게 했더니 이런 말을 들었다 —
「파일 올리면 받은 거고 아니면 못 받은 건데 왜 일일이 체크하나」.

그리고 더 나쁜 일이 있었다. 실측 R2026-0004 에서 심사위원이 2·3·4단계를
다 돌고도 **최종 결과가 0시간**이었다. 1단계를 한 번도 누르지 않았기
때문이다 — 보완 항목 결과는 「조건부인정」인 요소에만 효력이 있는데 그
요소가 하나도 없었다. 화면은 아무 말도 하지 않았다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from krpl_core.db import session_scope
from services.gateway.api import app
from services.review import close, preview, save_element_review, save_result
from services.review import load as review_ctx
from services.review.close import DEFAULT_OF
from services.review.ledger import build

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
def aid():
    with session_scope() as s:
        v = s.execute(text("""SELECT a.id FROM assessment a
            JOIN submission s ON s.id=a.submission_id
            WHERE s.case_number=:c AND a.kind='evidence' AND a.status='done'
            ORDER BY a.id DESC LIMIT 1"""), {"c": CASE}).scalar()
    if v is None:
        pytest.skip("근거 분석 결과 없음")
    return v


@pytest.fixture
def clean(aid):
    def wipe():
        with session_scope() as s:
            s.execute(text("DELETE FROM element_review WHERE assessment_id=:a"), {"a": aid})
            s.execute(text("DELETE FROM remediation_result WHERE assessment_id=:a"), {"a": aid})
    wipe()
    yield aid
    wipe()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ── 1단계 — 권고를 기본값으로 ────────────────────────────────────

def test_closing_the_first_stage_adopts_the_recommendation(clean):
    """사람은 **다르게 볼 것만** 고른다. 나머지는 권고대로 간다."""
    aid = clean
    with session_scope() as s:
        want = {x["element_id"]: DEFAULT_OF.get(x["recommendation"] or "", "조건부인정")
                for x in review_ctx(s, aid).judge_pool}
    with session_scope() as s:
        c = close(s, aid, 1)
    assert c.settled == len(want) and c.already == 0
    with session_scope() as s:
        got = {k: v["decision"] for k, v in review_ctx(s, aid).reviews.items()}
    for eid, w in want.items():
        assert got[eid] == w, eid


def test_it_never_touches_what_a_person_already_decided(clean):
    aid = clean
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        mine = [x["element_id"] for x in ctx.judge_pool][:3]
        assert mine, "판단 대상이 없다"
        for eid in mine:
            save_element_review(s, aid, eid, "불인정", note="사람이 정함", reviewer="시험")
    with session_scope() as s:
        c = close(s, aid, 1)
    assert c.already == len(mine)
    with session_scope() as s:
        got = review_ctx(s, aid).reviews
    for eid in mine:
        assert got[eid]["decision"] == "불인정" and got[eid]["note"] == "사람이 정함"


def test_a_denial_recommendation_becomes_a_denial(clean):
    """R5(훈련 이수 필요)를 조건부로 올려 주면 안 된다."""
    assert DEFAULT_OF["R5"] == "불인정"
    assert DEFAULT_OF["R0"] == "인정" and DEFAULT_OF["R1"] == "인정"
    assert DEFAULT_OF["R2"] == "조건부인정" and DEFAULT_OF["R3"] == "조건부인정"


def test_preview_says_what_will_happen_without_doing_it(clean):
    aid = clean
    with session_scope() as s:
        before = len(review_ctx(s, aid).reviews)
        c = preview(s, aid, 1)
    with session_scope() as s:
        assert len(review_ctx(s, aid).reviews) == before, "미리 보기가 값을 바꿨다"
    assert c.settled > 0 and c.detail


# ── 2·3·4단계 — 손대지 않은 것은 미통과 ─────────────────────────

@pytest.mark.parametrize("stage,method", [(2, "추가서류"), (3, "면접"), (4, "실기")])
def test_closing_a_method_stage_marks_the_rest_as_not_passed(clean, stage, method):
    aid = clean
    with session_scope() as s:
        close(s, aid, 1)
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        live, _ = ctx.split_items(method)
        if not live:
            pytest.skip(f"{method} 항목이 없다")
        first = live[0]
        save_result(s, aid, first.key, method, first.item, "통과", reviewer="시험")
        n_live = len(live)
    with session_scope() as s:
        c = close(s, aid, stage)
    assert c.already >= 1 and c.settled == n_live - 1
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        by = {i.key: i for i in ctx.items.get(method) or []}
    assert by[first.key].result == "통과", "사람이 찍은 것을 덮어썼다"
    rest = [i for k, i in by.items() if k != first.key and not i.superseded]
    assert all(i.result == "미통과" for i in rest if i.done)


def test_an_unknown_stage_is_refused(clean):
    for n in (0, 5, 9):
        with session_scope() as s:
            with pytest.raises(ValueError):
                close(s, aid_of(s, clean), n)


def aid_of(s, aid):
    return aid


# ── 종단 — 이것이 실제로 막혔던 자리다 ──────────────────────────

def test_closing_every_stage_makes_the_ledger_move(clean):
    """2·3·4단계를 다 돌고도 최종 결과가 0시간이던 그 상황."""
    aid = clean
    with session_scope() as s:
        before = build(review_ctx(s, aid))
    # 아무도 안 정했으면 기록 확인이 갈음한 것 말고는 전부 「미정」이다
    assert before.hours("미정") > 0, "미정이 없어 시험의 뜻이 없다"
    for stage in (1, 2, 3, 4):
        with session_scope() as s:
            close(s, aid, stage)
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        lg = build(ctx)
    assert lg.balanced, f"합 {lg.sum_hours}/{lg.total_hours}"
    assert lg.hours("미정") == 0, "마감했는데 아직 정하지 않은 시간이 남았다"
    assert lg.recognized_hours >= before.recognized_hours
    assert all(x.complete for x in ctx.states if x.n < 5), "안 끝난 단계가 있다"


def test_the_close_is_recorded_for_the_audit(clean):
    """무엇을 그대로 채택했는지 남아야 한다 — 이 버튼이 사람의 서명이다."""
    aid = clean
    with session_scope() as s:
        close(s, aid, 1)
    with session_scope() as s:
        sid = review_ctx(s, aid).submission_id
        n = s.execute(text("""SELECT count(*) FROM artifact WHERE submission_id=:i
            AND stage='review' AND name='1단계_마감'"""), {"i": sid}).scalar_one()
        log = s.execute(text("""SELECT action, actor FROM audit_log
            WHERE entity='assessment' AND entity_id=:a ORDER BY id DESC LIMIT 1"""),
            {"a": str(aid)}).first()
    assert n == 1, "감사 산출물이 없다"
    assert log and log[0] == "1단계_마감" and log[1] == "심사위원 합의"


# ── 화면 ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("stage", [1, 2, 3, 4])
def test_each_stage_offers_the_close_button(clean, client, stage):
    h = client.get(f"/assessments/{clean}/review/{stage}").text
    assert f'onclick="closeStage({stage})"' in h or "손댈 것이 남아 있지 않습니다" in h


def test_the_first_stage_says_what_the_default_will_be(clean, client):
    h = client.get(f"/assessments/{clean}/review/1").text
    assert "AI 권고대로" in h and "이미 정하신 것은 그대로 둡니다" in h
