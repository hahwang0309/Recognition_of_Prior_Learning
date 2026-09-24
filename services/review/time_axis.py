"""시간·기간 축 — 표시용 추정 (v1).

3차 TF: 「내용 일치성이 앞단, 시간은 보조지표」. App 은 Track B 에서 시간을 계산하지 않으므로
문서 조각에서 「n시간」과 「yyyy.mm ~ yyyy.mm / 현재」를 읽어 상·중·하만 매긴다.
App 본 계산이 아니다 — 화면에 「표시용 추정」으로 적는다. 나중에 본 계산이 생기면 이 모듈만 바꾼다.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

HOURS_TYPES = {"비NCS_교육수료증", "사내·기관_교육이수내역", "NCS기반_훈련이수증", "교육과정_편성표"}
PERIOD_TYPES = {"경력증명서", "4대보험_가입내역", "직무능력인정서", "고용보험_이력"}

_H = re.compile(r"(\d{2,4})\s*시간")
_D = re.compile(r"(20\d\d)\s*[.\-/년]\s*(\d{1,2})")
_RANGE = re.compile(r"(20\d\d\s*[.\-/년]\s*\d{1,2}(?:\s*[.\-/월]\s*\d{1,2})?)\s*[~∼–-]\s*(20\d\d\s*[.\-/년]\s*\d{1,2}(?:\s*[.\-/월]\s*\d{1,2})?|현재|재직\s*중)")


def _ym(s: str) -> tuple[int, int] | None:
    m = _D.search(s)
    return (int(m.group(1)), int(m.group(2))) if m else None


def extract(fragments: list[dict[str, Any]], today: date | None = None) -> dict[str, Any]:
    """조각 목록(doc_type·text·fid) → {hours, months, sources}."""
    today = today or date.today()
    hours, months = 0, 0
    src: list[str] = []
    for f in fragments:
        t, dt = f.get("text") or "", f.get("doc_type") or ""
        if dt in HOURS_TYPES:
            for m in _H.finditer(t):
                v = int(m.group(1))
                if v > hours and v <= 5000:
                    hours, src = v, [f.get("fid", "")]
        if dt in PERIOD_TYPES:
            for m in _RANGE.finditer(t):
                a, b = _ym(m.group(1)), _ym(m.group(2))
                if a is None:
                    continue
                if b is None:                                   # 현재 · 재직 중
                    b = (today.year, today.month)
                n = (b[0] - a[0]) * 12 + (b[1] - a[1])
                if n > months:
                    months, src = n, [f.get("fid", "")]
    return {"hours": hours or None, "months": months or None, "sources": src}


def band(required_hours: int, axis: dict[str, Any], rubric) -> tuple[str, str]:
    """(상|중|하, 설명). 시간이 있으면 요구시간 대비, 없으면 경력 개월로.

    required_hours 에는 **종목 총 요구시간**을 넘긴다. 과정 하나(예: 120시간)를 단위마다 견주면
    모든 단위가 「상」이 되어 뜻이 없다. 이 문턱(총 요구시간 100%/50% · 12/6개월)은 표시용이며
    rubric 에 없다 — 파라미터 표에 「표시용 추정」으로 적는다.
    """
    th = rubric.training_hours
    hi = 1.0
    lo = th.get("adjustment_floor", 0.5)
    if axis.get("hours"):
        h = axis["hours"]
        r = h / required_hours if required_hours else 0
        b = "상" if r >= hi else "중" if r >= lo else "하"
        return b, f"{h}/{required_hours}h"
    if axis.get("months"):
        m = axis["months"]
        b = "상" if m >= 12 else "중" if m >= 6 else "하"
        return b, f"경력 {m // 12}년 {m % 12}개월 (교육시간 없음)"
    return "하", "확인 불가"
