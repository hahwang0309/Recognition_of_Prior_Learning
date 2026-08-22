"""문서 → 조각(fragment).

AI 인용의 기준 단위를 만든다. 조각마다 고유 ID(fid)를 부여하고,
그 ID로만 인용하게 하여 사후 검증이 가능하도록 한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

DocFormat = Literal["narrative", "record", "dated", "list"]

# 진술 유형 판별 — 우선순위 순
NEG = re.compile(r"(적이 없|본 적|해본 적|없습니다|없음|않았|못했|못합니다|아닙니다|아니고"
                 r"|아님|모릅니다|잘 모|알지 못|바 없|미편성|미실시)")
IND = re.compile(r"(통보받|지시에 따라|검사팀|수의사를 불|업체에서 받|왕진|별도로 진행|대신 하)")
UNC = re.compile(r"(같습니다|듯|아마|정도|수준입니다|가량|편입니다|따라 한|추정|참고해)")
FREQ = re.compile(r"(매일|매주|주 ?\d회|월 ?\d회|연 ?\d회|매년|상시|가끔|몇 차례|소량)")
DATE = re.compile(r"(\d{4}[-.]\d{1,2}([-.]\d{1,2})?)")
KV = re.compile(r"^[^:：|]{1,24}\s*[:：]\s*\S")          # "근무기간: 2018.03 ~"
SENT_END = re.compile(r"(다\.|요\.|음\.|함\.)\s*$")


@dataclass
class Fragment:
    fid: str
    text: str
    stype: str                     # 직접수행|관찰·간접|불확실|부정|기재사항|기록|산출물
    freq: str | None = None
    date: str | None = None


@dataclass
class StructuredDoc:
    doc_key: str
    doc_format: DocFormat
    fragments: list[Fragment] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


def detect_format(text: str) -> DocFormat:
    """형식 자동 판별. 담당자가 지정하면 그것을 우선한다."""
    lines = [l.strip() for l in text.split("\n") if len(l.strip()) >= 3]
    if not lines:
        return "narrative"
    n = len(lines)
    dated = sum(1 for l in lines if DATE.match(l))
    kv = sum(1 for l in lines if KV.match(l))
    sent = sum(1 for l in lines if SENT_END.search(l))

    if dated / n >= 0.5:
        return "dated"
    if kv / n >= 0.5:
        return "record"
    if sent / n >= 0.5:
        return "narrative"
    return "list"


def classify(text: str) -> str:
    if NEG.search(text):
        return "부정"
    if IND.search(text):
        return "관찰·간접"
    if UNC.search(text):
        return "불확실"
    return "직접수행"


def _split_narrative(text: str) -> list[str]:
    """문장 단위. 줄바꿈과 종결어미 둘 다 사용한다."""
    out: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"(?<=다\.)\s+|(?<=요\.)\s+", line)
        out.extend(p.strip() for p in parts if len(p.strip()) >= 6)
    return out


def structure(text: str, doc_key: str, doc_format: DocFormat | None = None) -> StructuredDoc:
    fmt: DocFormat = doc_format or detect_format(text)
    frags: list[Fragment] = []

    if fmt == "narrative":
        for i, s in enumerate(_split_narrative(text), 1):
            f = FREQ.search(s)
            frags.append(Fragment(f"{doc_key}-S{i:02d}", s, classify(s),
                                  f.group() if f else None))
    elif fmt == "dated":
        for i, s in enumerate([l.strip() for l in text.split("\n") if len(l.strip()) >= 6], 1):
            d = DATE.search(s)
            frags.append(Fragment(f"{doc_key}-L{i:02d}", s, "기록",
                                  date=d.group(1) if d else None))
    else:  # record | list
        tag = "기재사항" if fmt == "record" else "산출물"
        pre = "R" if fmt == "record" else "P"
        for i, s in enumerate([l.strip() for l in text.split("\n") if len(l.strip()) >= 3], 1):
            frags.append(Fragment(f"{doc_key}-{pre}{i:02d}", s, tag))

    stats: dict[str, int] = {}
    for f in frags:
        stats[f.stype] = stats.get(f.stype, 0) + 1
    return StructuredDoc(doc_key, fmt, frags, stats)


# ── 기이수 능력단위 추출 (R0 판단 근거) ──
UCODE = re.compile(r"\b(\d{10})(?:_(\d{2}[vV]\d+))?\b")
HRS = re.compile(r"(\d+)\s*시간")
PASSED = re.compile(r"(합격|이수|수료)")
NOT_EVAL = re.compile(r"(내부평가.{0,6}(실시하지|없|미실시)|평가결과 미기재|능력단위 대응 정보 없)")


@dataclass
class PriorLearning:
    unit_code: str
    completed_hours: int | None
    evaluation: str | None
    evaluated: bool                 # 내부평가 합격 확인 여부 — R0 성립 조건
    fid: str
    doc_key: str
    source_text: str


def extract_prior_learning(frags: list[Fragment], doc_key: str,
                           valid_units: set[str] | None = None) -> list[PriorLearning]:
    """조각에서 능력단위 코드·이수시간·평가결과를 뽑는다."""
    doc_text = "\n".join(f.text for f in frags)
    doc_not_eval = bool(NOT_EVAL.search(doc_text))   # 문서 전체에 '평가 미실시' 선언이 있는가

    out: dict[str, PriorLearning] = {}
    for f in frags:
        for m in UCODE.finditer(f.text):
            u = m.group(1)
            if valid_units is not None and u not in valid_units:
                continue
            h = HRS.search(f.text)
            pv = PASSED.search(f.text)
            pl = PriorLearning(
                unit_code=u,
                completed_hours=int(h.group(1)) if h else None,
                evaluation=pv.group(0) if pv else None,
                evaluated=bool(pv) and not doc_not_eval,
                fid=f.fid, doc_key=doc_key, source_text=f.text[:200],
            )
            prev = out.get(u)
            if prev is None or (pl.completed_hours or 0) > (prev.completed_hours or 0):
                out[u] = pl
    return sorted(out.values(), key=lambda x: -(x.completed_hours or 0))
