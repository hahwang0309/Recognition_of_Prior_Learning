"""검토 화면을 열어 볼 수 있게 실사례 4건에 가상 검토를 채운다.

  python scripts/review_demo.py [--case R2026-0002] [--clear]

AI 권고를 그대로 따르는 검토를 넣는다 (R0·R1→인정, R2·R3→조건부인정,
R4→보류, R5→불인정). 최종 판정은 기록하지 않는다 — 그건 사람이 할 일이다.
"""
from __future__ import annotations

import argparse

from sqlalchemy import text

from krpl_core.db import session_scope
from services.review import record_decision, review_summary, save_element_review

MAP = {"R0": "인정", "R1": "인정", "R2": "조건부인정", "R3": "조건부인정",
       "R4": "보류", "R5": "불인정"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", action="append", help="심사번호. 생략하면 판정된 건 전부")
    ap.add_argument("--clear", action="store_true", help="검토·최종판정을 지우기만 한다")
    ap.add_argument("--decide", action="store_true",
                    help="권고안대로 최종 판정까지 기록한다 (⑥단계 산출물 생성)")
    a = ap.parse_args()

    with session_scope() as s:
        q = """SELECT a.id, s.case_number, s.id AS sid FROM assessment a
               JOIN submission s ON s.id = a.submission_id
               WHERE s.track='B' AND a.status IN ('done','manual_review')"""
        p: dict = {}
        if a.case:
            q += " AND s.case_number = ANY(:c)"
            p["c"] = a.case
        rows = list(s.execute(text(q + """ AND a.id = (SELECT max(id) FROM assessment
                                          WHERE submission_id = s.id)
                                          ORDER BY s.case_number"""), p).mappings())

    if not rows:
        print("판정된 Track B 건이 없다. ./scripts/dev.sh assess 를 먼저 실행")
        return 1

    print(f"{'심사번호':12} {'판정':>5}  {'검토':>7} {'감면(확정)':>11} {'조건부포함':>10}  권고안")
    print("-" * 68)
    for r in rows:
        with session_scope() as s:
            s.execute(text("DELETE FROM element_review WHERE assessment_id=:i"), {"i": r["id"]})
            s.execute(text("DELETE FROM final_decision WHERE submission_id=:i"), {"i": r["sid"]})
            if a.clear:
                s.execute(text("UPDATE submission SET status='assessed' WHERE id=:i"),
                          {"i": r["sid"]})
                print(f"{r['case_number']:12} {r['id']:>5}  지움")
                continue
            for eid, rec in s.execute(text("""
                    SELECT element_id, recommendation FROM assessment_element
                    WHERE assessment_id=:i"""), {"i": r["id"]}):
                save_element_review(s, r["id"], eid, MAP[rec], reviewer="(가상 검토)")
            sm = review_summary(s, r["id"])
            if a.decide:
                record_decision(s, r["id"], sm.suggest_decision(),
                                reason="(가상) 권고안 그대로 기록", decided_by="(가상 검토)")
            sm = review_summary(s, r["id"])
            print(f"{r['case_number']:12} {r['id']:>5}  {sm.n_reviewed:>3}/{sm.n_elements:<3} "
                  f"{sm.hours():>6}/{sm.total_hours:<4} {sm.hours(conditional=True):>9}   "
                  f"{sm.suggest_decision()}")
    if not a.clear:
        print("\n검토 화면:  http://localhost:8000/assessments/{판정번호}/review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
