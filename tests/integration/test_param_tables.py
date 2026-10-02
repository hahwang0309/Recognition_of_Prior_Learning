"""판정 파라미터 표 — 위원이 읽고 고쳐 말할 수 있어야 한다.

이 표는 회의에서 「이 값이 맞나」를 논의하는 자리다. 파일명·변수명이 섞이면
위원이 무엇을 고치라는 것인지 알 수 없고, 값이 낡으면 화면과 다른 것을 논의하게 된다.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from krpl_core.db import session_scope
from services.gateway.api import app

# 화면에 나오면 안 되는 말 — 파일명·변수명·내부 표기
JARGON = ("adjustment_floor", "hold_floor", "rubric", ".yaml", ".py", "config/",
          "App 본 계산", "ksa_coverage_min", "track_a", "track_b", "R0", "R5", "fid")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _rows(html: str) -> list[tuple[str, str, str]]:
    """표가 없으면 빈 목록. 확인 계획은 **제출 전에는 표가 없다** — 내용이 없는 화면이다."""
    i = html.find("판정 파라미터")
    if i < 0:
        return []
    return re.findall(r"<tr><td>([^<]+)</td><td>([^<]*)</td><td>([^<]*)</td>", html[i:])


def _screens(sid_a: int, aid_a: int, aid_b: int) -> dict[str, str]:
    return {"① 기록 확인": f"/submissions/{sid_a}/report/time",
            "③ 전문가 검토": f"/assessments/{aid_a}/review",
            "② 위원 검토": f"/assessments/{aid_b}/panel",
            "③ 확인 계획": f"/assessments/{aid_b}/plan"}


@pytest.fixture(scope="module")
def ids():
    with session_scope() as s:
        a = s.execute(text("""SELECT a.id, a.submission_id FROM assessment a
            WHERE a.kind='time' ORDER BY a.id DESC LIMIT 1""")).first()
        b = s.execute(text("""SELECT a.id FROM assessment a
            WHERE a.kind='evidence'
              AND EXISTS (SELECT 1 FROM assessment_element e WHERE e.assessment_id=a.id)
            ORDER BY a.id DESC LIMIT 1""")).scalar()
    if a is None or b is None:
        pytest.skip("판정이 없다")
    return {"aid_a": a[0], "sid_a": a[1], "aid_b": b}


def test_every_screen_has_a_parameter_table(client, ids):
    """확인 계획만 예외다 — 위원이 제출하기 전에는 보일 내용 자체가 없다."""
    for name, path in _screens(ids["sid_a"], ids["aid_a"], ids["aid_b"]).items():
        r = client.get(path)
        if r.status_code == 404:
            continue
        if name == "③ 확인 계획" and "아직 위원 판정이 제출되지 않았습니다" in r.text:
            continue
        assert _rows(r.text), f"{name} 에 파라미터 행이 없다"


def test_no_developer_words_in_the_tables(client, ids):
    """위원이 읽는 표다 — 파일명·변수명이 보이면 무엇을 고치라는 것인지 알 수 없다."""
    for name, path in _screens(ids["sid_a"], ids["aid_a"], ids["aid_b"]).items():
        r = client.get(path)
        if r.status_code == 404:
            continue
        flat = " ".join(" ".join(x) for x in _rows(r.text))
        for bad in JARGON:
            assert bad not in flat, f"{name} 파라미터 표에 개발자 말: {bad!r}"


def test_no_duplicate_rows(client, ids):
    """같은 항목이 두 번 있으면 위원이 어느 것을 보고 논의하는지 알 수 없다.

    실제로 위원 페이지에 「능력단위 판정」이 옛 규칙과 새 규칙으로 둘 다 있었다.
    """
    for name, path in _screens(ids["sid_a"], ids["aid_a"], ids["aid_b"]).items():
        r = client.get(path)
        if r.status_code == 404:
            continue
        keys = [x[0] for x in _rows(r.text)]
        assert len(keys) == len(set(keys)), f"{name} 에 같은 항목이 두 번: {keys}"


def test_the_thresholds_match_what_the_screen_computes(client, ids):
    """표의 값이 실제 판정 문턱과 같아야 한다 — 다르면 다른 것을 논의하게 된다.

    2026-10-02: Track B 는 수행준거 점수 규칙(모든 수행준거 ≥1 · 평균 ≥1.5 인정 · ≥1.0 보류)이다.
    """
    from krpl_core.config import get_rubric
    ur = get_rubric().track_b["unit_rule"]
    acc, hold = f"{float(ur['accept_mean']):.1f}", f"{float(ur['hold_mean']):.1f}"
    for path in (f"/assessments/{ids['aid_b']}/panel", f"/assessments/{ids['aid_b']}/plan"):
        r = client.get(path)
        if r.status_code == 404:
            continue
        flat = " ".join(" ".join(x) for x in _rows(r.text))
        if not flat:
            continue                      # 제출 전 확인 계획 — 표가 없다
        assert acc in flat and hold in flat and "0 인 수행준거" in flat, \
            f"{path} 의 표가 문턱(평균 {acc}/{hold} · 0 없음)을 말하지 않는다"
