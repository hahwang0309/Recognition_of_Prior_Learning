"""DB 엔진·세션. 모든 서비스가 공유한다."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from krpl_core.config import get_settings


@lru_cache
def get_engine():
    s = get_settings()
    return create_engine(s.database_url, pool_pre_ping=True, future=True)


@lru_cache
def _factory():
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """트랜잭션 스코프.

        with session_scope() as s:
            ...

    정상 종료 시 커밋, 예외 시 롤백. 반드시 with 문으로 쓸 것 —
    제너레이터를 for 문으로 순회하다 break 하면 커밋되지 않는다.
    """
    s = _factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_session() -> Iterator[Session]:
    """FastAPI 의존성 주입용."""
    with session_scope() as s:
        yield s
