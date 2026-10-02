"""K-RPL API. 담당자 내부 업무용."""
from __future__ import annotations

import json
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from krpl_core.config import get_rubric, get_settings
from krpl_core.db import get_session
from krpl_core.queue import enqueue, stats, stuck, worker_alive
from services.catalog import CatalogRepo
from services.ingest import UploadRejected, ingest_submission, store
from services.ingest.classify import guess_many
from krpl_core.audit import AuditStore, read_artifact
from datetime import datetime

from services.assess.case_state import case_state
from services.report import (
    env_label, render_artifact, render_audit_case, render_audit_list,
    render_case, render_dashboard, render_home, render_new, render_panel, render_plan,
    render_review, render_stage, render_stats, render_track_a, render_upload,
)
from services.review import (
    receive_document, record_decision, review_summary, save_element_review,
    save_pc_score, save_result, set_stage,
)
from services.review.plan import submit as plan_submit
from services.review.unit_hours import evidence_aid, save_unit_hours, unit_gaps
from services.review.remove import remove as remove_case
from services.report.exemption import render_exemption
from services.report.evidence_focus import render_evidence_focus
from services.review import close as review_close
from services.review import load as review_ctx
from services.gateway.schemas import (
    AssessmentOut, AssessmentStatus, AssessRequest, BulkReviewIn, DecisionIn,
    DecisionOut,
    ElementOut, ElementReviewIn, PcScoreIn, ElementReviewOut, FragmentOut, IngestOut,
    IngestRequest, ProgramOut, RecommendOut, ReviewSummaryOut, SubmissionCreate,
    GuessIn, GuessOut, RemoveIn, UnitHoursIn,
    RemediationIn, RemediationOut,
    SubmissionOut, TrackBAssessmentOut, TrackBElementOut, ValidationAttemptOut,
)

app = FastAPI(title="K-RPL 심사 지원 시스템", version="0.1.0")

# 상태별 다음 폴링 간격(초). 서버가 지정한다 — 클라이언트가 백오프를 짤 필요 없다.
POLL = {"received": 3, "queued": 5, "parsing": 3, "ingested": 3, "assessing": 20, "validating": 5}
STEP = {"received": "1/9 접수", "ingested": "4/9 수집 완료", "queued": "대기", "assessing": "6/9 판정 중",
        "validating": "7/9 검증 중", "assessed": "8/9 검토 대기", "needs_review": "8/9 전문가 확인 필요",
        "decided": "9/9 최종 판정 완료", "failed": "실패"}


@app.get("/health")
def health(s: Session = Depends(get_session)):
    rb = get_rubric()
    return {
        "status": "ok",
        "rubric_version": rb.version,
        "pending_decisions": len(rb.pending_decisions),
        "critical_pending": [p.issue for p in rb.critical_pending],
        "queue": stats(s),
    }


# ── 카탈로그 ──
@app.get("/programs", response_model=list[ProgramOut])
def list_programs(q: str | None = None, active_only: bool = True,
                  limit: int = Query(50, le=200), s: Session = Depends(get_session)):
    return [ProgramOut(**p.__dict__) for p in CatalogRepo(s).search_programs(q, active_only, limit)]


@app.get("/qualifications")
def list_quals(q: str | None = None, limit: int = Query(50, le=200),
               s: Session = Depends(get_session)):
    return CatalogRepo(s).search_qualifications(q, limit)


@app.get("/recommend", response_model=list[RecommendOut])
def recommend(qual: list[str] = Query(..., description="보유 자격 (복수 가능)"),
              limit: int = Query(10, le=50), s: Session = Depends(get_session)):
    """목표 종목 미정 시 — 보유 자격으로 유리한 종목을 찾아준다."""
    floor = get_rubric().training_hours["adjustment_floor"]
    return [
        RecommendOut(
            program_id=r["program_id"], official_name=r["official_name"],
            total_hours=r["total_hours"], common_units=r["common_units"], n_units=r["n_units"],
            credit_rate_strict=round((r["h_full"] or 0) / r["total_hours"], 4),
            credit_rate_adjusted=round((r["h_adj"] or 0) / r["total_hours"], 4),
        ) for r in CatalogRepo(s).recommend_programs(qual, floor, limit)
    ]


# ── 심사 ──
@app.post("/submissions", response_model=SubmissionOut, status_code=202)
def create_submission(body: SubmissionCreate, s: Session = Depends(get_session)):
    repo = CatalogRepo(s)
    if repo.get_program(body.target_program_id) is None:
        raise HTTPException(404, f"종목을 찾을 수 없습니다: {body.target_program_id}")
    if body.track == "A" and not body.qualifications:
        raise HTTPException(422, "Track A 는 보유 자격이 필요합니다. "
                                 "자격이 없으면 Track B 로 접수하세요")
    for q in body.qualifications:
        if repo.get_qualification(q) is None:
            raise HTTPException(404, f"자격을 찾을 수 없습니다: {q}")
    if s.execute(text("SELECT 1 FROM submission WHERE case_number=:c"),
                 {"c": body.case_number}).first():
        raise HTTPException(409, f"이미 접수된 심사번호입니다: {body.case_number}")

    sid = s.execute(text("""
        INSERT INTO submission (case_number, track, target_program_id, note)
        VALUES (:c, :t, :p, :n) RETURNING id"""),
        {"c": body.case_number, "t": body.track, "p": body.target_program_id,
         "n": body.note}).scalar_one()
    # 자격이 없으면 넣지 않는다. 빈 목록을 executemany 에 넘기면
    # 「A value is required for bind parameter」로 터진다.
    if body.qualifications:
        s.execute(text("""INSERT INTO document (submission_id, doc_key, doc_type, grade, issuer)
                          VALUES (:s, :k, '과정평가형자격', 'A', :q)"""),
                  [{"s": sid, "k": f"D{i:02d}", "q": q}
                   for i, q in enumerate(body.qualifications, 1)])
    if body.track == "A":
        enqueue(s, "track_a", {"submission_id": sid})   # 입력이 보유 자격뿐이라 바로 돌릴 수 있다
    # Track B 는 문서 수집 후 POST /submissions/{id}/assess 로 시작한다
    s.execute(text("""INSERT INTO audit_log (entity, entity_id, action, actor)
                      VALUES ('submission', :i, 'created', 'api')"""), {"i": str(sid)})
    return SubmissionOut(id=sid, case_number=body.case_number, track=body.track,
                         target_program_id=body.target_program_id, status="received")


@app.post("/submissions/{sid}/documents", response_model=IngestOut)
def upload_documents(sid: int, body: IngestRequest, s: Session = Depends(get_session)):
    """문서 수집 — 파싱·마스킹·구조화를 즉시 수행한다.

    식별정보는 여기서 제거된다. 원본 서류에 성명·주민번호가 있어도
    조각(fragment)에는 마스킹된 텍스트만 남는다.
    """
    if s.execute(text("SELECT 1 FROM submission WHERE id=:i"), {"i": sid}).first() is None:
        raise HTTPException(404, "접수 건을 찾을 수 없습니다")
    try:
        r = ingest_submission(s, sid, [d.model_dump() for d in body.documents])
    except FileNotFoundError as e:
        raise HTTPException(400, f"파일을 찾을 수 없습니다: {e}") from e
    return IngestOut(**r.summary(), submission_id=sid)


@app.get("/submissions/{sid}/fragments", response_model=list[FragmentOut])
def list_fragments(sid: int, doc_key: str | None = None, stype: str | None = None,
                   s: Session = Depends(get_session)):
    """조각 목록. AI 인용의 원문 대조에 쓴다."""
    q = "SELECT fid, doc_key, doc_type, grade, text, stype, freq FROM fragment WHERE submission_id=:i"
    p: dict = {"i": sid}
    if doc_key:
        q += " AND doc_key=:k"; p["k"] = doc_key
    if stype:
        q += " AND stype=:t"; p["t"] = stype
    return [FragmentOut(**r) for r in s.execute(text(q + " ORDER BY fid"), p).mappings()]


@app.post("/submissions/{sid}/assess", status_code=202)
def start_assessment(sid: int, body: AssessRequest | None = None,
                     s: Session = Depends(get_session)):
    """판정을 시작한다. Track B 는 문서 수집이 끝난 뒤에 부른다."""
    body = body or AssessRequest()
    sub = s.execute(text("SELECT track, status FROM submission WHERE id=:i"),
                    {"i": sid}).mappings().first()
    if sub is None:
        raise HTTPException(404, "접수 건을 찾을 수 없습니다")
    if sub["track"] == "B":
        n = s.execute(text("SELECT count(*) FROM fragment WHERE submission_id=:i"),
                      {"i": sid}).scalar_one()
        if not n:
            raise HTTPException(409, "조각이 없습니다. 문서를 먼저 올리세요")
    done = s.execute(text("""SELECT id FROM assessment
                             WHERE submission_id=:i AND status='done'"""), {"i": sid}).first()
    if done and not body.force:
        raise HTTPException(409, f"이미 판정된 건입니다 (assessment {done[0]}). force=true 로 다시 판정")
    kind = "track_a" if sub["track"] == "A" else "track_b"
    job = enqueue(s, kind, {"submission_id": sid, "profile": body.profile})
    s.execute(text("UPDATE submission SET status='queued' WHERE id=:i"), {"i": sid})
    return {"submission_id": sid, "job_id": job, "kind": kind, "retry_after": POLL["queued"]}


@app.get("/submissions/{sid}/status", response_model=AssessmentStatus)
def get_status(sid: int, s: Session = Depends(get_session)):
    row = s.execute(text("""
        SELECT s.id, s.case_number, s.status, a.id AS aid, a.status AS astatus
        FROM submission s LEFT JOIN assessment a ON a.submission_id = s.id
        WHERE s.id = :i ORDER BY a.id DESC LIMIT 1"""), {"i": sid}).mappings().first()
    if row is None:
        raise HTTPException(404, "접수 건을 찾을 수 없습니다")
    st = row["status"]
    return AssessmentStatus(
        submission_id=row["id"], case_number=row["case_number"], status=st,
        step=STEP.get(st), assessment_id=row["aid"], retry_after=POLL.get(st),
    )


@app.get("/assessments/{aid}", response_model=AssessmentOut | TrackBAssessmentOut)
def get_assessment(aid: int, s: Session = Depends(get_session)):
    """Track A 는 능력단위 단위, Track B 는 능력단위요소 단위로 돌려준다.
    응답의 `track` 을 보고 구분한다."""
    a = s.execute(text("""
        SELECT a.id, a.status, a.rubric_version, a.prompt_version, a.model, a.effort,
               a.attempts, a.cost_usd, a.overall_note,
               s.case_number, s.target_program_id, s.track
        FROM assessment a JOIN submission s ON s.id = a.submission_id
        WHERE a.id = :i"""), {"i": aid}).mappings().first()
    if a is None:
        raise HTTPException(404, "판정 결과를 찾을 수 없습니다")
    if a["track"] == "B":
        return _track_b_out(s, a)
    els = [
        ElementOut(
            unit_code=r["element_id"], verdict=r["evidence_level"],
            recommendation=r["recommendation"], verification=r["verification_method"],
            confidence=r["confidence"], **r["payload"],
        )
        for r in s.execute(text("""
            SELECT element_id, recommendation, evidence_level, verification_method,
                   confidence, payload FROM assessment_element
            WHERE assessment_id = :i ORDER BY (payload->>'required_hours')::int DESC"""),
            {"i": aid}).mappings()
    ]
    return AssessmentOut(
        assessment_id=a["id"], case_number=a["case_number"],
        program_id=a["target_program_id"], rubric_version=a["rubric_version"],
        model=a["model"], summary=json.loads(a["overall_note"]), elements=els,
    )


# 권고 순서대로 — 손 갈 일이 없는 것(R0)부터, 훈련이 필요한 것(R5)까지
_REC_ORDER = "ORDER BY recommendation, element_id"


def _track_b_out(s: Session, a) -> TrackBAssessmentOut:
    note = json.loads(a["overall_note"]) if a["overall_note"] else {}
    val = note.get("validation") or {}
    els = [
        TrackBElementOut(**{k: v for k, v in r["payload"].items()
                            if k in TrackBElementOut.model_fields})
        for r in s.execute(text(
            f"SELECT payload FROM assessment_element WHERE assessment_id=:i {_REC_ORDER}"),
            {"i": a["id"]}).mappings()
    ]
    return TrackBAssessmentOut(
        assessment_id=a["id"], case_number=a["case_number"],
        program_id=a["target_program_id"], status=a["status"],
        rubric_version=a["rubric_version"], prompt_version=a["prompt_version"],
        model=a["model"], attempts=a["attempts"],
        validation_passed=bool(val.get("passed")),
        n_expert_review=sum(1 for e in els if e.needs_expert_review),
        cost_usd=float(a["cost_usd"]) if a["cost_usd"] is not None else None,
        prior_learning_review=note.get("prior_learning_review"),
        overall_note=note.get("overall_note"),
        summary={"validation": val, "package": note.get("package")}, elements=els,
    )


@app.get("/assessments/{aid}/validation", response_model=list[ValidationAttemptOut])
def get_validation(aid: int, s: Session = Depends(get_session)):
    """기계 검증 이력. 몇 번 만에 통과했는지, 무엇이 걸렸는지 남는다."""
    rows = list(s.execute(text("""
        SELECT attempt, passed, error_count, errors FROM validation_log
        WHERE assessment_id=:i ORDER BY attempt"""), {"i": aid}).mappings())
    if not rows:
        if s.execute(text("SELECT 1 FROM assessment WHERE id=:i"), {"i": aid}).first() is None:
            raise HTTPException(404, "판정 결과를 찾을 수 없습니다")
        return []
    return [ValidationAttemptOut(
        attempt=r["attempt"], passed=r["passed"], error_count=r["error_count"],
        by_code=(r["errors"] or {}).get("by_code") or {},
        issues=(r["errors"] or {}).get("issues") or []) for r in rows]


# ── 전문가 검토 ──
def _need_assessment(s: Session, aid: int) -> None:
    if s.execute(text("SELECT 1 FROM assessment WHERE id=:i"), {"i": aid}).first() is None:
        raise HTTPException(404, "판정 결과를 찾을 수 없습니다")


@app.get("/assessments/{aid}/review", response_class=HTMLResponse)
def review_screen(aid: int, ro: int = 0, s: Session = Depends(get_session)):
    """전문가 검토 화면. 근거를 읽고 요소마다 의견을 남긴다. `?ro=1` 이면 열람 전용(입력·제출 막음)."""
    _need_assessment(s, aid)
    kind = s.execute(text("SELECT kind FROM assessment WHERE id=:i"),
                     {"i": aid}).scalar_one()
    return HTMLResponse(render_track_a(s, aid, readonly=bool(ro)) if kind == "time" else render_review(s, aid))


@app.get("/assessments/{aid}/review/summary", response_model=ReviewSummaryOut)
def review_progress(aid: int, s: Session = Depends(get_session)):
    _need_assessment(s, aid)
    sm = review_summary(s, aid)
    other = "proportional" if sm.rule == "all_elements" else "all_elements"
    return ReviewSummaryOut(
        assessment_id=sm.assessment_id, case_number=sm.case_number,
        total_hours=sm.total_hours, n_elements=sm.n_elements, n_reviewed=sm.n_reviewed,
        n_expert_review=sm.n_expert_review, complete=sm.complete, counts=sm.counts,
        n_settled=sm.n_settled, n_left=sm.n_left,
        rule=sm.rule, hours=sm.hours(), hours_conditional=sm.hours(conditional=True),
        hours_other_rule=sm.hours(other),
        hours_other_conditional=sm.hours(other, conditional=True), other_rule=other,
        rate=round(sm.rate(), 4),
        suggested=sm.suggest_decision(), units=sm.basis()["units"],
    )


@app.get("/assessments/{aid}/panel", response_class=HTMLResponse)
def panel(aid: int, ro: int = 0, s: Session = Depends(get_session)):
    """위원 페이지 — 한 지원자 한 쪽 (인정·보류·불인정 · 3점표 · 항목별 인정 · 파라미터). `?ro=1` 이면 열람 전용."""
    _need_assessment(s, aid)
    return HTMLResponse(render_panel(s, aid, readonly=bool(ro)))


@app.post("/assessments/{aid}/panel/submit")
def panel_submit(aid: int, reviewer: str | None = Form(None),
                 plan_units: list[str] = Form([]), plan_units_sent: str | None = Form(None),
                 s: Session = Depends(get_session)):
    """위원 판정 제출 → 단위 판정 스냅샷 + 보류 단위 확인 계획(AI 1회) → 계획 페이지로.

    `plan_units` — 위원이 「확인 계획에 포함」으로 고른 보류 단위(4차 TF 의견 14). 폼에 그 칸이
    있었다는 표시(`plan_units_sent`)가 없으면 예전 폼이므로 보류 단위 전부를 넣는다.
    """
    _need_assessment(s, aid)
    only = list(plan_units) if plan_units_sent else None
    plan_submit(s, aid, reviewer or None, only_codes=only)
    return RedirectResponse(f"/assessments/{aid}/plan", status_code=303)


@app.post("/assessments/{aid}/elements/{element_id}/pc")
def save_pc(aid: int, element_id: str, body: PcScoreIn, s: Session = Depends(get_session)):
    """수행준거 점수 저장(신형). 응답에 서버가 다시 센 단위 판정이 실린다 — 화면은 그 값으로 다시 그린다."""
    _need_assessment(s, aid)
    try:
        return save_pc_score(s, aid, element_id, body.ref, body.score, body.reviewer)
    except LookupError as ex:
        raise HTTPException(404, str(ex)) from ex
    except ValueError as ex:
        raise HTTPException(422, str(ex)) from ex


@app.get("/assessments/{aid}/plan", response_class=HTMLResponse)
def plan_page(aid: int, s: Session = Depends(get_session)):
    """확인 계획 — 보류 단위를 시험 · 시연/구현 · 면접으로 어떻게 확정할지 제안."""
    _need_assessment(s, aid)
    return HTMLResponse(render_plan(s, aid))


@app.post("/assessments/{aid}/elements/{element_id}/review", response_model=ElementReviewOut)
def save_review(aid: int, element_id: str, body: ElementReviewIn,
                s: Session = Depends(get_session)):
    _need_assessment(s, aid)
    try:
        return ElementReviewOut(**save_element_review(
            s, aid, element_id, body.decision, body.note, body.reviewer, body.excluded_evidence))
    except LookupError as ex:
        raise HTTPException(404, str(ex)) from ex
    except ValueError as ex:
        raise HTTPException(422, str(ex)) from ex


@app.post("/assessments/{aid}/reviews", response_model=list[ElementReviewOut])
def save_reviews(aid: int, body: BulkReviewIn, s: Session = Depends(get_session)):
    """여러 요소에 같은 의견을 한 번에 기록한다.

    요소마다 따로 부르면 저장 기록도 그만큼 쌓인다. 한 트랜잭션으로 묶어
    감사 기록도 한 번만 남긴다.
    """
    _need_assessment(s, aid)
    out = []
    try:
        for eid in body.element_ids:
            out.append(ElementReviewOut(**save_element_review(
                s, aid, eid, body.decision, body.note, body.reviewer, body.excluded_evidence)))
    except LookupError as ex:
        raise HTTPException(404, str(ex)) from ex
    except ValueError as ex:
        raise HTTPException(422, str(ex)) from ex
    return out


@app.post("/assessments/{aid}/units/hours")
def save_unit_credit(aid: int, body: UnitHoursIn, s: Session = Depends(get_session)):
    """능력단위별 추가 인정 시간을 저장한다 — 기록 확인 판정의 위원 페이지.

    돌려주는 것은 저장 **뒤**의 셈이다. 화면이 자기 계산을 믿고 그리면
    서버와 갈라진다 — 실제로 네 군데가 그렇게 갈라진 적이 있다.
    """
    _need_assessment(s, aid)
    gaps = save_unit_hours(s, aid, body.hours, body.reviewer)
    return {"assessment_id": aid,
            "units": [{"unit_code": g.unit_code, "unit_name": g.unit_name,
                       "required": g.required, "record": g.record, "gap": g.gap,
                       "granted": g.granted, "counted": g.counted,
                       "ratio": round(g.ratio_final, 4), "passes": g.passes,
                       "credited": g.credited, "to_pass": g.to_pass} for g in gaps],
            "granted_total": sum(g.granted for g in gaps),
            "credited_total": sum(g.credited for g in gaps)}


@app.get("/assessments/{aid}/exemption", response_class=HTMLResponse)
def exemption_report(aid: int, s: Session = Depends(get_session)):
    """면제 결과 — 제출 뒤 보는 한 장. 무엇이 얼마나 면제됐고 훈련이 얼마나 남았나."""
    _need_assessment(s, aid)
    # Track B 는 ③ 확인 계획에서 끝난다 — 면제 결과는 그 흐름에 없다.
    # 라우트만 남겨 두면 500 으로 죽는다(단계 어휘에 'final' 이 없다).
    track = s.execute(text("""SELECT sub.track FROM assessment a
        JOIN submission sub ON sub.id = a.submission_id WHERE a.id=:i"""), {"i": aid}).scalar()
    if (track or "A").upper() == "B":
        raise HTTPException(404, "Track B 는 확인 계획에서 끝납니다 — 면제 결과 화면이 없습니다")
    return HTMLResponse(render_exemption(s, aid))


@app.get("/assessments/{aid}/reviews", response_model=list[ElementReviewOut])
def list_reviews(aid: int, s: Session = Depends(get_session)):
    _need_assessment(s, aid)
    return [ElementReviewOut(
        element_id=r["element_id"], decision=r["decision"],
        ai_recommendation=r["ai_recommendation"],
        agrees_with_ai=(r["decision"] == "인정") == (r["ai_recommendation"] == "R0"))
        for r in s.execute(text("""SELECT element_id, decision, ai_recommendation
                                   FROM element_review WHERE assessment_id=:i
                                   ORDER BY element_id"""), {"i": aid}).mappings()]


@app.post("/submissions/{sid}/decision", response_model=DecisionOut)
def make_decision(sid: int, body: DecisionIn, s: Session = Depends(get_session)):
    """최종 판정 기록. 시스템이 정하지 않는다 — 사람이 정한 것을 받아 적는다."""
    owner = s.execute(text("SELECT submission_id FROM assessment WHERE id=:i"),
                      {"i": body.assessment_id}).scalar()
    if owner is None:
        raise HTTPException(404, "판정 결과를 찾을 수 없습니다")
    if owner != sid:
        raise HTTPException(409, f"판정 {body.assessment_id} 은 이 접수 건의 것이 아닙니다")
    try:
        return DecisionOut(**record_decision(
            s, body.assessment_id, body.decision, body.reason, body.decided_by,
            body.recognized_hours, body.conditional, body.allow_incomplete))
    except ValueError as ex:
        raise HTTPException(409, str(ex)) from ex


@app.get("/submissions/{sid}/decision", response_model=DecisionOut)
def get_decision(sid: int, s: Session = Depends(get_session)):
    r = s.execute(text("""SELECT submission_id, assessment_id, decision, recognized_hours,
                          total_hours, credit_basis, reason, decided_by
                          FROM final_decision WHERE submission_id=:i"""),
                  {"i": sid}).mappings().first()
    if r is None:
        raise HTTPException(404, "최종 판정이 아직 기록되지 않았습니다")
    return DecisionOut(**r)


# ── 감사 ──
@app.get("/audit", response_class=HTMLResponse)
def audit_list(s: Session = Depends(get_session)):
    """접수 건 목록. 각 건의 단계별 진행과 남은 산출물 수를 보여준다."""
    return HTMLResponse(render_audit_list(s))


@app.get("/audit/{case_number}", response_class=HTMLResponse)
def audit_case(case_number: str, s: Session = Depends(get_session)):
    """한 건의 단계별 산출물. 「잘 됐습니다」를 믿지 않아도 되게 하는 화면."""
    if s.execute(text("SELECT 1 FROM submission WHERE case_number=:c"),
                 {"c": case_number}).first() is None:
        raise HTTPException(404, f"접수 건을 찾을 수 없습니다: {case_number}")
    return HTMLResponse(render_audit_case(s, case_number))


@app.get("/audit/artifact/{artifact_id}", response_class=HTMLResponse)
def audit_artifact(artifact_id: int, s: Session = Depends(get_session)):
    """산출물 원문. 저장 당시 해시와 대조해 위·변조 여부를 함께 표시한다."""
    try:
        meta, body = read_artifact(s, artifact_id)
    except LookupError as ex:
        raise HTTPException(404, str(ex)) from ex
    return HTMLResponse(render_artifact(meta, body))


@app.get("/submissions/{sid}/manifest")
def audit_manifest(sid: int, s: Session = Depends(get_session)):
    """산출물 목록을 기계가 읽을 형태로. 해시가 들어 있어 외부 대조에 쓸 수 있다."""
    r = s.execute(text("SELECT case_number FROM submission WHERE id=:i"),
                  {"i": sid}).scalar()
    if r is None:
        raise HTTPException(404, "접수 건을 찾을 수 없습니다")
    return AuditStore(s, r, sid).manifest()


@app.get("/stats", response_class=HTMLResponse)
def stats_page(s: Session = Depends(get_session)):
    return HTMLResponse(render_stats(s))


@app.get("/stats.json")
def stats_json(s: Session = Depends(get_session)):
    """운영 지표. 대시보드·감시 도구가 긁어 갈 수 있게."""
    def one(sql):
        return dict(s.execute(text(sql)).mappings().one())
    return {
        "접수": one("""SELECT count(*) AS 전체,
            count(*) FILTER (WHERE status='decided') AS 최종판정,
            count(*) FILTER (WHERE status='needs_review') AS 확인필요,
            count(*) FILTER (WHERE status='failed') AS 실패 FROM submission"""),
        "판정": one("""SELECT count(*) AS 건수, avg(attempts)::numeric(4,2) AS 평균시도,
            coalesce(sum(cost_usd),0)::numeric(10,4) AS 누적비용,
            coalesce(sum(input_tokens),0) AS 입력토큰,
            coalesce(sum(output_tokens),0) AS 출력토큰
            FROM assessment WHERE status IN ('done','manual_review')"""),
        "검증": one("""SELECT count(*) AS 기록, count(*) FILTER (WHERE passed) AS 통과,
            count(DISTINCT assessment_id) FILTER (WHERE attempt=1 AND passed) AS 일차통과,
            count(DISTINCT assessment_id) AS 대상 FROM validation_log"""),
        "검토": one("""SELECT count(*) AS 요소,
            count(*) FILTER (WHERE (decision='인정')=(ai_recommendation='R0')) AS AI와일치
            FROM element_review"""),
        "산출물": one("SELECT count(*) AS 개수, coalesce(sum(n_bytes),0) AS 바이트 FROM artifact"),
        "큐": stats(s),
    }


# ══════════════════ 담당자 화면 ══════════════════
def _env(s: Session) -> str:
    return env_label(get_settings(), get_rubric())


def _next_case(s: Session) -> str:
    """다음 심사번호를 제안한다. 올해 쓴 것 중 가장 큰 번호 + 1.
    담당자가 고쳐도 되고, 겹치면 등록 단계에서 409 로 막힌다."""
    from datetime import date
    pre = f"{get_settings().app.case_number_prefix}{date.today().year}-"
    last = s.execute(text("""
        SELECT max(substring(case_number from '\\d{4}$')::int) FROM submission
        WHERE case_number LIKE :p"""), {"p": f"{pre}%"}).scalar()
    return f"{pre}{(last or 0) + 1:04d}"


TODO_OF = {"received": "서류", "ingested": "분석", "failed": "분석",
           "assessed": "검토", "needs_review": "확인"}
STEP_KO = {"received": "서류 대기", "ingested": "분석 대기", "queued": "분석 대기",
           "assessing": "분석 중", "assessed": "검토 대기",
           "needs_review": "확인 필요", "decided": "완료", "failed": "실패"}


@app.get("/", response_class=HTMLResponse)
def home(s: Session = Depends(get_session)):
    """첫 화면. 흐름을 보여 주고 지금 할 일로 바로 보낸다."""
    counts = dict(s.execute(text(
        "SELECT status, count(*) FROM submission GROUP BY 1")).all())
    todo: dict[str, int] = {}
    for st, n in counts.items():
        if k := TODO_OF.get(st):
            todo[k] = todo.get(k, 0) + n
    recent = [dict(r) | {"step": STEP_KO.get(r["status"], r["status"])}
              for r in s.execute(text("""
        SELECT sub.id, sub.case_number, sub.target_program_id, sub.status,
               sub.received_at, sub.track, p.official_name
        FROM submission sub LEFT JOIN catalog_wsd_program p
             ON p.program_id = sub.target_program_id
        ORDER BY sub.received_at DESC LIMIT 5""")).mappings()]
    return HTMLResponse(render_home(todo, recent, sum(counts.values()),
                                    len(get_rubric().pending_decisions), _env(s)))


@app.get("/cases/progress.json")
def cases_progress(s: Session = Depends(get_session)):
    """도는 중인 판정의 진행 상황. 화면이 이 값만 긁어 막대를 움직인다.

    통째로 새로고침하지 않는 이유는 검토 중인 화면이 튀지 않게 하기 위해서다.
    """
    rows = s.execute(text("""
        SELECT sub.id, sub.status, a.id AS aid, a.progress
        FROM submission sub
        LEFT JOIN LATERAL (SELECT * FROM assessment z WHERE z.submission_id=sub.id
                           ORDER BY z.id DESC LIMIT 1) a ON true
        WHERE sub.status IN ('queued','assessing')""")).mappings()
    out = {}
    for r in rows:
        pg = r["progress"] or {}
        total, done = pg.get("전체") or 0, pg.get("완료") or 0
        out[str(r["id"])] = {
            "status": r["status"],
            "step": pg.get("단계") or ("대기" if r["status"] == "queued" else "시작 중"),
            "done": done, "total": total,
            "pct": round(done / total * 100) if total else 0,
            "settled": pg.get("확정") or 0,
            "remaining": (pg.get("남은") or [])[:3],
        }
    return {"running": out, "queue": stats(s)}


@app.get("/cases", response_class=HTMLResponse)
def dashboard(s: Session = Depends(get_session)):
    """접수 현황. 단계별로 묶고 다음 할 일 버튼을 하나씩 놓는다."""
    rows = [dict(r) for r in s.execute(text("""
        SELECT sub.id, sub.case_number, sub.track, sub.target_program_id, sub.status,
               sub.received_at, sub.note, p.official_name,
               (SELECT count(*) FROM document d WHERE d.submission_id=sub.id) AS n_doc,
               (SELECT count(*) FROM fragment f WHERE f.submission_id=sub.id) AS n_frag,
               a.id AS aid,
               (SELECT count(*) FROM assessment_element x WHERE x.assessment_id=a.id) AS n_el,
               (SELECT count(*) FROM element_review v WHERE v.assessment_id=a.id) AS n_rev,
               fd.decision, fd.recognized_hours, fd.total_hours
        FROM submission sub
        LEFT JOIN catalog_wsd_program p ON p.program_id = sub.target_program_id
        LEFT JOIN LATERAL (SELECT * FROM assessment z WHERE z.submission_id=sub.id
                           ORDER BY z.id DESC LIMIT 1) a ON true
        LEFT JOIN final_decision fd ON fd.submission_id = sub.id
        -- 비고가 「★」로 시작하는 건은 맨 위에 — 집담회처럼 「오늘 볼 것」을 표시할 때 쓴다
        ORDER BY (sub.note LIKE '★%') DESC, sub.note, sub.received_at DESC""")).mappings()]

    # 「다음 할 일」과 시간 요약은 case_state 가 정한다 — 목록과 개요가
    # 각자 SQL 로 답하면 반드시 어긋난다. 건수가 적어 그대로 돈다.
    for r in rows:
        st = case_state(s, r["id"])
        if st is None:
            continue
        r["next_step"] = st.next_step
        r["hours_note"] = (f"확인 {st.credited_hours}h / 총 {st.total_hours}h"
                           if st.time else f"총 {st.total_hours}h")
        # 검토 진척은 **판단 대상**으로 센다. 요소 전체로 세면 이수 기록으로
        # 확정된 것까지 세어, 다 끝낸 건이 「22/30」으로 남아 보인다.
        r["n_judge"], r["n_judged"] = st.n_judge, st.judged
        r["n_settled"] = st.n_settled

    return HTMLResponse(render_dashboard(
        rows, stats(s), worker_alive(s), len(get_rubric().pending_decisions),
        _env(s), stuck=stuck(s)))


@app.get("/submissions/new", response_class=HTMLResponse)
def new_submission_form(s: Session = Depends(get_session)):
    rb = get_rubric()
    types = [{"name": k, "grade": v["grade"]} for k, v in rb.document_types.items()]
    return HTMLResponse(render_new([], types, _next_case(s), _env(s)))


@app.get("/submissions/{sid}/upload", response_class=HTMLResponse)
def upload_form(sid: int, s: Session = Depends(get_session)):
    sub = s.execute(text("""
        SELECT sub.id, sub.case_number, sub.track, sub.target_program_id, sub.status,
               p.official_name
        FROM submission sub LEFT JOIN catalog_wsd_program p
             ON p.program_id = sub.target_program_id
        WHERE sub.id = :i"""), {"i": sid}).mappings().first()
    if sub is None:
        raise HTTPException(404, "접수 건을 찾을 수 없습니다")
    rb = get_rubric()
    types = [{"name": k, "grade": v["grade"]} for k, v in rb.document_types.items()]
    existing = [dict(r) for r in s.execute(text("""
        SELECT d.doc_key, d.doc_type, d.grade, d.issuer,
               (SELECT count(*) FROM fragment f
                WHERE f.submission_id=d.submission_id AND f.doc_key=d.doc_key) AS n_frag
        FROM document d WHERE d.submission_id=:i ORDER BY d.doc_key"""),
        {"i": sid}).mappings()]
    st = get_settings().storage
    return HTMLResponse(render_upload(dict(sub), types, rb.grade_order, existing,
                                      _env(s), accept=st.allowed_extensions,
                                      max_mb=st.max_upload_mb))


@app.post("/submissions/{sid}/upload", response_model=IngestOut)
def upload_files(sid: int,
                     files: list[UploadFile] = File(...),
                     doc_types: list[str] = Form(...),
                     grades: list[str] = Form(...),
                     issuers: list[str] | None = Form(None),
                     s: Session = Depends(get_session)):
    """파일을 받아 저장하고 곧바로 수집한다.

    원본을 디스크에 남긴 뒤 그 경로로 수집을 부른다 —
    수집이 실패해도 파일은 남아 다시 시도할 수 있다.
    """
    sub = s.execute(text("SELECT case_number FROM submission WHERE id=:i"),
                    {"i": sid}).scalar()
    if sub is None:
        raise HTTPException(404, "접수 건을 찾을 수 없습니다")
    if not (len(files) == len(doc_types) == len(grades)):
        raise HTTPException(422, "파일 수와 종류·등급 수가 맞지 않습니다")

    rb = get_rubric()
    seq = s.execute(text("SELECT count(*) FROM document WHERE submission_id=:i"),
                    {"i": sid}).scalar_one()
    docs = []
    for n, (f, t, g) in enumerate(zip(files, doc_types, grades), start=seq + 1):
        if g not in rb.grades:
            raise HTTPException(422, f"모르는 신뢰도 등급입니다: {g}")
        if t not in rb.document_types:
            t = "기타"                     # 접수는 다 받는다. 종류 지정은 나중에 (2026-09-23)
        try:
            st = store(sub, f.filename or f"doc{n}", f.file.read(), n)
        except UploadRejected as ex:
            raise HTTPException(422, f"{f.filename}: {ex}") from ex
        docs.append({"doc_key": st.doc_key, "doc_type": t, "grade": g,
                     "file_path": str(st.path),
                     "issuer": (issuers or [None] * len(files))[n - seq - 1]})

    r = ingest_submission(s, sid, docs)
    return IngestOut(**r.summary(), submission_id=sid)


# ── 심사 개요와 보고서 ────────────────────────────────────────────
# 접수번호를 누르면 여기로 온다. 심사는 보고서를 만드는 일이고,
# 판단 입력은 보고서를 읽은 다음이다. 그래서 화면이 갈라져 있다.

@app.get("/submissions/{sid}", response_class=HTMLResponse)
def case_screen(sid: int, s: Session = Depends(get_session)):
    """심사 개요 — 어디까지 왔고 다음에 무엇을 할지."""
    out = render_case(s, sid)
    if out is None:
        raise HTTPException(404, "접수 건을 찾을 수 없습니다")
    return HTMLResponse(out)


@app.get("/submissions/{sid}/report/time", response_class=HTMLResponse)
def time_report(sid: int, s: Session = Depends(get_session)):
    """① 기록 확인 보고서 — 기록으로 확인되는 이수 시간."""
    aid = s.execute(text("""SELECT id FROM assessment
                            WHERE submission_id=:i AND kind='time'
                            ORDER BY id DESC LIMIT 1"""), {"i": sid}).scalar()
    if aid is None:
        raise HTTPException(404, "기록 확인 결과가 없습니다. 서류를 먼저 올리세요")
    return HTMLResponse(render_track_a(s, aid, editable=False))


@app.get("/submissions/{sid}/report/evidence", response_class=HTMLResponse)
def evidence_report(sid: int, s: Session = Depends(get_session)):
    """② 근거 분석 보고서 — 제출 자료에서 무엇이 확인됐나. 읽기 전용.

    검증을 3회 안에 통과하지 못한 판정(`manual_review`)도 연다. 산출물은 저장해
    두는데 보고서만 닫아 두면, 같은 판정을 위원 페이지는 그려 주는데 보고서는
    404 가 된다.

    고르는 기준은 상태가 아니라 **요소가 실제로 있는가**다. 뒤에 돌린 실행이
    빈 채로 끝나면 id 만 보고 그것을 집어 「결과가 비어 있습니다」를 내민다 —
    앞서 나온 멀쩡한 보고서를 덮어 버리는 셈이다.
    """
    aid = s.execute(text("""SELECT a.id FROM assessment a
                            WHERE a.submission_id=:i AND a.kind='evidence'
                              AND a.status IN ('done', 'manual_review')
                              AND EXISTS (SELECT 1 FROM assessment_element e
                                           WHERE e.assessment_id = a.id)
                            ORDER BY a.id DESC LIMIT 1"""), {"i": sid}).scalar()
    if aid is None:
        raise HTTPException(404, "근거 분석 결과가 없습니다")
    return HTMLResponse(render_evidence_focus(s, sid))


@app.post("/submissions/{sid}/evidence/confirm")
def confirm_evidence(sid: int, s: Session = Depends(get_session)):
    """② 근거 분석을 「확인했다」고 표시한다.

    ② 는 읽는 자리다 — 눌러서 바뀌는 것이 없으니 상태가 영영 그대로였고,
    기계 검증을 통과 못 한 건은 「확인 필요」에 머물러 다음으로 넘어가지 못했다.
    사람이 읽었다는 사실만 남기면 흐름이 ③ 으로 넘어간다.

    감사 기록에 남긴다 — 누가 언제 확인하고 넘어갔는지가 판정의 일부다.
    """
    aid = evidence_aid(s, sid)
    if aid is None:
        raise HTTPException(409, "확인할 근거 분석 결과가 없습니다")
    s.execute(text("""INSERT INTO audit_log (entity, entity_id, action, actor, detail)
                      VALUES ('assessment', :i, 'evidence_confirmed', 'user',
                              CAST(:d AS jsonb))"""),
              {"i": str(aid), "d": json.dumps({"submission_id": sid}, ensure_ascii=False)})
    # 「확인 필요」는 기계 검증을 통과 못 했으니 사람이 보라는 뜻이다. 사람이 보고
    # 넘어갔으면 그 상태에서 내려와야 한다 — 안 그러면 할 일 목록에 영영 남는다.
    s.execute(text("""UPDATE submission SET status='assessed'
                      WHERE id=:i AND status='needs_review'"""), {"i": sid})
    return RedirectResponse(f"/submissions/{sid}", status_code=303)


@app.post("/submissions/{sid}/remove")
def remove_submission(sid: int, body: RemoveIn, s: Session = Depends(get_session)):
    """접수 건을 지운다 — 되돌릴 수 없다.

    화면에서 온 요청이므로 끝나면 접수 현황으로 돌려보낸다. 지운 사실과 무엇이
    있었는지는 `audit_log` 에 남는다(그 표에는 외래키가 없어 살아남는다).
    """
    try:
        out = remove_case(s, sid, body.confirm, body.purge_audit, body.actor)
    except LookupError as ex:
        raise HTTPException(404, str(ex)) from ex
    except ValueError as ex:
        raise HTTPException(409, str(ex)) from ex
    return out


@app.post("/submissions/{sid}/analyze")
def start_analysis(sid: int, s: Session = Depends(get_session)):
    """② 근거 분석을 시작한다. 개요 화면의 버튼이 부른다.

    화면에서 온 요청이므로 끝나면 개요로 돌려보낸다 — JSON 을 띄우지 않는다.
    """
    st = case_state(s, sid)
    if st is None:
        raise HTTPException(404, "접수 건을 찾을 수 없습니다")
    # 이미 도는 중이거나 큐에서 기다리는 중이면 또 넣지 않는다.
    # 화면이 아무 말도 안 하던 때, 사람이 다시 눌러 같은 작업이 두 건 쌓였다.
    if st.analyzing or (st.evidence and st.evidence.done):
        return RedirectResponse(f"/submissions/{sid}", status_code=303)
    # manual_review·failed 로 끝난 것은 다시 돌릴 수 있다 — 위 조건이 그것을
    # 막지 않는다(done 도 running 도 아니므로).
    if not st.can_analyze:
        raise HTTPException(409, "근거 분석에 쓸 자료가 없습니다")
    enqueue(s, "track_b", {"submission_id": sid, "profile": None})
    s.execute(text("UPDATE submission SET status='queued' WHERE id=:i"), {"i": sid})
    return RedirectResponse(f"/submissions/{sid}", status_code=303)


# ── 전문가 검토 5단계 ─────────────────────────────────────────────
# 요소 서른셋에 한꺼번에 가·부를 찍으라고 하면 무엇부터 볼지 알 수 없다.
# 심사는 원래 순서가 있는 일이다 — 서류로 정할 것, 서류를 더 받을 것,
# 면접, 실기, 그리고 최종. 화면이 그 순서를 따라간다.

@app.get("/assessments/{aid}/review/{stage}", response_class=HTMLResponse)
def review_stage(aid: int, stage: int,
                 받음: str | None = Query(None), 조각: int | None = Query(None),
                 요소: int | None = Query(None),
                 s: Session = Depends(get_session)):
    ctx = review_ctx(s, aid)
    if ctx is None:
        raise HTTPException(404, "근거 분석 결과를 찾을 수 없습니다")
    if not 1 <= stage <= 5:
        raise HTTPException(404, "1~5 단계만 있습니다")
    set_stage(s, aid, stage)
    notice = ""
    if 받음:
        notice = (f"<b>{받음}</b>을(를) 받았습니다 — 조각 {조각 or 0}개를 수집했고, "
                  f"이 서류가 걸린 요소 {요소 or 0}개를 다시 판정합니다.")
    st = case_state(s, ctx.submission_id)
    return HTMLResponse(render_stage(ctx, stage, notice=notice,
                                     analyzing=bool(st and st.analyzing)))


@app.post("/assessments/{aid}/remediation", response_model=RemediationOut)
def record_remediation(aid: int, body: RemediationIn,
                       s: Session = Depends(get_session)):
    """보완 항목 하나의 결과를 기록한다.

    항목은 여러 요소에 걸쳐 병합돼 있다 — 「안전보건교육 이수확인서」 한 건이
    5개 단위 15개 요소를 한꺼번에 푼다. 요소마다 묻지 않는 이유다.
    """
    ctx = review_ctx(s, aid)
    if ctx is None:
        raise HTTPException(404, "근거 분석 결과를 찾을 수 없습니다")
    known = {i.key: i for g in ctx.items.values() for i in g}
    it = known.get(body.key)
    if it is None:
        raise HTTPException(404, "그런 보완 항목이 없습니다")
    try:
        save_result(s, aid, it.key, it.method, it.item, body.result,
                    note=body.note, reviewer=body.reviewer)
    except ValueError as ex:
        raise HTTPException(422, str(ex)) from ex
    s.execute(text("""INSERT INTO audit_log (entity, entity_id, action, actor, detail)
                      VALUES ('assessment', :i, 'remediation', :w, CAST(:d AS jsonb))"""),
              {"i": str(aid), "w": body.reviewer or "심사자",
               "d": json.dumps({"방법": it.method, "항목": it.item,
                                "결과": body.result, "대상요소": it.n_elements},
                               ensure_ascii=False)})
    fresh = review_ctx(s, aid)
    got, tot = fresh.recognized_hours()
    return RemediationOut(
        key=it.key, result=body.result,
        stamp=f"{body.reviewer or '심사자'} {datetime.now():%Y-%m-%d}",
        recognized_hours=got, total_hours=tot,
        n_recognized=sum(1 for v in fresh.outcome_of.values() if v == "인정"))


@app.post("/assessments/{aid}/items/{key}/document")
def receive_item_document(aid: int, key: str,
                          file: UploadFile = File(...),
                          doc_type: str | None = Form(None),
                          grade: str | None = Form(None),
                          reviewer: str | None = Form(None),
                          s: Session = Depends(get_session)):
    """2단계 항목에 추가 서류를 붙인다.

    받은 서류를 조각으로 수집하고, 그 서류가 풀려던 요소만 다시 판정한다.
    면접·실기 항목과 질문지가 새 자료를 반영해 다시 만들어진다.
    화면에서 온 요청이므로 끝나면 2단계로 돌려보낸다.
    """
    try:
        r = receive_document(s, aid, key, file.filename or "서류",
                             file.file.read(), doc_type=doc_type, grade=grade,
                             reviewer=reviewer)
    except UploadRejected as ex:
        raise HTTPException(422, f"{file.filename}: {ex}") from ex
    except LookupError as ex:
        raise HTTPException(404, str(ex)) from ex
    except ValueError as ex:
        raise HTTPException(422, str(ex)) from ex
    return RedirectResponse(
        f"/assessments/{aid}/review/2?받음={quote(r.doc_type)}&조각={r.n_fragments}"
        f"&요소={len(r.focus)}", status_code=303)


@app.post("/assessments/{aid}/stages/{stage}/close")
def close_stage(aid: int, stage: int, s: Session = Depends(get_session)):
    """단계를 마감한다. 손대지 않은 것만 기본값으로 확정한다.

    항목마다 찍게 하는 대신 단계마다 한 번 누르게 한다 — 올린 것은 받은
    것이고 안 올린 것은 못 받은 것이다.
    """
    try:
        c = review_close(s, aid, stage)
    except LookupError as ex:
        raise HTTPException(404, str(ex)) from ex
    except ValueError as ex:
        raise HTTPException(422, str(ex)) from ex
    return {"stage": c.stage, "settled": c.settled, "already": c.already,
            "total": c.total}


@app.post("/doc-types/guess", response_model=list[GuessOut])
def guess_doc_types(body: GuessIn):
    """파일 이름으로 서류 종류를 알아맞힌다.

    담당자가 파일 열한 개의 종류를 하나씩 고르는 것은 지루하고, 지루하면
    대충 고른다. 이름은 대개 정직하다 — 거기서 읽어 낸다.
    못 맞히면 비워서 돌려준다. 틀리게 맞히는 것보다 낫다.

    파일 이름만 받는다 — 내용은 올리기 전이라 아직 없다.
    """
    return [GuessOut(name=n, doc_type=g.doc_type, grade=g.grade, matched=g.matched)
            for n, g in zip(body.names, guess_many(body.names))]


@app.get("/submissions/{sid}/progress.json")
def case_progress(sid: int, s: Session = Depends(get_session)):
    """근거 분석이 어디까지 왔나. 개요 화면이 3초마다 이것만 긁는다.

    통째로 새로고침하면 스크롤이 튀고 열어 둔 것이 닫힌다.
    """
    st = case_state(s, sid)
    if st is None:
        raise HTTPException(404, "접수 건을 찾을 수 없습니다")
    if not st.analyzing:
        return {"done": True, "pct": 100, "text": "끝났습니다"}

    ev = st.evidence
    if st.waiting_in_queue:
        text_ = ("판정 워커가 돌고 있지 않습니다 — ./scripts/dev.sh worker"
                 if st.stalled else "차례를 기다리는 중")
        return {"done": False, "pct": 0, "text": text_, "stalled": st.stalled}

    n_done, n_all, phase, left = ev.steps
    tail = f" · {left[0]} 외 {len(left) - 1}" if len(left) > 1 else (
        f" · {left[0]}" if left else "")
    return {"done": False, "pct": round(n_done / n_all * 100) if n_all else 0,
            "text": f"{n_done}/{n_all or '?'} 능력단위 · {phase}{tail}",
            "stalled": False}
