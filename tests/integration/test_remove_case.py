"""접수 건 삭제 — 되돌릴 수 없으므로 잘못 눌러 지워지지 않는지를 본다."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from krpl_core.audit import audit_root
from krpl_core.db import session_scope
from services.gateway.api import app
from services.review.remove import preview, remove

CASE = "R2026-9999-삭제시험"


@pytest.fixture
def victim():
    """지워도 되는 접수 하나를 만든다 — 실사례를 쓰면 시험이 자료를 지운다."""
    with session_scope() as s:
        prog = s.execute(text("SELECT program_id FROM catalog_wsd_program LIMIT 1")).scalar()
        if prog is None:
            pytest.skip("카탈로그 없음")
        s.execute(text("DELETE FROM submission WHERE case_number=:c"), {"c": CASE})
        sid = s.execute(text("""INSERT INTO submission (case_number, track, target_program_id, status)
            VALUES (:c, 'B', :p, 'received') RETURNING id"""), {"c": CASE, "p": prog}).scalar_one()
        s.execute(text("""INSERT INTO document (submission_id, doc_key, doc_type, grade, file_path)
            VALUES (:i, 'D01', '기타', 'D', '/tmp/none.txt')"""), {"i": sid})
    yield sid
    with session_scope() as s:
        s.execute(text("DELETE FROM submission WHERE case_number=:c"), {"c": CASE})


def test_preview_says_what_will_disappear(victim):
    with session_scope() as s:
        info = preview(s, victim)
    assert info["case_number"] == CASE
    assert info["n_documents"] == 1 and info["has_decision"] is False


def test_a_wrong_case_number_deletes_nothing(victim):
    """목록에서 잘못 누른 한 번으로 지워지면 안 된다 — 번호를 직접 치게 한다."""
    with session_scope() as s:
        with pytest.raises(ValueError, match="심사번호가 다릅니다"):
            remove(s, victim, confirm="아무거나")
    with session_scope() as s:
        assert s.execute(text("SELECT count(*) FROM submission WHERE id=:i"),
                         {"i": victim}).scalar() == 1, "지워졌다"


def test_removing_takes_the_children_with_it(victim):
    with session_scope() as s:
        out = remove(s, victim, confirm=CASE)
    assert out["case_number"] == CASE
    with session_scope() as s:
        assert s.execute(text("SELECT count(*) FROM submission WHERE id=:i"), {"i": victim}).scalar() == 0
        assert s.execute(text("SELECT count(*) FROM document WHERE submission_id=:i"),
                         {"i": victim}).scalar() == 0, "문서가 남았다"
        # 지운 사실은 남는다 — audit_log 에는 외래키가 없다
        assert s.execute(text("""SELECT count(*) FROM audit_log
            WHERE entity='submission' AND entity_id=:i AND action='removed'"""),
            {"i": str(victim)}).scalar() == 1


def test_the_audit_folder_survives_unless_asked(victim):
    """감사 산출물은 기본으로 남긴다 — 잘못 지웠을 때 무엇을 보고 판정했는지가
    마지막으로 남는 자리다."""
    folder = audit_root() / CASE
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "x.json").write_text("{}", encoding="utf-8")
    try:
        with session_scope() as s:
            out = remove(s, victim, confirm=CASE)
        assert out["audit_kept"] and folder.exists(), "감사 산출물이 사라졌다"
    finally:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)


def test_purge_audit_removes_it(victim):
    folder = audit_root() / CASE
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "x.json").write_text("{}", encoding="utf-8")
    with session_scope() as s:
        out = remove(s, victim, confirm=CASE, purge_audit=True)
    assert not folder.exists() and "audit" in out["removed_files"]


def test_the_endpoint_refuses_a_wrong_confirmation(victim):
    c = TestClient(app)
    r = c.post(f"/submissions/{victim}/remove", json={"confirm": "틀린번호"})
    assert r.status_code == 409 and "심사번호" in r.json()["detail"]
    assert c.get(f"/submissions/{victim}").status_code == 200, "지워졌다"


def test_the_overview_has_the_delete_form(victim):
    h = TestClient(app).get(f"/submissions/{victim}").text
    assert 'id="rmc"' in h and f"/submissions/{victim}/remove" in h
    assert "되돌릴 수 없습니다" in h, "위험을 말하지 않는다"


def test_files_survive_when_the_delete_fails(victim):
    """DB 가 확정되기 전에는 파일을 건드리지 않는다.

    실제 사고(2026-09-25): 파일을 먼저 지우고 그 뒤 줄에서 예외가 나,
    **접수는 살아 있는데 감사 산출물만 사라졌다**(R2026-9103 수집 기록 4건).
    DB 는 롤백되지만 지워진 파일은 돌아오지 않는다.
    """
    folder = audit_root() / CASE
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "x.json").write_text("{}", encoding="utf-8")

    def boom(*a, **kw):
        raise RuntimeError("커밋이 터졌다")

    try:
        with session_scope() as s:
            s.commit = boom            # 이 세션에서만, 잠깐
            with pytest.raises(RuntimeError):
                remove(s, victim, confirm=CASE, purge_audit=True)
            del s.commit               # 세션을 닫을 때의 커밋까지 막으면 안 된다
            s.rollback()
        assert folder.exists() and (folder / "x.json").exists(), \
            "DB 가 확정되기 전에 파일을 지웠다"
    finally:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)


def test_nothing_is_deleted_twice(victim):
    """이미 지운 건을 또 지우려 하면 404 — 엉뚱한 폴더를 지우지 않는다."""
    with session_scope() as s:
        remove(s, victim, confirm=CASE)
    with session_scope() as s:
        with pytest.raises(LookupError):
            remove(s, victim, confirm=CASE)
