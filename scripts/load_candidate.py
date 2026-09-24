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


SKIP_PREFIX = ("00_", "~$")          # 00_사례_개요서 = 연구진의 예상 판정. AI 에 보이면 안 된다


def _guessed_manifest(src: Path) -> list[dict]:
    """접수목록.csv 가 없을 때 — 폴더의 문서를 파일명으로 분류해 접수목록을 만든다.
    사람이 보는 문서(docx 등)를 그대로 넣기 위한 경로 (2026-09-23)."""
    from services.ingest.classify import guess
    st = get_settings()
    rows = []
    for f in sorted(src.iterdir()):
        if not f.is_file() or f.name.startswith(SKIP_PREFIX) or f.name in (APPLY, MANIFEST, "README.md"):
            continue
        if f.suffix.lower().lstrip(".") not in st.storage.allowed_extensions:
            continue
        g = guess(f.name)
        rows.append({"파일": f.name, "종류": g.doc_type or "기타", "신뢰도등급": g.grade or "",
                     "발급기관": "", "발급일": ""})
        if g.doc_type is None:
            print(f"  ⚠ {f.name}: 파일명으로 종류를 알 수 없어 「기타」로 접수합니다", file=sys.stderr)
    return rows


def read_set(src: Path, program: str | None = None) -> tuple[dict, list[dict]]:
    """폴더 하나를 (신청서, 문서 목록) 으로 읽는다.

    신청서.yaml 이 없으면 --program 이 목표종목이 된다. 접수목록.csv 가 없으면 파일명으로 분류한다."""
    a, m = src / APPLY, src / MANIFEST
    if a.exists():
        apply = yaml.safe_load(a.read_text(encoding="utf-8")) or {}
    elif program:
        apply = {"목표종목": program}
    else:
        raise FileNotFoundError(f"{a} 가 없습니다 (또는 --program 으로 목표종목을 주십시오)")

    rb, st = get_rubric(), get_settings()
    if not m.exists():
        return apply, _rows_to_docs(src, _guessed_manifest(src), rb, st)
    with m.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return apply, _rows_to_docs(src, rows, rb, st)


def _rows_to_docs(src: Path, rows: list[dict], rb, st) -> list[dict]:
    docs: list[dict] = []
    if True:
        for n, row in enumerate(rows, 1):
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
            kind = (row.get("종류") or "").strip()
            # 종류는 화면(기준서)이 내미는 목록과 같아야 한다. 자유 텍스트로 두었더니
            # 「NCS 기반 훈련과정 이수증」과 「NCS기반_훈련이수증」이 갈라져,
            # 화면으로 올린 이수증이 「추가 자료」로 세어졌다.
            # 접수는 무엇이든 받는다(2026-09-23). 모르는 종류는 「기타」로 두고, 인정 근거로
            # 쓰려면 담당자가 종류를 지정하도록 보고서가 안내한다.
            if kind not in rb.document_types:
                print(f"  ⚠ {name}: 종류 {kind!r} 는 기준서에 없어 「기타」로 접수합니다", file=sys.stderr)
                kind = "기타"
            grade = (row.get("신뢰도등급") or "").strip()
            if grade not in rb.grades:
                grade = rb.document_types[kind]["grade"]
                print(f"  ⚠ {name}: 신뢰도 등급이 없어 종류 기본값 {grade} 로 둡니다", file=sys.stderr)
            docs.append({
                "doc_key": f"D{n:02d}",
                "doc_type": kind,
                "grade": grade,
                "issuer": (row.get("발급기관") or "").strip() or None,
                "issued_on": (row.get("발급일") or "").strip() or None,
                "file_path": str(path),
            })
    if not docs:
        raise ValueError(f"{src} 에 접수할 문서가 없습니다")
    return docs


def load(src: Path = SRC, case: str | None = None, program: str | None = None) -> tuple[str, int, object]:
    apply, docs = read_set(src, program)
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
        # 보유 자격 — 화면 접수(gateway/api.py)와 같게 doc_type='과정평가형자격' 행으로 둔다.
        # 기록 확인(track_a_service)은 이 행의 issuer 로 편성기준 시간을 찾는다.
        # 이 행이 없으면 이수증 실적값만으로 돌아 자격 편성기준 경로가 빠진다(2026-09-23 실측: 45% vs 55%).
        quals = [q for q in (apply.get("보유자격") or []) if q]
        for q in quals:
            if s.execute(text("SELECT 1 FROM catalog_cbq_qual WHERE qual_id=:q"), {"q": q}).first() is None:
                raise ValueError(f"편성기준 DB에 없는 자격입니다: {q!r} (신청서.yaml 보유자격은 cbq_qual_id 그대로)")
        if quals:
            s.execute(text("""INSERT INTO document (submission_id, doc_key, doc_type, grade, issuer)
                              VALUES (:s, :k, '과정평가형자격', 'A', :q)"""),
                      [{"s": sid, "k": f"Q{i:02d}", "q": q} for i, q in enumerate(quals, 1)])
        r = ingest_submission(s, sid, docs)
    return cn, sid, r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=SRC)
    ap.add_argument("--case", help="심사번호 (기본: 신청서.yaml 의 값)")
    ap.add_argument("--program", help="목표종목 (신청서.yaml 이 없을 때). 예: 건축설계_L3")
    a = ap.parse_args()
    try:
        cn, sid, r = load(a.src, a.case, a.program)
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
        b = d.get("bucket_hours") or {"인정": h["완전충족"] + h["조정범위내"], "보류": h.get("보류", 0),
                                       "불인정": h.get("시간부족", 0) + h["미이수"]}
        tot = d["total_hours"]
        print(f"  기록 확인 — 인정 {b['인정']}h ({b['인정'] / tot:.0%}) · 보류 {b['보류']}h · "
              f"불인정 {b['불인정']}h / {tot}h · 갈음불가 {len(d.get('갈음불가') or [])}건")
    print(f"\n  심사 개요: http://localhost:8000/submissions/{sid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
