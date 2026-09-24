"""기록 확인(Track A) — 조회 → 판정 → 저장.

## 근거는 두 갈래다

목표 종목이 요구하는 시간에 맞설 수 있는 「이미 확인된 이수 시간」은 두 곳에서 온다.

| 근거 | 출처 | 결정론? |
|---|---|---|
| 과정평가형 자격 | `catalog_cbq_composed` 편성시간 | 예 |
| 기이수 훈련 | 훈련이수증에서 뽑은 능력단위코드·시간·평가결과 | 예 |

판정기(`assess_track_a`)는 시간이 어디서 왔는지 묻지 않는다. `HeldUnit` 이면 된다.
그래서 둘을 합쳐 넣는다. 같은 능력단위에 둘 다 있으면 **큰 쪽**을 쓴다.

이 덕분에 과정평가형 자격이 없는 접수 건도 기록 확인이 돈다.
접수 4건 모두 자격이 없었고, 그래서 예전에는 이 판정이 아예 돌지 않았다.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from krpl_core.config import get_rubric
from krpl_rules import assess_track_a, held_units_for_time_check, rejected_units
from krpl_rules.track_a import HeldUnit
from services.assess.case_state import is_time_doc
from services.assess.package import build_package
from services.catalog import CatalogRepo


def _hash(program_id: str, sources: list[str], rubric_version: str) -> str:
    raw = json.dumps({"p": program_id, "q": sorted(sources), "r": rubric_version},
                     ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def prior_learning_view(s: Session, submission_id: int) -> tuple[list[HeldUnit], list[dict]]:
    """훈련 이수 기록을 「쓸 수 있는 것」과 「왜 못 쓰는지」로 갈라 돌려준다.

    보고서가 「0시간」만 보여 주면 심사위원은 서류를 안 낸 것인지, 냈는데
    안 쳐 준 것인지 구분할 수 없다. 그 둘은 다음에 할 일이 다르다.
    """
    try:
        pkg = build_package(s, submission_id)
    except LookupError:
        return [], []
    rb = get_rubric()
    held = [
        HeldUnit(unit_code=c.unit_code, composed_hours=c.completed_hours,
                 composed_hours_min=None, source=f"이수:{c.doc_key or c.fid}")
        for c in held_units_for_time_check(pkg, rb).values()
    ]
    skipped = [{"unit_code": r.unit_code, "unit_name": r.unit_name,
                "required_hours": r.required_hours, "completed_hours": r.completed_hours,
                "reason": r.reason, "doc_type": r.doc_type}
               for r in rejected_units(pkg, rb)]
    return held, skipped


def held_from_prior_learning(s: Session, submission_id: int) -> list[HeldUnit]:
    """훈련이수증에서 뽑은 기이수를 보유 시간으로 환산한다.

    `eligible_units()` 가 이미 「평가 합격 + 시간 하한」을 걸러 준다.
    편성 하한(80%)에 해당하는 값이 없으므로 `composed_hours_min` 은 비운다 —
    이수증에 적힌 시간은 편성 계획이 아니라 실제 이수 실적이라 흔들릴 여지가 없다.
    """
    return prior_learning_view(s, submission_id)[0]


def _merge(*groups: list[HeldUnit]) -> list[HeldUnit]:
    """능력단위별로 시간이 가장 큰 근거를 채택한다."""
    best: dict[str, HeldUnit] = {}
    for g in groups:
        for h in g:
            cur = best.get(h.unit_code)
            if cur is None or h.composed_hours > cur.composed_hours:
                best[h.unit_code] = h
    return [best[k] for k in sorted(best)]


def run_track_a(s: Session, submission_id: int) -> int:
    """접수 건의 기록 확인을 돌리고 assessment 레코드를 만든다. assessment_id 반환.

    같은 접수 건을 다시 돌리면 이전 기록 확인는 지운다 — 서류가 추가되면
    결과가 달라지므로, 어느 것이 최신인지 헷갈릴 행을 남기지 않는다.
    근거 분석(kind='evidence') 은 건드리지 않는다.
    """
    rb = get_rubric()
    sub = s.execute(text("""
        SELECT id, case_number, target_program_id FROM submission WHERE id=:i"""),
        {"i": submission_id}).mappings().first()
    if sub is None:
        # 접수 건이 지워졌는데 큐에 작업이 남은 경우. 다시 시도해도 소용없다.
        # `.one()` 이 내던 NoResultFound 는 PERMANENT 가 아니라서 영영 재시도했다
        # — 워커를 띄울 때마다 오류 한 줄이 나왔다. build_package 와 같게 맞춘다.
        raise LookupError(f"접수 건이 없습니다: submission_id={submission_id}")

    # 보유 자격 — document.doc_type='과정평가형자격' 의 issuer 에 자격명을 둔다
    qual_ids = [r[0] for r in s.execute(text("""
        SELECT issuer FROM document
        WHERE submission_id=:i AND doc_type='과정평가형자격' AND issuer IS NOT NULL"""),
        {"i": submission_id})]

    repo = CatalogRepo(s)
    prog = repo.get_program(sub["target_program_id"])
    if prog is None:
        raise ValueError(f"종목을 찾을 수 없음: {sub['target_program_id']}")

    by_qual = repo.held_units(qual_ids)
    by_prior, skipped = prior_learning_view(s, submission_id)
    held = _merge(by_qual, by_prior)

    result = assess_track_a(
        prog.program_id, prog.total_hours,
        repo.required_units(prog.program_id),
        held, rb,
    )

    summary = result.summary()
    summary["근거"] = {"자격": len(by_qual), "기이수": len(by_prior), "채택": len(held)}
    # 「이수 기록은 냈는데 갈음되지 않은」 단위. 보고서가 이유를 말할 수 있게 남긴다.
    summary["갈음불가"] = skipped
    # 보류 단위의 추가 증빙 안내에 쓴다 — 무엇을 이미 냈는지.
    summary["제출문서"] = sorted({r[0] for r in s.execute(text(
        "SELECT doc_type FROM document WHERE submission_id=:i"), {"i": submission_id})})

    s.execute(text("DELETE FROM assessment WHERE submission_id=:i AND kind='time'"),
              {"i": submission_id})

    now = datetime.now(timezone.utc)
    aid = s.execute(text("""
        INSERT INTO assessment (submission_id, kind, status, rubric_version, model,
                                input_hash, attempts, started_at, finished_at, overall_note)
        VALUES (:s, 'time', 'done', :rv, 'deterministic', :h, 1, :t, :t, :n)
        RETURNING id"""), {
        "s": submission_id, "rv": rb.version,
        "h": _hash(prog.program_id, qual_ids + [h.source for h in by_prior], rb.version),
        "t": now, "n": json.dumps(summary, ensure_ascii=False),
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

    # 근거 분석에 쓸 자료가 없으면 이 건은 기록 확인으로 끝난다 — 검토 대기로 올린다.
    # 자료가 있으면 status 를 건드리지 않는다. 다음 할 일은 개요 화면이 안내한다.
    kinds = [r[0] for r in s.execute(text(
        "SELECT doc_type FROM document WHERE submission_id=:i"), {"i": submission_id})]
    n_extra = sum(1 for k in kinds if not is_time_doc(k))
    if not n_extra:
        s.execute(text("""UPDATE submission SET status='assessed'
                          WHERE id=:i AND status IN ('received','ingested')"""),
                  {"i": submission_id})

    s.execute(text("""INSERT INTO audit_log (entity, entity_id, action, actor, detail)
                      VALUES ('assessment', :i, 'created', 'system', CAST(:d AS jsonb))"""),
              {"i": str(aid), "d": json.dumps(summary, ensure_ascii=False)})
    return aid
