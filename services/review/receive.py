"""추가 서류를 받아 심사에 반영한다.

## 왜 파일을 올리게 하나

2단계는 「받음 / 못 받음 / 미실시」 토글뿐이었다. 서류 실물이 시스템에
들어오지 않으므로, 그 서류에 실제로 무엇이 적혀 있는지 아무도 읽지 않고
「받음」 한 번으로 KSA 가 채워진 것으로 쳤다. 감사에서 그것을 물으면
내놓을 것이 없다.

## 받으면 다시 본다

서류가 들어오면 그 서류가 풀려던 요소만 다시 판정한다. 나머지 요소와
이미 내려진 검토 판단은 그대로 옮긴다 — 서류 한 장 때문에 서른세 개를
처음부터 다시 판단하게 하지 않는다.

    받은 서류 → 조각으로 수집 → 그 항목 「받음」 기록
              → 걸린 요소만 재판정(track_b, keep_from/focus)
              → 면접·실기 항목과 질문지가 새 자료를 반영해 다시 만들어진다
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from krpl_core.config import get_rubric
from krpl_core.queue import enqueue
from services.ingest.classify import guess
from services.ingest.service import ingest_submission
from services.ingest.upload import store
from services.review.context import load
from services.review.stages import save_result

log = logging.getLogger(__name__)


@dataclass
class Received:
    doc_key: str
    doc_type: str
    grade: str
    n_fragments: int
    focus: list[str]              # 다시 볼 요소
    job_id: int | None            # 재판정 작업. 이미 도는 중이면 None
    guessed: bool                 # 종류를 이름으로 알아맞혔나


def receive_document(s: Session, assessment_id: int, item_key: str,
                     filename: str, data: bytes, *,
                     doc_type: str | None = None, grade: str | None = None,
                     reviewer: str | None = None) -> Received:
    """2단계 항목에 서류 한 건을 붙이고, 걸린 요소만 다시 판정하게 한다."""
    ctx = load(s, assessment_id)
    if ctx is None:
        raise LookupError(f"검토를 찾을 수 없습니다: assessment_id={assessment_id}")
    item = next((i for i in (ctx.items.get("추가서류") or []) if i.key == item_key), None)
    if item is None:
        raise LookupError(f"추가 서류 항목이 아닙니다: {item_key}")

    # 종류·등급을 안 주면 파일 이름으로 알아맞힌다. 못 맞히면 기타로 둔다.
    g = guess(filename)
    doc_type = doc_type or g.doc_type or "기타"
    rb = get_rubric()
    grade = grade or g.grade or (rb.document_types.get(doc_type) or {}).get("grade") or "C"
    if grade not in rb.grades:
        raise ValueError(f"모르는 신뢰도 등급입니다: {grade}")

    case = ctx.case_number
    seq = s.execute(text("SELECT count(*) FROM document WHERE submission_id=:i"),
                    {"i": ctx.submission_id}).scalar_one() + 1
    st = store(case, filename, data, seq)
    res = ingest_submission(s, ctx.submission_id, [{
        "doc_key": st.doc_key, "doc_type": doc_type, "grade": grade,
        "file_path": str(st.path)}])

    save_result(s, assessment_id, item.key, "추가서류", item.item, "통과",
                note=f"제출 서류 {st.doc_key}", reviewer=reviewer)

    focus = sorted({t["eid"] for t in item.targets})
    job_id = _requeue(s, ctx.submission_id, assessment_id, focus)
    log.info("추가 서류 접수 %s — %s(%s) 조각 %d개 · 재판정 %d요소",
             case, doc_type, grade, res.n_fragments, len(focus))
    return Received(doc_key=st.doc_key, doc_type=doc_type, grade=grade,
                    n_fragments=res.n_fragments, focus=focus, job_id=job_id,
                    guessed=g.ok and doc_type == g.doc_type)


def _requeue(s: Session, submission_id: int, assessment_id: int,
             focus: list[str]) -> int | None:
    """재판정을 큐에 넣는다. 이미 기다리는 것이 있으면 범위만 넓힌다.

    서류를 연달아 세 장 올리면 판정이 세 번 돌아야 할 이유가 없다. 아직
    아무도 집지 않은 작업이 있으면 그것에 요소를 더한다.
    """
    row = s.execute(text("""
        SELECT id, payload FROM job
        WHERE kind='track_b' AND status='queued'
          AND (payload->>'submission_id')::int = :i
        ORDER BY id LIMIT 1"""), {"i": submission_id}).first()
    if row is not None:
        jid, payload = row[0], dict(row[1] or {})
        merged = sorted(set(payload.get("focus") or []) | set(focus))
        payload |= {"keep_from": payload.get("keep_from") or assessment_id,
                    "focus": merged}
        s.execute(text("UPDATE job SET payload=CAST(:p AS jsonb) WHERE id=:i"),
                  {"p": _json(payload), "i": jid})
        return jid
    return enqueue(s, "track_b", {"submission_id": submission_id,
                                  "keep_from": assessment_id, "focus": focus})


def _json(d: dict) -> str:
    import json
    return json.dumps(d, ensure_ascii=False)
