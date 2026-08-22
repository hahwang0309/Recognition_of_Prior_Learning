"""작업 워커.

핵심 — 실패 기록은 **별도 세션**에서 한다.
작업 중 예외가 나면 그 트랜잭션은 중단(aborted) 상태라 아무것도 쓸 수 없다.
"""
from __future__ import annotations

import logging
import signal
import time
from collections.abc import Callable

from krpl_core.config import get_settings
from krpl_core.db import session_scope
from krpl_core.queue import complete, dequeue, fail, reclaim_stale

# 다시 시도해도 결과가 같은 실패 — 대상이 사라졌거나 입력이 잘못된 경우.
# 재시도 횟수를 태우지 않고 바로 접는다.
PERMANENT = (LookupError, ValueError)

log = logging.getLogger(__name__)
Handler = Callable[[object, dict], None]


class Worker:
    def __init__(self, handlers: dict[str, Handler]):
        self.handlers = handlers
        self.kinds = list(handlers)
        self._stop = False

    def stop(self, *_):
        self._stop = True

    def reclaim(self, minutes: int = 30) -> None:
        """앞선 워커가 죽으며 잡아 둔 작업을 도로 대기로 돌린다.
        이걸 안 하면 그 작업은 아무도 집지 않은 채 영영 남는다."""
        with session_scope() as s:
            ids = reclaim_stale(s, minutes)
        if ids:
            log.warning("멈춰 있던 작업 %d건을 회수했습니다: %s", len(ids), ids)

    def run_once(self) -> bool:
        """작업 하나를 처리한다. 처리했으면 True, 큐가 비었으면 False."""
        job = None
        try:
            with session_scope() as s:
                job = dequeue(s, self.kinds)
                if job is None:
                    return False
                self.handlers[job["kind"]](s, job["payload"])
                complete(s, job["id"])
            log.info("job %s (%s) 완료", job["id"], job["kind"])
            return True
        except Exception as e:  # noqa: BLE001
            if job is None:
                raise
            # ★ 새 세션 — 위 트랜잭션은 롤백되어 쓰기가 불가능하다
            perm = isinstance(e, PERMANENT)
            with session_scope() as s2:
                st = fail(s2, job["id"], f"{type(e).__name__}: {e}",
                          job["attempts"], permanent=perm)
            log.error("job %s 실패(%s%s): %s", job["id"], st,
                      ", 재시도 안 함" if perm else "", e)
            return True

    def run_forever(self) -> None:
        cfg = get_settings().queue
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        log.info("워커 시작 — kinds=%s", self.kinds)
        self.reclaim()                       # 앞선 워커가 남긴 것부터 거둔다
        last = time.monotonic()
        while not self._stop:
            if not self.run_once():
                time.sleep(cfg.poll_interval_sec)
            if time.monotonic() - last > 300:   # 5분마다 한 번 더
                self.reclaim()
                last = time.monotonic()
        log.info("워커 종료")


def drain(handlers: dict[str, Handler], limit: int = 1000) -> int:
    """큐가 빌 때까지 처리한다. 테스트·배치용."""
    w, n = Worker(handlers), 0
    while n < limit and w.run_once():
        n += 1
    return n
