"""보고서 중심 흐름 종단 시험.

접수번호를 누르면 감사 화면(파일 목록)이 열리던 것을 심사 개요로 바꿨다.
그 흐름이 다시 어긋나지 않게 여기서 잡는다.

  접수 → (자동) 기록 확인 → 심사 개요 → ① 기록 확인 보고서
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


# ── 기록 확인 ────────────────────────────────────────────────────

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
    for step in ("기록 확인", "근거 분석", "전문가 검토", "최종 판정"):
        assert step in h, f"개요에 「{step}」 단계가 없다"


def test_overview_links_to_both_reports(client, sid):
    """근거 분석 링크는 **볼 수 있는 결과가 있을 때** 나온다.

    예전에는 「검증까지 통과한 판정(done)」일 때만 내밀었다. 그런데 검증을 다
    통과하지 못한 실행(manual_review)도 판단한 항목은 남아 있다. 그것을 볼 길을
    막아 두면 위원이 결과를 보려고 「다시 시도」를 누르고, 그때마다 AI 실호출이
    나간다 — 실제로 한 건에서 $0.81 이 더 나갔다.
    """
    h = client.get(f"/submissions/{sid}").text
    assert f"/submissions/{sid}/report/time" in h
    with session_scope() as s:
        usable = s.execute(text("""SELECT count(*) FROM assessment a
            WHERE a.submission_id=:i AND a.kind='evidence'
              AND a.status IN ('done','manual_review')
              AND EXISTS (SELECT 1 FROM assessment_element e WHERE e.assessment_id=a.id)"""),
            {"i": sid}).scalar_one()
    if usable:
        assert f"/submissions/{sid}/report/evidence" in h, "볼 수 있는 결과인데 들어갈 길이 없다"
    else:
        assert f"/submissions/{sid}/report/evidence" not in h
        assert "근거 분석 시작" in h or "해당 없음" in h or "진행 중" in h


def test_both_reports_render(client, sid):
    """확정 포맷 전체 보고서는 `/assessments/{aid}/report` 에 있다.

    `/submissions/{sid}/report/evidence` 는 「추가 인정이 필요한 단위를 문서별
    근거로 본다」에 집중한 화면으로 따로 만들었다(2026-09-24). 회람본 그대로의
    세 장짜리 보고서는 옮겨 두었고, 여기서 그것을 확인한다.
    """
    t = client.get(f"/submissions/{sid}/report/time")
    assert t.status_code == 200 and "RPL Track A 심사 보고서" in t.text
    with session_scope() as s:
        st = case_state(s, sid)
        aid = s.execute(text("""SELECT a.id FROM assessment a
            WHERE a.submission_id=:i AND a.kind='evidence'
              AND a.status IN ('done','manual_review')
              AND EXISTS (SELECT 1 FROM assessment_element e WHERE e.assessment_id=a.id)
            ORDER BY a.id DESC LIMIT 1"""), {"i": sid}).scalar()
    if aid is None:
        assert client.get(f"/submissions/{sid}/report/evidence").status_code == 404
        assert not st.evidence_done           # 아직 볼 것이 없다
        return
    ev = client.get(f"/assessments/{aid}/report")
    assert ev.status_code == 200 and "RPL Track B 심사 보고서" in ev.text
    # 연구팀 확정 포맷의 세 장이 모두 있어야 한다
    for chap in ("Ⅰ. 히트맵", "Ⅱ. 보완계획", "Ⅲ. 능력단위요소별 판정 근거"):
        assert chap in ev.text, f"확정 포맷의 「{chap}」 이 빠졌다"
    # 회람본에서 단계 화면으로 돌아갈 길이 있어야 한다. 이름은 단계 이름으로 쓴다
    # (예전에는 「전문가 검토로」였는데 같은 곳을 화면마다 다르게 불렀다).
    assert "② 근거 분석" in ev.text


def test_evidence_report_opens_when_validation_was_exhausted(client, sid):
    """검증을 못 통과한 판정(manual_review)도 보고서로 열린다.

    3회 안에 통과하지 못해도 산출물은 저장한다 — 전문가가 볼 것이 아무것도
    없는 상태가 가장 나쁘기 때문이다. 그런데 보고서만 `status='done'` 을 찾아
    404 였다. 같은 판정을 위원 페이지(`/panel`)는 그려 주고 있었다.
    """
    with session_scope() as s:
        prev = [dict(r) for r in s.execute(text("""SELECT id, status FROM assessment
            WHERE submission_id=:i AND kind='evidence'"""), {"i": sid}).mappings()]
    if not any(r["status"] == "done" for r in prev):
        pytest.skip("근거 분석 결과 없음")
    try:
        with session_scope() as s:
            s.execute(text("""UPDATE assessment SET status='manual_review'
                WHERE submission_id=:i AND kind='evidence'"""), {"i": sid})
        r = client.get(f"/submissions/{sid}/report/evidence")
        assert r.status_code == 200, "검증 미통과 판정의 보고서가 열리지 않는다"
        assert "RPL Track B 심사 보고서" in r.text
    finally:
        with session_scope() as s:
            for r in prev:
                s.execute(text("UPDATE assessment SET status=:s WHERE id=:i"),
                          {"s": r["status"], "i": r["id"]})


def test_evidence_report_stays_404_without_any_result(client):
    """요소가 하나도 없는 실패(failed)는 그대로 404 다 — 그릴 것이 없다."""
    with session_scope() as s:
        sid2 = s.execute(text("SELECT id FROM submission WHERE case_number='R2026-0001'")).scalar()
        if sid2 is None:
            pytest.skip("제빵 사례 없음")
        prev = [dict(r) for r in s.execute(text("""SELECT id, status FROM assessment
            WHERE submission_id=:i AND kind='evidence'"""), {"i": sid2}).mappings()]
    try:
        with session_scope() as s:
            s.execute(text("""UPDATE assessment SET status='failed'
                WHERE submission_id=:i AND kind='evidence'"""), {"i": sid2})
        assert client.get(f"/submissions/{sid2}/report/evidence").status_code == 404
    finally:
        with session_scope() as s:
            for r in prev:
                s.execute(text("UPDATE assessment SET status=:s WHERE id=:i"),
                          {"s": r["status"], "i": r["id"]})


def test_reports_agree_on_hours(client, sid):
    """두 보고서가 같은 숫자를 말해야 한다. 각자 세면 반드시 어긋난다."""
    with session_scope() as s:
        st = case_state(s, sid)
    for path in (f"/submissions/{sid}", f"/submissions/{sid}/report/time"):
        assert f"{st.total_hours}시간" in client.get(path).text


def test_reports_use_names_not_codes(client, sid):
    """이름은 기준에 있는 값이다. AI 가 받아 적어 준 것에 기대면 코드만 뜬다."""
    with session_scope() as s:
        aid = s.execute(text("""SELECT a.id FROM assessment a
            WHERE a.submission_id=:i AND a.kind='evidence'
              AND a.status IN ('done','manual_review')
              AND EXISTS (SELECT 1 FROM assessment_element e WHERE e.assessment_id=a.id)
            ORDER BY a.id DESC LIMIT 1"""), {"i": sid}).scalar()
    if aid is None:
        pytest.skip("근거 분석 결과 없음")
    h = client.get(f"/assessments/{aid}/report").text
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
        "이수 증빙은 「추가 자료」로 세지 않는다 — 기록 확인이 이미 썼다"


def test_analyze_redirects_back_to_the_overview(client, sid):
    """화면에서 온 요청이므로 JSON 을 띄우지 않고 개요로 돌려보낸다."""
    r = client.post(f"/submissions/{sid}/analyze", follow_redirects=False)
    assert r.status_code == 303, r.text
    assert r.headers["location"].endswith(f"/submissions/{sid}")


def test_missing_case_is_404(client):
    assert client.get("/submissions/99999999").status_code == 404
    assert client.get("/submissions/99999999/report/time").status_code == 404


def test_review_counts_only_what_needs_judgment(client, sid):
    """보고서는 요소를 다 싣지만, 검토로 넘어가는 것은 그중 판단할 것뿐이다.

    훈련이수증으로 확정된 항목까지 한 줄씩 누르게 하면 정작 따져야 할 것에
    쓸 힘이 흩어진다. 개요와 검토 화면이 같은 수를 말해야 한다.
    """
    with session_scope() as s:
        st = case_state(s, sid)
        if not st.evidence_done:
            pytest.skip("근거 분석 결과 없음")
    assert st.n_judge + st.n_settled == st.n_elements
    assert st.review_left == st.n_judge - st.judged

    overview = client.get(f"/submissions/{sid}").text
    review = client.get(f"/assessments/{st.evidence_done.id}/review").text
    if st.n_settled:
        # 두 화면이 같은 수를 말해야 한다
        assert f"{st.n_settled}개" in overview
        assert f"{st.n_settled}개" in review
    assert f"{st.n_judge}개" in review


# ── 면접 질문지·실기 과제는 어디 있나 ────────────────────────────

def test_the_overview_names_the_five_stages(client, sid):
    """「검토하기」 링크 하나뿐이면 면접 질문지와 실기 과제 목록이 어디
    있는지 알 수 없다 — 실제로 그 질문을 받았다."""
    h = client.get(f"/submissions/{sid}").text
    st_ = None
    with session_scope() as s:
        st_ = case_state(s, sid)
    if not st_.evidence_done:
        pytest.skip("근거 분석 결과 없음")
    assert '<div class="slinks">' in h, "다섯 단계로 가는 줄이 없다"
    aid = st_.evidence_done.id
    for n in range(1, 6):
        assert f'href="/assessments/{aid}/review/{n}"' in h, f"{n}단계로 가는 길이 없다"
    assert "면접 질문지" in h and "실기 과제" in h


def test_the_gauge_says_where_the_hours_stand(client, sid):
    """기록 확인만 읽어 「아직 확인되지 않은 시간」이 검토 뒤에도 그대로였다."""
    h = client.get(f"/submissions/{sid}").text
    with session_scope() as s:
        st_ = case_state(s, sid)
    if st_.decision and st_.decision.get("recognized_hours") is not None:
        # 판정이 나면 막대는 그것을 따른다 — 아래 시험이 따로 본다
        pytest.skip("최종 판정이 이미 났다")
    if st_.split is None:
        assert "기록으로 확인된 시간" in h
    else:
        assert f"지금까지 인정 <b>{st_.recognized_hours}</b>시간" in h
        assert f"아직 확인되지 않은 시간 <b>{st_.unresolved_hours}</b>시간" in h
        assert st_.recognized_hours + st_.unresolved_hours == st_.total_hours


def test_the_screens_say_기록_확인_not_시간_대조(client, sid):
    """「시간 대조」는 무엇을 대조하는지 모르는 말이었다."""
    for url in (f"/submissions/{sid}", "/"):
        h = client.get(url).text
        assert "시간 대조" not in h, url


def test_the_gauge_defers_to_the_recorded_decision(client, sid):
    """막대는 370시간, ④ 칸은 300시간이라 말한 적이 있다.
    최종 판정이 났으면 그것이 답이고, 계산과 다르면 그 차이를 적는다."""
    with session_scope() as s:
        st_ = case_state(s, sid)
    h = client.get(f"/submissions/{sid}").text
    if not st_.decision or st_.decision.get("recognized_hours") is None:
        pytest.skip("최종 판정이 없다")
    got = st_.decision["recognized_hours"]
    assert f"인정 <b>{got}</b>시간" in h
    if st_.split and st_.split.credited != got:
        assert "심사위원이" in h and "정했습니다" in h


def test_the_cost_covers_every_run(client, sid):
    """재판정한 건은 마지막 실행분만 보이면 실제보다 싸 보인다
    (실측 R2026-9010: $0.60 로 보였지만 처음 판정까지 합치면 $3.25)."""
    with session_scope() as s:
        st_ = case_state(s, sid)
    if not st_.evidence_done:
        pytest.skip("근거 분석 결과 없음")
    assert st_.runs_attempts >= st_.evidence_done.attempts
    assert st_.runs_cost >= (st_.evidence_done.cost or 0)
    h = client.get(f"/submissions/{sid}").text
    assert f"호출 {st_.runs_attempts}회" in h
    if st_.n_runs > 1:
        assert f"판정 {st_.n_runs}회" in h


def test_the_case_list_counts_the_same_things_as_the_overview(client, sid):
    """목록은 요소 전체로 세고 개요는 판단 대상으로 세면, 다 끝낸 건이
    목록에서는 「22/30」으로 남아 보인다."""
    with session_scope() as s:
        st_ = case_state(s, sid)
    if not st_.n_judge:
        pytest.skip("판단 대상이 없다")
    h = client.get("/cases").text
    i = h.find(st_.case_number)
    assert i >= 0
    row = h[i:i + 1200]
    assert f"검토 {st_.judged}/{st_.n_judge}" in row, "목록이 개요와 다르게 센다"
    assert f"/{st_.n_elements}<" not in row


def test_every_screen_says_which_track_was_received(client, sid):
    """접수부터 결과까지 어느 트랙으로 접수됐는지 알 수 있어야 한다.

    「Track A/B」가 이 앱에서 두 가지를 가리킨다 — 접수 구분(submission.track)과
    판정 종류(assessment.kind). 보고서 제목은 판정 종류이고 연구팀 확정 포맷이라
    고칠 수 없으므로, 접수 구분은 배지로 따로 적는다. 실제로 A 로 접수한 건에서
    Track B 보고서를 보고 「내가 A 로 한 것 맞나」를 확인할 길이 없었다.
    """
    with session_scope() as s:
        track = s.execute(text("SELECT track FROM submission WHERE id=:i"),
                          {"i": sid}).scalar_one()
    from services.report._shared import TRACK
    short = TRACK[track][0]

    for path in ("/", "/cases", f"/submissions/{sid}", f"/submissions/{sid}/upload"):
        h = client.get(path).text
        if path == "/" and CASE not in h:
            continue                      # 홈은 최근 5건만 싣는다
        assert 'class="trk' in h, f"{path} 에 접수 구분 배지가 없다"
        assert short in h, f"{path} 의 배지가 접수 구분({track})과 다르다"


def test_the_reports_separate_the_two_meanings_of_track(client, sid):
    """보고서 제목의 Track 은 판정 종류다. 접수 구분은 따로 적는다."""
    with session_scope() as s:
        track = s.execute(text("SELECT track FROM submission WHERE id=:i"),
                          {"i": sid}).scalar_one()
        aid = s.execute(text("""SELECT id FROM assessment WHERE submission_id=:i
                                AND kind='time' ORDER BY id DESC LIMIT 1"""),
                        {"i": sid}).scalar()
    if aid is None:
        pytest.skip("기록 확인 판정 없음")
    from services.report._shared import TRACK
    h = client.get(f"/assessments/{aid}/review").text
    assert "RPL Track A 심사 보고서" in h, "확정 포맷의 제목은 그대로여야 한다"
    assert "이 건의 접수 구분" in h
    assert TRACK[track][0] in h
    assert "판정 종류" in h, "제목의 Track 이 무엇을 뜻하는지 밝혀야 한다"


def test_a_run_that_failed_validation_is_still_reachable(client, sid):
    """검증을 못 통과한 실행도 개요에서 바로 열 수 있어야 한다.

    막아 두면 결과를 보려고 「다시 시도」를 누르게 되고, 그것은 유료 재호출이다.
    """
    with session_scope() as s:
        rows = [dict(r) for r in s.execute(text("""SELECT id, status FROM assessment
            WHERE submission_id=:i AND kind='evidence'"""), {"i": sid}).mappings()]
    if not rows:
        pytest.skip("근거 분석 판정 없음")
    try:
        with session_scope() as s:
            s.execute(text("""UPDATE assessment SET status='manual_review'
                WHERE submission_id=:i AND kind='evidence'"""), {"i": sid})
        h = client.get(f"/submissions/{sid}").text
        assert f"/submissions/{sid}/report/evidence" in h, "볼 길이 없다"
        assert "결과는 그대로 보실 수 있습니다" in h
        assert client.get(f"/submissions/{sid}/report/evidence").status_code == 200
    finally:
        with session_scope() as s:
            for r in rows:
                s.execute(text("UPDATE assessment SET status=:s WHERE id=:i"),
                          {"s": r["status"], "i": r["id"]})


def test_the_overview_does_not_link_to_the_audit_trail(client, sid):
    """감사 기록은 감사 화면에서 한 번에 본다 — 개요에서 갈래를 늘리지 않는다."""
    h = client.get(f"/submissions/{sid}").text
    assert "/audit/" not in h, "개요에 감사 기록 링크가 남아 있다"
