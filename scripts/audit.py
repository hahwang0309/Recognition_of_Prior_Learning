"""단계별 산출물을 터미널에서 확인한다.

  python scripts/audit.py                     접수 건 목록
  python scripts/audit.py R2026-0002          한 건의 단계별 요약 + 파일 경로
  python scripts/audit.py R2026-0002 --show 조각      산출물 내용 출력
  python scripts/audit.py R2026-0002 --verify         파일 해시를 다시 계산해 대조
  python scripts/audit.py --prune                     파일이 사라진 색인 행을 정리

브라우저 없이도, 앱을 신뢰하지 않고도 확인할 수 있게 하는 것이 목적이다.
`--verify` 는 DB 기록과 디스크 파일을 직접 비교한다.
"""
from __future__ import annotations

import argparse
import hashlib
import sys

from sqlalchemy import text

from krpl_core.audit import STAGE_KO, audit_root
from krpl_core.db import session_scope


def _kb(n: int) -> str:
    return f"{n / 1024:>6.0f}KB" if n >= 1024 else f"{n:>7}B"


def prune(dry: bool = False) -> int:
    """파일이 사라진 색인 행을 지운다.

    보관함을 통째로 지우면(`walk`, `rm -rf storage/audit`) 파일만 없어지고
    DB 색인은 남는다. 그대로 두면 감사 화면에 「파일 없음」이 잔뜩 뜬다 —
    기록이 있는데 못 여는 상태가 가장 헷갈린다.
    """
    with session_scope() as s:
        rows = list(s.execute(text("""
            SELECT a.id, a.path, sub.case_number FROM artifact a
            JOIN submission sub ON sub.id = a.submission_id""")).all())
        dead = [r for r in rows if not (audit_root() / r[1]).exists()]
        print(f"색인 {len(rows)}행 중 {len(dead)}행이 없는 파일을 가리킵니다.")
        by_case: dict[str, int] = {}
        for _, _, case in dead:
            by_case[case] = by_case.get(case, 0) + 1
        for case, n in sorted(by_case.items()):
            print(f"   {case}  {n}행")
        if dry or not dead:
            if dead:
                print("\n지우려면 --prune (지금은 --dry-run)")
            return 0
        s.execute(text("DELETE FROM artifact WHERE id = ANY(:i)"), {"i": [r[0] for r in dead]})
        print(f"\n{len(dead)}행 정리했습니다. 남은 색인 {len(rows) - len(dead)}행.")
    return 0


def list_cases() -> int:
    with session_scope() as s:
        rows = list(s.execute(text("""
            SELECT sub.case_number, sub.track, sub.status, sub.target_program_id,
                   (SELECT count(*) FROM fragment f WHERE f.submission_id=sub.id) nf,
                   (SELECT count(*) FROM artifact t WHERE t.submission_id=sub.id) na,
                   (SELECT count(*) FROM assessment_element x
                    WHERE x.assessment_id=(SELECT max(id) FROM assessment
                                           WHERE submission_id=sub.id)) ne,
                   fd.decision, fd.recognized_hours, fd.total_hours
            FROM submission sub LEFT JOIN final_decision fd ON fd.submission_id=sub.id
            ORDER BY sub.case_number""")).mappings())
    print(f"\n{'심사번호':12} {'T':2} {'상태':12} {'종목':22} {'조각':>4} {'요소':>4} "
          f"{'산출물':>5}  최종판정")
    print("─" * 96)
    for r in rows:
        dec = (f"{r['decision']} {r['recognized_hours']}/{r['total_hours']}h"
               if r["decision"] else "–")
        print(f"{r['case_number']:12} {r['track']:2} {r['status']:12} "
              f"{r['target_program_id'][:22]:22} {r['nf']:>4} {r['ne'] or 0:>4} "
              f"{r['na']:>5}  {dec}")
    print(f"\n총 {len(rows)}건 · 산출물 경로 {audit_root()}")
    print("한 건을 보려면:  python scripts/audit.py <심사번호>")
    return 0


def show_case(case: str, show: str | None, verify: bool) -> int:
    with session_scope() as s:
        sub = s.execute(text("""SELECT id, track, target_program_id, status, received_at
                                FROM submission WHERE case_number=:c"""),
                        {"c": case}).mappings().first()
        if sub is None:
            print(f"접수 건이 없습니다: {case}", file=sys.stderr)
            return 1
        arts = list(s.execute(text("""
            SELECT id, assessment_id, stage, seq, name, path, sha256, n_bytes, note, created_at
            FROM artifact WHERE submission_id=:i
            ORDER BY assessment_id NULLS FIRST, stage, seq, name"""),
            {"i": sub["id"]}).mappings())

    print(f"\n■ {case} · {sub['target_program_id']} · Track {sub['track']} "
          f"· 상태 {sub['status']} · 접수 {sub['received_at']:%Y-%m-%d %H:%M}")
    print(f"  {audit_root() / case}\n")

    if show:
        hit = [a for a in arts if show in a["name"]]
        if not hit:
            print(f"그런 산출물이 없습니다: {show}", file=sys.stderr)
            print("  있는 것:", ", ".join(sorted({a["name"] for a in arts})), file=sys.stderr)
            return 1
        for a in hit:
            p = audit_root() / a["path"]
            print(f"── {a['name']} ({_kb(a['n_bytes']).strip()}) {p}")
            print(p.read_text(encoding="utf-8") if p.exists() else "(파일 없음)")
        return 0

    bad = 0
    by_stage: dict[str, list] = {}
    for a in arts:
        by_stage.setdefault(a["stage"], []).append(a)
    for st, ko in STAGE_KO.items():
        items = by_stage.get(st, [])
        print(f"{ko}  ({len(items)}개)")
        if not items:
            print("     — 남은 파일 없음")
        for a in items:
            mark = ""
            if verify:
                p = audit_root() / a["path"]
                if not p.exists():
                    mark, bad = "  ⚠ 파일 없음", bad + 1
                elif hashlib.sha256(p.read_bytes()).hexdigest() != a["sha256"]:
                    mark, bad = "  ⚠ 해시 불일치", bad + 1
                else:
                    mark = "  ✓"
            print(f"     [{a['id']:>4}] {a['name']:16} {_kb(a['n_bytes'])} "
                  f"{a['sha256'][:10]}{mark}")
            if a["note"]:
                print(f"            {a['note'][:96]}")
        print()

    if verify:
        print(f"대조 결과: {len(arts) - bad}/{len(arts)} 일치"
              + (f" · ⚠ 어긋남 {bad}건" if bad else " · 모두 저장 당시와 같습니다"))
    print(f"내용 보기:  python scripts/audit.py {case} --show 조각")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("case", nargs="?", help="심사번호. 생략하면 목록")
    ap.add_argument("--show", help="산출물 이름 일부 (예: 조각, 마스킹, AI응답)")
    ap.add_argument("--verify", action="store_true", help="파일 해시를 다시 계산해 대조")
    ap.add_argument("--prune", action="store_true", help="파일이 사라진 색인 행 정리")
    ap.add_argument("--dry-run", action="store_true", help="--prune 대상만 보여준다")
    a = ap.parse_args()
    if a.prune or a.dry_run:
        return prune(a.dry_run)
    return list_cases() if not a.case else show_case(a.case, a.show, a.verify)


if __name__ == "__main__":
    raise SystemExit(main())
