"""실패한 작업이 몇 번 만에 접히는가.

워커를 띄울 때마다 같은 오류 한 줄이 나왔다 —

    job 84 실패(queued): No row was found when one was required

없어진 접수 건에 걸린 작업이 **영영 재시도**되고 있었다. 두 가지가 겹쳤다.

  ① `dequeue` 가 올린 attempts 는 핸들러와 같은 트랜잭션이라, 핸들러가 터지면
     롤백되어 되돌아간다. DB 의 attempts 는 늘 0 이었고 `max_attempts: 3` 은
     죽은 설정이었다 — 실패한 **모든** 작업이 끝없이 되돌아온다.
  ② `run_track_a` 가 `.one()` 을 써서 NoResultFound 를 냈다. 그것은
     PERMANENT 가 아니라 「다시 해 보면 될지도 모르는 실패」로 처리됐다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from krpl_core.config import get_settings
from krpl_core.db import session_scope
from krpl_core.queue import enqueue
from krpl_core.worker import Worker

KIND = "시험_실패"


def _boom(msg: str = "일시적 실패"):
    def h(s, p):
        raise RuntimeError(msg)
    return h


def _permanent(s, p):
    raise LookupError("대상이 없습니다")


@pytest.fixture
def job():
    with session_scope() as s:
        s.execute(text("DELETE FROM job WHERE kind=:k"), {"k": KIND})
        jid = enqueue(s, KIND, {"x": 1})
    yield jid
    with session_scope() as s:
        s.execute(text("DELETE FROM job WHERE kind=:k"), {"k": KIND})


def _state(jid: int) -> tuple[str, int]:
    with session_scope() as s:
        r = s.execute(text("SELECT status, attempts FROM job WHERE id=:i"),
                      {"i": jid}).one()
    return r[0], r[1]


def _run_now(w: Worker, jid: int) -> None:
    """백오프를 건너뛰고 바로 한 번 돌린다."""
    with session_scope() as s:
        s.execute(text("UPDATE job SET next_run_at=now() WHERE id=:i"), {"i": jid})
    w.run_once()


# ── ① attempts 가 남는가 ──────────────────────────────────────────

def test_attempts_survive_a_failed_handler(job):
    """핸들러가 터져 트랜잭션이 롤백돼도 시도 횟수는 남아야 한다."""
    w = Worker({KIND: _boom()})
    _run_now(w, job)
    status, attempts = _state(job)
    assert attempts == 1, f"시도가 기록되지 않았다: {attempts}"
    assert status == "queued"


def test_a_failing_job_gives_up_after_max_attempts(job):
    """끝없이 되돌아오면 워커를 띄울 때마다 같은 오류가 나온다."""
    n = get_settings().queue.max_attempts
    w = Worker({KIND: _boom()})
    for i in range(n):
        _run_now(w, job)
        status, attempts = _state(job)
        assert attempts == i + 1, f"{i+1}회째인데 attempts={attempts}"
    assert status == "failed", f"{n}회를 채웠는데 {status}"

    # 접힌 뒤에는 더 집지 않는다
    _run_now(w, job)
    assert _state(job) == ("failed", n)


def test_the_error_is_kept(job):
    w = Worker({KIND: _boom("이 문장이 남아야 한다")})
    _run_now(w, job)
    with session_scope() as s:
        err = s.execute(text("SELECT last_error FROM job WHERE id=:i"),
                        {"i": job}).scalar()
    assert "이 문장이 남아야 한다" in err


# ── ② 다시 해도 소용없는 실패 ─────────────────────────────────────

def test_a_permanent_failure_is_not_retried(job):
    """대상이 사라졌으면 세 번 더 돌려도 결과가 같다."""
    w = Worker({KIND: _permanent})
    _run_now(w, job)
    status, attempts = _state(job)
    assert status == "failed", "다시 시도할 이유가 없는데 큐로 돌아갔다"
    assert attempts == 1, "한 번 만에 접혀야 한다"


def test_track_a_on_a_missing_submission_is_permanent():
    """없어진 접수 건에 걸린 시간 대조 작업 — 이것이 실제로 쌓여 있었다."""
    from services.assess.worker import HANDLERS
    with session_scope() as s:
        s.execute(text("""DELETE FROM job WHERE kind='track_a'
            AND (payload->>'submission_id')::int = 99999999"""))
        jid = enqueue(s, "track_a", {"submission_id": 99999999})
    try:
        Worker(HANDLERS).run_once()
        status, attempts = _state(jid)
        assert status == "failed", f"영영 재시도한다: {status}"
        assert attempts == 1
        with session_scope() as s:
            err = s.execute(text("SELECT last_error FROM job WHERE id=:i"),
                            {"i": jid}).scalar()
        # 무엇이 없는지 말해야 한다 — NoResultFound 만으로는 알 수 없었다
        assert "접수 건이 없습니다" in err and "99999999" in err
    finally:
        with session_scope() as s:
            s.execute(text("DELETE FROM job WHERE id=:i"), {"i": jid})


def test_track_b_on_a_missing_submission_is_permanent_too():
    """track_b 는 원래 이렇게 돌고 있었다. 둘이 같아야 한다."""
    from services.assess.worker import HANDLERS
    with session_scope() as s:
        s.execute(text("""DELETE FROM job WHERE kind='track_b'
            AND (payload->>'submission_id')::int = 99999998"""))
        jid = enqueue(s, "track_b", {"submission_id": 99999998, "profile": None})
    try:
        Worker(HANDLERS).run_once()
        status, attempts = _state(jid)
        assert status == "failed" and attempts == 1
    finally:
        with session_scope() as s:
            s.execute(text("DELETE FROM job WHERE id=:i"), {"i": jid})


# ── 성공한 작업 ───────────────────────────────────────────────────

def test_a_successful_job_is_marked_done(job):
    w = Worker({KIND: lambda s, p: None})
    _run_now(w, job)
    status, attempts = _state(job)
    assert status == "done" and attempts == 1
