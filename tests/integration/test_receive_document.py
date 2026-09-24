"""추가 서류를 받으면 면접·실기가 그것을 반영한다.

2단계는 「받음 / 못 받음 / 미실시」 토글뿐이었다. 서류 실물이 시스템에
들어오지 않으니 그 서류에 무엇이 적혀 있는지 아무도 읽지 않았고, 3·4단계
질문지도 그대로였다.

  받은 서류 → 조각으로 수집 → 그 항목 「받음」
            → **걸린 요소만** 재판정(이전 판정과 검토 기록은 옮긴다)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from krpl_core.db import session_scope
from krpl_core.llm import ReplayClient
from services.assess.track_b_service import run_track_b
from services.gateway.api import app
from services.review import load as review_ctx
from services.review import receive_document, save_element_review

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/trackb"
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


@pytest.fixture
def run():
    """이 시험만의 판정 한 벌. 끝나면 자국을 지운다."""
    with session_scope() as s:
        sid = s.execute(text("SELECT id FROM submission WHERE case_number=:c"),
                        {"c": CASE}).scalar()
        aid = run_track_b(s, sid, client=ReplayClient(FIXTURES))
    made = [aid]
    yield sid, aid, made
    with session_scope() as s:
        for a in made:
            s.execute(text("DELETE FROM element_review WHERE assessment_id=:a"), {"a": a})
            s.execute(text("DELETE FROM remediation_result WHERE assessment_id=:a"), {"a": a})
        s.execute(text("DELETE FROM assessment WHERE id = ANY(:a)"), {"a": made})
        s.execute(text("""DELETE FROM job WHERE kind='track_b'
                          AND (payload->>'submission_id')::int=:i"""), {"i": sid})


DOC = ("안전보건교육 이수확인서\n\n"
       "성명: (마스킹)\n교육과정: 산업안전보건법 정기 안전보건교육\n"
       "교육시간: 24시간\n이수일자: 2024-11-20\n평가결과: 수료\n").encode()


def _doc_item(aid: int):
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        g = ctx.items.get("추가서류") or []
        if not g:
            pytest.skip("추가서류 항목이 없다")
        return max(g, key=lambda i: i.n_elements)


# ── 받으면 무슨 일이 일어나나 ────────────────────────────────────

def test_receiving_a_document_ingests_it(run):
    sid, aid, made = run
    it = _doc_item(aid)
    with session_scope() as s:
        r = receive_document(s, aid, it.key, "안전보건교육_이수확인서.txt", DOC,
                             reviewer="시험")
    assert r.n_fragments > 0, "조각이 하나도 안 생겼다 — 서류를 읽지 않은 것이다"
    assert r.doc_type and r.grade
    with session_scope() as s:
        n = s.execute(text("""SELECT count(*) FROM fragment
                              WHERE submission_id=:i AND doc_key=:k"""),
                      {"i": sid, "k": r.doc_key}).scalar_one()
    assert n == r.n_fragments


def test_the_document_type_is_guessed_from_the_file_name(run):
    _, aid, _ = run
    it = _doc_item(aid)
    with session_scope() as s:
        r = receive_document(s, aid, it.key, "안전보건교육 수료증.txt", DOC)
    assert r.doc_type == "비NCS_교육수료증", r.doc_type


def test_it_marks_the_item_received(run):
    _, aid, _ = run
    it = _doc_item(aid)
    with session_scope() as s:
        receive_document(s, aid, it.key, "확인서.txt", DOC, reviewer="시험")
    with session_scope() as s:
        got = review_ctx(s, aid)
        same = next(i for i in got.items["추가서류"] if i.key == it.key)
    assert same.result == "통과" and not same.superseded


def test_it_queues_a_re_analysis_scoped_to_that_document(run):
    """서류 한 장 때문에 서른세 개를 통째로 다시 돌리지 않는다."""
    sid, aid, _ = run
    it = _doc_item(aid)
    with session_scope() as s:
        r = receive_document(s, aid, it.key, "확인서.txt", DOC)
    with session_scope() as s:
        p = s.execute(text("SELECT payload FROM job WHERE id=:i"),
                      {"i": r.job_id}).scalar_one()
    assert p["submission_id"] == sid
    assert p["keep_from"] == aid
    assert set(p["focus"]) == {t["eid"] for t in it.targets}
    assert len(p["focus"]) < 33, "전체를 다시 돌리려 한다"


def test_two_documents_share_one_re_analysis(run):
    """연달아 올린다고 판정이 두 번 돌 이유는 없다. 아직 아무도 집지 않은
    작업이 있으면 범위만 넓힌다."""
    sid, aid, _ = run
    from services.review.receive import _requeue
    with session_scope() as s:
        a = _requeue(s, sid, aid, ["X_1", "X_2"])
    with session_scope() as s:
        b = _requeue(s, sid, aid, ["X_2", "X_3"])
    assert a == b, "작업이 두 개 쌓였다"
    with session_scope() as s:
        p = s.execute(text("SELECT payload FROM job WHERE id=:i"), {"i": b}).scalar_one()
    assert p["focus"] == ["X_1", "X_2", "X_3"]
    assert p["keep_from"] == aid


# ── 다시 돌릴 때 무엇을 옮기나 ───────────────────────────────────

def test_the_re_run_keeps_everything_it_did_not_look_at(run):
    sid, aid, made = run
    it = _doc_item(aid)
    focus = sorted({t["eid"] for t in it.targets})
    with session_scope() as s:
        before = {r[0]: r[1] for r in s.execute(text(
            "SELECT element_id, payload FROM assessment_element WHERE assessment_id=:a"),
            {"a": aid})}
        new = run_track_b(s, sid, client=ReplayClient(FIXTURES),
                          keep_from=aid, focus=focus)
    made.append(new)
    with session_scope() as s:
        after = {r[0]: r[1] for r in s.execute(text(
            "SELECT element_id, payload FROM assessment_element WHERE assessment_id=:a"),
            {"a": new})}
        note = json.loads(s.execute(text(
            "SELECT overall_note FROM assessment WHERE id=:i"), {"i": new}).scalar_one())
    assert set(after) == set(before), "요소가 빠지거나 늘었다"
    kept = [e for e in before if e not in focus]
    assert all(after[e] == before[e] for e in kept), "안 본 요소가 바뀌었다"
    assert note["실행"]["재분석"]["이전판정"] == aid
    # 요소는 셋 중 하나로 온다 — 코드 확정(기이수) · 이월 · 다시 봄
    r = note["실행"]["재분석"]
    assert r["이월요소"] + note["실행"]["기이수_코드확정"] + len(focus) == len(before)
    assert r["다시본요소"] == focus


def test_the_re_run_carries_the_reviews_it_did_not_redo(run):
    """서류 한 장 때문에 서른세 개를 처음부터 다시 판단하게 하지 않는다."""
    sid, aid, made = run
    it = _doc_item(aid)
    focus = sorted({t["eid"] for t in it.targets})
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        for x in ctx.judge_pool:
            save_element_review(s, aid, x["element_id"], "조건부인정", reviewer="시험")
        judged = {x["element_id"] for x in ctx.judge_pool}
    with session_scope() as s:
        new = run_track_b(s, sid, client=ReplayClient(FIXTURES),
                          keep_from=aid, focus=focus)
    made.append(new)
    with session_scope() as s:
        moved = {r[0] for r in s.execute(text(
            "SELECT element_id FROM element_review WHERE assessment_id=:a"), {"a": new})}
    assert moved == judged - set(focus), "옮긴 판단이 맞지 않는다"
    assert not (moved & set(focus)), "다시 볼 요소의 판단까지 옮겼다"


# ── 화면 ──────────────────────────────────────────────────────────

def test_the_second_stage_offers_a_place_to_upload(run):
    _, aid, _ = run
    with TestClient(app) as c:
        h = c.get(f"/assessments/{aid}/review/2").text
    assert 'enctype="multipart/form-data"' in h, "서류를 올릴 자리가 없다"
    assert f"/items/" in h and "/document" in h


def test_an_unknown_item_is_404(run):
    _, aid, _ = run
    with TestClient(app) as c:
        r = c.post(f"/assessments/{aid}/items/없는열쇠/document",
                   files={"file": ("a.txt", DOC, "text/plain")})
    assert r.status_code == 404
