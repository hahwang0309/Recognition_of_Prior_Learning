"""접수 건 하나가 지금 어디까지 왔는지 — 화면들이 공유하는 단 하나의 답.

## 왜 모으는가

같은 질문(「이 건은 근거 분석을 돌릴 수 있나」, 「검토는 몇 개 남았나」)을
대시보드와 개요 화면이 각자 SQL 로 답하면 반드시 어긋난다. 실제로 판정 화면과
목록 화면이 다른 말을 하고 있었다. 그래서 답은 여기서만 만든다.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.review.triage import needs_judgment

# 시간 대조가 이미 값을 뽑아 쓴 자료. 근거 분석에서 「추가 자료」로 세지 않는다.
TIME_DOC_TYPES = {"과정평가형자격", "NCS 기반 훈련과정 이수증", "교육과정 편성표"}

log = logging.getLogger(__name__)


@dataclass
class Run:
    """판정 한 번."""
    id: int
    status: str
    model: str | None
    attempts: int
    cost: float | None
    started_at: datetime | None
    finished_at: datetime | None
    note: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, Any] | None = None
    n_elements: int = 0

    @property
    def done(self) -> bool:
        return self.status == "done"

    @property
    def running(self) -> bool:
        return self.status in ("running", "queued")


@dataclass
class CaseState:
    submission_id: int
    case_number: str
    track: str
    status: str
    received_at: datetime | None
    program_id: str
    program_name: str
    total_hours: int
    n_documents: int
    n_fragments: int
    extra_docs: list[dict]                  # 근거 분석에 쓸 수 있는 자료
    time: Run | None                        # ① 시간 대조
    evidence: Run | None                    # ② 근거 분석 — **가장 최근** 실행
    # 이미 끝난 근거 분석. 새 실행이 도는 중이라도 지난 보고서는 계속 열려야 한다.
    # 이것을 나누지 않았을 때, 재실행 한 번에 완성된 보고서가 화면에서 사라졌다.
    evidence_done: Run | None
    n_reviewed: int                         # ③ 전문가 검토 — 판단이 기록된 요소 수
    n_judge: int                            # 사람이 따져야 하는 요소 수
    next_stage: int                         # 다음에 손댈 검토 단계 (1~5)
    stage_line: str                         # 다섯 단계 진척을 한 줄로
    n_settled: int                          # 기록으로 확정돼 확인만 하면 되는 수
    judged: int                             # 그중 판단이 기록된 수
    decision: dict | None                   # ④ 최종 판정

    # ── ① 시간 대조에서 나온 숫자 ──
    @property
    def credited_hours(self) -> int:
        h = (self.time.note.get("hours") if self.time else None) or {}
        return int(h.get("완전충족", 0)) + int(h.get("조정범위내", 0))

    @property
    def open_hours(self) -> int:
        """기록으로 덮이지 않아 근거 분석이 다뤄야 할 시간."""
        h = (self.time.note.get("hours") if self.time else None) or {}
        return int(h.get("시간부족", 0)) + int(h.get("미이수", 0))

    @property
    def credited_ratio(self) -> float:
        return self.credited_hours / self.total_hours if self.total_hours else 0.0

    @property
    def skipped(self) -> list[dict]:
        """이수 기록은 냈으나 갈음되지 않은 단위 — 왜인지까지."""
        return (self.time.note.get("갈음불가") if self.time else None) or []

    # ── ② 근거 분석 ──
    @property
    def can_analyze(self) -> bool:
        """돌릴 만한 자료가 있는가. 없으면 버튼을 내밀지 않는다."""
        return bool(self.extra_docs)

    @property
    def n_elements(self) -> int:
        return self.evidence_done.n_elements if self.evidence_done else 0

    @property
    def analyzing(self) -> bool:
        return bool(self.evidence and self.evidence.running)

    # ── ③ 검토 ──
    # 진척은 **판단 대상**으로 센다. 훈련이수증으로 확정된 항목까지 한 줄씩
    # 누르게 하면 정작 따져야 할 것에 쓸 힘이 흩어진다. 확정분은 묶음으로
    # 한 번에 확인한다 (검토 화면의 「인정 N개」 버튼).
    @property
    def review_done(self) -> bool:
        return self.n_judge > 0 and self.judged >= self.n_judge

    @property
    def review_left(self) -> int:
        return max(0, self.n_judge - self.judged)

    # ── 다음에 할 일 하나 ──
    @property
    def next_step(self) -> tuple[str, str] | None:
        """(문구, 링크). 링크가 'analyze' 면 화면이 POST 로 처리한다."""
        if self.decision:
            return None
        if self.n_documents == 0:
            return ("서류 올리기", f"/submissions/{self.submission_id}/upload")
        if self.analyzing:
            return None                                  # 진행 중 — 기다린다
        if self.evidence_done:
            if not self.review_done:
                return (f"검토하기 ({self.review_left}개 남음)",
                        f"/assessments/{self.evidence_done.id}/review")
            return ("최종 판정 기록", f"/assessments/{self.evidence_done.id}/review#decide")
        if self.can_analyze:
            return ("근거 분석 시작", "analyze")
        return ("최종 판정 기록", f"/submissions/{self.submission_id}#decide")


def _note(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            return json.loads(raw)
        except ValueError:
            return {}
    return {}


def _runs(s: Session, submission_id: int, *, only_done: bool = False) -> dict[str, Run]:
    """kind 별로 가장 최근 판정 하나씩. only_done 이면 끝난 것 중에서 고른다."""
    out: dict[str, Run] = {}
    where = " AND a.status='done'" if only_done else ""
    for r in s.execute(text(f"""
        SELECT DISTINCT ON (a.kind)
               a.kind, a.id, a.status, a.model, a.attempts, a.cost_usd,
               a.started_at, a.finished_at, a.overall_note, a.progress,
               (SELECT count(*) FROM assessment_element e WHERE e.assessment_id=a.id) AS n
        FROM assessment a WHERE a.submission_id=:i{where}
        ORDER BY a.kind, a.id DESC"""), {"i": submission_id}).mappings():
        out[r["kind"]] = Run(
            id=r["id"], status=r["status"], model=r["model"], attempts=r["attempts"],
            cost=float(r["cost_usd"]) if r["cost_usd"] is not None else None,
            started_at=r["started_at"], finished_at=r["finished_at"],
            note=_note(r["overall_note"]), progress=r["progress"], n_elements=r["n"])
    return out


def case_state(s: Session, submission_id: int) -> CaseState | None:
    sub = s.execute(text("""
        SELECT s.id, s.case_number, s.track, s.status, s.received_at,
               s.target_program_id, g.official_name, g.total_hours
        FROM submission s
        LEFT JOIN catalog_wsd_program g ON g.program_id = s.target_program_id
        WHERE s.id=:i"""), {"i": submission_id}).mappings().first()
    if sub is None:
        return None

    docs = [dict(r) for r in s.execute(text("""
        SELECT d.doc_type, d.doc_key, d.grade, d.issuer,
               (SELECT count(*) FROM fragment f
                 WHERE f.submission_id=d.submission_id AND f.doc_key=d.doc_key) AS n_frag
        FROM document d WHERE d.submission_id=:i ORDER BY d.doc_key"""),
        {"i": submission_id}).mappings()]

    runs = _runs(s, submission_id)
    done_runs = _runs(s, submission_id, only_done=True)
    ev, ev_done = runs.get("evidence"), done_runs.get("evidence")
    n_reviewed = n_judge = n_settled = judged = 0
    next_stage, stage_line = 1, ""
    if ev_done is not None:
        n_reviewed = s.execute(text(
            "SELECT count(DISTINCT element_id) FROM element_review WHERE assessment_id=:a"),
            {"a": ev_done.id}).scalar_one()
        done_ids = {r[0] for r in s.execute(text(
            "SELECT DISTINCT element_id FROM element_review WHERE assessment_id=:a"),
            {"a": ev_done.id})}
        rows = [dict(r) for r in s.execute(text(
            "SELECT element_id, payload FROM assessment_element WHERE assessment_id=:a"),
            {"a": ev_done.id}).mappings()]
        for r in rows:
            if needs_judgment(r["payload"] or {}):
                n_judge += 1
                judged += r["element_id"] in done_ids
            else:
                n_settled += 1

        # 다섯 단계 가운데 어디에 서 있나. 계산은 services/review 에만 둔다 —
        # 개요와 검토 화면이 각자 세면 「몇 단계」가 서로 다르게 나온다.
        try:
            from services.review import load as _review_ctx
            rc = _review_ctx(s, ev_done.id)
            if rc is not None:
                next_stage = rc.next_stage
                stage_line = " · ".join(
                    f"{x.n}{x.title} " + ("건너뜀" if x.skipped else
                                          "완료" if x.complete else f"{x.done}/{x.total}")
                    for x in rc.states if x.n < 5)
        except Exception:                                     # noqa: BLE001
            log.warning("검토 단계 계산 실패 assessment=%s", ev_done.id, exc_info=True)

    dec = s.execute(text("""
        SELECT decision, reason, decided_by, recognized_hours, total_hours, decided_at
        FROM final_decision WHERE submission_id=:i
        ORDER BY id DESC LIMIT 1"""), {"i": submission_id}).mappings().first()

    return CaseState(
        submission_id=sub["id"], case_number=sub["case_number"], track=sub["track"],
        status=sub["status"], received_at=sub["received_at"],
        program_id=sub["target_program_id"],
        program_name=sub["official_name"] or sub["target_program_id"],
        total_hours=sub["total_hours"] or 0,
        n_documents=len(docs), n_fragments=sum(d["n_frag"] for d in docs),
        extra_docs=[d for d in docs if d["doc_type"] not in TIME_DOC_TYPES],
        time=done_runs.get("time") or runs.get("time"),
        evidence=ev, evidence_done=ev_done, n_reviewed=n_reviewed,
        n_judge=n_judge, n_settled=n_settled, judged=judged,
        next_stage=next_stage, stage_line=stage_line,
        decision=dict(dec) if dec else None,
    )


def case_states(s: Session, ids: list[int]) -> dict[int, CaseState]:
    """목록 화면용. N+1 을 피할 만큼 크지 않으므로 그대로 돈다."""
    return {i: st for i in ids if (st := case_state(s, i)) is not None}
