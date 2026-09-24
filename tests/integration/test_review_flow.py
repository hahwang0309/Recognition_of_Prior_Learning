"""전문가 검토 다섯 단계 종단 시험.

  1 인정 여부 검토 → 2 추가 서류 → 3 면접 → 4 실기 → 5 최종

확인하는 것은 셋이다.
  ① 대시보드가 모든 단계에 붙고 단계마다 갱신되는가
  ② 면접·실기 질문지가 「질문 · 목적 · 응답에 담겨야 할 것」을 담는가
  ③ 인정 시간이 Track A 기록 확인과 어긋나지 않는가
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
from services.review import record_decision, save_element_review, save_result

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


def els_table(html: str) -> str:
    """요소별 근거 표만 잘라 낸다. 화면 전체에서 세면 원장 줄까지 걸린다."""
    i = html.find('<details class="els">')
    assert i >= 0, "요소 표가 없다"
    return html[i:]


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

@pytest.mark.parametrize("stage,method", [(2, "추가서류"), (3, "면접"), (4, "실기")])
def test_question_sheet_has_all_three_parts(client, aid, stage, method):
    """질문 · 질문의 목적 · 무엇이 확인되면 인정되나.

    부르는 말은 단계마다 다르다 — 서류를 받는 자리에 「응답」은 맞지 않는다.
    """
    from services.report.stage_view import COVER_TITLE
    with session_scope() as s:
        ctx = review_ctx(s, aid)
    if not ctx.items.get(method):
        pytest.skip(f"{method} 항목이 없다")
    h = client.get(f"/assessments/{aid}/review/{stage}").text
    assert "왜 이 방법인가" in h, "질문의 목적이 없다"
    assert COVER_TITLE[stage] in h, "무엇이 확인되면 인정되는지가 없다"
    assert "이것이 풀리면 인정되는 것" in h, "대상 요소가 없다"
    if any(i.oral_check for i in ctx.items[method]):
        assert re.search(r'<ol class="qs">', h), "질문 목록이 없다"


def test_cover_title_fits_the_stage():
    """서류를 받는 자리에 「응답에 담겨야 할 것」이라 쓰면 안 된다."""
    from services.report.stage_view import COVER_TITLE
    assert "응답" not in COVER_TITLE[2] and "서류" in COVER_TITLE[2]
    assert "응답" in COVER_TITLE[3]
    assert "실기" in COVER_TITLE[4]


def test_waiting_rows_point_at_the_stage_that_resolves_them(clean, client):
    """「아직 판단하지 않았습니다」만 보고는 어느 단계로 가야 할지 알 수 없다."""
    aid = clean
    h = client.get(f"/assessments/{aid}/review/5").text
    with session_scope() as s:
        ctx = review_ctx(s, aid)
    n_wait = sum(1 for v in ctx.outcome_of.values() if v == "대기")
    assert n_wait, "대기가 없어 시험의 뜻이 없다"
    assert els_table(h).count("단계에서 정하기") == n_wait
    # 아직 아무것도 안 정했으므로 전부 1단계를 가리켜야 한다
    assert els_table(h).count("1단계에서 정하기") == n_wait


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
    """1단계에서 권고대로만 찍으면 인정 시간이 Track A 기록 확인과 같아야 한다.

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
        pytest.skip("기록 확인 결과 없음")
    hours = json.loads(note)["hours"]
    from_time = hours["완전충족"] + hours["조정범위내"]

    with session_scope() as s:
        got, tot = review_ctx(s, aid).recognized_hours()
    assert got == from_time, f"검토 {got}시간 vs 기록 확인 {from_time}시간"


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


# ── 무엇을 고르는 자리인가 ────────────────────────────────────────

def test_the_second_stage_has_no_buttons_at_all(client, aid):
    """「파일 올리면 받은 거고 아니면 못 받은 건데 왜 일일이 체크하나」 —
    맞는 말이다. 2단계에서 사람이 하는 일은 파일을 올리는 것뿐이다."""
    from services.report.stage_view import CHOICES
    assert CHOICES[2] == []
    h = client.get(f"/assessments/{aid}/review/2").text
    assert 'onclick="mark(this)"' not in h, "2단계에 아직 결과 버튼이 있다"
    assert 'enctype="multipart/form-data"' in h, "서류를 올릴 자리가 없다"


def test_the_face_to_face_stages_have_one_button(client, aid):
    """통과 여부만 알면 된다. 버튼은 하나면 된다."""
    from services.report.stage_view import CHOICES
    for stage in (3, 4):
        assert [c[0] for c in CHOICES[stage]] == ["통과"], stage
        h = client.get(f"/assessments/{aid}/review/{stage}").text
        assert 'data-r="미통과"' not in h and 'data-r="미실시"' not in h, stage


def test_every_choice_says_what_happens_next(client, aid):
    from services.report.stage_view import CHOICES
    for stage in (3, 4):
        assert all(c[2] for c in CHOICES[stage]), stage
        assert any("인정됩니다" in c[2] for c in CHOICES[stage]), stage


def test_a_result_that_is_not_a_pass_is_shown_as_a_state(client, aid):
    """버튼이 하나뿐이어도 「미통과」로 기록된 것은 보여야 한다."""
    from services.review.stages import Item
    from services.report.stage_view import _item_card
    with session_scope() as s:
        ctx = review_ctx(s, aid)
    it = Item(key="k", method="면접", item="어떤 확인", result="미통과",
              note="마감 시점까지 통과로 표시되지 않음",
              targets=[{"eid": ctx.elements[0]["element_id"], "unit_code": "u",
                        "unit": "단위", "element": "요소", "ksa": []}])
    h = _item_card(it, ctx, 3)
    assert "미통과" in h and "마감 시점까지" in h
    assert 'data-r="미통과"' not in h, "미통과를 고르는 버튼은 없어야 한다"


def test_a_saved_pass_comes_back_marked(clean, client):
    aid = clean
    with session_scope() as s:
        ctx = review_ctx(s, aid)
    it = next((i for m in ("면접", "실기") for i in (ctx.items.get(m) or [])), None)
    if it is None:
        pytest.skip("면접·실기 항목이 없다")
    stage = 3 if it.method == "면접" else 4
    r = client.post(f"/assessments/{aid}/remediation", json={
        "key": it.key, "method": it.method, "item": it.item, "result": "통과"})
    assert r.status_code == 200, r.text
    h = client.get(f"/assessments/{aid}/review/{stage}").text
    card = h[h.index(f'data-k="{it.key}"'):]
    assert 'class="on" data-r="통과"' in card[:2500], "다시 열었더니 안 켜져 있다"


def test_the_screen_reacts_when_a_result_is_saved(client, aid):
    """하나를 찍으면 인정 시간도 히트맵도 달라진다. 그것이 안 보이면
    저장이 안 된 줄 안다 — 서버가 그린 그대로를 가져와 바꿔치기한다."""
    h = client.get(f"/assessments/{aid}/review/2").text
    assert "async function refresh()" in h
    assert "section.dash" in h and "'.steps'" in h and "'.bar3'" in h
    assert "refresh();" in h


def test_a_note_without_a_choice_says_so(client, aid):
    """결과를 안 고르고 비고만 적으면 아무 일도 일어나지 않았다."""
    h = client.get(f"/assessments/{aid}/review/2").text
    assert "결과를 먼저 고르십시오" in h


def test_an_item_that_cannot_change_anything_says_so(client, aid):
    """무엇을 눌러도 인정 시간이 안 움직이면 「저장이 안 된다」로 읽힌다.
    실측 R2026-9002 — 27개 요소가 모두 1단계에서 정해져 2단계를 아무리
    눌러도 숫자가 그대로였다."""
    from services.report.stage_view import _no_effect
    from services.review.stages import Item
    with session_scope() as s:
        ctx = review_ctx(s, aid)
    eid = ctx.elements[0]["element_id"]
    it = Item(key="k", method="추가서류", item="서류",
              targets=[{"eid": eid, "unit_code": "u", "unit": "단위",
                        "element": "요소", "ksa": []}])
    got = ctx.outcome_of.get(eid)
    out = _no_effect(it, ctx)
    if got == "대기":
        assert out == "", "아직 정해지지 않았는데 소용없다고 말한다"
    else:
        assert "결과를 바꾸지 못합니다" in out
        assert "조건부인정" in out, "되돌리는 길을 알려 주지 않는다"


def test_the_final_record_carries_the_number_the_screen_showed(clean, client):
    """5단계 화면은 370시간, 판정 기록은 「확정 150 · 조건부 350」이었다.
    감사에서 어느 쪽을 근거로 볼지 알 수 없다 — 같은 값이어야 한다."""
    aid = clean
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        for x in ctx.judge_pool:
            save_element_review(s, aid, x["element_id"], "인정", reviewer="시험")
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        got, tot = ctx.recognized_hours()
        r = record_decision(s, aid, "부분인정", decided_by="시험")
    assert r["recognized_hours"] == got, "판정 기록이 화면과 다른 값을 적었다"
    b = r["credit_basis"]["검토결과"]
    assert b and b["인정시간"] == got and b["총시간"] == tot
    assert "단계" in b and "요소" in b


def test_the_record_flags_credited_units_whose_elements_were_denied(clean, client):
    """기록으로 시간은 갈음됐는데 요소는 미인정인 단위를 조용히 넘기면
    안 된다 — 실측 R2026-9010 에서 70시간이 그랬다."""
    aid = clean
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        for x in ctx.judge_pool:
            save_element_review(s, aid, x["element_id"], "불인정", reviewer="시험")
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        clash = ctx.credited_but_denied()
        r = record_decision(s, aid, "부분인정", decided_by="시험")
    assert r["credit_basis"]["검토결과"]["갈음됐으나_요소미인정"] == clash
    h = client.get(f"/assessments/{aid}/review/5").text
    if clash:
        assert "기록으로 시간은 갈음됐으나" in h, "화면이 말해 주지 않는다"


def test_the_final_table_survives_the_clash_warning(clean, client):
    """경고를 담을 변수를 표 변수와 같은 이름으로 썼더니 요소 표가 통째로
    사라졌다. 경고가 있어도 표는 남아야 한다."""
    aid = clean
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        for x in ctx.judge_pool:
            save_element_review(s, aid, x["element_id"], "불인정", reviewer="시험")
        n = len(ctx.elements)
    h = client.get(f"/assessments/{aid}/review/5").text
    assert els_table(h).count('<td><span class="tag2') == n, "요소 표가 사라졌다"


def test_the_decision_is_recorded_on_the_final_stage(client, aid):
    """판정 입력이 두 화면에 있으면 숫자가 갈라진다 — 옛 검토 화면은 1단계
    판단만 세어 같은 건에 350시간이라고 적었다(5단계는 370시간)."""
    h5 = client.get(f"/assessments/{aid}/review/5").text
    assert 'id="decide"' in h5 and 'id="dsave"' in h5, "5단계에 판정 입력이 없다"
    old = client.get(f"/assessments/{aid}/review").text
    assert 'id="save"' not in old, "옛 화면에 아직 판정 입력이 남아 있다"
    assert f'/assessments/{aid}/review/5#decide' in old, "5단계로 가는 길이 없다"


def test_the_final_stage_seeds_the_hours_from_the_ledger(client, aid):
    """계산값이 미리 들어가 있어야 한다 — 사람이 바꾸면 그 차이가 남는다."""
    from services.review.ledger import build
    with session_scope() as s:
        lg = build(review_ctx(s, aid))
    h = client.get(f"/assessments/{aid}/review/5").text
    assert f'max="{lg.total_hours}"' in h
    assert "계산값 <b>" in h and f"{lg.recognized_hours}시간</b>" in h


# ── 판정 이력 ─────────────────────────────────────────────────────

def test_each_decision_keeps_its_own_evidence(clean, client):
    """다시 기록하면 앞선 판정의 근거가 덮여 사라졌다 — 「370시간으로 정했다가
    300시간으로 바꿨다」는 사실만 남고 왜 그랬는지는 알 수 없었다."""
    aid = clean
    with session_scope() as s:
        sid = review_ctx(s, aid).submission_id
        s.execute(text("DELETE FROM audit_log WHERE entity='final_decision' "
                       "AND entity_id=:i"), {"i": str(sid)})
        s.execute(text("DELETE FROM artifact WHERE submission_id=:i AND stage='decide'"),
                  {"i": sid})
        ctx = review_ctx(s, aid)
        for x in ctx.judge_pool:
            save_element_review(s, aid, x["element_id"], "인정", reviewer="시험")
    for h in (100, 200):
        with session_scope() as s:
            record_decision(s, aid, "부분인정", reason=f"{h}시간", decided_by="시험",
                            recognized_hours=h)
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        names = [r[0] for r in s.execute(text("""
            SELECT name FROM artifact WHERE submission_id=:i AND stage='decide'
            ORDER BY id"""), {"i": ctx.submission_id})]
    assert names == ["최종판정_1회", "최종판정_2회"], names
    log = ctx.decision_log
    assert [x["n"] for x in log] == [2, 1], "새것이 앞에 와야 한다"
    assert [x["hours"] for x in log] == [200, 100], "그때 정한 시간이 남아야 한다"
    assert all(x["artifact"] for x in log), "회차마다 근거가 붙어야 한다"


def test_the_screen_shows_the_decision_history(clean, client):
    aid = clean
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        for x in ctx.judge_pool:
            save_element_review(s, aid, x["element_id"], "인정", reviewer="시험")
    with session_scope() as s:
        record_decision(s, aid, "부분인정", reason="a", decided_by="시험",
                        recognized_hours=7)
    h = client.get(f"/assessments/{aid}/review/5").text
    assert "판정 이력" in h and "7시간" in h
    assert "계산값" in h, "덮어쓴 값과 계산값의 차이를 적어야 한다"


def test_it_warns_when_results_changed_after_the_decision(clean, client):
    """판정 뒤 면접·실기 결과가 들어오면 낡은 판정이 그대로 남는다."""
    aid = clean
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        for x in ctx.judge_pool:
            save_element_review(s, aid, x["element_id"], "조건부인정", reviewer="시험")
    with session_scope() as s:
        record_decision(s, aid, "부분인정", reason="a", decided_by="시험")
    with session_scope() as s:
        ctx = review_ctx(s, aid)
        assert ctx.changed_after_decision is None, "아직 안 바뀌었는데 바뀌었다고 한다"
        it = next((i for g in ctx.items.values() for i in g), None)
        if it is None:
            pytest.skip("보완 항목이 없다")
        save_result(s, aid, it.key, it.method, it.item, "통과", reviewer="시험")
    with session_scope() as s:
        assert review_ctx(s, aid).changed_after_decision is not None
    h = client.get(f"/assessments/{aid}/review/5").text
    assert "판정 뒤에 검토 결과가 바뀌었습니다" in h


def test_the_final_stage_prints_as_a_signable_sheet(client, aid):
    """심사위원이 들고 앉아 서명하는 종이. 누르는 것은 종이에서 쓸모가 없다."""
    h = client.get(f"/assessments/{aid}/review/5").text
    css = h[:h.index("</style>")]
    assert "@page" in css, "인쇄 여백이 없다"
    for gone in (".decide button", ".src", ".steps", ".bar3"):
        assert gone in css, f"{gone} 을 인쇄에서 감추지 않는다"
    assert "signrow" in h, "서명란이 없다"
    assert "break-inside:avoid" in css, "표가 쪽 사이에서 잘린다"
    assert "thead{display:table-header-group}" in css, "쪽을 넘기면 머리행이 사라진다"
