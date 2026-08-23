"""지원자 제출 자료 한 세트를 접수해 넣는다.

  python scripts/load_candidate.py                     # test/candidate01
  python scripts/load_candidate.py --src <디렉터리>
  python scripts/load_candidate.py --case R2026-0101

## 폴더 하나가 지원자 한 사람이다

실제 접수는 **파일 여러 개**로 온다. 그래서 자료도 그렇게 두었다.

  신청서.yaml    지원자가 적는 것 — 심사번호·목표종목·보유자격
  접수목록.csv   담당자가 접수 때 입력하는 것 — 파일별 종류·신뢰도 등급·발급기관·발급일
  01_….hwpx …    제출 파일 그대로

화면의 「새 접수 → 서류 올리기」와 같은 일을 명령줄에서 한다. 담당자가 화면에서
고르는 값이 `접수목록.csv` 에 미리 적혀 있다는 것만 다르다.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import yaml
from sqlalchemy import text

from krpl_core.config import get_rubric, get_settings
from krpl_core.db import session_scope
from krpl_core.models import Submission
from services.ingest.service import ingest_submission

SRC = Path(__file__).resolve().parents[2] / "test/candidate01"
APPLY, MANIFEST = "신청서.yaml", "접수목록.csv"


def read_set(src: Path) -> tuple[dict, list[dict]]:
    """폴더 하나를 (신청서, 문서 목록) 으로 읽는다."""
    a, m = src / APPLY, src / MANIFEST
    for p in (a, m):
        if not p.exists():
            raise FileNotFoundError(f"{p} 가 없습니다")
    apply = yaml.safe_load(a.read_text(encoding="utf-8")) or {}

    rb, st = get_rubric(), get_settings()
    docs: list[dict] = []
    with m.open(encoding="utf-8-sig", newline="") as f:
        for n, row in enumerate(csv.DictReader(f), 1):
            name = (row.get("파일") or "").strip()
            if not name:
                continue
            path = src / name
            if not path.exists():
                raise FileNotFoundError(f"{MANIFEST} 에 적힌 파일이 없습니다: {path}")
            ext = path.suffix.lower().lstrip(".")
            if ext not in st.storage.allowed_extensions:
                raise ValueError(f"{name}: 읽을 수 없는 형식 {ext!r} "
                                 f"(가능: {', '.join(st.storage.allowed_extensions)})")
            grade = (row.get("신뢰도등급") or "").strip()
            if grade not in rb.grades:
                raise ValueError(f"{name}: 모르는 신뢰도 등급 {grade!r} "
                                 f"(가능: {', '.join(rb.grades)})")
            docs.append({
                "doc_key": f"D{n:02d}",
                "doc_type": (row.get("종류") or "").strip(),
                "grade": grade,
                "issuer": (row.get("발급기관") or "").strip() or None,
                "issued_on": (row.get("발급일") or "").strip() or None,
                "file_path": str(path),
            })
    if not docs:
        raise ValueError(f"{MANIFEST} 에 문서가 없습니다")
    return apply, docs


def load(src: Path = SRC, case: str | None = None) -> tuple[str, int, object]:
    apply, docs = read_set(src)
    cn = case or apply.get("심사번호") or "R2026-9001"
    program = apply.get("목표종목")

    with session_scope() as s:
        if s.execute(text("SELECT 1 FROM catalog_wsd_program WHERE program_id=:p"),
                     {"p": program}).first() is None:
            raise ValueError(f"카탈로그에 없는 종목입니다: {program}")
        s.execute(text("DELETE FROM submission WHERE case_number=:c"), {"c": cn})
        sub = Submission(case_number=cn, track="B", target_program_id=program,
                         note=apply.get("비고") or None)
        s.add(sub)
        s.flush()
        sid = sub.id
        r = ingest_submission(s, sid, docs)
    return cn, sid, r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=SRC)
    ap.add_argument("--case", help="심사번호 (기본: 신청서.yaml 의 값)")
    a = ap.parse_args()
    try:
        cn, sid, r = load(a.src, a.case)
    except (FileNotFoundError, ValueError) as ex:
        print(ex, file=sys.stderr)
        return 1

    ev = sum(1 for p in r.prior_learning if p["evaluated"])
    print(f"\n{cn} 접수 완료")
    print(f"  문서 {r.n_documents}건 · 조각 {r.n_fragments}개 · "
          f"기이수 {len(r.prior_learning)}건(평가확인 {ev}) · "
          f"가려진 항목 {sum(r.masked.values())}건")
    for w in r.warnings:
        print(f"  ⚠ {w}", file=sys.stderr)

    with session_scope() as s:
        note = s.execute(text("""
            SELECT overall_note FROM assessment
            WHERE submission_id=:i AND kind='time' ORDER BY id DESC LIMIT 1"""),
            {"i": sid}).scalar()
    if note:
        d = json.loads(note)
        h = d["hours"]
        got = h["완전충족"] + h["조정범위내"]
        print(f"  시간 대조 {got}/{d['total_hours']}시간 "
              f"({got / d['total_hours']:.0%}) · 갈음불가 {len(d.get('갈음불가') or [])}건")
    print(f"\n  심사 개요: http://localhost:8000/submissions/{sid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
