"""파일 이름으로 서류 종류를 알아맞힌다.

담당자가 파일 열한 개의 종류를 하나씩 고르는 것은 지루하고, 지루하면 대충
고른다. 종류를 잘못 고르면 등급도 따라 틀리고, 이수증을 놓치면 시간 대조가
통째로 어긋난다.

**틀리게 맞히는 것보다 못 맞혔다고 말하는 것이 낫다.**
"""
from __future__ import annotations

import pytest

from services.ingest.classify import guess, normalize

# 시험 지원자 자료의 실제 파일 이름 → 접수목록.csv 가 정답이다
REAL = [
    ("01_NCS기반_훈련과정_이수증.hwpx", "NCS기반_훈련이수증"),
    ("02_국가기술자격증.hwpx", "국가기술자격증"),
    ("03_경력증명서.hwpx", "경력증명서"),
    ("04_4대보험_가입내역.hwpx", "4대보험_가입내역"),
    ("05_정규교육_성적증명서.hwpx", "학위·성적증명서"),
    ("06_교육과정_편성표.hwpx", "교육과정_편성표"),
    ("07_주방일지_발췌.txt", "작업일지·업무일지"),
    ("08_총주방장_확인서.txt", "제3자_확인서"),
    ("09_경력기술서.txt", "경력기술서·자기소개서"),
    ("10_조리_포트폴리오.txt", "포트폴리오·산출물"),
    ("11_면접_예비답변.txt", "경력기술서·자기소개서"),
]

# 실제로 오는 이름들 — 사본·최종·날짜·공백 구분이 붙는다
MESSY = [
    ("경력증명서(사본).pdf", "경력증명서"),
    ("2026_경력기술서_최종.txt", "경력기술서·자기소개서"),
    ("작업일지 발췌 20250114.txt", "작업일지·업무일지"),
    ("NCS기반 훈련과정 이수증.hwp", "NCS기반_훈련이수증"),
    ("용접기능사 자격증.pdf", "국가기술자격증"),
    ("졸업증명서.pdf", "학위·성적증명서"),
    ("반장 확인서.txt", "제3자_확인서"),
    ("건강보험 자격득실 확인서.pdf", "4대보험_가입내역"),
]


@pytest.mark.parametrize("name,want", REAL)
def test_the_real_file_names_are_recognised(name, want):
    g = guess(name)
    assert g.doc_type == want, f"{name} → {g.doc_type} (걸린 말: {g.matched!r})"


@pytest.mark.parametrize("name,want", MESSY)
def test_messy_names_are_recognised(name, want):
    assert guess(name).doc_type == want, name


def test_specific_beats_generic():
    """「비NCS_교육수료증」과 「수료증」이 같이 걸리면 구체적인 쪽이 맞다."""
    assert guess("비NCS_교육수료증.pdf").doc_type == "비NCS_교육수료증"
    assert guess("교육수료증.pdf").doc_type == "비NCS_교육수료증"
    # 훈련이수증은 수료증이 아니다 — 능력단위 코드를 담고 있어 시간 대조에 쓰인다
    assert guess("직업훈련 이수증.hwpx").doc_type == "NCS기반_훈련이수증"


def test_a_confirmation_letter_is_not_an_insurance_record():
    """「자격득실 확인서」는 확인서지만 4대보험 자료다. 긴 쪽이 이긴다."""
    assert guess("자격득실확인서.pdf").doc_type == "4대보험_가입내역"
    assert guess("총주방장 확인서.txt").doc_type == "제3자_확인서"


@pytest.mark.parametrize("name", ["스캔0001.pdf", "무제.txt", "", "   ", "20260620.pdf"])
def test_unrecognised_names_stay_empty(name):
    """못 맞히면 비운다. 목록의 첫 항목을 조용히 넣으면 담당자가 그대로 두는
    순간 자기소개서가 공적증빙 A등급으로 들어간다."""
    g = guess(name)
    assert g.doc_type is None and g.grade is None and not g.ok


def test_grade_comes_from_the_rubric():
    from krpl_core.config import get_rubric
    dt = get_rubric().document_types
    for name, want in REAL:
        g = guess(name)
        assert g.grade == dt[want]["grade"], name


def test_it_says_which_word_it_matched():
    """왜 그렇게 봤는지 화면이 보여 줄 수 있어야 한다."""
    g = guess("01_NCS기반_훈련과정_이수증.hwpx")
    assert g.matched and g.matched in normalize("01_NCS기반_훈련과정_이수증.hwpx")


def test_every_document_type_can_be_reached_by_its_own_name():
    """기준서에 종류를 새로 넣고 별칭을 안 달아도, 이름 그대로는 걸려야 한다."""
    from krpl_core.config import get_rubric
    for name in get_rubric().document_types:
        assert guess(f"{name}.pdf").doc_type is not None, name


def test_normalize_strips_the_noise():
    assert normalize("01_경력_증명서(최종).pdf") == "경력증명서"
    assert normalize("작업일지 발췌 20250114.txt") == "작업일지발췌"
    assert normalize("경력증명서 사본.hwp") == "경력증명서"
