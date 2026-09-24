"""문서 수집 — 파싱 → 마스킹 → 구조화 → 저장.

[2] 문서 파싱 · [3] 구조화 · [4] 기이수 추출 단계를 담당한다.
모두 결정론적이다.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from krpl_core.audit import AuditStore, masking_report
from krpl_core.config import get_settings
from krpl_parsers import Masker, parse_file
from krpl_parsers.masking import MaskResult
from krpl_parsers.structuring import (
    DocFormat, StructuredDoc, extract_prior_learning, structure,
)

log = logging.getLogger(__name__)


@dataclass
class IngestResult:
    submission_id: int
    n_documents: int = 0
    n_fragments: int = 0
    masked: dict[str, int] = field(default_factory=dict)
    prior_learning: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "n_documents": self.n_documents,
            "n_fragments": self.n_fragments,
            "masked": self.masked,
            "prior_learning": self.prior_learning,
            "warnings": self.warnings,
        }


def _valid_units(s: Session, program_id: str) -> set[str]:
    return {r[0] for r in s.execute(text(
        "SELECT unit_code FROM catalog_wsd_required WHERE program_id=:p"), {"p": program_id})}


def ingest_document(
    s: Session, submission_id: int, doc_key: str, doc_type: str, grade: str,
    file_path: str | Path, issuer: str | None = None, issued_on: str | None = None,
    doc_format: DocFormat | None = None, masker: Masker | None = None,
    trace: bool = False,
) -> tuple[StructuredDoc, MaskResult]:
    """문서 한 건을 파싱·마스킹·구조화하여 저장한다."""
    cfg = get_settings().ingest
    masker = masker or Masker(cfg.masking.enabled, cfg.masking.patterns)

    parsed = parse_file(file_path)
    m = masker(parsed.text, trace=trace)
    doc = structure(m.text, doc_key, doc_format)

    s.execute(text("""
        INSERT INTO document (submission_id, doc_key, doc_type, grade, issuer,
                              issued_on, file_path, parsed_format)
        VALUES (:s, :k, :t, :g, :i, :d, :f, :fmt)
        ON CONFLICT (submission_id, doc_key) DO UPDATE
        SET doc_type=EXCLUDED.doc_type, grade=EXCLUDED.grade, issuer=EXCLUDED.issuer,
            issued_on=EXCLUDED.issued_on, file_path=EXCLUDED.file_path,
            parsed_format=EXCLUDED.parsed_format"""),
        {"s": submission_id, "k": doc_key, "t": doc_type, "g": grade, "i": issuer,
         "d": issued_on, "f": str(file_path), "fmt": doc.doc_format})

    s.execute(text("DELETE FROM fragment WHERE submission_id=:s AND doc_key=:k"),
              {"s": submission_id, "k": doc_key})
    if doc.fragments:
        s.execute(text("""
            INSERT INTO fragment (submission_id, fid, doc_key, doc_type, grade, text, stype, freq)
            VALUES (:s, :fid, :k, :t, :g, :x, :st, :fr)"""),
            [{"s": submission_id, "fid": f.fid, "k": doc_key, "t": doc_type, "g": grade,
              "x": f.text, "st": f.stype, "fr": f.freq} for f in doc.fragments])
    return doc, m


def ingest_submission(s: Session, submission_id: int, documents: list[dict]) -> IngestResult:
    """접수 건의 문서 전체를 수집한다.

    documents 각 항목: doc_key, doc_type, grade, file_path, issuer?, issued_on?, doc_format?
    """
    sub = s.execute(text("""SELECT case_number, target_program_id
                            FROM submission WHERE id=:i"""),
                    {"i": submission_id}).mappings().one()
    valid = _valid_units(s, sub["target_program_id"])

    cfg = get_settings().ingest
    masker = Masker(cfg.masking.enabled, cfg.masking.patterns)
    res = IngestResult(submission_id)
    all_pl: dict[str, dict] = {}
    store = AuditStore(s, sub["case_number"], submission_id)
    hits: list[dict] = []
    docs_seen: list[dict] = []

    for d in documents:
        try:
            doc, m = ingest_document(
                s, submission_id, d["doc_key"], d["doc_type"], d["grade"],
                d["file_path"], d.get("issuer"), d.get("issued_on"),
                d.get("doc_format"), masker, trace=True,
            )
            counts = m.counts
            hits += [h.as_dict() | {"문서": d["doc_key"]} for h in m.hits]
            docs_seen.append({"doc_key": d["doc_key"], "doc_type": d["doc_type"],
                              "grade": d["grade"], "file_path": str(d["file_path"]),
                              "서술형식": doc.doc_format, "조각수": len(doc.fragments),
                              "조각유형": doc.stats})
        except Exception as e:  # noqa: BLE001
            res.warnings.append(f"{d['doc_key']} 파싱 실패: {type(e).__name__}: {e}")
            continue

        res.n_documents += 1
        res.n_fragments += len(doc.fragments)
        for k, v in counts.items():
            res.masked[k] = res.masked.get(k, 0) + v
        if not doc.fragments:
            res.warnings.append(f"{d['doc_key']} 추출된 조각 없음 — 스캔 이미지일 수 있음")

        for pl in extract_prior_learning(doc.fragments, d["doc_key"], valid):
            prev = all_pl.get(pl.unit_code)
            cand = {"unit_code": pl.unit_code, "completed_hours": pl.completed_hours,
                    "evaluation": pl.evaluation, "evaluated": pl.evaluated,
                    "fid": pl.fid, "doc_key": pl.doc_key, "grade": d["grade"]}
            if prev is None or (cand["completed_hours"] or 0) > (prev["completed_hours"] or 0):
                all_pl[pl.unit_code] = cand

    res.prior_learning = sorted(all_pl.values(), key=lambda x: -(x["completed_hours"] or 0))

    # ── 감사 기록 — 이 단계가 실제로 무엇을 했는지 파일로 남긴다 ──
    store.write("ingest", "문서목록", docs_seen, seq=1,
                note="파싱된 문서와 서술형식·조각 수")
    store.write("ingest", "마스킹기록", masking_report(res.masked, hits), seq=2,
                note=(("가려진 항목 " + " · ".join(f"{k} {v}건" for k, v in res.masked.items()))
                      if res.masked else "가려진 항목 없음")
                     + " — 가려진 값 자체는 저장하지 않는다")
    store.write("ingest", "조각", [dict(r) for r in s.execute(text("""
        SELECT fid, doc_key, doc_type, grade, stype, text FROM fragment
        WHERE submission_id=:i ORDER BY fid"""), {"i": submission_id}).mappings()], seq=3,
        note="AI 가 인용할 수 있는 단위. 여기 없는 것은 인용될 수 없다")
    store.write("ingest", "기이수추출", res.prior_learning, seq=4,
                note="R0(기이수 인정검토) 성립 여부의 근거")
    if res.warnings:
        store.write("ingest", "경고", res.warnings, seq=5)

    s.execute(text("UPDATE submission SET status='ingested' WHERE id=:i"), {"i": submission_id})
    s.execute(text("""INSERT INTO audit_log (entity, entity_id, action, actor, detail)
                      VALUES ('submission', :i, 'ingested', 'system', CAST(:d AS jsonb))"""),
              {"i": str(submission_id), "d": json.dumps(res.summary(), ensure_ascii=False)})

    # 기록 확인는 결정론이고 초 단위로 끝난다. 사람이 시작 버튼을 누를 이유가 없다.
    # 여기서 실패해도 수집 자체는 유효하므로 접수를 통째로 되돌리지는 않는다.
    try:
        from services.assess.track_a_service import run_track_a
        run_track_a(s, submission_id)
    except Exception:                                    # noqa: BLE001
        log.warning("기록 확인 자동 실행 실패 submission=%s", submission_id, exc_info=True)
    return res
