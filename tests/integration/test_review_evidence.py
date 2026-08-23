"""검토 화면의 근거·미확보 표시.

「기술1」·「태도3」만 적으면 무엇이 비었는지 알 수 없다. 뜻은 고시 원문
(`catalog_ncs_ksa`)에 있으므로 화면이 거기서 가져와 붙인다.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from krpl_core.db import session_scope
from services.catalog import label_of, labels, pretty_ref
from services.gateway.api import app

CASE = "R2026-0002"


@pytest.fixture(scope="module", autouse=True)
def demo_data():
    with session_scope() as s:
        if s.execute(text("SELECT 1 FROM submission WHERE case_number=:c"),
                     {"c": CASE}).first() is None:
            sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
            try:
                import load_demo
                load_demo.load()
            except FileNotFoundError as ex:
                pytest.skip(f"실사례 원본 없음: {ex}")


@pytest.fixture(scope="module")
def aid():
    with session_scope() as s:
        v = s.execute(text("""SELECT a.id FROM assessment a
            JOIN submission s ON s.id=a.submission_id
            WHERE s.case_number=:c AND a.kind='evidence' AND a.status='done'
            ORDER BY a.id DESC LIMIT 1"""), {"c": CASE}).scalar()
    if v is None:
        pytest.skip("근거 분석 결과 없음")
    return v


@pytest.fixture(scope="module")
def page(aid):
    with TestClient(app) as c:
        return c.get(f"/assessments/{aid}/review").text


@pytest.fixture(scope="module")
def payloads(aid):
    with session_scope() as s:
        return [dict(r) for r in s.execute(text("""
            SELECT element_id, payload FROM assessment_element
            WHERE assessment_id=:a ORDER BY element_id"""), {"a": aid}).mappings()]


# ── KSA 레이블 ────────────────────────────────────────────────────

def test_every_reference_resolves_to_a_label(payloads):
    """화면에 뜨는 모든 KSA 참조가 고시 원문의 이름으로 이어져야 한다."""
    with session_scope() as s:
        lab = labels(s, [x["element_id"] for x in payloads])
    missing = []
    for x in payloads:
        p = x["payload"]
        refs = [v.get("ksa_ref") for v in (p.get("evidence") or [])]
        refs += [(u.get("ref") if isinstance(u, dict) else u)
                 for u in (p.get("uncovered_ksa") or [])]
        for r in filter(None, refs):
            if not label_of(lab, x["element_id"], r):
                missing.append((x["element_id"], r))
    assert not missing, f"이름을 못 찾은 참조: {missing[:8]}"


def test_labels_appear_on_screen(page, payloads):
    with session_scope() as s:
        lab = labels(s, [x["element_id"] for x in payloads])
    shown = {v for v in lab.values() if v}
    assert shown, "레이블이 하나도 없다"
    hit = sum(1 for v in shown if v in page)
    assert hit >= 10, f"화면에 실제 이름이 거의 없다 ({hit}개)"


def test_bare_reference_never_stands_alone(page):
    """「기술1 · 미확보」처럼 번호만 적힌 자리가 남아 있으면 안 된다."""
    assert not re.search(r"(기술|지식|태도)\d+\s*·\s*(미확보|부정진술)", page)


def test_reference_is_spaced_for_reading(page):
    assert ('<span class="ref">기술 1</span>' in page
            or '<span class="ref">지식 1</span>' in page)
    assert pretty_ref("기술1") == "기술 1"


# ── 표 ────────────────────────────────────────────────────────────

def test_evidence_is_a_table(page):
    assert "<th>KSA</th><th>근거 인용문</th><th>자료</th><th>원문</th>" in page


def test_uncovered_is_a_table_with_reasons(page, payloads):
    assert "<th>KSA</th><th>왜 비어 있나</th><th>구분</th>" in page
    # AI 가 남긴 「왜 비었나」를 버리지 않는다 — 예전에는 통째로 사라졌다
    notes = [u.get("note") for x in payloads
             for u in (x["payload"].get("uncovered_ksa") or [])
             if isinstance(u, dict) and u.get("note")]
    assert notes, "대조할 note 가 없다"
    assert sum(1 for n in set(notes) if n in page) >= 3, "미확보 사유가 화면에 없다"


def test_grade_letters_carry_their_meaning(page, payloads):
    """「E등급」만 봐서는 무슨 자료인지 알 수 없다.

    이 건에 실제로 쓰인 등급만 본다 — A(공적증빙) 근거가 없는 사례도 있다.
    """
    from services.report.track_b_review import GRADE_KO
    used = {(v.get("grade") or "").strip().upper()[:1]
            for x in payloads for v in (x["payload"].get("evidence") or [])}
    used |= {g for x in payloads
             for g in ((x["payload"].get("period_backing") or {}).get("grades") or [])}
    used = {g for g in used if g in GRADE_KO}
    assert used, "등급이 붙은 근거가 없다"
    for g in sorted(used):
        assert GRADE_KO[g] in page, f"{g}등급의 뜻 「{GRADE_KO[g]}」 이 없다"


def test_source_names_the_document(page):
    """fid(D07-S03)만으로는 무슨 서류인지 알 수 없다."""
    with session_scope() as s:
        kinds = {r[0] for r in s.execute(text("""
            SELECT DISTINCT doc_type FROM document d
            JOIN submission b ON b.id=d.submission_id WHERE b.case_number=:c"""),
            {"c": CASE})}
    assert sum(1 for k in kinds if k in page) >= 3, "자료 칸에 서류 이름이 없다"


# ── 다른 능력단위 이수 기록 ────────────────────────────────────────

def test_cross_unit_evidence_is_flagged(page, payloads):
    """다른 능력단위 이수로 이 단위의 KSA 를 뒷받침한 것은 드러내야 한다."""
    n = 0
    for x in payloads:
        own = x["element_id"].split("_")[0]
        for v in x["payload"].get("evidence") or []:
            m = re.match(r"\s*(\d{10})[_\s]", v.get("quote") or "")
            if m and m.group(1) != own:
                n += 1
    if not n:
        pytest.skip("이 사례에는 타단위 근거가 없다")
    assert page.count("⚠ 다른 능력단위(") == n, f"{n}건 가운데 일부가 표시되지 않았다"
    assert "타단위 근거" in page, "요소 줄에 건수가 세어져 있지 않다"


# ── 화면에 새면 안 되는 것 ────────────────────────────────────────

def test_no_control_characters_leak(page):
    r"""CSS 유니코드 이스케이프를 파이썬 문자열에 쓰면 8진 이스케이프로 먹힌다.

    실제로 `quotes:'\201C'` 가 U+0081 이 되어 화면에 「·C인용문·D」로 나왔다.
    """
    bad = {hex(ord(c)) for c in page if ord(c) < 32 and c not in "\n\r\t"}
    bad |= {hex(ord(c)) for c in page if 0x7F <= ord(c) <= 0x9F}
    assert not bad, f"제어문자가 화면에 들어 있다: {sorted(bad)}"


def test_context_button_only_when_it_adds_something(page, aid):
    """원문이 인용문과 (문장부호만 빼고) 같으면 눌러도 같은 글자만 나온다."""
    with session_scope() as s:
        sid = s.execute(text("SELECT submission_id FROM assessment WHERE id=:a"),
                        {"a": aid}).scalar()
        frags = {r[0]: r[1] for r in s.execute(text(
            "SELECT fid, text FROM fragment WHERE submission_id=:i"), {"i": sid})}
        els = [dict(r) for r in s.execute(text(
            "SELECT payload FROM assessment_element WHERE assessment_id=:a"),
            {"a": aid}).mappings()]
    norm = lambda x: re.sub(r"[\s.。·,、]+", "", x or "")   # noqa: E731
    want = sum(1 for x in els for v in (x["payload"].get("evidence") or [])
               for f in (v.get("fids") or [])
               if frags.get(f) and norm(frags[f]) != norm(v.get("quote")))
    assert page.count(">문맥</button>") == want


def test_element_row_shows_the_hours_at_stake(page):
    """몇 시간짜리 판단인지 보이지 않으면 경중을 가릴 수 없다."""
    assert re.search(r'<span class="un">[^<]*\d+시간</span>', page)
