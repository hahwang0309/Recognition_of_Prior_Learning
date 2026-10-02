"""KSA 레이블 조회 — 「기술1」이 무슨 기술인지.

## 왜 필요한가

화면이 `기술1 · 미확보` 라고만 적으면 심사위원은 무엇이 비었는지 알 수 없다.
그 번호는 고시 원문의 자리표일 뿐이고, 뜻은 `catalog_ncs_ksa` 에 있다.
`기술1` → 「예열 기구 사용 기술」.

## 중복

한 KSA 는 수행준거(pc_no)마다 되풀이 저장돼 있다. 같은
(능력단위, 요소번호, 유형, 번호)면 글이 같으므로 아무 행이나 쓰면 된다.
실측: 1601050111 요소1 의 기술1 이 4행, 서로 다른 글은 1개.
"""
from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.orm import Session

# AI 가 내놓는 참조 형식. 「기술1」·「지식12」·「태도3」 — 2026-10-02 부터 「준거1」(수행준거)도.
REF = re.compile(r"^\s*(기술|지식|태도|준거)\s*(\d+)\s*$")


def parse_ref(ref: str) -> tuple[str, int] | None:
    m = REF.match(ref or "")
    return (m.group(1), int(m.group(2))) if m else None


def element_no(element_id: str) -> int | None:
    """`1601050111_21v3.2` → 2. 버전 표기 안의 점과 헷갈리지 않게 뒤에서 자른다."""
    tail = (element_id or "").rsplit(".", 1)
    return int(tail[-1]) if len(tail) == 2 and tail[-1].isdigit() else None


def labels(s: Session, element_ids: list[str]) -> dict[tuple[str, str], str]:
    """{(element_id, "기술1"): "예열 기구 사용 기술"}.

    한 번에 조회한다 — 요소 서른 개를 한 줄씩 물으면 서른 번 왕복한다.
    """
    keys = [(eid, eid.split("_")[0], element_no(eid)) for eid in element_ids]
    pairs = [(u, n) for _, u, n in keys if n is not None]
    if not pairs:
        return {}
    rows = s.execute(text("""
        SELECT DISTINCT ON (unit_code, element_no, ksa_type, ksa_no)
               unit_code, element_no, ksa_type, ksa_no, ksa_text
        FROM catalog_ncs_ksa
        WHERE (unit_code, element_no) IN (
            SELECT * FROM unnest(CAST(:u AS text[]), CAST(:n AS int[])))
        ORDER BY unit_code, element_no, ksa_type, ksa_no"""),
        {"u": [u for u, _ in pairs], "n": [n for _, n in pairs]}).all()

    by_unit: dict[tuple[str, int], dict[str, str]] = {}
    for unit, no, typ, num, txt in rows:
        by_unit.setdefault((unit, no), {})[f"{typ}{num}"] = txt
    # 수행준거 「준거n」 — 신형(2026-10-02) 판정의 참조 단위. 같은 사전에 넣어 label_of 가 한 길로 찾게 한다.
    for unit, no, num, txt in s.execute(text("""
        SELECT unit_code, element_no, pc_no, pc_text FROM catalog_ncs_pc
        WHERE (unit_code, element_no) IN (
            SELECT * FROM unnest(CAST(:u AS text[]), CAST(:n AS int[])))"""),
        {"u": [u for u, _ in pairs], "n": [n for _, n in pairs]}).all():
        by_unit.setdefault((unit, no), {})[f"준거{num}"] = txt

    out: dict[tuple[str, str], str] = {}
    for eid, unit, no in keys:
        for ref, txt in (by_unit.get((unit, no)) or {}).items():
            out[(eid, ref)] = txt
    return out


def label_of(lookup: dict[tuple[str, str], str], element_id: str, ref: str) -> str:
    """찾지 못하면 빈 문자열. 화면은 번호만이라도 보여 준다."""
    p = parse_ref(ref)
    return lookup.get((element_id, f"{p[0]}{p[1]}"), "") if p else ""


def pretty_ref(ref: str) -> str:
    """「기술1」 → 「기술 1」. 번호가 붙어 있으면 읽기 어렵다."""
    p = parse_ref(ref)
    return f"{p[0]} {p[1]}" if p else (ref or "")
