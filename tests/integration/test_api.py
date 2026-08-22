"""API 종단 시험 — 접수 → 워커 → 조회."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from krpl_core.db import session_scope
from krpl_core.worker import drain
from services.assess.worker import HANDLERS
from services.gateway.api import app


@pytest.fixture(scope="module")
def client():
    with session_scope() as s:
        # 이 시험이 만든 건만 지운다 — 다른 시험·데모 자료를 비우지 않는다
        s.execute(text("DELETE FROM submission WHERE case_number LIKE 'R2026-9%' OR case_number LIKE 'R2026-01%'"))
    return TestClient(app)


def test_health(client):
    r = client.get("/health").json()
    assert r["status"] == "ok" and r["rubric_version"] == "0.2"
    assert r["pending_decisions"] >= 1          # 미확정 항목이 노출된다


def test_program_search(client):
    r = client.get("/programs", params={"q": "제빵"}).json()
    assert any(p["program_id"] == "제빵_L2" for p in r)
    assert all(p["official_status"] == "유효" for p in r)


def test_recommend(client):
    r = client.get("/recommend", params={"qual": ["정보처리산업기사"], "limit": 5}).json()
    assert r and r[0]["credit_rate_adjusted"] >= r[-1]["credit_rate_adjusted"]
    assert all(0 <= x["credit_rate_strict"] <= 1 for x in r)


def test_unknown_program_rejected(client):
    r = client.post("/submissions", json={"case_number": "R2026-9001", "track": "A",
                                          "target_program_id": "없는종목_L9",
                                          "qualifications": ["제빵기능사"]})
    assert r.status_code == 404


def test_unknown_qualification_rejected(client):
    r = client.post("/submissions", json={"case_number": "R2026-9002", "track": "A",
                                          "target_program_id": "제빵_L2",
                                          "qualifications": ["없는자격"]})
    assert r.status_code == 404


def test_invalid_case_number_rejected(client):
    r = client.post("/submissions", json={"case_number": "홍길동", "track": "A",
                                          "target_program_id": "제빵_L2",
                                          "qualifications": ["제빵기능사"]})
    assert r.status_code == 422                 # 식별정보는 애초에 못 넣는다


def test_full_flow(client):
    r = client.post("/submissions", json={"case_number": "R2026-0101", "track": "A",
                                          "target_program_id": "SW개발_L3",
                                          "qualifications": ["정보처리산업기사"]})
    assert r.status_code == 202
    sid = r.json()["id"]

    st = client.get(f"/submissions/{sid}/status").json()
    assert st["status"] == "received" and st["retry_after"] == 3      # 서버가 폴링 시점 지정

    assert drain(HANDLERS) >= 1

    st = client.get(f"/submissions/{sid}/status").json()
    assert st["status"] == "assessed" and st["retry_after"] is None   # 완료 → 폴링 종료
    aid = st["assessment_id"]

    a = client.get(f"/assessments/{aid}").json()
    assert a["rubric_version"] == "0.2" and a["model"] == "deterministic"
    assert len(a["elements"]) == 9
    assert a["summary"]["credit_rate_strict"] == pytest.approx(0.7701, abs=1e-3)
    e = next(x for x in a["elements"] if x["unit_name"] == "개발자 환경 구축")
    assert (e["verdict"], e["recommendation"]) == ("시간부족", "R2")
    assert e["evidence"][0]["source"] == "정보처리산업기사"          # 근거 추적


def test_duplicate_case_number_rejected(client):
    body = {"case_number": "R2026-0101", "track": "A",
            "target_program_id": "제빵_L2", "qualifications": ["제빵기능사"]}
    assert client.post("/submissions", json=body).status_code == 409
