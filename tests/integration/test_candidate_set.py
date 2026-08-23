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
    _write_manifest(tmp_path, [{"파일": "경력기술서.txt", "종류": "경력기술서·자기소개서",
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
    _write_manifest(tiny, [{"파일": "없는파일.txt", "종류": "경력기술서·자기소개서",
                            "신뢰도등급": "E", "발급기관": "본인", "발급일": ""}])
    with pytest.raises(FileNotFoundError, match="없는파일"):
        load_candidate.read_set(tiny)


def test_unknown_grade_is_refused(tiny):
    """등급은 기준서가 정한 A~E 뿐이다."""
    _write_manifest(tiny, [{"파일": "경력기술서.txt", "종류": "경력기술서·자기소개서",
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
        {"파일": "경력기술서.txt", "종류": "경력기술서·자기소개서", "신뢰도등급": "E",
         "발급기관": "본인", "발급일": ""},
        {"파일": "두번째.txt", "종류": "경력기술서·자기소개서", "신뢰도등급": "E",
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
        assert got == ("경력기술서·자기소개서", "E")
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


# ── 화면으로 새 접수 ──────────────────────────────────────────────

def _client():
    from fastapi.testclient import TestClient
    from services.gateway.api import app
    return TestClient(app)


def _drop(*cases: str) -> None:
    with session_scope() as s:
        for c in cases:
            s.execute(text("DELETE FROM submission WHERE case_number=:c"), {"c": c})


def test_track_b_can_be_filed_without_a_qualification():
    """경력·훈련으로 하는 심사라 과정평가형 자격이 없는 것이 오히려 흔하다.

    화면은 Track B 에서 자격 없이 저장을 허용하는데 API 스키마가 최소 1개를
    강제해 422 를 뱉었다. 그 길로 접수한 적이 없어 드러나지 않았다 —
    실사례 4건은 API 를 거치지 않고 DB 에 바로 넣은 것이다.
    """
    _drop("R2026-9099")
    try:
        r = _client().post("/submissions", json={
            "case_number": "R2026-9099", "track": "B",
            "target_program_id": "양식조리_L4", "qualifications": [],
            "note": "자격 없이 경력만"})
        assert r.status_code == 202, r.text
        with session_scope() as s:
            n = s.execute(text("""SELECT count(*) FROM document d
                JOIN submission b ON b.id=d.submission_id
                WHERE b.case_number='R2026-9099'"""), {}).scalar_one()
        assert n == 0, "자격이 없는데 자격 문서가 들어갔다"
    finally:
        _drop("R2026-9099")


def test_track_a_still_needs_one():
    """Track A 는 보유 자격이 유일한 입력이라 없으면 돌릴 것이 없다."""
    _drop("R2026-9098")
    try:
        r = _client().post("/submissions", json={
            "case_number": "R2026-9098", "track": "A",
            "target_program_id": "양식조리_L4", "qualifications": []})
        assert r.status_code == 422
        assert "Track B" in r.json()["detail"], "무엇을 하라는지 말해야 한다"
    finally:
        _drop("R2026-9098")


def test_the_candidate_can_be_filed_through_the_api():
    """README 가 시키는 대로 화면에서 넣을 수 있어야 한다."""
    import yaml
    if not (SRC / "신청서.yaml").exists():
        pytest.skip("test/candidate01 이 없다")
    apply = yaml.safe_load((SRC / "신청서.yaml").read_text(encoding="utf-8"))
    case = "R2026-9097"
    _drop(case)
    try:
        r = _client().post("/submissions", json={
            "case_number": case, "track": "B",
            "target_program_id": apply["목표종목"],
            "qualifications": apply.get("보유자격") or [],
            "note": apply.get("비고")})
        assert r.status_code == 202, r.text
        assert r.json()["status"] == "received"
    finally:
        _drop(case)


# ── 문서 종류 어휘 ────────────────────────────────────────────────

def test_screen_and_code_agree_on_document_kinds():
    """화면이 내미는 목록과 코드가 견주는 이름이 같아야 한다.

    화면은 기준서의 `document_types` 를 그대로 내민다. 그런데 시간 대조가
    쓰는 이름은 코드에 따로 적혀 있어 갈라졌다 — 화면으로 올린 이수증이
    「추가 자료」로 세어졌다. 이제 기준서(`time_source`)가 정한다.
    """
    from krpl_core.config import get_rubric
    from services.assess.case_state import is_time_doc

    dt = get_rubric().document_types
    marked = {k for k, v in dt.items() if isinstance(v, dict) and v.get("time_source")}
    assert marked, "기준서에 time_source 표시가 하나도 없다"
    for k in marked:
        assert is_time_doc(k), f"기준서가 표시한 {k} 를 코드가 못 알아본다"
    for k in set(dt) - marked:
        assert not is_time_doc(k), f"표시 없는 {k} 가 시간 대조 자료로 잡힌다"


def test_legacy_free_text_names_still_match():
    """실사례 데이터는 자유 텍스트로 들어가 있다. 그것도 알아봐야 한다."""
    from services.assess.case_state import is_time_doc
    for old in ("NCS 기반 훈련과정 이수증", "교육과정 편성표", "과정평가형자격"):
        assert is_time_doc(old), old
    for other in ("경력증명서", "비NCS 교육 수료증", "작업일지 발췌"):
        assert not is_time_doc(other), other


def test_manifest_kinds_come_from_the_rubric(tiny):
    """접수목록에 자유 텍스트를 적으면 막는다 — 그래야 갈라지지 않는다."""
    _write_manifest(tiny, [{"파일": "경력기술서.txt", "종류": "내 맘대로 지은 종류",
                            "신뢰도등급": "E", "발급기관": "본인", "발급일": ""}])
    with pytest.raises(ValueError, match="모르는 서류 종류"):
        load_candidate.read_set(tiny)


@pytest.mark.skipif(not (SRC / "접수목록.csv").exists(), reason="test/candidate01 이 없다")
def test_the_real_manifest_uses_screen_vocabulary():
    from krpl_core.config import get_rubric
    _, docs = load_candidate.read_set(SRC)
    dt = get_rubric().document_types
    for d in docs:
        assert d["doc_type"] in dt, d["doc_type"]


@pytest.mark.skipif(not (SRC / "접수목록.csv").exists(), reason="test/candidate01 이 없다")
def test_time_documents_are_not_counted_as_extra():
    """이수증·편성표는 시간 대조가 이미 값을 뽑아 썼다. 두 번 세지 않는다."""
    from services.assess.case_state import case_state, is_time_doc
    cn, sid, _ = load_candidate.load(SRC)
    with session_scope() as s:
        st = case_state(s, sid)
    assert st.extra_docs, "추가 자료가 하나도 없다"
    assert not any(is_time_doc(d["doc_type"]) for d in st.extra_docs)
    assert st.n_documents - len(st.extra_docs) == 2, "이수증·편성표 2건이 빠져야 한다"


# ── 접수 뒤 어디로 가나 ───────────────────────────────────────────

def test_upload_screen_leads_to_the_case_overview():
    """서류를 올리고 나면 그 건의 심사 개요로 가야 한다.

    홈으로 보내고 있었다 — 개요 화면이 생기기 전에 쓴 코드다. 방금 올린 건을
    목록에서 다시 찾아야 했고, 다음 할 일(「근거 분석 시작」)도 거기 있다.
    """
    case = "R2026-9096"
    _drop(case)
    c = _client()
    try:
        r = c.post("/submissions", json={
            "case_number": case, "track": "B",
            "target_program_id": "양식조리_L4", "qualifications": []})
        sid = r.json()["id"]
        h = c.get(f"/submissions/{sid}/upload").text
        assert f"const next = `/submissions/${{SID}}`" in h, "업로드 뒤 갈 곳이 개요가 아니다"
        assert "location.href = next" in h
        assert "location.href = '/'" not in h, "아직 홈으로 보내는 자리가 남아 있다"
        assert f"location.href='/submissions/{sid}'\">나중에 하기" in h, \
            "「나중에 하기」도 개요로 가야 한다"
    finally:
        _drop(case)


def test_warnings_are_not_flashed_past():
    """경고가 있으면 넘기지 않는다 — 1.4초에 스쳐 지나가면 못 읽는다."""
    case = "R2026-9095"
    _drop(case)
    c = _client()
    try:
        sid = c.post("/submissions", json={
            "case_number": case, "track": "B",
            "target_program_id": "양식조리_L4", "qualifications": []}).json()["id"]
        h = c.get(f"/submissions/{sid}/upload").text
        assert "if (warn)" in h, "경고가 있을 때 멈추지 않는다"
        assert "그래도 계속" in h, "경고를 읽은 뒤 갈 길이 없다"
    finally:
        _drop(case)


# ── 서류 종류 자동 매칭 ───────────────────────────────────────────

def test_guess_endpoint_answers_for_every_name():
    c = _client()
    names = ["01_NCS기반_훈련과정_이수증.hwpx", "09_경력기술서.txt", "스캔0001.pdf"]
    r = c.post("/doc-types/guess", json={"names": names})
    assert r.status_code == 200
    d = r.json()
    assert [x["name"] for x in d] == names, "보낸 순서대로 돌려줘야 한다"
    assert d[0]["doc_type"] == "NCS기반_훈련이수증" and d[0]["grade"] == "B"
    assert d[0]["matched"], "무엇에 걸렸는지 말해야 한다"
    assert d[2]["doc_type"] is None, "못 맞히면 비운다"


def test_guess_endpoint_handles_an_empty_list():
    assert _client().post("/doc-types/guess", json={"names": []}).json() == []


def test_upload_screen_asks_the_server_and_never_guesses_on_its_own():
    """판별은 서버 한 곳에만 둔다 — 화면에도 같은 규칙을 두면 곧 갈라진다."""
    case = "R2026-9094"
    _drop(case)
    c = _client()
    try:
        sid = c.post("/submissions", json={
            "case_number": case, "track": "B",
            "target_program_id": "양식조리_L4", "qualifications": []}).json()["id"]
        h = c.get(f"/submissions/{sid}/upload").text
        assert "/doc-types/guess" in h, "화면이 판별을 물어보지 않는다"
        # 못 맞힌 것은 비워 두고, 목록 첫 항목을 조용히 넣지 않는다
        assert '<option value="">— 고르세요 —</option>' in h
        assert "Object.keys(DEFAULT_GRADE)[0]" not in h, \
            "아직 첫 항목을 기본값으로 넣는 자리가 남아 있다"
        # 종류를 못 정한 파일이 있으면 올리지 못한다
        assert "종류를 고르세요 (${left}건 남음)" in h
        assert "left > 0" in h
    finally:
        _drop(case)


def test_the_whole_real_set_is_guessed_correctly():
    """접수목록.csv 가 정답이다. 담당자가 하나도 안 고쳐도 되어야 한다."""
    if not (SRC / "접수목록.csv").exists():
        pytest.skip("test/candidate01 이 없다")
    _, docs = load_candidate.read_set(SRC)
    names = [Path(d["file_path"]).name for d in docs]
    got = _client().post("/doc-types/guess", json={"names": names}).json()
    wrong = [(n, g["doc_type"], d["doc_type"])
             for n, g, d in zip(names, got, docs) if g["doc_type"] != d["doc_type"]]
    assert not wrong, f"자동 매칭이 접수목록과 어긋난다: {wrong}"
