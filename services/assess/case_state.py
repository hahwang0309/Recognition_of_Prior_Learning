"""접수 건 하나가 지금 어디까지 왔는지 — 화면들이 공유하는 단 하나의 답.

## 왜 모으는가

같은 질문(「이 건은 근거 분석을 돌릴 수 있나」, 「검토는 몇 개 남았나」)을
대시보드와 개요 화면이 각자 SQL 로 답하면 반드시 어긋난다. 실제로 판정 화면과
목록 화면이 다른 말을 하고 있었다. 그래서 답은 여기서만 만든다.
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from krpl_core.queue import worker_alive

from services.review.triage import needs_judgment

def _norm(s: str) -> str:
    """문서 종류 이름을 견주기 좋게 다듬는다.

    같은 문서를 두 이름으로 부르고 있었다 — 화면(기준서)은 `NCS기반_훈련이수증`,
    실사례 데이터는 `NCS 기반 훈련과정 이수증`. 그래서 화면으로 올린 이수증이
    「추가 자료」로 세어졌다. 공백·밑줄·가운뎃점을 지우고 견준다.
    """
    return re.sub(r"[\s_·∙‧・]|과정|기반", "", s or "")


@lru_cache(maxsize=1)
def _time_doc_types() -> frozenset[str]:
    """기록 확인이 이미 값을 뽑아 쓴 자료. 근거 분석에서 「추가 자료」로 세지 않는다.

    어느 문서가 그런지는 정책이므로 기준서(`document_types.*.time_source`)가 정한다.
    코드에 적어 두었더니 화면 어휘와 어긋났다.
    """
    from krpl_core.config import get_rubric
    names = {"과정평가형자격"}
    for name, spec in (get_rubric().document_types or {}).items():
        if isinstance(spec, dict) and spec.get("time_source"):
            names.add(name)
    return frozenset(_norm(n) for n in names)


def is_time_doc(doc_type: str) -> bool:
    return _norm(doc_type) in _time_doc_types()


# 예전 이름을 그대로 쓰던 자리를 위해 남긴다. 견줄 때는 is_time_doc() 을 쓴다.
TIME_DOC_TYPES = {"과정평가형자격", "NCS기반_훈련이수증", "교육과정_편성표"}

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

    @property
    def broke(self) -> bool:
        """끝나긴 했는데 쓸 수 없는 상태.

        `manual_review` 는 검증을 통과하지 못해 사람이 봐야 하는 것이고,
        `failed` 는 도중에 죽은 것이다. 둘 다 done 도 running 도 아니라
        화면에서 통째로 보이지 않았다 — 「시작」 버튼만 다시 떴다.
        """
        return self.status in ("manual_review", "failed")

    @property
    def steps(self) -> tuple[int, int, str, list[str]]:
        """(끝난 청크, 전체 청크, 지금 하는 일, 남은 능력단위 이름).

        진행률은 판정이 한글 열쇠(전체·완료·단계·남은)로 적는다. 화면이
        영어 열쇠(total·done·phase)로 읽고 있었다 — 능력단위 7개를 도는
        내내 「0/1 능력단위」라고 말했다. 읽는 자리를 여기 하나로 둔다.
        """
        p = self.progress or {}
        done = int(p.get("완료") or 0)
        total = int(p.get("전체") or 0)
        phase = str(p.get("단계") or "분석 중")
        left = [str(x) for x in (p.get("남은") or [])]
        return done, total, phase, left

    @property
    def trouble(self) -> str:
        """무엇이 잘못됐는지 한 줄로."""
        v = (self.note.get("validation") or {}) if isinstance(self.note, dict) else {}
        by = v.get("by_code") or {}
        if self.status == "manual_review":
            got, want = v.get("n_elements"), v.get("n_expected")
            head = (f"요소 {want}개 가운데 {got}개만 판단됐습니다"
                    if got is not None and want else "기계 검증을 통과하지 못했습니다")
            top = " · ".join(f"{k} {n}건" for k, n in list(by.items())[:3])
            return head + (f" ({top})" if top else "")
        return "분석이 도중에 멈췄습니다"


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
    queued_at: datetime | None              # 큐에 든 근거 분석 작업 (아직 안 잡힘)
    worker_ok: bool                         # 워커가 최근에 작업을 집었나
    time: Run | None                        # ① 기록 확인
    evidence: Run | None                    # ② 근거 분석 — **가장 최근** 실행
    # 이미 끝난 근거 분석. 새 실행이 도는 중이라도 지난 보고서는 계속 열려야 한다.
    # 이것을 나누지 않았을 때, 재실행 한 번에 완성된 보고서가 화면에서 사라졌다.
    evidence_done: Run | None
    evidence_ack: bool                      # ② 를 사람이 읽고 넘어갔나
    n_reviewed: int                         # ③ 전문가 검토 — 판단이 기록된 요소 수
    n_judge: int                            # 사람이 따져야 하는 요소 수
    next_stage: int                         # 다음에 손댈 검토 단계 (1~5)
    stage_line: str                         # 다섯 단계 진척을 한 줄로
    # 다섯 단계 각각 — {n, title, total, done, skipped, complete}.
    # 개요에서 면접 질문지·실기 과제 목록으로 바로 들어갈 수 있어야 한다.
    stages: list[dict]
    n_settled: int                          # 기록으로 확정돼 확인만 하면 되는 수
    judged: int                             # 그중 판단이 기록된 수
    decision: dict | None                   # ④ 최종 판정
    # 이 접수 건에 든 근거 분석 비용·호출을 모두 합친 것. 마지막 판정의 것만
    # 보이면 재판정한 건은 실제보다 싸 보인다 (실측 R2026-9010: $0.60 로
    # 보였지만 처음 판정까지 합치면 $3.25 다).
    runs_cost: float = 0.0
    runs_attempts: int = 0
    n_runs: int = 0
    # 검토가 시작된 뒤의 시간 배분. 검토 전에는 None 이고, 그때는 기록 확인
    # 결과(credited_hours/open_hours)만으로 말한다.
    split: Any = None                       # services.review.HourSplit | None

    # ── ① 기록 확인에서 나온 숫자 ──
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

    # ── 검토까지 반영한 시간 ──
    # 개요의 막대는 이쪽을 쓴다. 기록 확인만 읽었더니, 전문가가 100시간을 더
    # 인정한 뒤에도 「아직 확인되지 않은 시간」이 그대로였다.
    @property
    def expert_hours(self) -> int:
        """사람이 판단해 기록 위에 더 인정한 시간."""
        return self.split.expert if self.split else 0

    @property
    def recognized_hours(self) -> int:
        """지금까지 인정된 시간 — 기록 + 전문가 판단."""
        return self.split.credited if self.split else self.credited_hours

    @property
    def pending_hours(self) -> int:
        """면접·실기·추가서류 결과를 기다리는 시간."""
        return self.split.pending if self.split else 0

    @property
    def training_hours(self) -> int:
        """확인으로는 풀리지 않아 훈련으로 채워야 하는 시간."""
        return self.split.training if self.split else 0

    @property
    def unresolved_hours(self) -> int:
        """아직 인정되지 않은 시간. 검토 전에는 기록 확인이 남긴 것과 같다."""
        return self.split.open if self.split else self.open_hours

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
        """도는 중이거나 큐에서 기다리는 중.

        큐를 보지 않았더니 「근거 분석 시작」을 눌러도 버튼이 그대로 있었다 —
        워커가 집기 전에는 assessment 행이 없기 때문이다. 사용자는 아무 반응이
        없다고 여기고 다시 눌렀고, 같은 작업이 두 건 쌓였다.
        """
        return bool(self.queued_at) or bool(self.evidence and self.evidence.running)

    @property
    def waiting_in_queue(self) -> bool:
        """큐에 있는데 아직 아무도 집지 않았다."""
        return bool(self.queued_at) and not (self.evidence and self.evidence.running)

    # 갓 넣은 작업이 집히기까지 걸리는 시간. 워커는 이 간격으로 큐를 본다.
    # 그 안에는 「아무도 집어 가지 않습니다」라고 말하지 않는다 — 정상이다.
    GRACE_SEC = 30

    @property
    def stalled(self) -> bool:
        """기다리는데 워커가 없다. 이대로 두면 영영 안 된다.

        `worker_alive` 는 「최근에 작업을 집었나」를 본다. 놀던 워커는 살아
        있어도 그 흔적이 없으므로, 넣자마자 물으면 죽은 것으로 보인다.
        그래서 **기다린 시간**을 함께 본다.
        """
        if not (self.waiting_in_queue and not self.worker_ok):
            return False
        if self.queued_at is None:
            return False
        from datetime import datetime, timezone
        now = datetime.now(self.queued_at.tzinfo or timezone.utc)
        return (now - self.queued_at).total_seconds() > self.GRACE_SEC

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
            if self.stalled:
                return ("워커를 띄워야 합니다", f"/submissions/{self.submission_id}")
            return None                                  # 진행 중 — 기다린다
        # 끝났는데 쓸 수 없는 것 — 목록에서도 「시작」이 아니라 그렇다고 말한다
        if (self.evidence and self.evidence.broke
                and not self.evidence_done):
            word = "확인 필요" if self.evidence.status == "manual_review" else "분석 실패"
            return (f"{word} — 열어 보기", f"/submissions/{self.submission_id}")
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


def _confirmed(s: Session, submission_id: int) -> bool:
    """② 를 사람이 읽고 넘어갔나.

    「어느 실행을 보나」는 보고서·개요와 **같은 함수**로 판단한다. 각자 고르면
    갈라진다 — 확인은 요소가 있는 실행에 붙는데 개요는 최신 실행을 보던 탓에,
    확인을 눌러도 화면이 그대로인 적이 있었다.
    """
    from services.review.unit_hours import evidence_aid
    aid = evidence_aid(s, submission_id)
    if aid is None:
        return False
    return bool(s.execute(text("""SELECT 1 FROM audit_log
        WHERE entity='assessment' AND action='evidence_confirmed'
          AND entity_id=:i LIMIT 1"""), {"i": str(aid)}).first())


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
    next_stage, stage_line, split = 1, "", None
    stages: list[dict] = []
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
                split = rc.hour_split()
                next_stage = rc.next_stage
                stages = [{"n": x.n, "title": x.title, "total": x.total,
                           "done": x.done, "skipped": x.skipped,
                           "moot": x.moot, "complete": x.complete}
                          for x in rc.states]
                stage_line = " · ".join(
                    f"{x.n}{x.title} " + ("건너뜀" if x.skipped else
                                          "완료" if x.complete else f"{x.done}/{x.total}")
                    for x in rc.states if x.n < 5)
        except Exception:                                     # noqa: BLE001
            log.warning("검토 단계 계산 실패 assessment=%s", ev_done.id, exc_info=True)

    # 큐에 든 작업. assessment 행은 워커가 집어야 생기므로, 그 전까지는
    # 여기를 보지 않으면 「시작을 눌렀다」는 사실 자체가 화면에서 사라진다.
    queued_at = s.execute(text("""
        SELECT min(created_at) FROM job
        WHERE kind='track_b' AND status='queued'
          AND (payload->>'submission_id')::int = :i"""), {"i": submission_id}).scalar()

    tot = s.execute(text("""
        SELECT coalesce(sum(cost_usd),0), coalesce(sum(attempts),0), count(*)
        FROM assessment WHERE submission_id=:i AND kind='evidence'"""),
        {"i": submission_id}).one()

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
        extra_docs=[d for d in docs if not is_time_doc(d["doc_type"])],
        queued_at=queued_at, worker_ok=worker_alive(s),
        time=done_runs.get("time") or runs.get("time"),
        evidence=ev, evidence_done=ev_done,
        evidence_ack=_confirmed(s, submission_id), n_reviewed=n_reviewed,
        n_judge=n_judge, n_settled=n_settled, judged=judged,
        next_stage=next_stage, stage_line=stage_line, stages=stages, split=split,
        decision=dict(dec) if dec else None,
        runs_cost=float(tot[0] or 0), runs_attempts=int(tot[1] or 0),
        n_runs=int(tot[2] or 0),
    )


def case_states(s: Session, ids: list[int]) -> dict[int, CaseState]:
    """목록 화면용. N+1 을 피할 만큼 크지 않으므로 그대로 돈다."""
    return {i: st for i in ids if (st := case_state(s, i)) is not None}
