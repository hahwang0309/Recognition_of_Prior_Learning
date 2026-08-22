"""NCS 카탈로그 적재: SQLite(derived/) → PostgreSQL.

원본은 Data(20260812)/derived/ 의 krpl.sqlite · ncs_ksa.sqlite.
멱등적으로 동작한다 — 다시 실행하면 기존 카탈로그를 지우고 다시 넣는다.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

from sqlalchemy import text

from krpl_core.config import get_rubric
from krpl_core.db import get_engine

DEFAULT_SRC = Path(
    "/Users/hahwang/Dropbox/2026_일학습병행훈련/Data(20260812)/derived"
)

# (대상 테이블, 원본 SQLite, 원본 쿼리, 컬럼)
SPECS = [
    ("catalog_ncs_unit", "krpl", """
        SELECT unit_code, unit_name, level, std_hours, sebunryu_code,
               sebunryu_name, daebunryu_name, latest_version FROM dim_ncs_unit""",
     "unit_code unit_name level std_hours sebunryu_code sebunryu_name daebunryu_name latest_version"),

    ("catalog_ncs_element", "krpl", """
        SELECT element_id, unit_code, unit_version, unit_name, element_no,
               element_name, sebunryu_code FROM dim_unit_element""",
     "element_id unit_code unit_version unit_name element_no element_name sebunryu_code"),

    ("catalog_wsd_program", "krpl", """
        SELECT wsd_program_id, jikjong, level, total_hours_sum, n_units,
               official_jongmok, official_status, daebunryu, jungbunryu, qc_status, note
        FROM dim_wsd_program""",
     "program_id jikjong level total_hours n_units official_name official_status daebunryu jungbunryu qc_status note"),

    ("catalog_wsd_required", "krpl", """
        SELECT wsd_program_id, unit_code, unit_version, unit_name, unit_level,
               required_hours, min_hours FROM fact_wsd_required""",
     "program_id unit_code unit_version unit_name unit_level required_hours min_hours"),

    ("catalog_cbq_qual", "krpl", """
        SELECT cbq_qual_id, grade, version, total_A, essential_B, B_min, B_max,
               n_units, qc_status FROM dim_cbq_qual""",
     "qual_id grade version total_a essential_b b_min b_max n_units qc_status"),

    ("catalog_cbq_composed", "krpl", """
        SELECT cbq_qual_id, unit_code, unit_version, unit_name, unit_level,
               sebunryu_name, composed_hours, composed_hours_min, composed_hours_max
        FROM fact_cbq_composed""",
     "qual_id unit_code unit_version unit_name unit_level sebunryu_name composed_hours composed_hours_min composed_hours_max"),

    ("catalog_unit_version", "krpl", """
        SELECT unit_code, wsd_versions, cbq_versions, ncs_version, version_match,
               needs_review, resolution FROM dim_unit_version""",
     "unit_code wsd_versions cbq_versions ncs_version version_match needs_review resolution"),

    ("catalog_ncs_pc", "ksa", """
        SELECT unit_code, element_no, pc_no, pc_text FROM fact_performance_criteria""",
     "unit_code element_no pc_no pc_text"),

    ("catalog_ncs_ksa", "ksa", """
        SELECT unit_code, element_no, pc_no, ksa_type, ksa_no, ksa_text FROM fact_ksa""",
     "unit_code element_no pc_no ksa_type ksa_no ksa_text"),
]

BATCH = 5000


def load(src: Path, only: str | None = None) -> None:
    eng = get_engine()
    conns = {
        "krpl": sqlite3.connect(src / "krpl.sqlite"),
        "ksa": sqlite3.connect(src / "ncs_ksa.sqlite"),
    }
    floor = get_rubric().training_hours["adjustment_floor"]

    with eng.begin() as pg:
        # 참조 데이터는 통째로 갈아끼운다 (FK 순서 고려)
        for tbl, *_ in reversed(SPECS):
            if only and only != tbl:
                continue
            pg.execute(text(f"TRUNCATE {tbl} CASCADE"))

        for tbl, srckey, query, cols in SPECS:
            if only and only != tbl:
                continue
            t0 = time.time()
            names = cols.split()
            ph = ", ".join(f":{c}" for c in names)
            ins = text(f"INSERT INTO {tbl} ({', '.join(names)}) VALUES ({ph})")
            cur = conns[srckey].execute(query)
            n = 0
            while rows := cur.fetchmany(BATCH):
                payload = []
                for r in rows:
                    d = dict(zip(names, r))
                    if tbl == "catalog_wsd_required" and d.get("min_hours") is None:
                        d["min_hours"] = round((d["required_hours"] or 0) * floor)
                    if tbl == "catalog_unit_version":
                        d["needs_review"] = bool(d["needs_review"])
                    payload.append(d)
                pg.execute(ins, payload)
                n += len(payload)
            print(f"  {tbl:24s} {n:>9,}행  {time.time()-t0:5.1f}s", flush=True)
    for c in conns.values():
        c.close()


def verify() -> int:
    eng = get_engine()
    expect = {
        "catalog_ncs_unit": 13296, "catalog_ncs_element": 47199,
        "catalog_ncs_pc": 196646, "catalog_ncs_ksa": 2457444,
        "catalog_wsd_program": 454, "catalog_wsd_required": 3988,
        "catalog_cbq_qual": 216, "catalog_cbq_composed": 2030,
        "catalog_unit_version": 4333,
    }
    bad = 0
    print("\n검증:")
    with eng.connect() as c:
        for tbl, want in expect.items():
            got = c.execute(text(f"SELECT count(*) FROM {tbl}")).scalar_one()
            ok = got == want
            bad += not ok
            print(f"  {'✅' if ok else '❌'} {tbl:24s} {got:>9,} (기대 {want:,})")
    return bad


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--src", type=Path, default=DEFAULT_SRC)
    p.add_argument("--only")
    p.add_argument("--verify-only", action="store_true")
    a = p.parse_args()
    if not a.verify_only:
        print(f"적재 시작 — 원본 {a.src}")
        load(a.src, a.only)
    sys.exit(1 if verify() else 0)
