"""지원자 제출 자료 한 세트를 폴더에서 읽어 접수한다.

실제 접수는 파일 여러 개로 온다. 그래서 시험 자료도 그렇게 두었다 —
`신청서.yaml` + `접수목록.csv` + 제출 파일들.

`test/candidate01` 은 git 저장소 밖(프로젝트 루트)에 있으므로, 없으면 건너뛴다.
대신 형식 검사와 접수 계산은 이 시험이 만든 임시 세트로 확인한다.
"""
from __future__ import annotations

import csv
import shutil
import zipfile
from pathlib import Path

import sys

import pytest
from sqlalchemy import text

from krpl_core.db import session_scope

# 적재기는 scripts/ 에 있다 — 꾸러미가 아니라 명령줄 도구라서 경로를 잡아 준다.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import load_candidate  # noqa: E402

SRC = load_candidate.SRC


def _write_manifest(d: Path, rows: list[dict]) -> None:
    with (d / "접수목록.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, ["파일", "종류", "신뢰도등급", "발급기관", "발급일"])
        w.writeheader()
        w.writerows(rows)


@pytest.fixture
def tiny(tmp_path: Path) -> Path:
    """가장 작은 세트 — 파일 하나."""
    (tmp_path / "신청서.yaml").write_text(
        "심사번호: R2026-9900\n목표종목: 양식조리_L4\n", encoding="utf-8")
    (tmp_path / "경력기술서.txt").write_text(
        "호텔 양식당에서 4년간 육류 조리를 담당했습니다.\n", encoding="utf-8")
    _write_manifest(tmp_path, [{"파일": "경력기술서.txt", "종류": "경력기술서",
                                "신뢰도등급": "E", "발급기관": "본인",
                                "발급일": "2026-06-20"}])
    return tmp_path


# ── 형식 검사 ─────────────────────────────────────────────────────

def test_missing_manifest_says_so(tmp_path):
    (tmp_path / "신청서.yaml").write_text("심사번호: X\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="접수목록.csv"):
        load_candidate.read_set(tmp_path)


def test_missing_application_says_so(tmp_path):
    _write_manifest(tmp_path, [])
    with pytest.raises(FileNotFoundError, match="신청서.yaml"):
        load_candidate.read_set(tmp_path)


def test_file_named_in_manifest_must_exist(tiny):
    _write_manifest(tiny, [{"파일": "없는파일.txt", "종류": "경력기술서",
                            "신뢰도등급": "E", "발급기관": "본인", "발급일": ""}])
    with pytest.raises(FileNotFoundError, match="없는파일"):
        load_candidate.read_set(tiny)


def test_unknown_grade_is_refused(tiny):
    """등급은 기준서가 정한 A~E 뿐이다."""
    _write_manifest(tiny, [{"파일": "경력기술서.txt", "종류": "경력기술서",
                            "신뢰도등급": "Z", "발급기관": "본인", "발급일": ""}])
    with pytest.raises(ValueError, match="모르는 신뢰도 등급"):
        load_candidate.read_set(tiny)


def test_unreadable_format_is_refused_before_ingest(tiny):
    """읽을 수 없는 파일을 받으면 조각 0개짜리 문서가 조용히 들어간다.
    받는 자리에서 막는다."""
    (tiny / "스캔본.jpg").write_bytes(b"\xff\xd8\xff")
    _write_manifest(tiny, [{"파일": "스캔본.jpg", "종류": "경력증명서",
                            "신뢰도등급": "B", "발급기관": "본인", "발급일": ""}])
    with pytest.raises(ValueError, match="읽을 수 없는 형식"):
        load_candidate.read_set(tiny)


def test_empty_manifest_is_refused(tiny):
    _write_manifest(tiny, [])
    with pytest.raises(ValueError, match="문서가 없습니다"):
        load_candidate.read_set(tiny)


def test_doc_keys_run_in_order(tiny):
    shutil.copy(tiny / "경력기술서.txt", tiny / "두번째.txt")
    _write_manifest(tiny, [
        {"파일": "경력기술서.txt", "종류": "경력기술서", "신뢰도등급": "E",
         "발급기관": "본인", "발급일": ""},
        {"파일": "두번째.txt", "종류": "면접 예비답변", "신뢰도등급": "E",
         "발급기관": "본인", "발급일": ""}])
    _, docs = load_candidate.read_set(tiny)
    assert [d["doc_key"] for d in docs] == ["D01", "D02"]


# ── 접수 ──────────────────────────────────────────────────────────

def test_loading_a_tiny_set_works(tiny):
    cn, sid, r = load_candidate.load(tiny)
    try:
        assert cn == "R2026-9900"
        assert r.n_documents == 1 and r.n_fragments >= 1
        with session_scope() as s:
            got = s.execute(text("""SELECT doc_type, grade FROM document
                WHERE submission_id=:i"""), {"i": sid}).one()
        assert got == ("경력기술서", "E")
    finally:
        with session_scope() as s:
            s.execute(text("DELETE FROM submission WHERE case_number=:c"), {"c": cn})


def test_case_number_can_be_overridden(tiny):
    cn, _, _ = load_candidate.load(tiny, case="R2026-9901")
    try:
        assert cn == "R2026-9901"
    finally:
        with session_scope() as s:
            s.execute(text("DELETE FROM submission WHERE case_number=:c"), {"c": cn})


def test_loading_twice_leaves_one_submission(tiny):
    cn, _, _ = load_candidate.load(tiny)
    load_candidate.load(tiny)
    try:
        with session_scope() as s:
            n = s.execute(text("SELECT count(*) FROM submission WHERE case_number=:c"),
                          {"c": cn}).scalar_one()
        assert n == 1, "다시 넣었더니 두 건이 됐다"
    finally:
        with session_scope() as s:
            s.execute(text("DELETE FROM submission WHERE case_number=:c"), {"c": cn})


# ── hwpx ──────────────────────────────────────────────────────────

def test_generated_hwpx_is_readable(tmp_path):
    """기관 발급 증명서를 hwpx 표로 만든다. 파서가 표만 읽으므로
    능력단위코드·시간·평가결과는 **한 행에** 있어야 한다."""
    import sys
    sys.path.insert(0, str(SRC))
    try:
        import make_hwpx
    except ImportError:
        pytest.skip("make_hwpx.py 가 없다")

    p = tmp_path / "t.hwpx"
    make_hwpx.write(p, [[["능력단위코드", "이수시간", "내부평가"],
                         ["1301010203_21v4", "90시간", "합격(84점)"]]])
    assert zipfile.is_zipfile(p)

    from krpl_parsers import parse_file
    d = parse_file(p)
    assert d.tables and len(d.tables[0]) == 2
    line = [x for x in d.text.split("\n") if "1301010203" in x]
    assert line, "코드가 든 줄이 없다"
    assert "90시간" in line[0] and "합격" in line[0], \
        f"코드·시간·평가가 한 줄에 있어야 한다: {line[0]}"


# ── 실제 세트 ─────────────────────────────────────────────────────

@pytest.mark.skipif(not (SRC / "접수목록.csv").exists(),
                    reason="test/candidate01 이 없다 (저장소 밖)")
def test_the_real_set_lands_as_designed():
    """자료를 손보다가 설계 의도가 깨지면 여기서 잡힌다."""
    import json
    cn, sid, r = load_candidate.load(SRC)
    assert r.n_documents == 11, f"문서가 11건이 아니다: {r.n_documents}"
    ev = [p for p in r.prior_learning if p["evaluated"]]
    assert len(ev) == 3, f"이수증에서 3단위가 잡혀야 한다: {len(ev)}"
    assert not sum(r.masked.values()), "지어낸 자료에 가려질 개인정보가 있으면 안 된다"

    with session_scope() as s:
        note = s.execute(text("""SELECT overall_note FROM assessment
            WHERE submission_id=:i AND kind='time' ORDER BY id DESC LIMIT 1"""),
            {"i": sid}).scalar()
    assert note, "시간 대조가 자동으로 돌지 않았다"
    d = json.loads(note)
    h = d["hours"]
    assert h["완전충족"] + h["조정범위내"] == 150, f"인정 150시간이어야 한다: {h}"
    assert d["total_hours"] == 450
    # 편성표만 낸 3단위는 이유와 함께 남아야 한다
    assert len(d["갈음불가"]) == 3, d["갈음불가"]
    assert all(x["reason"] for x in d["갈음불가"])
