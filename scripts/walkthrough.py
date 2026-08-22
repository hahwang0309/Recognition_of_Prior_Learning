"""처음부터 끝까지 한 번에 돌리고, 무엇이 남았는지 보여준다.

  python scripts/walkthrough.py            4건 전부
  python scripts/walkthrough.py --case R2026-0002

지금까지 만든 것이 실제로 도는지 **직접** 확인하기 위한 것이다.
각 단계가 끝날 때마다 그 단계가 남긴 파일을 함께 보여주므로,
설명을 믿는 대신 파일을 열어 보면 된다.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

from krpl_core.audit import STAGE_KO, audit_root
from krpl_core.db import session_scope

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / ".venv/bin/python")


def run(title: str, args: list[str]) -> bool:
    print(f"\n{'━' * 78}\n▶ {title}\n{'━' * 78}")
    r = subprocess.run([PY, *args], cwd=ROOT, capture_output=True, text=True)
    out = (r.stdout or "").rstrip()
    if out:
        print(out)
    if r.returncode:
        print((r.stderr or "").rstrip()[-1500:], file=sys.stderr)
    return r.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", action="append", help="심사번호. 생략하면 4건 전부")
    ap.add_argument("--keep", action="store_true", help="기존 산출물을 지우지 않는다")
    a = ap.parse_args()
    cases = a.case or ["R2026-0001", "R2026-0002", "R2026-0003", "R2026-0004"]

    if not a.keep:
        import shutil
        if audit_root().exists():
            shutil.rmtree(audit_root())
        # 파일만 지우고 색인을 남기면 감사 화면에 「파일 없음」이 뜬다. 함께 비운다.
        with session_scope() as s:
            n = s.execute(text("DELETE FROM artifact")).rowcount
        print(f"이전 산출물을 지웠습니다: {audit_root()} (색인 {n}행 포함)")

    ok = run("① 문서 수집 — 실사례 4건을 파싱·마스킹·조각화", ["scripts/load_demo.py"])
    ok &= run("②③④ AI 입력 조립 → 분석 → 기계 검증",
              ["scripts/assess.py", *cases, "--force"])
    ok &= run("⑤⑥ 전문가 검토 → 최종 판정 (권고안대로 기록한 가상 검토)",
              ["scripts/review_demo.py", "--decide"])

    print(f"\n{'━' * 78}\n▶ 남은 산출물\n{'━' * 78}")
    with session_scope() as s:
        rows = list(s.execute(text("""
            SELECT sub.case_number, a.stage, count(*) n, sum(a.n_bytes) b
            FROM artifact a JOIN submission sub ON sub.id = a.submission_id
            WHERE sub.case_number = ANY(:c) GROUP BY 1,2"""), {"c": cases}).mappings())
    grid: dict[str, dict[str, int]] = {}
    for r in rows:
        grid.setdefault(r["case_number"], {})[r["stage"]] = r["n"]
    hdr = "".join(f"{STAGE_KO[st][:6]:>10}" for st in STAGE_KO)
    print(f"{'심사번호':12}{hdr}")
    for c in sorted(grid):
        print(f"{c:12}" + "".join(f"{grid[c].get(st, 0):>10}" for st in STAGE_KO))
    print(f"\n총 {sum(r['n'] for r in rows)}개 · {sum(r['b'] for r in rows) / 1024:.0f}KB")

    print(f"\n{'━' * 78}\n▶ 해시 대조 (파일이 저장 당시와 같은지)\n{'━' * 78}")
    for c in cases:
        subprocess.run([PY, "scripts/audit.py", c, "--verify"], cwd=ROOT,
                       capture_output=True, text=True).stdout
        r = subprocess.run([PY, "scripts/audit.py", c, "--verify"], cwd=ROOT,
                           capture_output=True, text=True)
        line = [x for x in r.stdout.splitlines() if "대조 결과" in x]
        print(f"  {c}  {line[0].split(':', 1)[1].strip() if line else '?'}")

    print(f"""
{'━' * 78}
확인하는 방법
{'━' * 78}
  화면    ./scripts/dev.sh api      →  http://localhost:8000/audit
  터미널  ./scripts/dev.sh audit {cases[0]}
          ./scripts/dev.sh audit {cases[0]} --show 조각
          ./scripts/dev.sh audit {cases[0]} --verify
  파일    {audit_root()}
""")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
