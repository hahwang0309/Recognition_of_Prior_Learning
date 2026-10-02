"""NCS 구조 조회 — 능력단위 → 요소 → 수행준거(·KSA). 한 곳에서만 읽는다.

2026-10-02: 판정 단위가 KSA 항목에서 **수행준거**로 바뀌었다(4차 TF). 수행준거는
`catalog_ncs_pc` 에 (unit_code, element_no, pc_no) 로 있고, 참조는 「준거1」「준거2」…
(pc_no 순). 이 DB 의 KSA 는 수행준거에 연결돼 있지 않다 — 요소의 KSA 전부가
모든 pc_no 아래 똑같이 복사돼 있다(2026-10-02 실측, 47,617 요소 예외 0). 그래서
수행준거↔KSA 매핑은 만들 수 없고, KSA 는 구형(항목 단위) 판정을 읽을 때만 쓴다.

전에는 같은 조회가 coverage.py · track_b_panel.py · plan.py 에 셋 있었다.
"""
from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.orm import Session

PC_REF = re.compile(r"^\s*준거\s*(\d+)\s*$")


def pc_ref(no: int) -> str:
    return f"준거{no}"


def parse_pc_ref(ref: str) -> int | None:
    m = PC_REF.match(ref or "")
    return int(m.group(1)) if m else None


def element_no(element_id: str) -> int | None:
    """`1601050111_21v3.2` → 2. 판 표기의 점과 헷갈리지 않게 뒤에서 자른다."""
    tail = (element_id or "").rsplit(".", 1)
    return int(tail[-1]) if len(tail) == 2 and tail[-1].isdigit() else None


def unit_of(element_id: str) -> str:
    return (element_id or "").split("_", 1)[0]


def pcs_of(s: Session, unit_codes: list[str]) -> dict[tuple[str, int], list[dict]]:
    """{(unit_code, element_no): [{"ref": "준거1", "no": 1, "text": "…할 수 있다."}, …]} — pc_no 순."""
    out: dict[tuple[str, int], list[dict]] = {}
    if not unit_codes:
        return out
    for uc, en, no, txt in s.execute(text("""
        SELECT unit_code, element_no, pc_no, pc_text FROM catalog_ncs_pc
        WHERE unit_code = ANY(:c) ORDER BY unit_code, element_no, pc_no"""), {"c": list(unit_codes)}):
        out.setdefault((uc, en), []).append({"ref": pc_ref(no), "no": no, "text": txt})
    return out


def ksa_of(s: Session, unit_codes: list[str]) -> dict[tuple[str, int], list[tuple[str, str]]]:
    """{(unit_code, element_no): [("기술1", "컴파일러 사용 능력"), …]} — 수행준거마다 반복된 행을 한 번만.
    구형(항목 단위) 판정을 읽을 때만 쓴다."""
    out: dict[tuple[str, int], list[tuple[str, str]]] = {}
    if not unit_codes:
        return out
    seen: set[tuple] = set()
    for uc, en, kt, kn, txt in s.execute(text("""
        SELECT unit_code, element_no, ksa_type, ksa_no, ksa_text FROM catalog_ncs_ksa
        WHERE unit_code = ANY(:c) ORDER BY unit_code, element_no, ksa_type, ksa_no, pc_no"""),
        {"c": list(unit_codes)}):
        k = (uc, en, f"{kt}{kn}")
        if k in seen:
            continue
        seen.add(k)
        out.setdefault((uc, en), []).append((k[2], txt))
    return out


def pcs_by_element(s: Session, element_ids: list[str]) -> dict[str, list[dict]]:
    """{element_id: [수행준거…]} — 판정 요소 id 로 바로 찾을 때."""
    codes = sorted({unit_of(e) for e in element_ids})
    table = pcs_of(s, codes)
    return {e: table.get((unit_of(e), element_no(e) or 0), []) for e in element_ids}
