"""조각 번호(fid)에 무슨 자료인지 붙인다.

## 왜

`D09-S09` 는 기계가 조각을 가리키는 이름이다. 사람은 그것만 보고 무슨 자료인지
알 수 없다. 심사위원이 판단해야 하는 것은 「그 진술을 얼마나 믿을 수 있나」인데,
번호만으로는 본인 진술인지 기관 발급 서류인지조차 알 수 없다.

  ✗ 직무 수행 증거는 D09-S09 한 건뿐이고 그마저 D08-S06 과 어긋난다
  ○ 직무 수행 증거는 본인진술(D09-S09) 한 건뿐이고
     그마저 상급 신뢰도인 제3자 진술(D08-S06, D등급)과 어긋난다

## 어디를 고치나

두 곳에서 맨몸 fid 가 나온다.

  ① **AI 가 쓴 문장 안** — 권고 사유·소견·상충 설명. 프롬프트로 시키되,
     이미 만들어 둔 판정에도 소급해야 하므로 화면이 다시 쓴다.
  ② **자료 칸의 fid 목록** — `D03-P02,D03-P03,…`. 여기는 종류를 앞에 붙인다.

## 이미 이름이 붙은 것은 건드리지 않는다

AI 가 스스로 `D08-S06(제3자, D등급)` 이라고 적을 때가 있다. 그 앞에 또 붙이면
겹쳐 읽힌다. 바로 뒤가 여는 괄호면 그대로 둔다.
"""
from __future__ import annotations

import re
from functools import lru_cache

# 조각 번호 — `D09-S09`. 문서키(D + 두 자리) + 조각 종류 한 글자 + 두어 자리.
#
# `\b` 를 쓰면 안 된다. 파이썬 정규식에서 한글도 낱말 문자라
# 「D09-S13에서」의 `3` 과 `에` 사이에는 낱말 경계가 서지 않는다.
# 실측으로 그런 자리가 그대로 맨몸으로 남았다. 영숫자만 막는다.
FID = re.compile(r"(?<![\w-])D\d{2}-[A-Z]\d{2,3}(?![\dA-Za-z])")


@lru_cache(maxsize=1)
def _grade_labels() -> dict[str, str]:
    """A → 공적증빙 … E → 본인진술. 기준서가 정한다."""
    from krpl_core.config import get_rubric
    return {k: (v or {}).get("label") or k for k, v in get_rubric().grades.items()}


def grade_label(grade: str | None) -> str:
    g = (grade or "").strip().upper()[:1]
    return _grade_labels().get(g, "")


def name_of(fid: str, meta: dict[str, tuple[str, str]]) -> str:
    """이 조각을 뭐라고 부를까. 등급 이름이 신뢰도를 바로 말해 준다."""
    doc_type, grade = meta.get(fid, ("", ""))
    return grade_label(grade) or doc_type or ""


def label(text: str, meta: dict[str, tuple[str, str]]) -> str:
    """문장 안의 맨몸 fid 에 자료 이름을 붙인다.

    `meta` 는 {fid: (문서종류, 등급)}. 모르는 fid 는 그대로 둔다 —
    지어내는 것보다 낫다.

    ## 붙이지 않아야 하는 자리

    AI 가 스스로 설명을 붙일 때가 있고, 그 위에 또 붙이면 겹쳐 읽힌다.
    실측으로 이런 것들이 나왔다.

      「본인진술 D09-S09」        → 앞에 이미 이름이 있다
      「대응(D06-P04)」          → 이미 괄호 안이다. 괄호를 또 열면 겹친다
      「D08-S06(제3자, D등급)」   → 뒤에 설명이 붙어 있다
      「D10-P01~P07」            → 범위 표기. 뒤쪽을 건드리면 말이 깨진다
    """
    if not text:
        return text
    known = {k for k in meta}

    def sub(m: re.Match) -> str:
        fid = m.group(0)
        nm = name_of(fid, meta)
        if not nm or fid not in known:
            return fid
        before = text[max(0, m.start() - 14):m.start()]
        after = text[m.end():m.end() + 2]
        # 뒤에 설명이 붙었거나 범위 표기이면 그대로 둔다
        if after[:1] in ("(", "~", "-", "–"):
            return fid
        # 이미 괄호 안에 있으면 괄호를 또 열지 않고 이름만 앞에 붙인다
        opened = before.rfind("(") > before.rfind(")")
        # 바로 앞에 같은 이름이 이미 적혀 있으면 되풀이하지 않는다
        if before.rstrip().endswith(nm):
            return fid
        # 바로 앞이 가운뎃점이면 이름을 붙이지 않는다 —
        # 「산출물·기록(D07-L05)·산출물·기록(D10-P06)」처럼 이름 안의 점과
        # 잇는 점이 섞여 어디가 끊기는지 알 수 없게 된다.
        if before.rstrip().endswith(("·", "∙", "‧")):
            return fid
        return f"{nm} {fid}" if opened else f"{nm}({fid})"

    return FID.sub(sub, text)


def listing(fids: list[str], meta: dict[str, tuple[str, str]]) -> str:
    """fid 목록을 「종류 fid, fid」로. 같은 문서의 조각은 묶는다.

    `D03-P02,D03-P03,D04-P02` → `경력증명서 D03-P02·P03 · 4대보험_가입내역 D04-P02`
    """
    if not fids:
        return ""
    order: list[str] = []
    by_doc: dict[str, list[str]] = {}
    for f in fids:
        doc = meta.get(f, ("", ""))[0] or f.split("-")[0]
        if doc not in by_doc:
            order.append(doc)
            by_doc[doc] = []
        by_doc[doc].append(f)
    out = []
    for doc in order:
        got = by_doc[doc]
        head = got[0]
        rest = [g.split("-", 1)[1] for g in got[1:]]
        out.append(f"{doc} {head}" + ("·" + "·".join(rest) if rest else ""))
    return " · ".join(out)


def meta_of(s, submission_id: int) -> dict[str, tuple[str, str]]:
    """{fid: (문서종류, 등급)} 한 번에."""
    from sqlalchemy import text as _t
    return {r[0]: (r[1], r[2]) for r in s.execute(_t(
        "SELECT fid, doc_type, grade FROM fragment WHERE submission_id=:i"),
        {"i": submission_id})}
