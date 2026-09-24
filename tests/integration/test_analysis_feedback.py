"""「근거 분석 시작」을 누른 뒤 무슨 일이 일어나는지 화면이 말해야 한다.

눌러도 버튼이 그대로였다. 워커가 집기 전에는 assessment 행이 없어서
화면이 큐를 보지 못했기 때문이다. 사용자는 아무 반응이 없다고 여기고
다시 눌렀고, 같은 작업이 두 건 쌓였다.

여기서 잡는 것은 넷이다.
  ① 눌렀다는 사실이 화면에 남는가 (큐 대기)
  ② 워커가 없으면 없다고 말하는가
  ③ 도는 동안 진행률이 스스로 갱신되는가
  ④ 끝났는데 쓸 수 없는 상태(manual_review·failed)를 감추지 않는가
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from krpl_core.db import session_scope
from services.assess.case_state import case_state
from services.gateway.api import app

CASE = "R2026-0002"
# 검증이 어긋난 모습 — 요소 27개 가운데 9개만 판단됨
_NOTE = ('{"validation": {"n_elements": 9, "n_expected": 27,'
         ' "by_code": {"element_\ub204\ub77d": 18}}}')


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
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def fresh():
    """근거 분석이 아직 없는 접수 건 하나. 시험이 끝나면 지운다."""
    case = "R2026-9080"
    with session_scope() as s:
        s.execute(text("DELETE FROM submission WHERE case_number=:c"), {"c": case})
        sid = s.execute(text("""
            INSERT INTO submission (case_number, track, target_program_id, status)
            VALUES (:c, 'B', '양식조리_L4', 'ingested') RETURNING id"""),
            {"c": case}).scalar_one()
        # 근거 분석에 쓸 자료가 있어야 「시작」이 나온다
        s.execute(text("""INSERT INTO document (submission_id, doc_key, doc_type, grade)
                          VALUES (:i, 'D01', '경력기술서·자기소개서', 'E')"""), {"i": sid})
    yield sid
    with session_scope() as s:
        s.execute(text("DELETE FROM job WHERE (payload->>'submission_id')::int = :i"),
                  {"i": sid})
        s.execute(text("DELETE FROM submission WHERE case_number=:c"), {"c": case})


def _touch_worker(minutes_ago: float = 0) -> None:
    """워커가 최근에 작업을 집은 흔적을 만든다."""
    with session_scope() as s:
        s.execute(text("""
            INSERT INTO job (kind, status, payload, locked_at, created_at)
            VALUES ('track_b', 'done', '{}'::jsonb, :t, now())"""),
            {"t": datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)})


def _clear_worker_marks() -> None:
    with session_scope() as s:
        s.execute(text("DELETE FROM job WHERE payload = '{}'::jsonb"))


# ── ① 눌렀다는 사실이 남는가 ──────────────────────────────────────

def test_pressing_start_shows_up_on_the_screen(client, fresh):
    """워커가 집기 전에도 「시작을 눌렀다」가 보여야 한다."""
    sid = fresh
    with session_scope() as s:
        assert not case_state(s, sid).analyzing

    client.post(f"/submissions/{sid}/analyze", follow_redirects=False)

    with session_scope() as s:
        st = case_state(s, sid)
    assert st.analyzing, "눌렀는데 화면이 모른다"
    assert st.waiting_in_queue and st.queued_at is not None

    h = client.get(f"/submissions/{sid}").text
    assert "근거 분석 시작</button>" not in h, "아직 시작 버튼이 그대로 있다"


def test_pressing_twice_queues_one_job(client, fresh):
    """반응이 없어 보이면 사람은 다시 누른다. 두 번 눌러도 한 건이어야 한다."""
    sid = fresh
    for _ in range(3):
        client.post(f"/submissions/{sid}/analyze", follow_redirects=False)
    with session_scope() as s:
        n = s.execute(text("""SELECT count(*) FROM job
            WHERE kind='track_b' AND status='queued'
              AND (payload->>'submission_id')::int = :i"""), {"i": sid}).scalar_one()
    assert n == 1, f"같은 작업이 {n}건 쌓였다"


# ── ② 워커가 없으면 말하는가 ──────────────────────────────────────

def test_a_fresh_job_is_not_called_stalled(client, fresh):
    """방금 넣은 작업에 「아무도 집어 가지 않습니다」라고 하면 안 된다.
    워커는 몇 초 간격으로 큐를 보고, 놀던 워커는 살아 있어도 최근에 집은
    흔적이 없어 죽은 것으로 보인다."""
    sid = fresh
    _clear_worker_marks()
    client.post(f"/submissions/{sid}/analyze", follow_redirects=False)
    with session_scope() as s:
        st = case_state(s, sid)
    assert st.waiting_in_queue and not st.stalled, "갓 넣었는데 멈췄다고 한다"
    h = client.get(f"/submissions/{sid}").text
    assert "워커가 돌고 있지 않습니다" not in h
    assert "차례를 기다리는 중" in h


def test_a_stalled_queue_says_so(client, fresh):
    """큐에 넣기만 하고 아무도 집지 않으면 영영 안 된다. 그렇다고 말해야 한다."""
    sid = fresh
    _clear_worker_marks()
    client.post(f"/submissions/{sid}/analyze", follow_redirects=False)
    # 넣은 지 한참 됐는데도 안 집혔을 때가 진짜 멈춘 것이다
    with session_scope() as s:
        s.execute(text("""UPDATE job SET created_at = now() - interval '10 minutes'
            WHERE kind='track_b' AND status='queued'
              AND (payload->>'submission_id')::int = :i"""), {"i": sid})
    with session_scope() as s:
        st = case_state(s, sid)
    if st.worker_ok:
        pytest.skip("이 환경에서는 워커가 살아 있다")
    assert st.stalled
    h = client.get(f"/submissions/{sid}").text
    assert "워커가 돌고 있지 않습니다" in h
    assert "dev.sh worker" in h, "무엇을 하라는지 말해야 한다"

    d = client.get(f"/submissions/{sid}/progress.json").json()
    assert d["stalled"] is True and not d["done"]


def test_a_live_worker_is_not_reported_as_stalled(client, fresh):
    sid = fresh
    _touch_worker(minutes_ago=1)
    try:
        client.post(f"/submissions/{sid}/analyze", follow_redirects=False)
        with session_scope() as s:
            st = case_state(s, sid)
        assert st.worker_ok and st.waiting_in_queue and not st.stalled
        h = client.get(f"/submissions/{sid}").text
        assert "차례를 기다리는 중" in h
        assert "워커가 돌고 있지 않습니다" not in h
    finally:
        _clear_worker_marks()


# ── ③ 진행률 ──────────────────────────────────────────────────────

def test_the_screen_polls_while_it_runs(client, fresh):
    sid = fresh
    client.post(f"/submissions/{sid}/analyze", follow_redirects=False)
    h = client.get(f"/submissions/{sid}").text
    assert f"/submissions/${{SID}}/progress.json" in h, "진행률을 긁지 않는다"
    assert "setTimeout(tick, 3000)" in h


def test_a_quiet_case_does_not_poll(client, fresh):
    """도는 것이 없으면 3초마다 두드릴 이유가 없다.

    앞선 시험이 남긴 큐에 걸리지 않도록 이 시험이 쓸 건을 직접 만든다.
    """
    sid = fresh
    with session_scope() as s:
        assert not case_state(s, sid).analyzing
    h = client.get(f"/submissions/{sid}").text
    assert "progress.json" not in h
    assert "근거 분석 시작" in h, "아직 시작할 수 있는 상태여야 한다"


def test_progress_endpoint_reports_the_running_step(client):
    """도는 동안 몇/몇인지 말해야 한다."""
    # 그 접수의 **최신** 근거 분석이어야 한다. 뒤에 다른 행이 있으면
    # 화면은 그것을 보므로 이 시험이 헛돈다.
    with session_scope() as s:
        row = s.execute(text("""
            SELECT DISTINCT ON (a.submission_id) a.submission_id, a.id, a.status
            FROM assessment a WHERE a.kind='evidence'
            ORDER BY a.submission_id, a.id DESC""")).all()
        row = next(((sid_, aid_) for sid_, aid_, stt in row
                    if stt == 'done' and not case_state(s, sid_).queued_at), None)
    if row is None:
        pytest.skip("최신이 done 인 근거 분석이 없다")
    sid, aid = row
    # JSON 안의 : 을 SQLAlchemy 가 바인드 변수로 읽는다. 값으로 넘긴다.
    #
    # **판정이 실제로 적는 열쇠말을 그대로 쓴다.** 예전에는 여기서 영어
    # 열쇠(done·total·phase)로 지어낸 값을 넣었다. 화면도 영어로 읽고 있었으니
    # 시험은 통과했지만, 판정이 적는 것은 한글이라 실제 화면은 능력단위 일곱
    # 개를 도는 내내 「0/1」이라고 말했다. 실측으로 드러났다.
    import json as _json
    prog = _json.dumps({"단계": "분석", "전체": 9, "완료": 4, "확정": 0,
                        "남은": ["가금 방역관리", "가금위생관리"], "끝난": []},
                       ensure_ascii=False)
    with session_scope() as s:
        s.execute(text("""UPDATE assessment SET status='running',
            progress=CAST(:p AS jsonb) WHERE id=:a"""), {"a": aid, "p": prog})
    try:
        d = client.get(f"/submissions/{sid}/progress.json").json()
        assert not d["done"] and d["pct"] == 44
        assert "4/9" in d["text"] and "가금 방역관리" in d["text"]
        assert "분석" in d["text"]
    finally:
        with session_scope() as s:
            s.execute(text("UPDATE assessment SET status='done' WHERE id=:a"), {"a": aid})


def test_progress_of_an_unknown_case_is_404(client):
    assert client.get("/submissions/99999999/progress.json").status_code == 404


# ── ④ 끝났는데 쓸 수 없는 것 ──────────────────────────────────────

@pytest.mark.parametrize("status,word", [("manual_review", "확인 필요"), ("failed", "실패")])
def test_a_broken_result_is_not_hidden(client, fresh, status, word):
    """done 도 running 도 아닌 상태는 화면에서 통째로 빠져 있었다 —
    「시작」 버튼만 다시 떠서 눌러도 아무 일이 없는 것처럼 보였다."""
    sid = fresh
    with session_scope() as s:
        s.execute(text("""
            INSERT INTO assessment (submission_id, kind, status, rubric_version,
                                    model, attempts, started_at, finished_at, overall_note)
            VALUES (:i, 'evidence', :st, 'v0.2', 'test', 18, now(), now(), :n)"""),
            {"i": sid, "st": status, "n": _NOTE})
        st = case_state(s, sid)
    assert st.evidence.broke and not st.evidence_done
    assert st.evidence.trouble.strip()

    h = client.get(f"/submissions/{sid}").text
    assert word in h, f"{status} 가 화면에 없다"
    assert "다시 시도" in h, "다시 돌릴 길이 없다"
    if status == "manual_review":
        assert "27개 가운데 9개" in h, "무엇이 어긋났는지 말해야 한다"


def test_a_broken_result_can_be_retried(client, fresh):
    """못 쓰는 결과가 남아 있어도 다시 돌릴 수 있어야 한다."""
    sid = fresh
    with session_scope() as s:
        s.execute(text("""
            INSERT INTO assessment (submission_id, kind, status, rubric_version,
                                    model, attempts, started_at, finished_at)
            VALUES (:i, 'evidence', 'manual_review', 'v0.2', 'test', 3, now(), now())"""),
            {"i": sid})
    r = client.post(f"/submissions/{sid}/analyze", follow_redirects=False)
    assert r.status_code == 303
    with session_scope() as s:
        n = s.execute(text("""SELECT count(*) FROM job
            WHERE kind='track_b' AND status='queued'
              AND (payload->>'submission_id')::int = :i"""), {"i": sid}).scalar_one()
    assert n == 1, "다시 시도가 큐에 들어가지 않았다"
