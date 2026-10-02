"""전문가 검토 — 요소별 의견을 받아 감면 시간으로 굴린다.

## 원칙

**AI 산출물을 덮어쓰지 않는다.** 전문가 의견은 `element_review` 에 따로 쌓인다.
나중에 「기계는 R3 라 했는데 사람은 인정했다」 같은 대조가 가능해야 하기 때문이다.

**감면 시간은 계산식을 함께 남긴다.** 몇 시간이 감면됐는지보다
왜 그 숫자가 나왔는지가 분쟁에서 중요하다.

## 시간을 굴리는 방식

Track B 는 **능력단위요소** 단위로 검토하지만 훈련시간은 **능력단위** 단위로 편성된다.
둘을 잇는 규칙이 `rubric.final_decision.unit_credit_rule` 이다.

  all_elements   요소가 전부 인정되어야 그 능력단위 시간을 감면한다 (보수적, 기본값)
  proportional   인정된 요소 비율만큼 감면한다

⚠ 이 규칙은 아직 확정되지 않았다(D-7). 그래서 **두 방식의 결과를 모두 계산해** 보여준다.
간담회에서 고르면 YAML 한 줄이 바뀐다.

조건부인정은 면접·실기를 통과해야 확정되므로 **확정분과 나누어** 센다.
"""
from __future__ import annotations

import json

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from krpl_core.audit import AuditStore
from krpl_core.config import get_rubric
from services.review.triage import needs_judgment


@dataclass
class UnitRoll:
    """능력단위 하나의 검토 현황."""
    unit_code: str
    unit_name: str
    required_hours: int
    n_elements: int
    n_인정: int = 0
    n_조건부인정: int = 0
    n_불인정: int = 0
    n_보류: int = 0
    n_미검토: int = 0

    @property
    def n_reviewed(self) -> int:
        return self.n_elements - self.n_미검토

    def hours(self, rule: str, conditional: bool) -> float:
        """감면 시간. conditional=True 면 조건부인정도 포함해 센다."""
        ok = self.n_인정 + (self.n_조건부인정 if conditional else 0)
        if rule == "proportional":
            return self.required_hours * ok / self.n_elements if self.n_elements else 0.0
        return float(self.required_hours) if ok == self.n_elements else 0.0


@dataclass
class ReviewSummary:
    assessment_id: int
    case_number: str
    program_id: str
    total_hours: int
    rule: str
    units: list[UnitRoll] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    n_elements: int = 0
    n_reviewed: int = 0
    n_expert_review: int = 0
    # 사람이 묻지 않아도 되는 것 — 이수 기록으로 확정된 요소.
    # n_reviewed 에 이미 포함돼 있고, 여기서는 「몇 개를 안 물었나」만 알려 준다.
    n_settled: int = 0

    @property
    def n_to_judge(self) -> int:
        """사람이 실제로 정해야 하는 요소 수."""
        return self.n_elements - self.n_settled

    @property
    def n_left(self) -> int:
        return max(0, self.n_elements - self.n_reviewed)

    @property
    def complete(self) -> bool:
        return self.n_left == 0 and self.n_elements > 0

    def hours(self, rule: str | None = None, conditional: bool = False) -> int:
        return round(sum(u.hours(rule or self.rule, conditional) for u in self.units))

    def rate(self, rule: str | None = None, conditional: bool = False) -> float:
        return self.hours(rule, conditional) / self.total_hours if self.total_hours else 0.0

    def suggest_decision(self) -> str:
        """권고안. 사람이 바꿀 수 있다 — 시스템이 확정하지 않는다."""
        th = get_rubric().final_decision["thresholds"]
        r = self.rate()
        if r >= th["전체인정"]:
            return "전체인정"
        return "불인정" if r <= th["불인정"] else "부분인정"

    def basis(self) -> dict[str, Any]:
        """계산식을 통째로 남긴다. 나중에 「왜 이 숫자냐」에 답하기 위한 것."""
        return {
            "rule": self.rule,
            "total_hours": self.total_hours,
            "확정": {"hours": self.hours(), "rate": round(self.rate(), 4)},
            "조건부포함": {"hours": self.hours(conditional=True),
                        "rate": round(self.rate(conditional=True), 4)},
            "다른_규칙_적용시": {
                r: {"확정": self.hours(r), "조건부포함": self.hours(r, True)}
                for r in ("all_elements", "proportional") if r != self.rule},
            "counts": self.counts,
            "units": [{"unit_code": u.unit_code, "unit_name": u.unit_name,
                       "required_hours": u.required_hours, "n_elements": u.n_elements,
                       "인정": u.n_인정, "조건부인정": u.n_조건부인정,
                       "불인정": u.n_불인정, "보류": u.n_보류, "미검토": u.n_미검토,
                       "감면": round(u.hours(self.rule, False), 1)} for u in self.units],
        }


def _unit_of(element_id: str) -> str:
    """1601050111_21v3.2 → 1601050111"""
    return element_id.split("_", 1)[0]


def review_summary(s: Session, assessment_id: int) -> ReviewSummary:
    rb = get_rubric()
    a = s.execute(text("""
        SELECT a.id, s.case_number, s.target_program_id, p.total_hours
        FROM assessment a JOIN submission s ON s.id = a.submission_id
        LEFT JOIN catalog_wsd_program p ON p.program_id = s.target_program_id
        WHERE a.id = :i"""), {"i": assessment_id}).mappings().one()

    hours = {r[0]: (r[1], r[2]) for r in s.execute(text("""
        SELECT r.unit_code, COALESCE(r.unit_name, r.unit_code), r.required_hours
        FROM catalog_wsd_required r WHERE r.program_id = :p"""),
        {"p": a["target_program_id"]})}

    rows = [dict(r) for r in s.execute(text("""
        SELECT e.element_id, e.recommendation, e.payload,
               COALESCE((e.payload->>'needs_expert_review')::bool, false) AS flag,
               v.decision
        FROM assessment_element e
        LEFT JOIN element_review v
               ON v.assessment_id = e.assessment_id AND v.element_id = e.element_id
        WHERE e.assessment_id = :i ORDER BY e.element_id"""),
        {"i": assessment_id}).mappings()]

    # 훈련이수증에 능력단위코드·시간·평가결과가 적혀 있어 규칙으로 확정된 요소는
    # **묻지 않는다.** 그런데 여기서는 「미검토」로 세고 있어 두 가지가 어긋났다.
    #   ① 「최종 판정 기록」 버튼이 영영 잠긴다 — 화면은 18개를 시켰는데
    #      버튼은 27개를 요구했다
    #   ② 감면 시간이 낮게 나온다 — 검토 화면 100h, 5단계 최종 250h 로 갈렸다
    # 확정분은 인정으로 센다. `outcomes()`(5단계)가 이미 그렇게 하고 있다.
    for r in rows:
        if r["decision"] is None and not needs_judgment(r["payload"] or {}):
            r["decision"] = "인정"
            r["settled"] = True

    rolls: dict[str, UnitRoll] = {}
    counts = {d: 0 for d in rb.final_decision["element_decisions"]}
    counts["미검토"] = 0
    for r in rows:
        uc = _unit_of(r["element_id"])
        name, req = hours.get(uc, (uc, 0))
        u = rolls.setdefault(uc, UnitRoll(uc, name, req or 0, 0))
        u.n_elements += 1
        d = r["decision"] or "미검토"
        counts[d] = counts.get(d, 0) + 1
        setattr(u, f"n_{d}", getattr(u, f"n_{d}") + 1)

    return ReviewSummary(
        assessment_id=assessment_id, case_number=a["case_number"],
        program_id=a["target_program_id"], total_hours=a["total_hours"] or 0,
        rule=rb.final_decision["unit_credit_rule"],
        units=sorted(rolls.values(), key=lambda u: (-u.required_hours, u.unit_code)),
        counts=counts, n_elements=len(rows),
        n_reviewed=sum(1 for r in rows if r["decision"]),
        n_settled=sum(1 for r in rows if r.get("settled")),
        n_expert_review=sum(1 for r in rows if r["flag"]),
    )


def save_element_review(s: Session, assessment_id: int, element_id: str,
                        decision: str, note: str | None = None,
                        reviewer: str | None = None,
                        excluded_evidence: list[str] | None = None) -> dict[str, Any]:
    rb = get_rubric()
    if decision not in rb.final_decision["element_decisions"]:
        raise ValueError(f"의견 값이 잘못됨: {decision} "
                         f"(가능: {rb.final_decision['element_decisions']})")
    rec = s.execute(text("""
        SELECT recommendation FROM assessment_element
        WHERE assessment_id=:a AND element_id=:e"""),
        {"a": assessment_id, "e": element_id}).scalar()
    if rec is None:
        raise LookupError(f"해당 요소가 없습니다: {element_id}")

    s.execute(text("""
        INSERT INTO element_review (assessment_id, element_id, decision,
                                    ai_recommendation, note, reviewer, excluded_evidence)
        VALUES (:a, :e, :d, :r, :n, :w, CAST(:x AS jsonb))
        ON CONFLICT (assessment_id, element_id) DO UPDATE
        SET decision=EXCLUDED.decision, note=EXCLUDED.note,
            reviewer=EXCLUDED.reviewer, reviewed_at=now(),
            excluded_evidence=COALESCE(EXCLUDED.excluded_evidence, element_review.excluded_evidence)"""),
        {"a": assessment_id, "e": element_id, "d": decision, "r": rec,
         "n": note, "w": reviewer,
         "x": json.dumps(excluded_evidence) if excluded_evidence is not None else None})
    s.execute(text("""INSERT INTO audit_log (entity, entity_id, action, actor, detail)
                      VALUES ('element_review', :i, 'saved', :w, CAST(:d AS jsonb))"""),
              {"i": f"{assessment_id}:{element_id}", "w": reviewer or "unknown",
               "d": f'{{"decision":"{decision}","ai":"{rec}"}}'})
    _snapshot_reviews(s, assessment_id)
    return {"element_id": element_id, "decision": decision, "ai_recommendation": rec,
            "agrees_with_ai": (decision == "인정") == (rec == "R0")}


def _snapshot_reviews(s: Session, assessment_id: int) -> None:
    """검토 현황을 파일로 갱신한다. 최종 판정 전에도 열어 볼 수 있어야 한다."""
    r = s.execute(text("""SELECT sub.id, sub.case_number FROM assessment a
                          JOIN submission sub ON sub.id=a.submission_id WHERE a.id=:i"""),
                  {"i": assessment_id}).mappings().one()
    rows = [dict(x) | {"reviewed_at": x["reviewed_at"].isoformat()} for x in s.execute(text("""
        SELECT element_id, decision, ai_recommendation, note, reviewer, reviewed_at
        FROM element_review WHERE assessment_id=:i ORDER BY element_id"""),
        {"i": assessment_id}).mappings()]
    diff = sum(1 for x in rows if (x["decision"] == "인정") != (x["ai_recommendation"] == "R0"))
    AuditStore(s, r["case_number"], r["id"], assessment_id).write(
        "review", "요소별검토", rows, seq=1,
        note=f"{len(rows)}개 기록 · AI 권고와 다른 판단 {diff}건")


def record_decision(s: Session, assessment_id: int, decision: str,
                    reason: str | None = None, decided_by: str | None = None,
                    recognized_hours: int | None = None,
                    conditional: bool = False, allow_incomplete: bool = False) -> dict[str, Any]:
    """최종 판정을 기록한다. 감면 시간은 검토 결과에서 계산하되 사람이 덮어쓸 수 있다."""
    rb = get_rubric()
    if decision not in rb.final_decision["decisions"]:
        raise ValueError(f"판정 값이 잘못됨: {decision} (가능: {rb.final_decision['decisions']})")

    # 이 앱은 심사위원 개인이 아니라 **합의된 결론**을 받아 적는다.
    # 판정자 칸을 없앴으므로 비어 오면 그렇게 적는다 — 감사 기록이 비면
    # 나중에 누가 정한 것인지 알 수 없다.
    decided_by = decided_by or "심사위원 합의"

    sm = review_summary(s, assessment_id)
    if not sm.complete and not allow_incomplete:
        raise ValueError(f"검토가 끝나지 않았습니다 ({sm.n_reviewed}/{sm.n_elements}). "
                         f"그래도 기록하려면 allow_incomplete=true")

    # 다섯 단계 검토가 낸 값이 기준이다. `review_summary` 는 1단계 판단만 세므로
    # 면접·실기 결과와 기록 갈음이 빠진다 — 실측 R2026-9010 에서 화면은
    # 370시간, 판정 기록은 「확정 150 · 조건부 350」이라 서로 다른 말을 했다.
    from services.review.context import load as _load
    ctx = _load(s, assessment_id)
    staged = None
    if ctx is not None:
        got, tot = ctx.recognized_hours()
        counts: dict[str, int] = {}
        for v in ctx.outcome_of.values():
            counts[v] = counts.get(v, 0) + 1
        staged = {
            "인정시간": got, "총시간": tot,
            "기록갈음": sum(ctx.credited_units.values()),
            "요소": counts,
            "단계": {x.title: ("건너뜀" if x.skipped else f"{x.done}/{x.total}")
                   for x in ctx.states},
            # 시간은 갈음됐는데 요소는 미인정인 단위 — 조용히 넘기지 않는다
            "갈음됐으나_요소미인정": ctx.credited_but_denied(),
        }

    if recognized_hours is not None:
        hours = recognized_hours
    elif conditional:
        # 「조건부인정까지 다 인정된다고 치면」 — 확인 결과를 기다리지 않고
        # 위쪽을 보고 싶을 때 쓰는 셈법이다. 다섯 단계 결과보다 앞선다.
        hours = sm.hours(conditional=True)
    elif staged is not None:
        hours = staged["인정시간"]
    else:
        hours = sm.hours()
    basis = sm.basis()
    basis["검토결과"] = staged
    basis["conditional_counted"] = conditional
    basis["hours_overridden"] = recognized_hours is not None
    # 실제로 적어 넣은 시간. 계산값만 남기면 이력에서 「그때 얼마로 정했나」를
    # 알 수 없다 — 사람이 덮어쓴 건이 바로 그렇다.
    basis["기록한_인정시간"] = hours
    basis["suggested_decision"] = sm.suggest_decision()
    basis["pending_rubric_decisions"] = [p.key for p in rb.pending_decisions]

    sid = s.execute(text("SELECT submission_id FROM assessment WHERE id=:i"),
                    {"i": assessment_id}).scalar_one()
    s.execute(text("""
        INSERT INTO final_decision (submission_id, assessment_id, decision, reason,
                                    decided_by, decided_on, recognized_hours,
                                    total_hours, credit_basis)
        VALUES (:s, :a, :d, :r, :w, :o, :h, :t, CAST(:b AS jsonb))
        ON CONFLICT (submission_id) DO UPDATE
        SET assessment_id=EXCLUDED.assessment_id, decision=EXCLUDED.decision,
            reason=EXCLUDED.reason, decided_by=EXCLUDED.decided_by,
            decided_on=EXCLUDED.decided_on, recognized_hours=EXCLUDED.recognized_hours,
            total_hours=EXCLUDED.total_hours, credit_basis=EXCLUDED.credit_basis,
            decided_at=now()"""),
        {"s": sid, "a": assessment_id, "d": decision, "r": reason, "w": decided_by,
         "o": date.today(), "h": hours, "t": sm.total_hours,
         "b": __import__("json").dumps(basis, ensure_ascii=False)})
    # ── 감사 기록 — 사람이 무엇을 보고 무엇을 정했는지 ──
    case = s.execute(text("SELECT case_number FROM submission WHERE id=:i"),
                     {"i": sid}).scalar_one()
    store = AuditStore(s, case, sid, assessment_id)
    _snapshot_reviews(s, assessment_id)
    # 판정마다 따로 남긴다. 같은 이름·번호로 쓰면 앞선 판정의 근거가 덮여
    # 사라진다 — 실측으로 두 번 판정했는데 산출물은 하나뿐이었다.
    #
    # 회차는 **판정 횟수**로 센다. 산출물 개수로 세면 예전에 덮어써서 빠진
    # 것 때문에 번호가 밀려 이력과 근거가 엉뚱하게 짝지어진다.
    n_before = s.execute(text("""
        SELECT count(*) FROM audit_log
        WHERE entity='final_decision' AND entity_id=:i"""), {"i": str(sid)}).scalar_one()
    store.write("decide", f"최종판정_{n_before + 1}회", {
        "판정": decision, "감면시간": hours, "총시간": sm.total_hours,
        "사유": reason, "판정자": decided_by, "판정일": str(date.today()),
        "산출근거": basis}, seq=n_before + 1,
        note=f"{decision} · {hours}/{sm.total_hours}시간"
             + (" · 시간 직접 지정" if basis["hours_overridden"] else " · 검토 결과에서 계산"))

    s.execute(text("UPDATE submission SET status='decided' WHERE id=:i"), {"i": sid})
    s.execute(text("""INSERT INTO audit_log (entity, entity_id, action, actor, detail)
                      VALUES ('final_decision', :i, :d, :w, CAST(:b AS jsonb))"""),
              {"i": str(sid), "d": decision, "w": decided_by or "unknown",
               "b": __import__("json").dumps(basis, ensure_ascii=False)})
    return {"submission_id": sid, "assessment_id": assessment_id, "decision": decision,
            "recognized_hours": hours, "total_hours": sm.total_hours,
            "credit_basis": basis, "reason": reason, "decided_by": decided_by}


def save_pc_score(s: Session, assessment_id: int, element_id: str, ref: str, score: int,
                  reviewer: str | None = None) -> dict[str, Any]:
    """위원이 수행준거 점수를 고친다 (신형, 2026-10-02). 돌려주는 것은 **저장 뒤 서버가 다시 센 단위 결과**다.

    화면이 자기 계산을 믿고 그리면 서버와 갈라진다(2026-09-28 사고). 그래서 응답에 단위 판정을
    담아 화면이 그 값으로 다시 그리게 한다. AI 값과 같은 점수를 고르면 위원 표시를 지운다.
    표시는 요소의 excluded_evidence 에 "pc:<ref>=<n>" 으로 쌓인다(수행준거 번호는 요소마다 다시 시작).
    """
    from services.catalog.ncs_struct import element_no, ksa_of, pcs_of, unit_of
    from services.review.coverage import PC, element_scores, unit_verdict_of
    rb = get_rubric()
    sc = (rb.track_b.get("pc_scoring") or {})
    if score not in (sc.get("values") or [0, 1, 2]):
        raise ValueError(f"점수 값이 잘못됨: {score} (가능: {sc.get('values') or [0, 1, 2]})")
    uc = unit_of(element_id)
    pcs = pcs_of(s, [uc]).get((uc, element_no(element_id) or 0), [])
    if ref not in {p["ref"] for p in pcs}:
        raise LookupError(f"해당 수행준거가 없습니다: {element_id} {ref}")
    row = s.execute(text("""SELECT payload FROM assessment_element
                            WHERE assessment_id=:a AND element_id=:e"""),
                    {"a": assessment_id, "e": element_id}).scalar()
    if row is None:
        raise LookupError(f"해당 요소가 없습니다: {element_id}")
    old = list(s.execute(text("""SELECT excluded_evidence FROM element_review
                                 WHERE assessment_id=:a AND element_id=:e"""),
                         {"a": assessment_id, "e": element_id}).scalar() or [])
    marks = [m for m in old if not (isinstance(m, str) and m.startswith(f"{PC}{ref}="))]
    ai = next((r for r in element_scores(row, pcs, (), rb) if r["ref"] == ref), None)
    ai_score = ai["score"] if ai else 0
    if score != ai_score:
        marks.append(f"{PC}{ref}={score}")
    # 단위 판정은 그 단위의 요소 전부로 다시 센다
    xs = [dict(r) for r in s.execute(text("""SELECT element_id, payload FROM assessment_element
        WHERE assessment_id=:a AND element_id LIKE :p"""), {"a": assessment_id, "p": uc + "\\_%"}).mappings()]
    marks_of = {r[0]: list(r[1] or []) for r in s.execute(text("""SELECT element_id, excluded_evidence
        FROM element_review WHERE assessment_id=:a"""), {"a": assessment_id})}
    marks_of[element_id] = marks
    ksa_all = {k: [r for r, _ in v] for k, v in ksa_of(s, [uc]).items()}
    unit = unit_verdict_of(xs, rb, marks_of, uc, ksa_all, pcs_of(s, [uc]), lambda e: element_no(e) or 0)
    save_element_review(s, assessment_id, element_id, unit["verdict"], None, reviewer, marks)
    unit.pop("scores", None)
    return {"element_id": element_id, "ref": ref, "score": score,
            "src": "reviewer" if score != ai_score else ("rule" if ai and ai["src"] == "rule" else "ai"),
            "ai_score": ai_score, "unit_code": uc, "unit": unit}
