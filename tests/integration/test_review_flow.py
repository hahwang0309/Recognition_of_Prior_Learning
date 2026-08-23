"""전문가 검토 다섯 단계 종단 시험.

  1 인정 여부 검토 → 2 추가 서류 → 3 면접 → 4 실기 → 5 최종

확인하는 것은 셋이다.
  ① 대시보드가 모든 단계에 붙고 단계마다 갱신되는가
  ② 면접·실기 질문지가 「질문 · 목적 · 응답에 담겨야 할 것」을 담는가
  ③ 인정 시간이 Track A 시간 대조와 어긋나지 않는가
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from krpl_core.db import session_scope
from services.gateway.api import app
from services.review import load as review_ctx
from services.review import save_element_review, save_result

CASE = "R2026-0002"
# 권고를 그대로 따라 찍는다 — 사람이 어떻게 정하든 계산이 도는지만 본다
MAP = {"R0": "인정", "R1": "인정", "R2": "조건부인정",
       "R3": "조건부인정", "R4": "보류", "R5": "불인정"}


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
    """이 시험이 남긴 판단을 지운다. 다른 시험의 전제를 흔들지 않는다."""
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


# ── 화면 ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("stage", [1, 2, 3, 4, 5])
def test_every_stage_renders(client, aid, stage):
    r = client.get(f"/assessments/{aid}/review/{stage}")
    assert r.status_code == 200
    assert f"{stage}." in r.text


def test_out_of_range_stage_is_404(client, aid):
    for n in (0, 6, 99):
        assert client.get(f"/assessments/{aid}/review/{n}").status_code == 404


@pytest.mark.parametrize("stage", [1, 2, 3, 4, 5])
def test_dashboard_rides_along_on_every_stage(client, aid, stage):
    """종합 현황이 모든 단계에 붙어야 한다 — 통과를 찍어도 전체에서
    무슨 뜻인지 보이지 않으면 찍을 이유가 없다."""
    h = client.get(f"/assessments/{aid}/review/{stage}").text
    assert '<section class="dash">' in h
    assert '<table class="hm">' in h, "히트맵이 없다"
    assert re.search(r'<th class="rl">요소 \d+</th>', h), "히트맵 행이 없다"


def test_stage_bar_shows_where_you_are(client, aid):
    h = client.get(f"/assessments/{aid}/review/3").text
    assert '<div class="steps">' in h
    # 지금 단계는 링크가 아니라 그냥 글이어야 한다 — 자기 자신으로 가는 링크는 없다
    assert re.search(r'<span class="on"><b>3\. 면접</b>', h)
    assert f'href="/assessments/{aid}/review/1"' in h


# ── 질문지 ────────────────────────────────────────────────────────

@pytest.mark.parametrize("stage,method", [(3, "면접"), (4, "실기")])
def test_question_sheet_has_all_three_parts(client, aid, stage, method):
    """질문 · 질문의 목적 · 응답에 담겨야 할 주요 사항."""
    with session_scope() as s:
        ctx = review_ctx(s, aid)
    if not ctx.items.get(method):
        pytest.skip(f"{method} 항목이 없다")
    h = client.get(f"/assessments/{aid}/review/{stage}").text
    assert "왜 이 방법인가" in h, "질문의 목적이 없다"
    assert "응답에 담겨야 할 것" in h, "응답 필수 사항이 없다"
    assert "이것이 풀리면 인정되는 것" in h, "대상 요소가 없다"
    if any(i.oral_check for i in ctx.items[method]):
        assert re.search(r"<ol class=\"qs\">", h), "질문 목록이 없다"


def test_must_cover_uses_real_ksa_names(client, aid):
    """「지식1」이 아니라 「금속 재료에 관한 지식」이라고 적어야 한다."""
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        names = {v for v in ctx.ksa.values() if v}
    if not ctx.items.get("면접"):
        pytest.skip("면접 항목이 없다")
    h = client.get(f"/assessments/{aid}/review/3").text
    assert sum(1 for n in names if n in h) >= 3, "KSA 이름이 화면에 없다"


def test_merged_item_is_shown_once(client, aid):
    """같은 서류를 열다섯 번 확인하게 하지 않는다."""
    with session_scope() as s:
        ctx = review_ctx(s, aid)
    for method, stage in (("추가서류", 2), ("면접", 3), ("실기", 4)):
        group = ctx.items.get(method) or []
        if not group:
            continue
        h = client.get(f"/assessments/{aid}/review/{stage}").text
        assert h.count('<div class="item ') == len(group)
        spanning = [i for i in group if i.n_elements > 1]
        for it in spanning[:1]:
            assert f"요소 {it.n_elements}개" in h


# ── 흐름 ──────────────────────────────────────────────────────────

def test_walking_the_five_stages(clean, client):
    aid = clean
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        assert ctx.next_stage == 1
        pool = list(ctx.judge_pool)

    # 1단계 — 판단 대상에만 찍는다
    with session_scope() as s:
        for x in pool:
            save_element_review(s, aid, x["element_id"],
                                MAP[x["recommendation"]], reviewer="시험")
    with session_scope() as s:
        ctx = review_ctx(s, aid)
    assert ctx.n_judged == len(pool)
    assert ctx.states[0].complete
    # 묻지 않은 것(기록으로 확정)은 대기로 남으면 안 된다
    assert all(v != "대기" or ctx.reviews.get(k, {}).get("decision") == "보류"
               for k, v in ctx.outcome_of.items()
               if k not in {x["element_id"] for x in pool})

    # 2~4단계 — 항목에 결과를 찍는다
    for method in ("추가서류", "면접", "실기"):
        with session_scope() as s:
            ctx = review_ctx(s, aid)
            for it in ctx.items.get(method) or []:
                save_result(s, aid, it.key, it.method, it.item, "통과", reviewer="시험")
    with session_scope() as s:
        ctx = review_ctx(s, aid)
    assert ctx.next_stage == 5, "다 찍었는데 최종으로 가지 않는다"
    assert all(st.complete for st in ctx.states if st.n < 5)

    # 5단계 — 모든 요소가 이유를 달고 정해져 있어야 한다
    for o in ctx.outcomes:
        assert o.decision in ("인정", "미인정", "대기")
        assert o.basis and all(b.strip() for b in o.basis), o.element_id
    h = client.get(f"/assessments/{aid}/review/5").text
    assert "무엇 때문에" in h


def test_a_failed_item_denies_the_elements_it_covered(clean):
    aid = clean
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        for x in ctx.judge_pool:
            save_element_review(s, aid, x["element_id"],
                                MAP[x["recommendation"]], reviewer="시험")
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        group = ctx.items.get("면접") or []
        if not group:
            pytest.skip("면접 항목이 없다")
        target = max(group, key=lambda i: i.n_elements)
        covered = {t["eid"] for t in target.targets}
        save_result(s, aid, target.key, target.method, target.item,
                    "미통과", reviewer="시험")
    with session_scope() as s:
        got = review_ctx(s, aid).outcome_of
    assert all(got[e] == "미인정" for e in covered), "미통과인데 인정으로 남았다"


def test_recognized_hours_match_the_time_report(clean):
    """1단계에서 권고대로만 찍으면 인정 시간이 Track A 시간 대조와 같아야 한다.

    두 계산이 어긋나면 어느 쪽을 믿어야 할지 알 수 없다.
    """
    aid = clean
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        for x in ctx.judge_pool:
            save_element_review(s, aid, x["element_id"],
                                MAP[x["recommendation"]], reviewer="시험")
        sid = ctx.submission_id
        import json
        note = s.execute(text("""SELECT overall_note FROM assessment
            WHERE submission_id=:i AND kind='time' ORDER BY id DESC LIMIT 1"""),
            {"i": sid}).scalar()
    if not note:
        pytest.skip("시간 대조 결과 없음")
    hours = json.loads(note)["hours"]
    from_time = hours["완전충족"] + hours["조정범위내"]

    with session_scope() as s:
        got, tot = review_ctx(s, aid).recognized_hours()
    assert got == from_time, f"검토 {got}시간 vs 시간 대조 {from_time}시간"


def test_result_api_records_and_reports_back(clean, client):
    aid = clean
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        group = next((g for g in ctx.items.values() if g), [])
    if not group:
        pytest.skip("보완 항목이 없다")
    it = group[0]
    r = client.post(f"/assessments/{aid}/remediation", json={
        "key": it.key, "method": it.method, "item": it.item,
        "result": "통과", "reviewer": "시험"})
    assert r.status_code == 200
    d = r.json()
    assert d["key"] == it.key and d["result"] == "통과"
    assert d["total_hours"] > 0 and "시험" in d["stamp"]

    with session_scope() as s:
        row = s.execute(text("""SELECT result, decided_by FROM remediation_result
            WHERE assessment_id=:a AND item_key=:k"""),
            {"a": aid, "k": it.key}).one()
    assert row == ("통과", "시험")


def test_unknown_item_and_bad_result_are_refused(clean, client):
    aid = clean
    with session_scope() as s:
        group = next((g for g in review_ctx(s, aid).items.values() if g), [])
    if not group:
        pytest.skip("보완 항목이 없다")
    assert client.post(f"/assessments/{aid}/remediation", json={
        "key": "0" * 16, "method": "면접", "item": "x", "result": "통과"}).status_code == 404
    assert client.post(f"/assessments/{aid}/remediation", json={
        "key": group[0].key, "method": group[0].method, "item": group[0].item,
        "result": "합격"}).status_code == 422


def test_recording_a_result_leaves_an_audit_trail(clean, client):
    aid = clean
    with session_scope() as s:
        group = next((g for g in review_ctx(s, aid).items.values() if g), [])
    if not group:
        pytest.skip("보완 항목이 없다")
    before = _audit_count(aid)
    client.post(f"/assessments/{aid}/remediation", json={
        "key": group[0].key, "method": group[0].method, "item": group[0].item,
        "result": "미통과", "reviewer": "시험"})
    assert _audit_count(aid) == before + 1


def _audit_count(aid: int) -> int:
    with session_scope() as s:
        return s.execute(text("""SELECT count(*) FROM audit_log
            WHERE entity='assessment' AND entity_id=:i AND action='remediation'"""),
            {"i": str(aid)}).scalar_one()
