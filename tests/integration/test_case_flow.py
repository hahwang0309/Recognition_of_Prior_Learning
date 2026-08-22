"""보고서 중심 흐름 종단 시험.

접수번호를 누르면 감사 화면(파일 목록)이 열리던 것을 심사 개요로 바꿨다.
그 흐름이 다시 어긋나지 않게 여기서 잡는다.

  접수 → (자동) 시간 대조 → 심사 개요 → ① 시간 대조 보고서
       → (자료가 있으면) 근거 분석 → ② 근거 분석 보고서 → ③ 검토
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from krpl_core.db import session_scope
from services.assess.case_state import TIME_DOC_TYPES, case_state
from services.assess.track_a_service import run_track_a
from services.gateway.api import app

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
            except FileNotFoundError as e:
                pytest.skip(f"실사례 원본 없음: {e}")


@pytest.fixture(scope="module")
def sid():
    with session_scope() as s:
        v = s.execute(text("SELECT id FROM submission WHERE case_number=:c"),
                      {"c": CASE}).scalar()
    if v is None:
        pytest.skip("실사례 없음")
    return v


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ── 시간 대조 ────────────────────────────────────────────────────

def test_time_comparison_runs_without_a_qualification(sid):
    """과정평가형 자격이 없어도 훈련 이수 기록으로 돈다.

    예전에는 자격이 있을 때만 돌았다. 접수 4건 모두 자격이 없어 한 건도
    돌지 않았고, 그래서 눌러 볼 보고서 자체가 없었다.
    """
    with session_scope() as s:
        n_qual = s.execute(text("""SELECT count(*) FROM document
            WHERE submission_id=:i AND doc_type='과정평가형자격'"""), {"i": sid}).scalar_one()
        aid = run_track_a(s, sid)
        st = case_state(s, sid)

    assert n_qual == 0, "이 사례는 자격이 없어야 시험의 뜻이 산다"
    assert aid and st.time and st.time.done
    assert st.time.note["근거"]["기이수"] > 0, "훈련 이수 기록이 근거로 잡혀야 한다"
    assert st.credited_hours > 0
    assert st.credited_hours + st.open_hours == st.total_hours


def test_time_comparison_is_reproducible(sid):
    """같은 서류면 몇 번을 돌려도 같은 값이다. 판단이 들어가지 않는다."""
    runs = []
    for _ in range(3):
        with session_scope() as s:
            run_track_a(s, sid)
            st = case_state(s, sid)
            runs.append((st.credited_hours, st.open_hours, len(st.skipped)))
    assert len(set(runs)) == 1, f"실행마다 값이 달라졌다: {runs}"


def test_rerun_leaves_one_time_assessment(sid):
    """다시 돌리면 이전 것은 지운다 — 어느 것이 최신인지 헷갈릴 행을 남기지 않는다."""
    with session_scope() as s:
        run_track_a(s, sid)
        run_track_a(s, sid)
        n = s.execute(text("""SELECT count(*) FROM assessment
            WHERE submission_id=:i AND kind='time'"""), {"i": sid}).scalar_one()
        n_ev = s.execute(text("""SELECT count(*) FROM assessment
            WHERE submission_id=:i AND kind='evidence'"""), {"i": sid}).scalar_one()
    assert n == 1
    assert n_ev >= 1, "근거 분석은 건드리지 않아야 한다"


def test_unusable_records_carry_a_reason():
    """「0시간」만 보여 주면 안 낸 것인지 안 쳐 준 것인지 알 수 없다.

    제빵 사례는 편성표만 냈다 — 능력단위는 적혀 있으나 이수시간도 평가결과도 없다.
    """
    with session_scope() as s:
        sid2 = s.execute(text("SELECT id FROM submission WHERE case_number='R2026-0001'")).scalar()
        if sid2 is None:
            pytest.skip("제빵 사례 없음")
        run_track_a(s, sid2)
        st = case_state(s, sid2)
    assert st.credited_hours == 0
    assert st.skipped, "갈음되지 않은 단위가 이유와 함께 남아야 한다"
    assert all(x["reason"] for x in st.skipped)


# ── 화면 ─────────────────────────────────────────────────────────

def test_case_number_opens_the_overview(client, sid):
    """접수번호 → 심사 개요. 감사 화면이 아니다."""
    h = client.get("/cases").text
    assert f'href="/submissions/{sid}"' in h, "목록의 접수번호가 개요로 가지 않는다"
    assert f'href="/audit/{CASE}"><b>' not in h, "접수번호가 아직 감사 화면으로 간다"

    # 홈은 최근 5건만 보인다 — 이 건이 실려 있을 때만 확인한다
    home = client.get("/").text
    if CASE in home:
        assert f'href="/submissions/{sid}"' in home, "홈의 접수번호가 개요로 가지 않는다"

    h = client.get(f"/submissions/{sid}").text
    assert h.startswith("<!doctype html>") and CASE in h
    for step in ("시간 대조", "근거 분석", "전문가 검토", "최종 판정"):
        assert step in h, f"개요에 「{step}」 단계가 없다"


def test_overview_links_to_both_reports(client, sid):
    """근거 분석 보고서 링크는 분석이 끝났을 때만 나온다 —
    아직 안 돈 건에 「보고서 보기」를 내밀면 눌러 봐야 404 다."""
    h = client.get(f"/submissions/{sid}").text
    assert f"/submissions/{sid}/report/time" in h
    with session_scope() as s:
        st = case_state(s, sid)
    if st.evidence_done:
        assert f"/submissions/{sid}/report/evidence" in h
    else:
        assert f"/submissions/{sid}/report/evidence" not in h
        assert "근거 분석 시작" in h or "해당 없음" in h or "진행 중" in h


def test_both_reports_render(client, sid):
    t = client.get(f"/submissions/{sid}/report/time")
    assert t.status_code == 200 and "RPL Track A 심사 보고서" in t.text
    ev = client.get(f"/submissions/{sid}/report/evidence")
    with session_scope() as s:
        st = case_state(s, sid)
    if not st.evidence_done:
        assert ev.status_code == 404          # 아직 안 돌았다
        return
    assert ev.status_code == 200 and "RPL Track B 심사 보고서" in ev.text
    # 연구팀 확정 포맷의 세 장이 모두 있어야 한다
    for chap in ("Ⅰ. 히트맵", "Ⅱ. 보완계획", "Ⅲ. 능력단위요소별 판정 근거"):
        assert chap in ev.text, f"확정 포맷의 「{chap}」 이 빠졌다"
    # 보고서에서 검토로 가는 길이 있어야 한다 — 읽고 나서 판단한다
    assert "전문가 검토로" in ev.text


def test_reports_agree_on_hours(client, sid):
    """두 보고서가 같은 숫자를 말해야 한다. 각자 세면 반드시 어긋난다."""
    with session_scope() as s:
        st = case_state(s, sid)
    for path in (f"/submissions/{sid}", f"/submissions/{sid}/report/time"):
        assert f"{st.total_hours}시간" in client.get(path).text


def test_reports_use_names_not_codes(client, sid):
    """이름은 기준에 있는 값이다. AI 가 받아 적어 준 것에 기대면 코드만 뜬다."""
    r = client.get(f"/submissions/{sid}/report/evidence")
    if r.status_code == 404:
        pytest.skip("근거 분석 결과 없음")
    h = r.text
    with session_scope() as s:
        names = [r[0] for r in s.execute(text("""
            SELECT DISTINCT e.element_name FROM catalog_ncs_element e
            JOIN assessment_element ae ON ae.element_id = e.element_id
            JOIN assessment a ON a.id = ae.assessment_id
            WHERE a.submission_id=:i AND a.kind='evidence' LIMIT 5"""), {"i": sid})]
    assert names, "대조할 요소명을 못 찾음"
    assert any(n in h for n in names), f"보고서에 요소 이름이 없다: {names}"


def test_reports_avoid_internal_jargon(client, sid):
    """Track A·B 는 연구팀 확정 포맷의 제목이므로 그대로 둔다.
    걸러야 할 것은 코드 안쪽 이름(payload 키·함수명)이 화면에 새는 것이다."""
    for path in ("/report/time", "/report/evidence"):
        r = client.get(f"/submissions/{sid}{path}")
        if r.status_code == 404:
            continue
        h = r.text
        for bad in ("track_a", "track_b", "needs_expert_review", "decided_by",
                    "uncovered_ksa", "qualitative_note", "HILM", "submission_id"):
            assert bad not in h, f"{path} 에 내부 이름 노출: {bad}"


def test_decision_words_carry_their_meaning(client):
    """버튼 넷이 무슨 뜻인지 화면이 말해야 한다. 그것이 없어서 판단이 어려웠다."""
    from krpl_core.config import get_rubric
    means = get_rubric().final_decision.get("element_decision_meanings") or {}
    assert set(means) == set(get_rubric().final_decision["element_decisions"])

    with session_scope() as s:
        aid = s.execute(text("""SELECT a.id FROM assessment a JOIN submission s
            ON s.id=a.submission_id WHERE s.case_number=:c AND a.kind='evidence'
            ORDER BY a.id DESC LIMIT 1"""), {"c": CASE}).scalar()
    if aid is None:
        pytest.skip("근거 분석 결과 없음")
    h = client.get(f"/assessments/{aid}/review").text
    for word, meaning in means.items():
        assert word in h and meaning in h, f"검토 화면에 「{word}」 의 뜻이 없다"


# ── 근거 분석을 시작할 수 있는가 ──────────────────────────────────

def test_no_false_failure_notice(client, sid):
    """실패하지 않았는데 「끝나지 못했습니다」라고 적으면 안 된다.

    evidence 와 evidence_done 은 서로 다른 조회에서 오므로 같은 판정이라도
    객체가 다르다. `is not` 로 비교했더니 멀쩡한 건마다 실패 문구가 붙었다.
    """
    with session_scope() as s:
        st = case_state(s, sid)
        if not st.evidence_done:
            pytest.skip("근거 분석 결과 없음")
        stale = st.evidence is not None and st.evidence.id != st.evidence_done.id
    h = client.get(f"/submissions/{sid}").text
    if not stale:
        assert "끝나지 못했습니다" not in h, "실패하지 않았는데 실패했다고 적혀 있다"


def test_finished_report_survives_a_rerun(client, sid):
    """새 분석이 도는 중이라도 이미 나온 보고서는 계속 열려야 한다."""
    with session_scope() as s:
        st = case_state(s, sid)
        if not st.evidence_done:
            pytest.skip("근거 분석 결과 없음")
        aid = st.evidence_done.id
        # 뒤이어 실행 하나가 도는 상황을 만든다
        s.execute(text("""INSERT INTO assessment
            (submission_id, kind, status, rubric_version, model, attempts, started_at)
            VALUES (:i,'evidence','running','v0.2','test',0, now())"""), {"i": sid})
    try:
        with session_scope() as s:
            st2 = case_state(s, sid)
        assert st2.analyzing, "도는 중으로 잡혀야 한다"
        assert st2.evidence_done and st2.evidence_done.id == aid, "지난 결과를 잃었다"
        assert client.get(f"/submissions/{sid}/report/evidence").status_code == 200
        assert f"/submissions/{sid}/report/evidence" in client.get(f"/submissions/{sid}").text
    finally:
        with session_scope() as s:
            s.execute(text("""DELETE FROM assessment
                WHERE submission_id=:i AND kind='evidence' AND model='test'"""), {"i": sid})


def test_analysis_offered_only_when_there_is_material(sid):
    with session_scope() as s:
        st = case_state(s, sid)
    assert st.can_analyze, "경력·수행 자료가 있으면 분석을 권해야 한다"
    assert all(d["doc_type"] not in TIME_DOC_TYPES for d in st.extra_docs), \
        "이수 증빙은 「추가 자료」로 세지 않는다 — 시간 대조가 이미 썼다"


def test_analyze_redirects_back_to_the_overview(client, sid):
    """화면에서 온 요청이므로 JSON 을 띄우지 않고 개요로 돌려보낸다."""
    r = client.post(f"/submissions/{sid}/analyze", follow_redirects=False)
    assert r.status_code == 303, r.text
    assert r.headers["location"].endswith(f"/submissions/{sid}")


def test_missing_case_is_404(client):
    assert client.get("/submissions/99999999").status_code == 404
    assert client.get("/submissions/99999999/report/time").status_code == 404
