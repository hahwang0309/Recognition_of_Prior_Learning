"""Track B 실사례 4건을 수집해 넣는다 (2단계 확인용).

  python scripts/load_demo.py [--src DIR] [--keep]

시험이 submission 테이블을 비우므로, 수동 확인 상태를 되살릴 때 쓴다.
원본은 `@@APPLICANT` / `@@DOC` 헤더로 구분된 평문 한 파일이다.
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

from sqlalchemy import text

from krpl_core.db import session_scope
from krpl_core.models import Submission
from services.ingest.service import ingest_submission

SRC = Path(__file__).resolve().parents[2] / "Data(20260812)" / "derived" / "trackB" / "submission"   # 연구 폴더의 시연 자료
CASE = {"B001": "R2026-0001", "B002": "R2026-0002", "B003": "R2026-0003", "B004": "R2026-0004"}

APPLICANT = re.compile(r"^@@APPLICANT\s+(\S+)\s*\|\s*([^|]+?)\s*\|")
DOC = re.compile(r"^@@DOC\s+(\S+)\s*\|\s*([^|]+?)\s*\|\s*([A-E])\s*\|"
                 r"\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*(\S+)\s*$")


def parse(path: Path, outdir: Path) -> tuple[str, str, list[dict]]:
    """한 파일을 (지원자코드, 종목, 문서목록) 으로 쪼갠다. 본문은 개별 파일로 떨군다."""
    applicant = program = None
    docs: list[dict] = []
    buf: list[str] = []

    def flush() -> None:
        if not docs or not buf:
            return
        f = outdir / f"{applicant}_{docs[-1]['doc_key']}.txt"
        f.write_text("\n".join(buf).strip() + "\n", encoding="utf-8")
        docs[-1]["file_path"] = str(f)

    for line in path.read_text(encoding="utf-8").splitlines():
        if m := APPLICANT.match(line):
            applicant, program = m.group(1), m.group(2)
            continue
        if m := DOC.match(line):
            flush()
            buf = []
            docs.append({"doc_key": m.group(1), "doc_type": m.group(2), "grade": m.group(3),
                         "issuer": m.group(4) or None, "issued_on": m.group(5) or None,
                         "doc_format": m.group(6), "file_path": None})
            continue
        buf.append(line)
    flush()

    missing = [d["doc_key"] for d in docs if not d["file_path"]]
    if missing:
        raise ValueError(f"{path.name}: 본문 없는 문서 {missing}")
    return applicant, program, docs


def load(src: Path = SRC, keep: bool = False) -> list[tuple]:
    """4건을 수집해 넣고 요약 행을 돌려준다. 시험에서도 이 함수를 쓴다."""
    files = sorted(src.glob("B*.txt"))
    if not files:
        raise FileNotFoundError(f"원본이 없다: {src}")

    tmp = Path(tempfile.mkdtemp(prefix="krpl_demo_"))
    rows = []
    for f in files:
        applicant, program, docs = parse(f, tmp)
        case = CASE.get(applicant, f"R2026-9{applicant[1:]}")

        with session_scope() as s:
            if s.execute(text("SELECT 1 FROM catalog_wsd_program WHERE program_id=:p"),
                         {"p": program}).first() is None:
                print(f"  건너뜀 {case} — 카탈로그에 없는 종목: {program}", file=sys.stderr)
                continue
            s.execute(text("DELETE FROM submission WHERE case_number=:c"), {"c": case})
            sub = Submission(case_number=case, track="B", target_program_id=program,
                             note=f"demo:{applicant}")
            s.add(sub)
            s.flush()
            r = ingest_submission(s, sub.id, docs)

        ev = sum(1 for p in r.prior_learning if p["evaluated"])
        rows.append((case, program, r.n_documents, r.n_fragments,
                     len(r.prior_learning), ev, sum(r.masked.values()), r.warnings))

    if keep:
        print(f"쪼갠 본문: {tmp}")
    else:
        for f in tmp.iterdir():
            f.unlink()
        tmp.rmdir()
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=SRC)
    ap.add_argument("--keep", action="store_true", help="쪼갠 본문 파일을 지우지 않는다")
    a = ap.parse_args()
    try:
        rows = load(a.src, a.keep)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1

    w = max((len(r[1]) for r in rows), default=10)
    print(f"\n{'심사번호':<12} {'종목':<{w}} {'문서':>4} {'조각':>4} {'기이수':>6} {'평가확인':>8} {'마스킹':>6}")
    print("-" * (12 + w + 32))
    for case, program, nd, nf, npl, ev, nm, _ in rows:
        print(f"{case:<12} {program:<{w}} {nd:>4} {nf:>4} {npl:>6} {ev:>8} {nm:>6}")

    for case, *_, warns in rows:
        for x in warns:
            print(f"  ⚠ {case}: {x}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
