"""문서 수집 종단 시험 — 업로드 → 마스킹 → 조각화 → 조회."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from krpl_core.db import session_scope
from services.gateway.api import app


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    with session_scope() as s:
        # 이 시험이 만든 건만 지운다 — 다른 시험·데모 자료를 비우지 않는다
        s.execute(text("DELETE FROM submission WHERE case_number LIKE 'R2026-02%'"))
    return TestClient(app)


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    d = tmp_path_factory.mktemp("uploads")
    (d / "career.txt").write_text(
        "근무기간: 2020.03.10 ~ 2026.05.31 (6년 2개월)\n"
        "직무: 용접공\n담당자 연락처: 010-1111-2222\n", encoding="utf-8")
    (d / "training.txt").write_text(
        "1601050111_21v3 피복아크용접 맞대기용접 120시간 · 내부평가 합격(82점)\n"
        "1601050105_21v3 피복아크용접 가용접 작업 40시간 · 내부평가 합격(88점)\n", encoding="utf-8")
    (d / "log.txt").write_text(
        "2025-02-11 | 블록 3-A 맞대기용접. 판두께 12mm, 전류 260A.\n"
        "2025-03-05 | 수평자세 필렛용접. 가스유량 20L/min.\n", encoding="utf-8")
    (d / "story.txt").write_text(
        "용접기 전류와 전압을 재료 두께에 맞춰 설정했습니다.\n"
        "파이프 용접은 담당한 바 없습니다.\n"
        "비파괴검사는 검사팀이 별도로 진행했습니다.\n", encoding="utf-8")
    return d


def _create(client, case="R2026-0201"):
    r = client.post("/submissions", json={"case_number": case, "track": "B",
                                          "target_program_id": "수동용접(CO2용접)_L4",
                                          "qualifications": ["이산화탄소가스아크용접기능사"]})
    assert r.status_code == 202
    return r.json()["id"]


def test_ingest_flow(client, files):
    sid = _create(client)
    r = client.post(f"/submissions/{sid}/documents", json={"documents": [
        {"doc_key": "D01", "doc_type": "경력증명서", "grade": "B",
         "file_path": str(files / "career.txt"), "issuer": "○○중공업"},
        {"doc_key": "D02", "doc_type": "NCS기반_훈련이수증", "grade": "B",
         "file_path": str(files / "training.txt")},
        {"doc_key": "D03", "doc_type": "작업일지", "grade": "C",
         "file_path": str(files / "log.txt")},
        {"doc_key": "D04", "doc_type": "경력기술서", "grade": "E",
         "file_path": str(files / "story.txt")},
    ]})
    assert r.status_code == 200
    d = r.json()
    assert d["n_documents"] == 4 and d["n_fragments"] >= 10
    assert d["masked"] == {"전화번호": 1}                      # 연락처만 마스킹
    assert d["warnings"] == []

    # 기이수 — 평가확인된 것만 R0 대상
    pl = {x["unit_code"]: x for x in d["prior_learning"]}
    assert set(pl) == {"1601050111", "1601050105"}
    assert pl["1601050111"]["completed_hours"] == 120
    assert all(x["evaluated"] for x in pl.values())


def test_format_detection(client, files):
    sid = _create(client, "R2026-0202")
    client.post(f"/submissions/{sid}/documents", json={"documents": [
        {"doc_key": "D01", "doc_type": "경력증명서", "grade": "B", "file_path": str(files / "career.txt")},
        {"doc_key": "D03", "doc_type": "작업일지", "grade": "C", "file_path": str(files / "log.txt")},
        {"doc_key": "D04", "doc_type": "경력기술서", "grade": "E", "file_path": str(files / "story.txt")},
    ]})
    with session_scope() as s:
        fmt = dict(s.execute(text(
            "SELECT doc_key, parsed_format FROM document WHERE submission_id=:i"), {"i": sid}).all())
    assert fmt == {"D01": "record", "D03": "dated", "D04": "narrative"}


def test_fragment_ids_and_types(client, files):
    sid = _create(client, "R2026-0203")
    client.post(f"/submissions/{sid}/documents", json={"documents": [
        {"doc_key": "D04", "doc_type": "경력기술서", "grade": "E", "file_path": str(files / "story.txt")},
    ]})
    fr = client.get(f"/submissions/{sid}/fragments").json()
    assert [f["fid"] for f in fr] == ["D04-S01", "D04-S02", "D04-S03"]
    assert [f["stype"] for f in fr] == ["직접수행", "부정", "관찰·간접"]
    assert all(f["grade"] == "E" for f in fr)


def test_dates_preserved(client, files):
    sid = _create(client, "R2026-0204")
    client.post(f"/submissions/{sid}/documents", json={"documents": [
        {"doc_key": "D03", "doc_type": "작업일지", "grade": "C", "file_path": str(files / "log.txt")},
    ]})
    fr = client.get(f"/submissions/{sid}/fragments", params={"doc_key": "D03"}).json()
    assert fr[0]["text"].startswith("2025-02-11")             # 날짜 오탐 회귀 방지
    assert "***" not in " ".join(f["text"] for f in fr)


def test_missing_file_rejected(client):
    sid = _create(client, "R2026-0205")
    r = client.post(f"/submissions/{sid}/documents", json={"documents": [
        {"doc_key": "D01", "doc_type": "경력증명서", "grade": "B", "file_path": "/없는/파일.txt"},
    ]})
    assert r.status_code == 200 and r.json()["n_documents"] == 0
    assert "파싱 실패" in r.json()["warnings"][0]              # 한 건 실패가 전체를 막지 않는다


def test_unknown_submission(client, files):
    r = client.post("/submissions/99999/documents", json={"documents": [
        {"doc_key": "D01", "doc_type": "경력증명서", "grade": "B", "file_path": str(files / "career.txt")}]})
    assert r.status_code == 404


def test_invalid_doc_key_rejected(client, files):
    sid = _create(client, "R2026-0206")
    r = client.post(f"/submissions/{sid}/documents", json={"documents": [
        {"doc_key": "문서1", "doc_type": "경력증명서", "grade": "B", "file_path": str(files / "career.txt")}]})
    assert r.status_code == 422
