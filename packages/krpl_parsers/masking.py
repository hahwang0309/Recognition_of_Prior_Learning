"""식별정보 마스킹.

시스템은 심사번호만 다루지만 **제출 서류 원본에는 성명·주민번호가 남는다.**
LLM 전송 전에 여기서 제거한다. 설계서 제Ⅷ장의 '자동 마스킹' 조치.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 패턴명 → (정규식, 치환문자열)
PATTERNS: dict[str, tuple[re.Pattern, str]] = {
    # 900101-1234567 / 9001011234567
    "주민등록번호": (re.compile(r"\b(\d{6})[-\s]?([1-4]\d{6})\b"), r"\1-*******"),
    # 010-1234-5678 / 02-123-4567 / 01012345678
    "전화번호": (re.compile(r"\b(0\d{1,2})[-.\s]?(\d{3,4})[-.\s]?(\d{4})\b"), r"\1-****-****"),
    "이메일": (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "***@***"),
    # 110-123-456789. 날짜(2025-02-11)·전화·능력단위와 충돌하지 않도록
    # ① 첫 묶음이 4자리 연도(19xx·20xx)면 제외  ② 마지막 묶음이 5자리 이상이어야 계좌로 본다
    "계좌번호": (re.compile(r"\b(?!(?:19|20)\d{2}-)\d{2,6}-\d{2,6}-\d{5,8}\b"),
                "***-***-******"),
    # 여권 M12345678
    "여권번호": (re.compile(r"\b[A-Z]{1,2}\d{7,8}\b"), "********"),
}


@dataclass
class MaskHit:
    """어디서 무엇이 가려졌는지. **가려진 값 자체는 담지 않는다.**

    감사에 필요한 것은 「마스킹이 실제로 일어났다」는 사실과 위치이지
    가려진 값이 아니다. 값을 남기면 마스킹한 의미가 없다.
    """
    pattern: str
    line_no: int
    n_chars: int                   # 원래 값의 길이
    before: str                    # 앞 문맥 (값 제외)
    after: str                     # 뒤 문맥 (값 제외)

    def as_dict(self) -> dict:
        return {"유형": self.pattern, "줄": self.line_no, "가려진_글자수": self.n_chars,
                "앞": self.before, "뒤": self.after}


@dataclass
class MaskResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)
    hits: list[MaskHit] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


class Masker:
    def __init__(self, enabled: bool = True, patterns: list[str] | None = None):
        self.enabled = enabled
        names = patterns or list(PATTERNS)
        unknown = set(names) - set(PATTERNS)
        if unknown:
            raise ValueError(f"알 수 없는 마스킹 패턴: {sorted(unknown)}")
        self.active = {n: PATTERNS[n] for n in names}

    def __call__(self, text: str, *, trace: bool = False) -> MaskResult:
        """trace=True 면 감사용 위치 기록도 함께 만든다 (값은 담지 않는다)."""
        if not self.enabled or not text:
            return MaskResult(text)
        counts: dict[str, int] = {}
        hits: list[MaskHit] = []
        for name, (rx, repl) in self.active.items():
            if trace:
                for m in rx.finditer(text):
                    line = text.count("\n", 0, m.start()) + 1
                    hits.append(MaskHit(name, line, len(m.group()),
                                        text[max(0, m.start() - 14):m.start()].rsplit("\n", 1)[-1],
                                        text[m.end():m.end() + 14].split("\n", 1)[0]))
            text, n = rx.subn(repl, text)
            if n:
                counts[name] = n
        return MaskResult(text, counts, sorted(hits, key=lambda h: h.line_no))


def mask_text(text: str, patterns: list[str] | None = None) -> MaskResult:
    return Masker(True, patterns)(text)
