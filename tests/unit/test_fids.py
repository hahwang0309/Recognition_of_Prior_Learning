"""조각 번호(fid)에 무슨 자료인지 붙인다.

`D09-S09` 는 기계가 조각을 가리키는 이름이다. 사람은 그것만 보고 무슨 자료인지
알 수 없다 — 본인 진술인지 기관 발급 서류인지조차 알 수 없다.

  ✗ 직무 수행 증거는 D09-S09 한 건뿐이고 그마저 D08-S06 과 어긋난다
  ○ 직무 수행 증거는 본인진술(D09-S09) 한 건뿐이고
     그마저 상급 신뢰도인 제3자 진술(D08-S06, D등급)과 어긋난다
"""
from __future__ import annotations

import pytest

from services.report.fids import FID, grade_label, label, listing, name_of

META = {
    "D09-S09": ("경력기술서·자기소개서", "E"),
    "D09-S13": ("경력기술서·자기소개서", "E"),
    "D08-S06": ("제3자_확인서", "D"),
    "D03-P02": ("경력증명서", "B"),
    "D03-P03": ("경력증명서", "B"),
    "D04-P02": ("4대보험_가입내역", "A"),
    "D10-P01": ("포트폴리오·산출물", "C"),
    "D07-L05": ("작업일지·업무일지", "C"),
}


def test_grade_labels_come_from_the_rubric():
    assert grade_label("E") == "본인진술"
    assert grade_label("D") == "제3자진술"
    assert grade_label("A") == "공적증빙"
    assert grade_label(None) == "" and grade_label("Z") == ""


def test_a_bare_fid_gets_a_name():
    assert label("증거는 D09-S09 한 건뿐이다", META) == "증거는 본인진술(D09-S09) 한 건뿐이다"


def test_hangul_right_after_the_fid_still_matches():
    """파이썬 정규식에서 한글도 낱말 문자라 `\\b` 로는 잡히지 않는다.
    실측으로 「D09-S13에서」가 그대로 맨몸으로 남았다."""
    assert label("D09-S13에서 수료증이 없다고 진술", META).startswith("본인진술(D09-S13)에서")


def test_an_unknown_fid_is_left_alone():
    """지어내는 것보다 그대로 두는 편이 낫다."""
    assert label("모르는 조각 D99-Z99 는 그대로", META) == "모르는 조각 D99-Z99 는 그대로"


# ── 겹쳐 쓰지 않는다 ──────────────────────────────────────────────

def test_a_name_already_written_is_not_repeated():
    """AI 가 「본인진술 D09-S09」라고 쓸 때가 있다. 또 붙이면 겹친다."""
    assert label("본인진술 D09-S09 한 건", META) == "본인진술 D09-S09 한 건"


def test_an_explanation_already_attached_is_left_alone():
    """「D08-S06(제3자, D등급)」 — 뒤에 설명이 붙어 있다."""
    got = label("그마저 D08-S06(제3자, D등급)과 어긋난다", META)
    assert got == "그마저 D08-S06(제3자, D등급)과 어긋난다"


def test_inside_parentheses_it_does_not_open_another():
    """이미 괄호 안이면 괄호를 또 열지 않는다 — 「대응(기관발급(D06-P04))」."""
    got = label("교과에 대응(D03-P02), 평가기록 없음", META)
    assert got == "교과에 대응(기관발급 D03-P02), 평가기록 없음"   # D03 은 B등급
    assert "((" not in got


def test_a_range_is_left_alone():
    """「D10-P01~P07」은 범위 표기다. 앞을 건드리면 말이 깨진다."""
    assert label("포트폴리오 8건(D10-P01~P07)", META) == "포트폴리오 8건(D10-P01~P07)"


def test_a_middle_dot_before_it_is_left_alone():
    """이름 안의 가운뎃점과 잇는 점이 섞이면 어디가 끊기는지 알 수 없다 —
    「산출물·기록(D07-L05)·산출물·기록(D10-P01)」."""
    got = label("D07-L05·D10-P01 의 산출물", META)
    assert got.count("(") == 1, got


# ── 목록 ──────────────────────────────────────────────────────────

def test_a_list_groups_by_document():
    got = listing(["D03-P02", "D03-P03", "D04-P02"], META)
    assert got == "경력증명서 D03-P02·P03 · 4대보험_가입내역 D04-P02"


def test_an_empty_list_is_empty():
    assert listing([], META) == ""


def test_an_unknown_fid_falls_back_to_its_document_key():
    assert "D99" in listing(["D99-Z01"], {})


# ── 무엇으로 부르나 ───────────────────────────────────────────────

def test_the_grade_name_wins_over_the_document_type():
    """신뢰도가 판단의 핵심이라 등급 이름을 앞세운다."""
    assert name_of("D08-S06", META) == "제3자진술"
    assert name_of("D09-S09", META) == "본인진술"


def test_a_document_with_no_grade_falls_back_to_its_type():
    assert name_of("X", {"X": ("경력증명서", "")}) == "경력증명서"


@pytest.mark.parametrize("s,ok", [
    ("D09-S09", True), ("D09-S099", True), ("D9-S09", False),
    ("D09S09", False), ("XD09-S09", False), ("D09-s09", False),
])
def test_what_counts_as_a_fid(s, ok):
    assert bool(FID.fullmatch(s)) is ok


def test_the_prompt_tells_the_model_the_same_rule():
    """화면이 뒤늦게 붙이는 것보다 처음부터 잘 쓰는 편이 낫다."""
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "config/prompts/trackb_v5.md"
    t = p.read_text(encoding="utf-8")
    assert "조각 번호에는 무슨 자료인지 붙인다" in t
    assert "본인진술(D09-S09)" in t
