"""파일 이름으로 서류 종류를 알아맞힌다.

## 왜

담당자가 파일 열한 개의 종류를 하나씩 고르는 것은 지루하고, 지루하면 대충
고른다. 종류를 잘못 고르면 등급도 따라 틀리고, 이수증을 놓치면 시간 대조가
통째로 어긋난다.

이름은 대개 정직하다 — `01_NCS기반_훈련과정_이수증.hwpx`. 거기서 읽어 낸다.

## 못 맞히면 비워 둔다

**틀리게 맞히는 것보다 못 맞혔다고 말하는 것이 낫다.** 예전에는 목록의 첫
항목(국가기술자격증)을 조용히 넣어 두었다 — 담당자가 그대로 두면 자기소개서가
공적증빙 A등급으로 들어간다. 못 맞힌 것은 비워 두고 화면이 표시한다.

## 어휘는 기준서에 있다

무엇을 무엇으로 볼지는 정책이므로 `document_types.*.aliases` 가 정한다.
코드에 적어 두면 화면 목록과 갈라진다 — 실제로 그런 일이 있었다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from krpl_core.config import get_rubric

# 견줄 때 지우는 것 — 번호·구분자·확장자·괄호. 「01_경력_증명서(최종).pdf」 → 「경력증명서」
_DROP = re.compile(r"[\s_·∙‧・\-–—.,()\[\]{}<>'\"]+")
_SEQ = re.compile(r"^\d+")          # 앞머리 일련번호
_TAIL = re.compile(r"(사본|원본|최종|수정|스캔|복사본|제출용|\d{4}년?|\d{6,8})$")


def normalize(s: str) -> str:
    """이름을 견주기 좋게 다듬는다. 한글 자모 결합도 맞춘다(NFC)."""
    s = unicodedata.normalize("NFC", s or "").lower()
    s = s.rsplit(".", 1)[0] if "." in s else s          # 확장자
    s = _DROP.sub("", s)
    s = _SEQ.sub("", s)
    for _ in range(3):                                   # 「…사본최종」처럼 겹칠 수 있다
        s2 = _TAIL.sub("", s)
        if s2 == s:
            break
        s = s2
    return s


@dataclass(frozen=True)
class Guess:
    doc_type: str | None
    grade: str | None
    matched: str = ""          # 어느 말에 걸렸는지 — 왜 그렇게 봤는지 보여 준다

    @property
    def ok(self) -> bool:
        return self.doc_type is not None


@lru_cache(maxsize=1)
def _table() -> list[tuple[str, str, str]]:
    """(별칭, 종류, 등급). 긴 별칭이 앞에 온다 — 구체적인 것이 이겨야 한다.

    「비NCS_교육수료증」과 「수료증」이 같이 걸리면 앞의 것이 맞다.
    """
    out: list[tuple[str, str, str]] = []
    for name, spec in (get_rubric().document_types or {}).items():
        if not isinstance(spec, dict):
            continue
        grade = spec.get("grade") or "C"
        words = list(spec.get("aliases") or []) + [name]
        for w in words:
            n = normalize(str(w))
            if n:
                out.append((n, name, grade))
    return sorted(out, key=lambda x: -len(x[0]))


def guess(filename: str) -> Guess:
    """파일 이름 하나를 종류로. 못 맞히면 `doc_type` 이 None."""
    n = normalize(filename)
    if not n:
        return Guess(None, None)
    for alias, name, grade in _table():
        if alias in n:
            return Guess(name, grade, alias)
    return Guess(None, None)


def guess_many(names: list[str]) -> list[Guess]:
    return [guess(x) for x in names]
