"""Track A 판정 오케스트레이션 — 조회 → 판정 → 저장."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from krpl_core.config import get_rubric
from krpl_rules import assess_track_a
from services.catalog import CatalogRepo


def _hash(program_id: str, qual_ids: list[str], rubric_version: str) -> str:
    raw = json.dumps({"p": program_id, "q": sorted(qual_ids), "r": rubric_version},
                     ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def run_track_a(s: Session, submission_id: int) -> int:
    """접수 건을 판정하고 assessment 레코드를 만든다. assessment_id 반환."""
    rb = get_rubric()
    sub = s.execute(text("""
        SELECT id, case_number, target_program_id FROM submission WHERE id=:i"""),
        {"i": submission_id}).mappings().one()

    # 보유 자격 — Track A 는 document.doc_type='과정평가형자격' 의 issuer 에 자격명을 둔다
    qual_ids = [r[0] for r in s.execute(text("""
        SELECT issuer FROM document
        WHERE submission_id=:i AND doc_type='과정평가형자격' AND issuer IS NOT NULL"""),
        {"i": submission_id})]

    repo = CatalogRepo(s)
    prog = repo.get_program(sub["target_program_id"])
    if prog is None:
        raise ValueError(f"종목을 찾을 수 없음: {sub['target_program_id']}")

    result = assess_track_a(
        prog.program_id, prog.total_hours,
        repo.required_units(prog.program_id),
        repo.held_units(qual_ids),
        rb,
    )

    now = datetime.now(timezone.utc)
    aid = s.execute(text("""
        INSERT INTO assessment (submission_id, status, rubric_version, model,
                                input_hash, attempts, started_at, finished_at, overall_note)
        VALUES (:s, 'done', :rv, 'deterministic', :h, 1, :t, :t, :n)
        RETURNING id"""), {
        "s": submission_id, "rv": rb.version,
        "h": _hash(prog.program_id, qual_ids, rb.version), "t": now,
        "n": json.dumps(result.summary(), ensure_ascii=False),
    }).scalar_one()

    s.execute(text("""
        INSERT INTO assessment_element
            (assessment_id, element_id, recommendation, evidence_level,
             verification_method, confidence, payload)
        VALUES (:a, :e, :r, :v, :m, :c, CAST(:p AS jsonb))"""),
        [{"a": aid, "e": e.unit_code, "r": e.recommendation, "v": e.verdict,
          "m": e.verification, "c": e.confidence,
          "p": json.dumps({
              "unit_name": e.unit_name, "required_hours": e.required_hours,
              "min_hours": e.min_hours, "completed_hours": e.completed_hours,
              "ratio": e.ratio, "evidence": e.evidence, "note": e.note},
              ensure_ascii=False)} for e in result.elements])

    s.execute(text("UPDATE submission SET status='assessed' WHERE id=:i"), {"i": submission_id})
    s.execute(text("""INSERT INTO audit_log (entity, entity_id, action, actor, detail)
                      VALUES ('assessment', :i, 'created', 'system', CAST(:d AS jsonb))"""),
              {"i": str(aid), "d": json.dumps(result.summary(), ensure_ascii=False)})
    return aid
