"""PostgreSQL 작업 큐.

SELECT … FOR UPDATE SKIP LOCKED 로 집는다. 외부 의존성이 없고,
연 1,000건 규모에서 Celery+Redis 를 대체한다.

## 죽은 워커가 잡고 있던 작업

집는 순간 `running` 으로 바꾸고 커밋하므로, 그 뒤 워커가 죽으면
DB 잠금은 풀려도 **작업은 `running` 인 채로 남는다.** 아무도 다시 집지 않는다.
실제로 8시간 넘게 방치된 작업이 있었고, 그 탓에 화면은 워커가 살아 있다고 표시했다.

그래서 `reclaim_stale()` 이 있다. 워커가 뜰 때와 주기적으로 불러,
너무 오래 잡혀 있는 작업을 도로 대기 상태로 돌린다.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from krpl_core.config import get_settings


def enqueue(s: Session, kind: str, payload: dict[str, Any]) -> int:
    return s.execute(text("""
        INSERT INTO job (kind, payload) VALUES (:k, CAST(:p AS jsonb)) RETURNING id"""),
        {"k": kind, "p": json.dumps(payload, ensure_ascii=False)}).scalar_one()


def dequeue(s: Session, kinds: list[str] | None = None) -> dict[str, Any] | None:
    """실행 가능한 작업 하나를 잠그고 가져온다. 없으면 None."""
    cond = "AND kind = ANY(:kinds)" if kinds else ""
    row = s.execute(text(f"""
        UPDATE job SET status='running', locked_at=now(), attempts=attempts+1
        WHERE id = (
            SELECT id FROM job
            WHERE status='queued' AND next_run_at <= now() {cond}
            ORDER BY next_run_at, id
            FOR UPDATE SKIP LOCKED LIMIT 1)
        RETURNING id, kind, payload, attempts"""),
        {"kinds": kinds} if kinds else {}).mappings().first()
    return dict(row) if row else None


def complete(s: Session, job_id: int) -> None:
    s.execute(text("UPDATE job SET status='done', last_error=NULL WHERE id=:i"), {"i": job_id})


def fail(s: Session, job_id: int, error: str, attempts: int,
         permanent: bool = False) -> str:
    """재시도 여부를 판단해 상태를 정한다. 반환값은 최종 상태.

    permanent=True 면 재시도하지 않는다 — 대상이 사라졌거나 입력이 잘못된 경우,
    같은 작업을 세 번 더 돌려도 결과가 같다.

    ## attempts 를 여기서 다시 쓴다

    `dequeue` 가 attempts 를 올리지만 그것은 **핸들러와 같은 트랜잭션**이라,
    핸들러가 터지면 롤백되어 되돌아간다. 그래서 DB 의 attempts 는 늘 0 이었고
    `max_attempts` 가 죽은 설정이 되어 **실패한 작업이 영영 재시도**됐다.
    실측: 다섯 번 돌려도 attempts=0.

    호출자는 롤백 전에 읽어 둔 값을 넘겨 준다. 그 값을 여기서 적는다.
    """
    cfg = get_settings().queue
    if permanent or attempts >= cfg.max_attempts:
        s.execute(text("""UPDATE job SET status='failed', last_error=:e,
                          attempts=:n WHERE id=:i"""),
                  {"i": job_id, "e": error[:2000], "n": attempts})
        return "failed"
    delay = cfg.backoff_base_sec * (2 ** (attempts - 1))
    s.execute(text("""UPDATE job SET status='queued', last_error=:e, attempts=:n,
                      next_run_at = now() + make_interval(secs => :d) WHERE id=:i"""),
              {"i": job_id, "e": error[:2000], "n": attempts, "d": delay})
    return "queued"


def reclaim_stale(s: Session, minutes: int = 30) -> list[int]:
    """너무 오래 잡혀 있는 작업을 도로 대기로 돌린다.

    워커가 죽으면 작업이 `running` 인 채 남아 아무도 집지 않는다.
    시도 횟수는 그대로 두므로 max_attempts 를 넘으면 다음 차례에 실패로 정리된다.
    """
    rows = s.execute(text("""
        UPDATE job SET status='queued', locked_at=NULL,
               last_error = coalesce(last_error || ' | ', '')
                            || :m || '분 넘게 잡혀 있어 회수함'
        WHERE status='running' AND locked_at < now() - make_interval(mins => :m)
        RETURNING id"""), {"m": minutes}).scalars().all()
    return list(rows)


def worker_alive(s: Session, minutes: int = 5, running_minutes: int = 30) -> bool:
    """워커가 살아 있는가.

    ① 최근 `minutes` 안에 작업을 집은 흔적이 있으면 살아 있다.
    ② 지금 **돌고 있는** 작업이 있고 그것이 회수 한계 안이면 살아 있다.

    ②가 없으면, 판정 하나가 30분 걸리는 동안 새로 집는 일이 없어 화면이
    「워커가 죽었다」고 말한다. `status='running'` 만 보면 죽은 워커가 남긴
    작업에 속으므로, 회수 한계(기본 30분)를 함께 본다 — 그보다 오래 잡혀
    있으면 `reclaim_stale()` 이 도로 대기로 돌린다.
    """
    return bool(s.execute(text("""
        SELECT 1 FROM job
        WHERE locked_at > now() - make_interval(mins => :m)
           OR (status='running' AND locked_at > now() - make_interval(mins => :r))
        LIMIT 1"""), {"m": minutes, "r": running_minutes}).first())


def stuck(s: Session, minutes: int = 30) -> list[dict[str, Any]]:
    """오래 잡혀 있는 작업 목록. 화면에 그대로 보여 준다."""
    return [dict(r) for r in s.execute(text("""
        SELECT id, kind, payload, attempts, locked_at,
               round(extract(epoch from (now()-locked_at))/60) AS 분
        FROM job WHERE status='running'
          AND locked_at < now() - make_interval(mins => :m)
        ORDER BY locked_at"""), {"m": minutes}).mappings()]


def stats(s: Session) -> dict[str, int]:
    return {r.status: r.n for r in s.execute(text(
        "SELECT status, count(*) AS n FROM job GROUP BY status"))}
