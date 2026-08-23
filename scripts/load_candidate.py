"""시험용 가상 지원자 자료를 접수해 넣는다.

  python scripts/load_candidate.py                    # test/candidate01 전부
  python scripts/load_candidate.py --src <디렉터리>
  python scripts/load_candidate.py --case R2026-0101  # 심사번호 지정

원본 형식은 `load_demo.py` 와 같다 — `@@APPLICANT` / `@@DOC` 헤더로 나눈 평문.

자료는 **프로젝트 루트의 `test/`** 에 있다. git 저장소는 `App/` 하나뿐이라
그 폴더는 버전 관리 밖이다 — 이 스크립트만 저장소에 들어간다.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from sqlalchemy import text

from krpl_core.db import session_scope
from krpl_core.models import Submission
from services.ingest.service import ingest_submission

# 저장소 루트의 test/ 아래. 앱 폴더 바깥이라 두 단계 위로 올라간다.
SRC = Path(__file__).resolve().parents[2] / "test/candidate01"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_demo import parse  # noqa: E402  같은 형식을 읽으므로 그대로 쓴다


def load(src: Path = SRC, case: str | None = None, keep: bool = False) -> list[tuple]:
    files = sorted(src.glob("*.txt"))
    if not files:
        raise FileNotFoundError(f"원본이 없다: {src}")

    tmp = Path(tempfile.mkdtemp(prefix="krpl_cand_"))
    rows = []
    try:
        for n, f in enumerate(files, 1):
            applicant, program, docs = parse(f, tmp)
            cn = case or f"R2026-9{n:03d}"

            with session_scope() as s:
                if s.execute(text("SELECT 1 FROM catalog_wsd_program WHERE program_id=:p"),
                             {"p": program}).first() is None:
                    print(f"  건너뜀 {cn} — 카탈로그에 없는 종목: {program}", file=sys.stderr)
                    continue
                s.execute(text("DELETE FROM submission WHERE case_number=:c"), {"c": cn})
                sub = Submission(case_number=cn, track="B", target_program_id=program,
                                 note=f"시험 지원자 {applicant}")
                s.add(sub)
                s.flush()
                r = ingest_submission(s, sub.id, docs)

            ev = sum(1 for p in r.prior_learning if p["evaluated"])
            rows.append((cn, program, r.n_documents, r.n_fragments,
                         len(r.prior_learning), ev, sum(r.masked.values()), r.warnings))
    finally:
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
    ap.add_argument("--case", help="심사번호 (기본 R2026-9001…)")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    try:
        rows = load(a.src, a.case, a.keep)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1

    print(f"\n{'심사번호':<12} {'종목':<16} {'문서':>4} {'조각':>4} {'기이수':>6} {'평가확인':>8} {'마스킹':>6}")
    print("-" * 62)
    for cn, program, nd, nf, npl, ev, nm, _ in rows:
        print(f"{cn:<12} {program:<16} {nd:>4} {nf:>4} {npl:>6} {ev:>8} {nm:>6}")
    for cn, *_, warns in rows:
        for x in warns:
            print(f"  ⚠ {cn}: {x}", file=sys.stderr)

    with session_scope() as s:
        for cn, *_ in rows:
            sid = s.execute(text("SELECT id FROM submission WHERE case_number=:c"),
                            {"c": cn}).scalar()
            print(f"\n  심사 개요: http://localhost:8000/submissions/{sid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
