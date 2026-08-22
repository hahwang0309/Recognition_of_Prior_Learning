"""시험 공통 설정 — 운영 데이터와 완전히 분리한다.

시험이 운영 DB·감사 보관함을 건드리면 **감사 기록 자체를 믿을 수 없게 된다.**
실제로 그런 일이 있었다: 파일만 나누고 DB 를 공유해서, 시험이 R2026-0002 의
감사 색인을 시험용 경로로 덮어썼다. 화면에는 「파일 없음」이 떴다.

그래서 여기서 두 가지를 강제한다.
  ① `KRPL_ENV=test` — 감사 산출물을 storage/_test/ 로 보낸다
  ② `KRPL_DATABASE_URL` — 시험 전용 DB. `.env` 값이 있어도 **덮어쓴다.**
     이름이 _test 로 끝나지 않으면 시험을 시작하지 않는다.
"""
import os
import shutil
import sys
from pathlib import Path

import yaml

APP = Path(__file__).resolve().parents[1]

# get_settings() 첫 호출 전에 정해야 한다 — import 순서에 의존하므로 여기가 유일한 자리다.
os.environ["KRPL_ENV"] = "test"
os.environ.setdefault("KRPL_LLM_BACKEND", "replay")   # 시험이 실제 LLM 을 부르지 않도록

_cfg = yaml.safe_load((APP / "config/environments/test.yaml").read_text(encoding="utf-8"))
_url = os.environ.get("KRPL_TEST_DATABASE_URL") or _cfg["database_url"]
if not _url.rsplit("/", 1)[-1].endswith("_test"):
    sys.exit(f"시험 DB 이름이 _test 로 끝나지 않습니다: {_url}\n"
             "운영 데이터를 건드릴 수 있어 중단합니다.")
os.environ["KRPL_DATABASE_URL"] = _url                # .env 값이 있어도 덮어쓴다

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _isolated_storage():
    """시험용 감사 보관함만 비운다. storage/audit/ 는 손대지 않는다."""
    from krpl_core.audit import audit_root
    root = audit_root()
    assert "_test" in str(root), f"시험이 운영 보관함을 가리킴: {root}"
    if root.exists():
        shutil.rmtree(root)
    yield
