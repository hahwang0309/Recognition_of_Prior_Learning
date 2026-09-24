"""인정 원장 — 총 필수 시간이 어느 경로로 갔는지.

5단계 「최종 결과」에 요소 서른 줄짜리 표 하나뿐이었다. 근거는 되지만
종합이 아니다. 심사위원이 서명 직전에 알고 싶은 것은 이것이다 —

  420시간 가운데 기록으로 얼마, 서류로 얼마, 면접으로 얼마, 실기로 얼마,
  그래도 안 되면 훈련으로 얼마.

**규칙 하나** — 1시간도 빠짐없이 정확히 하나의 경로에 속한다. 합이 총 필수
시간과 다르면 결함이다. 이 시험이 그것을 붙든다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from krpl_core.db import session_scope
from services.review import load as review_ctx
from services.review import save_element_review, save_result
from services.review.ledger import PATHS, build

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


def ledger(aid):
    with session_scope() as s:
        return build(review_ctx(s, aid))


# ── 규칙 하나 ─────────────────────────────────────────────────────

def test_every_hour_lands_in_exactly_one_path(clean):
    lg = ledger(clean)
    assert lg.balanced, (
        f"합 {lg.sum_hours} ≠ 총 필수 {lg.total_hours} · "
        + " ".join(f"{k}={lg.hours(k)}" for k, _, _ in PATHS))
    assert len({r.unit_code for r in lg.rows}) == len(lg.rows), "능력단위가 두 줄에 있다"


def test_it_stays_balanced_after_every_kind_of_judgment(clean):
    """무엇을 찍든 합은 총 필수 시간이다."""
    aid = clean
    for decision in ("인정", "조건부인정", "불인정", "보류"):
        with session_scope() as s:
            ctx = review_ctx(s, aid)
            for x in ctx.judge_pool:
                save_element_review(s, aid, x["element_id"], decision, reviewer="시험")
        lg = ledger(aid)
        assert lg.balanced, f"{decision} 뒤에 합이 {lg.sum_hours}/{lg.total_hours}"


def test_it_stays_balanced_after_remediation_results(clean):
    aid = clean
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        for x in ctx.judge_pool:
            save_element_review(s, aid, x["element_id"], "조건부인정", reviewer="시험")
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        for m in ("추가서류", "면접", "실기"):
            for i, it in enumerate(ctx.items.get(m) or []):
                save_result(s, aid, it.key, m, it.item,
                            "통과" if i % 2 == 0 else "미통과", reviewer="시험")
    lg = ledger(aid)
    assert lg.balanced
    assert lg.recognized_hours <= lg.total_hours


# ── 경로를 제대로 가르나 ─────────────────────────────────────────

def test_a_record_credited_unit_goes_to_the_record_path(clean):
    """기록 확인이 갈음한 단위는 검토 결과와 상관없이 ① 기록이다."""
    aid = clean
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        credited = set(ctx.credited_units)
    if not credited:
        pytest.skip("기록 확인이 갈음한 단위가 없다")
    lg = ledger(aid)
    got = {r.unit_code for r in lg.by_path("기록")}
    assert got == credited
    assert lg.hours("기록") == sum(r.hours for r in lg.by_path("기록"))
    for r in lg.by_path("기록"):
        assert r.why and ("시간" in r.why[0] or "갈음" in r.why[0]), r.why


def test_the_record_row_says_what_it_was_credited_with(clean):
    """「자동차정비기능사 30시간 / 요구 50시간 (60%) — 조정범위내」"""
    lg = ledger(clean)
    rows = lg.by_path("기록")
    if not rows:
        pytest.skip("기록 확인이 갈음한 단위가 없다")
    assert any("요구" in r.why[0] and "%" in r.why[0] for r in rows)


def test_a_denied_unit_goes_to_training(clean):
    aid = clean
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        credited = set(ctx.credited_units)
        pool = [x["element_id"] for x in ctx.judge_pool
                if x["element_id"].split("_")[0] not in credited]
        if not pool:
            pytest.skip("기록 밖 판단 대상이 없다")
        for eid in pool:
            save_element_review(s, aid, eid, "불인정", reviewer="시험")
    lg = ledger(aid)
    assert lg.by_path("훈련"), "불인정으로 찍었는데 훈련 경로가 비었다"
    assert all(r.state == "훈련 필요" for r in lg.by_path("훈련"))
    assert lg.balanced


def test_an_unjudged_unit_is_not_called_an_interview(clean):
    """아직 아무도 안 본 것을 「면접으로 확인할 시간」이라 부르면 안 된다."""
    lg = ledger(clean)
    for r in lg.rows:
        if r.path == "미정":
            assert r.state == "미정" and r.stage == 1


def test_a_mixed_unit_is_counted_once_but_shows_both(clean):
    """면접과 실기가 한 단위에 섞이면 한쪽에만 넣되 줄에는 둘 다 적는다."""
    aid = clean
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        for x in ctx.judge_pool:
            save_element_review(s, aid, x["element_id"], "조건부인정", reviewer="시험")
    lg = ledger(aid)
    # 훈련 항목이 걸린 단위는 면접·실기가 섞여 있어도 훈련이다 — 확인으로
    # 풀리지 않기 때문이다. 확인 경로에 남은 것만 본다.
    mixed = [r for r in lg.rows if len(r.methods) > 1 and r.path in ("면접", "실기")]
    for r in mixed:
        assert "면접" in r.method_line and "실기" in r.method_line
        assert r.path == max(r.methods.items(), key=lambda x: (x[1], x[0] == "실기"))[0]
    assert lg.balanced


# ── 짚어야 할 것 ─────────────────────────────────────────────────

def test_a_credited_unit_whose_elements_were_denied_is_flagged(clean):
    """시간은 갈음됐는데 요소는 미인정 — 조용히 넘기면 안 된다."""
    aid = clean
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        credited = set(ctx.credited_units)
        pool = [x["element_id"] for x in ctx.judge_pool
                if x["element_id"].split("_")[0] in credited]
        if not pool:
            pytest.skip("기록으로 갈음된 단위에 판단 대상이 없다")
        for eid in pool:
            save_element_review(s, aid, eid, "불인정", reviewer="시험")
    lg = ledger(aid)
    flagged = [r for r in lg.by_path("기록") if r.flag]
    assert flagged, "경고가 붙지 않았다"
    assert all("미인정" in r.flag for r in flagged)
    assert lg.balanced


def test_open_paths_list_what_is_left(clean):
    lg = ledger(clean)
    left = dict((k, h) for k, h, _ in lg.open_paths)
    assert lg.recognized_hours + sum(left.values()) == lg.total_hours


# ── 화면 ──────────────────────────────────────────────────────────

def test_the_final_screen_shows_the_ledger(clean):
    """「최종 결과」에 요소 표 하나뿐이면 종합이 아니다."""
    from fastapi.testclient import TestClient
    from services.gateway.api import app
    aid = clean
    with TestClient(app) as c:
        h = c.get(f"/assessments/{aid}/review/5").text
    lg = ledger(aid)
    assert '<div class="lbar">' in h, "원장 막대가 없다"
    assert "남은 일" in h or "남은 일이 없습니다" in h
    for k, name, _ in PATHS:
        if lg.hours(k):
            assert name in h, f"{name} 블록이 없다"
    # 요소 표는 남되 접혀 있다 — 종합이 아니라 근거다
    assert '<details class="els">' in h
    assert f"인정 <b>{lg.recognized_hours}</b>" in h


def test_the_screen_says_so_when_the_ledger_does_not_balance(clean, monkeypatch):
    """합이 안 맞으면 이 화면을 믿을 수 없다. 감추지 않는다."""
    from fastapi.testclient import TestClient
    from services.gateway.api import app
    import services.report.stage_view as sv
    real = sv.ledger_of

    def broken(ctx):
        lg = real(ctx)
        if lg.rows:
            lg.rows[0].hours += 7
        return lg
    monkeypatch.setattr(sv, "ledger_of", broken)
    with TestClient(app) as c:
        h = c.get(f"/assessments/{clean}/review/5").text
    assert "총 필수" in h and "다릅니다" in h


def test_the_record_path_is_coloured_only_in_the_bar():
    """색 클래스를 그대로 두었더니 같은 클래스를 단 블록이 통째로 칠해져
    글씨가 안 보였다."""
    from services.report.stage_view import CSS
    assert ".lbar i.p-rec" in CSS
    assert "\n.p-rec{background" not in CSS
