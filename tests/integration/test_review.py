"""전문가 검토 종단 시험 — 요소별 의견 → 감면 시간 → 최종 판정 기록.

여기서 확인하는 것은 두 가지다.
  ① 시간 계산이 규칙대로 굴러가는가 (능력단위 단위로 접힌다)
  ② 시스템이 사람 대신 판정하지 않는가 (권고안만 내고, 기록은 받아 적는다)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from krpl_core.db import session_scope
from krpl_core.llm import ReplayClient
from services.assess.track_b_service import run_track_b
from services.gateway.api import app
from services.review import record_decision, review_summary, save_element_review

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/trackb"
CASE = "R2026-0002"
MAP = {"R0": "인정", "R1": "인정", "R2": "조건부인정", "R3": "조건부인정",
       "R4": "보류", "R5": "불인정"}


@pytest.fixture(scope="module", autouse=True)
def demo_data():
    with session_scope() as s:
        if s.execute(text("SELECT 1 FROM submission WHERE case_number=:c"),
                     {"c": CASE}).first() is None:
            sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
            try:
                import load_demo
                load_demo.load()
            except FileNotFoundError as e:
                pytest.skip(f"실사례 원본 없음: {e}")


@pytest.fixture
def aid():
    """검토 이력이 없는 새 판정 하나."""
    with session_scope() as s:
        sid = s.execute(text("SELECT id FROM submission WHERE case_number=:c"),
                        {"c": CASE}).scalar()
        s.execute(text("DELETE FROM final_decision WHERE submission_id=:i"), {"i": sid})
        i = run_track_b(s, sid, client=ReplayClient(FIXTURES))
    yield i
    with session_scope() as s:
        s.execute(text("DELETE FROM assessment WHERE id=:i"), {"i": i})


@pytest.fixture
def client():
    return TestClient(app)


def _recs(s, aid) -> list[tuple[str, str]]:
    return [(r[0], r[1]) for r in s.execute(text(
        "SELECT element_id, recommendation FROM assessment_element WHERE assessment_id=:i"),
        {"i": aid})]


def review_all(aid, mapping=None) -> None:
    mapping = mapping or MAP
    with session_scope() as s:
        for eid, rec in _recs(s, aid):
            save_element_review(s, aid, eid, mapping[rec], reviewer="시험")


# ── 진행 상황 ──
def test_summary_starts_empty(aid):
    with session_scope() as s:
        sm = review_summary(s, aid)
    assert sm.n_elements == 33 and sm.n_reviewed == 0 and not sm.complete
    assert sm.counts["미검토"] == 33 and sm.hours() == 0
    assert sm.total_hours == 410 and len(sm.units) == 10


def test_save_records_ai_recommendation_for_comparison(aid):
    """사람 의견과 기계 권고를 나란히 남긴다 — 나중에 대조할 수 있어야 한다."""
    with session_scope() as s:
        eid, rec = _recs(s, aid)[0]
        r = save_element_review(s, aid, eid, "불인정", note="현장 확인 필요", reviewer="심사위원 A")
        row = s.execute(text("""SELECT decision, ai_recommendation, note, reviewer
                                FROM element_review WHERE assessment_id=:a AND element_id=:e"""),
                        {"a": aid, "e": eid}).mappings().one()
    assert r["ai_recommendation"] == rec == row["ai_recommendation"]
    assert row["decision"] == "불인정" and row["reviewer"] == "심사위원 A"


def test_save_is_idempotent(aid):
    with session_scope() as s:
        eid = _recs(s, aid)[0][0]
        save_element_review(s, aid, eid, "인정")
        save_element_review(s, aid, eid, "보류", note="다시 봄")
        rows = s.execute(text("""SELECT decision, note FROM element_review
                                 WHERE assessment_id=:a AND element_id=:e"""),
                         {"a": aid, "e": eid}).mappings().all()
    assert len(rows) == 1 and rows[0]["decision"] == "보류" and rows[0]["note"] == "다시 봄"


def test_rejects_unknown_decision_and_element(aid):
    with session_scope() as s:
        eid = _recs(s, aid)[0][0]
        with pytest.raises(ValueError, match="의견 값이 잘못됨"):
            save_element_review(s, aid, eid, "대충인정")
        with pytest.raises(LookupError):
            save_element_review(s, aid, "9999999999_99v9.1", "인정")


# ── 시간 계산 ──
def test_hours_fold_up_by_unit(aid):
    """요소 단위로 검토하지만 시간은 능력단위 단위로 접힌다."""
    review_all(aid)
    with session_scope() as s:
        sm = review_summary(s, aid)
    assert sm.complete and sm.counts == {"인정": 15, "조건부인정": 15,
                                         "불인정": 3, "보류": 0, "미검토": 0}
    # 전부 인정된 능력단위만 감면된다
    full = [u for u in sm.units if u.n_인정 == u.n_elements]
    assert sm.hours() == sum(u.required_hours for u in full) == 190
    assert sm.rate() == pytest.approx(190 / 410)
    assert sm.hours(conditional=True) == 270      # 조건부까지 세면 늘어난다
    assert sm.suggest_decision() == "부분인정"


def test_partial_unit_earns_nothing_under_all_elements(aid):
    """요소 하나만 빠져도 그 능력단위 시간은 감면되지 않는다 — 보수적 규칙."""
    review_all(aid)
    with session_scope() as s:
        before = review_summary(s, aid).hours()
        # 전부 인정된 능력단위에서 요소 하나를 보류로 바꾼다
        u = next(u for u in review_summary(s, aid).units if u.n_인정 == u.n_elements)
        eid = s.execute(text("""SELECT element_id FROM assessment_element
                                WHERE assessment_id=:a AND element_id LIKE :p LIMIT 1"""),
                        {"a": aid, "p": f"{u.unit_code}%"}).scalar()
        save_element_review(s, aid, eid, "보류")
        after = review_summary(s, aid)
    assert after.hours() == before - u.required_hours
    assert after.hours("proportional") > after.hours("all_elements")   # 비율 규칙이면 일부 남는다


def test_both_rules_are_computed(aid):
    """D-7 미확정 — 두 방식을 모두 계산해 보여준다."""
    review_all(aid)
    with session_scope() as s:
        sm = review_summary(s, aid)
        b = sm.basis()
    assert b["rule"] == "all_elements"
    assert b["확정"]["hours"] == 190 and b["조건부포함"]["hours"] == 270
    assert b["다른_규칙_적용시"]["proportional"] == {"확정": 190, "조건부포함": 322}


def test_full_acceptance_suggests_전체인정(aid):
    review_all(aid, {r: "인정" for r in MAP})
    with session_scope() as s:
        sm = review_summary(s, aid)
    assert sm.hours() == sm.total_hours and sm.suggest_decision() == "전체인정"


def test_full_rejection_suggests_불인정(aid):
    review_all(aid, {r: "불인정" for r in MAP})
    with session_scope() as s:
        sm = review_summary(s, aid)
    assert sm.hours() == 0 and sm.suggest_decision() == "불인정"


# ── 최종 판정 ──
def test_decision_requires_complete_review(aid):
    with session_scope() as s:
        with pytest.raises(ValueError, match="검토가 끝나지 않았습니다"):
            record_decision(s, aid, "부분인정")


def test_decision_records_calculation_basis(aid):
    """몇 시간이냐보다 왜 그 숫자냐가 남아야 한다."""
    review_all(aid)
    with session_scope() as s:
        r = record_decision(s, aid, "부분인정", reason="검사 항목은 실기 후 확정",
                            decided_by="심사위원 A")
        row = s.execute(text("""SELECT decision, reason, decided_by, decided_on,
                                recognized_hours, total_hours, credit_basis
                                FROM final_decision WHERE assessment_id=:i"""),
                        {"i": aid}).mappings().one()
        st = s.execute(text("""SELECT status FROM submission WHERE id=(
                               SELECT submission_id FROM assessment WHERE id=:i)"""),
                       {"i": aid}).scalar_one()
    assert r["recognized_hours"] == 190 and row["recognized_hours"] == 190
    assert row["total_hours"] == 410 and row["decided_on"] is not None
    b = row["credit_basis"]
    assert b["rule"] == "all_elements" and b["hours_overridden"] is False
    assert b["suggested_decision"] == "부분인정"
    assert len(b["units"]) == 10 and sum(u["감면"] for u in b["units"]) == 190
    assert "recommendations.R1.requires.ksa_coverage_min" in b["pending_rubric_decisions"]
    assert st == "decided"


def test_human_may_override_hours_and_decision(aid):
    """시스템 권고안과 다르게 기록할 수 있어야 한다. 사람이 정한다."""
    review_all(aid)
    with session_scope() as s:
        r = record_decision(s, aid, "전체인정", recognized_hours=410,
                            reason="TF 합의", decided_by="TF")
    assert r["decision"] == "전체인정" and r["recognized_hours"] == 410
    assert r["credit_basis"]["hours_overridden"] is True
    assert r["credit_basis"]["suggested_decision"] == "부분인정"   # 권고안은 그대로 남는다


def test_conditional_can_be_counted(aid):
    review_all(aid)
    with session_scope() as s:
        r = record_decision(s, aid, "부분인정", conditional=True)
    assert r["recognized_hours"] == 270 and r["credit_basis"]["conditional_counted"] is True


def test_decision_is_idempotent(aid):
    review_all(aid)
    with session_scope() as s:
        record_decision(s, aid, "부분인정", decided_by="A")
        record_decision(s, aid, "불인정", decided_by="B")
        rows = s.execute(text("""SELECT decision, decided_by FROM final_decision
                                 WHERE assessment_id=:i"""), {"i": aid}).mappings().all()
    assert len(rows) == 1 and rows[0]["decision"] == "불인정" and rows[0]["decided_by"] == "B"


def test_rejects_unknown_decision(aid):
    review_all(aid)
    with session_scope() as s:
        with pytest.raises(ValueError, match="판정 값이 잘못됨"):
            record_decision(s, aid, "조건부인정")     # 요소 의견 값이지 최종 판정 값이 아니다


# ── API ──
def test_api_review_flow(client, aid):
    with session_scope() as s:
        pairs = _recs(s, aid)
        sid = s.execute(text("SELECT submission_id FROM assessment WHERE id=:i"),
                        {"i": aid}).scalar_one()

    d = client.get(f"/assessments/{aid}/review/summary").json()
    assert d["complete"] is False and d["n_reviewed"] == 0
    assert d["rule"] == "all_elements" and d["other_rule"] == "proportional"

    for eid, rec in pairs:
        r = client.post(f"/assessments/{aid}/elements/{eid}/review",
                        json={"decision": MAP[rec], "reviewer": "심사위원 A"})
        assert r.status_code == 200
        assert r.json()["ai_recommendation"] == rec

    d = client.get(f"/assessments/{aid}/review/summary").json()
    assert d["complete"] and d["n_reviewed"] == 33
    assert (d["hours"], d["hours_conditional"]) == (190, 270)
    assert (d["hours_other_rule"], d["hours_other_conditional"]) == (190, 322)
    assert d["suggested"] == "부분인정"

    r = client.post(f"/submissions/{sid}/decision",
                    json={"assessment_id": aid, "decision": "부분인정",
                          "reason": "검사 항목은 실기 후 확정", "decided_by": "심사위원 A"})
    assert r.status_code == 200 and r.json()["recognized_hours"] == 190
    assert client.get(f"/submissions/{sid}/decision").json()["decision"] == "부분인정"
    assert client.get(f"/submissions/{sid}/status").json()["status"] == "decided"


def test_api_blocks_premature_decision(client, aid):
    with session_scope() as s:
        sid = s.execute(text("SELECT submission_id FROM assessment WHERE id=:i"),
                        {"i": aid}).scalar_one()
    r = client.post(f"/submissions/{sid}/decision",
                    json={"assessment_id": aid, "decision": "부분인정"})
    assert r.status_code == 409 and "검토가 끝나지 않았습니다" in r.json()["detail"]
    r = client.post(f"/submissions/{sid}/decision",
                    json={"assessment_id": aid, "decision": "부분인정", "allow_incomplete": True})
    assert r.status_code == 200 and r.json()["recognized_hours"] == 0


def test_api_rejects_mismatched_assessment(client, aid):
    r = client.post("/submissions/999999/decision",
                    json={"assessment_id": aid, "decision": "부분인정"})
    assert r.status_code == 409


def test_api_validates_decision_vocabulary(client, aid):
    with session_scope() as s:
        eid = _recs(s, aid)[0][0]
    assert client.post(f"/assessments/{aid}/elements/{eid}/review",
                       json={"decision": "대충인정"}).status_code == 422
    assert client.post(f"/assessments/{aid}/elements/9999999999_99v9.1/review",
                       json={"decision": "인정"}).status_code == 404


def test_api_lists_reviews_with_agreement(client, aid):
    review_all(aid)
    rows = client.get(f"/assessments/{aid}/reviews").json()
    assert len(rows) == 33
    agree = [r for r in rows if r["agrees_with_ai"]]
    # R0 15개를 인정했고 나머지는 인정하지 않았으므로 전부 일치한다
    assert len(agree) == 33


# ── 화면 ──
def test_review_screen_renders(client, aid):
    r = client.get(f"/assessments/{aid}/review")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    h = r.text
    assert "선행학습인정 검토" in h and CASE in h
    assert "판정이 아니라 판정의 근거" in h
    assert "용접부 온도 관리하기" in h            # 고시 원문의 요소 이름
    assert "R0 기이수 인정검토" in h              # 코드만 두지 않고 뜻을 붙인다
    assert h.count('class="el') == 33
    assert "D01-R04" in h                        # 인용 출처
    assert "확정 대기 중인 기준 항목이 7건" in h


def test_screen_shows_saved_reviews(client, aid):
    with session_scope() as s:
        eid = _recs(s, aid)[0][0]
        save_element_review(s, aid, eid, "조건부인정", note="아래보기만 확인됨")
    h = client.get(f"/assessments/{aid}/review").text
    assert "아래보기만 확인됨" in h
    assert '<button class="d on" data-d="조건부인정"' in h


def test_screen_has_no_methodology_jargon(client, aid):
    """읽는 사람은 RPL·직종 전문가다. 내부 용어를 노출하지 않는다."""
    h = client.get(f"/assessments/{aid}/review").text
    for bad in ("needs_expert_review", "evidence_level", "ksa_ref",
                "confidence", "all_elements", "proportional"):
        assert bad not in h, f"내부 용어 노출: {bad}"


def test_time_comparison_uses_its_own_report(client):
    """시간 대조와 근거 분석은 화면이 다르다. 가르는 것은 assessment.kind 다.

    예전에는 submission.track 으로 갈랐다. 그런데 한 접수 건이 둘 다 가질 수
    있게 되면서 그 기준으로는 갈리지 않는다.
    """
    with session_scope() as s:
        aid = s.execute(text("""SELECT id FROM assessment WHERE kind='time'
                                ORDER BY id DESC LIMIT 1""")).scalar()
    if aid is None:
        pytest.skip("시간 대조 판정 없음")
    h = client.get(f"/assessments/{aid}/review").text
    assert "시간 대조 보고서" in h
    assert "Track A" not in h                       # 내부 용어를 화면에 쓰지 않는다
