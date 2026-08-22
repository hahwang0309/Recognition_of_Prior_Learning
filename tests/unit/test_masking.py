"""마스킹 회귀 시험.

식별정보는 반드시 지우되, **증거를 훼손하면 안 된다.**
작업일지의 날짜가 계좌번호로 오인되어 지워진 사고가 있었다.
"""
import pytest

from krpl_parsers import mask_text

MUST_MASK = [
    ("주민등록번호", "홍길동 900101-1234567"),
    ("주민등록번호", "9001011234567 확인"),
    ("전화번호", "연락처 010-1234-5678"),
    ("전화번호", "02-123-4567 로 연락"),
    ("이메일", "hong@example.com 으로 회신"),
    ("계좌번호", "국민 110-123-456789 입금"),
    ("여권번호", "여권 M12345678"),
]

MUST_KEEP = [
    "2025-03-04 | 3동 입추 준비. 계사 세척 완료.",          # ← 실제 사고 사례
    "2025-02-11 | 블록 3-A 맞대기용접. 판두께 12mm.",
    "근무기간: 2018.03.02 ~ 2026.06.30 (8년 4개월)",
    "취득일 2020.08.14 · 자격번호 20○○○○○○",
    "능력단위 1601050111_21v3 피복아크용접 120시간",
    "전류 260A 전압 28V 와이어 1.2mm 가스유량 20L/min",
    "산란율 91.2%. 사료요구율 2.1~2.3. 폐사 3수.",
    "커밋 1,240건 · 최근 커밋 2026.05",
    "훈련기간: 2019.09.04 ~ 2024.02.29 (총 960시간)",
]


@pytest.mark.parametrize("kind,src", MUST_MASK)
def test_must_mask(kind, src):
    r = mask_text(src)
    assert kind in r.counts, f"{kind} 미검출: {src}"
    assert "***" in r.text or "*******" in r.text


@pytest.mark.parametrize("src", MUST_KEEP)
def test_must_not_mask(src):
    r = mask_text(src)
    assert r.total == 0, f"오탐 {r.counts}: {src} → {r.text}"
    assert r.text == src


def test_masking_disabled():
    from krpl_parsers import Masker
    assert Masker(False)("주민번호 900101-1234567").total == 0


def test_selected_patterns_only():
    from krpl_parsers import Masker
    r = Masker(True, ["이메일"])("a@b.com 010-1234-5678")
    assert "이메일" in r.counts and "전화번호" not in r.counts


def test_unknown_pattern_rejected():
    from krpl_parsers import Masker
    with pytest.raises(ValueError, match="알 수 없는"):
        Masker(True, ["없는패턴"])
