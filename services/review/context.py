"""검토 한 건에 필요한 것을 한 번에 모은다.

다섯 단계 화면이 저마다 같은 조회를 되풀이하면 반드시 어긋난다 —
어떤 화면은 이름을 카탈로그에서, 어떤 화면은 AI 출력에서 읽는 식이 된다.
그 일이 실제로 있었다. 그래서 읽는 자리를 여기 하나로 둔다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.catalog import labels
from services.review.stages import (
    Item, Outcome, apply_results, collect_items, load_results, next_open_stage,
    outcomes, stage_states, StageState,
)
from services.review.triage import needs_judgment, split


@dataclass
class ReviewContext:
    assessment_id: int
    submission_id: int
    case_number: str
    program_id: str
    program_name: str
    total_hours: int
    rubric_version: str
    stage: int                                   # 저장된 현재 단계
    elements: list[dict] = field(default_factory=list)
    names: dict[str, tuple[str, str]] = field(default_factory=dict)
    ksa: dict[tuple[str, str], str] = field(default_factory=dict)
    hours: dict[str, int] = field(default_factory=dict)
    frags: dict[str, str] = field(default_factory=dict)
    dtypes: dict[str, str] = field(default_factory=dict)
    reviews: dict[str, dict] = field(default_factory=dict)
    items: dict[str, list[Item]] = field(default_factory=dict)
    decision: dict | None = None

    # ── 파생 ──
    @property
    def n_elements(self) -> int:
        return len(self.elements)

    @property
    def judge_pool(self) -> list[dict]:
        """1단계에서 사람이 판단할 요소. 기록으로 확정된 것은 뺀다."""
        return [x for x in self.elements if needs_judgment(x["payload"] or {})]

    @property
    def buckets(self) -> dict[str, list[dict]]:
        return split(self.elements)

    @property
    def n_judged(self) -> int:
        return sum(1 for x in self.judge_pool if x["element_id"] in self.reviews)

    @property
    def outcomes(self) -> list[Outcome]:
        return outcomes(self.elements, self.reviews, self.items, self.names)

    @property
    def outcome_of(self) -> dict[str, str]:
        return {o.element_id: o.decision for o in self.outcomes}

    @property
    def states(self) -> list[StageState]:
        return stage_states(len(self.judge_pool), self.n_judged, self.items)

    @property
    def next_stage(self) -> int:
        return next_open_stage(self.states)

    @property
    def rec_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for x in self.elements:
            out[x["recommendation"]] = out.get(x["recommendation"], 0) + 1
        return out

    # ── 히트맵 재료 ──
    def grid(self) -> tuple[list[dict], dict[tuple[str, int], dict], int]:
        """(능력단위 목록, 칸, 최대 요소 번호). 능력단위는 요구시간 내림차순."""
        units: dict[str, dict] = {}
        cells: dict[tuple[str, int], dict] = {}
        max_no = 1
        for x in self.elements:
            code = x["element_id"].split("_")[0]
            no = _element_no(x["element_id"])
            u = units.setdefault(code, {
                "code": code, "name": x["_un"], "hours": self.hours.get(code, 0),
                "els": []})
            u["els"].append(x)
            cells[(code, no)] = x
            max_no = max(max_no, no)
        ordered = sorted(units.values(), key=lambda u: (-u["hours"], u["code"]))
        return ordered, cells, max_no

    def recognized_hours(self) -> tuple[int, int]:
        """(인정 시간, 총 필수 시간).

        능력단위 시간은 그 단위의 요소가 **전부** 인정돼야 붙는다 —
        기준의 `unit_credit_rule: all_elements` 를 따른다(쟁점 D-7, 미확정).
        """
        got = self.outcome_of
        by_unit: dict[str, list[str]] = {}
        for x in self.elements:
            by_unit.setdefault(x["element_id"].split("_")[0], []).append(x["element_id"])
        hours = 0
        for code, eids in by_unit.items():
            if all(got.get(i) == "인정" for i in eids):
                hours += self.hours.get(code, 0)
        return hours, self.total_hours


def _element_no(element_id: str) -> int:
    tail = (element_id or "").rsplit(".", 1)
    return int(tail[-1]) if len(tail) == 2 and tail[-1].isdigit() else 1


def load(s: Session, assessment_id: int) -> ReviewContext | None:
    a = s.execute(text("""
        SELECT a.id, a.submission_id, a.rubric_version, a.review_stage,
               s.case_number, s.target_program_id, p.official_name, p.total_hours
        FROM assessment a JOIN submission s ON s.id=a.submission_id
        LEFT JOIN catalog_wsd_program p ON p.program_id=s.target_program_id
        WHERE a.id=:i AND a.kind='evidence'"""), {"i": assessment_id}).mappings().first()
    if a is None:
        return None

    els = [dict(r) for r in s.execute(text("""
        SELECT element_id, recommendation, evidence_level, verification_method,
               confidence, payload FROM assessment_element
        WHERE assessment_id=:i ORDER BY element_id"""),
        {"i": assessment_id}).mappings()]

    # 이름은 **기준에 있는 값**이다. AI 가 받아 적어 준 것에 기대면 코드만 뜬다.
    names = {r[0]: (r[1], r[2]) for r in s.execute(text("""
        SELECT element_id, unit_name, element_name FROM catalog_ncs_element
        WHERE element_id = ANY(:i)"""), {"i": [x["element_id"] for x in els]})}
    for x in els:
        un, en = names.get(x["element_id"], (None, None))
        p = x["payload"] or {}
        x["_un"] = un or p.get("unit_name") or x["element_id"].split("_")[0]
        x["_en"] = en or p.get("element_name") or x["element_id"]

    ctx = ReviewContext(
        assessment_id=a["id"], submission_id=a["submission_id"],
        case_number=a["case_number"], program_id=a["target_program_id"],
        program_name=a["official_name"] or a["target_program_id"],
        total_hours=a["total_hours"] or 0, rubric_version=a["rubric_version"],
        stage=a["review_stage"] or 1, elements=els, names=names)

    ctx.ksa = labels(s, [x["element_id"] for x in els])
    ctx.hours = {r[0]: r[1] for r in s.execute(text("""
        SELECT unit_code, required_hours FROM catalog_wsd_required
        WHERE program_id=:p"""), {"p": ctx.program_id})}
    for fid, txt, dt in s.execute(text("""
            SELECT fid, text, doc_type FROM fragment WHERE submission_id=:i"""),
            {"i": ctx.submission_id}):
        ctx.frags[fid], ctx.dtypes[fid] = txt, dt
    ctx.reviews = {r["element_id"]: dict(r) for r in s.execute(text("""
        SELECT element_id, decision, note, reviewer FROM element_review
        WHERE assessment_id=:i"""), {"i": assessment_id}).mappings()}
    ctx.decision = _one(s.execute(text("""
        SELECT decision, reason, decided_by, recognized_hours, total_hours, decided_at
        FROM final_decision WHERE submission_id=:i ORDER BY id DESC LIMIT 1"""),
        {"i": ctx.submission_id}).mappings().first())

    ctx.items = collect_items(els, names)
    apply_results(ctx.items, load_results(s, assessment_id))
    return ctx


def set_stage(s: Session, assessment_id: int, stage: int) -> None:
    s.execute(text("UPDATE assessment SET review_stage=:n WHERE id=:i"),
              {"n": max(1, min(5, int(stage))), "i": assessment_id})


def _one(row: Any) -> dict | None:
    return dict(row) if row else None
