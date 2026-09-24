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
    Item, Outcome, apply_results, carry_over, collect_items, is_live,
    load_results, next_open_stage, outcomes, stage_states, StageState,
)
from services.review.triage import needs_judgment, split


@dataclass(frozen=True)
class HourSplit:
    """총 필수 시간을 네 칸으로 가른 것. 합은 total 이다."""
    total: int
    record: int                   # 이수 기록으로 확인
    expert: int                   # 전문가가 판단해 더 인정
    unjudged: int                 # 아직 1단계 판단이 안 된 시간
    pending: int                  # 면접·실기·추가서류 결과를 기다리는 시간
    training: int                 # 훈련으로 채워야 함
    methods: dict[str, int] = field(default_factory=dict)   # 남은 시간을 방법별로

    @property
    def credited(self) -> int:
        return self.record + self.expert

    @property
    def open(self) -> int:
        """아직 인정되지 않은 시간."""
        return self.unjudged + self.pending + self.training

    def pct(self, h: int) -> float:
        return h / self.total * 100 if self.total else 0.0


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
    # 기록 확인(Track A)이 시간을 갈음해 준 능력단위 → 그 요구시간.
    # 이것을 안 읽고 요소에서 다시 셌더니, 과정평가형 자격으로 320시간이
    # 확인된 건에서 막대는 「기록 100시간」, ① 칸은 「320시간」이라 했다.
    credited_units: dict[str, int] = field(default_factory=dict)
    # 기록 확인이 능력단위마다 남긴 것 — 판정·요구시간·이수시간·근거 출처.
    # 원장이 「무엇으로 갈음했는지」를 한 줄로 적을 때 쓴다.
    track_a_units: dict[str, dict] = field(default_factory=dict)
    # 능력단위 코드 → 그 단위를 판단한 AI 응답 원본(artifact.id).
    # 원장의 줄에서 「이 판단의 원본 보기」로 바로 가기 위한 것이다.
    unit_artifact: dict[str, int] = field(default_factory=dict)
    frags: dict[str, str] = field(default_factory=dict)
    dtypes: dict[str, str] = field(default_factory=dict)
    reviews: dict[str, dict] = field(default_factory=dict)
    items: dict[str, list[Item]] = field(default_factory=dict)
    decision: dict | None = None
    # 판정 이력 — 새것이 앞. [{판정, 시간, 판정자, 시각, artifact}]
    decision_log: list[dict] = field(default_factory=list)
    # 판정 뒤에 결과가 바뀌었으면 그 시각. 판정을 다시 해야 한다는 뜻이다.
    changed_after_decision: Any = None

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

    def split_items(self, method: str) -> tuple[list[Item], list[Item]]:
        """(아직 결과를 바꿀 수 있는 항목, 더는 바꾸지 못하는 항목).

        뒤엣것도 화면에서 감추지는 않는다 — 왜 안 세는지 보여야 한다.
        """
        got = self.outcome_of
        group = self.items.get(method) or []
        live = [i for i in group if i.done or is_live(i, got)]
        return live, [i for i in group if i not in live]

    @property
    def states(self) -> list[StageState]:
        return stage_states(len(self.judge_pool), self.n_judged, self.items,
                            self.outcome_of)

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

    def hour_split(self) -> "HourSplit":
        """시간이 지금 어디에 놓여 있나 — 네 칸으로 가른다.

        개요 화면의 막대가 여기서 나온다. 예전에는 기록 확인 결과만 읽어서,
        전문가가 100시간을 더 인정한 뒤에도 「아직 확인되지 않은 시간」이
        그대로였다 (실측: 450시간 중 기록 150 + 전문가 100 인데 300시간이라고
        적혀 있었다. 맞는 값은 200시간이다).

          기록      이수 기록만으로 단위 전체가 확정된 시간
          전문가    사람이 판단해 더 인정한 시간
          미판단    아직 1단계 판단이 안 된 시간 (여기서 갈린다)
          대기      면접·실기·추가서류 결과를 기다리는 시간
          훈련      확인으로는 풀리지 않아 훈련으로 채워야 하는 시간

        단위 시간은 그 단위의 요소가 **전부** 인정돼야 붙는다
        (`unit_credit_rule: all_elements`, 쟁점 D-7 미확정) — 그래서 요소
        하나가 대기면 단위 시간 전부가 대기다.
        """
        got = self.outcome_of
        rule_only = {x["element_id"] for x in self.elements
                     if not needs_judgment(x["payload"] or {})}
        by_unit = self.by_unit()

        # 어느 요소가 어느 방법의 결과를 기다리나
        pending_of: dict[str, set[str]] = {}
        for method, group in self.items.items():
            for it in group:
                if it.done:
                    continue
                for t in it.targets:
                    pending_of.setdefault(t["eid"], set()).add(method)

        # 1단계 판단이 아직 안 된 요소 — 여기가 정해져야 방법이 정해진다
        unjudged_el = {x["element_id"] for x in self.elements
                       if x["element_id"] not in rule_only
                       and x["element_id"] not in self.reviews}

        rec = exp = unj = wait = train = 0
        methods: dict[str, int] = {}
        for code, eids in by_unit.items():
            h = self.hours.get(code, 0)
            if code in self.credited_units:
                rec += h                      # 기록 확인이 이미 갈음한 단위
                continue
            ds = [got.get(i) for i in eids]
            if all(d == "인정" for d in ds):
                # 규칙만으로 확정된 것은 기록 쪽, 사람이 정한 것은 전문가 쪽
                if all(i in rule_only for i in eids):
                    rec += h
                else:
                    exp += h
            elif any(d == "미인정" for d in ds):
                train += h
            elif any(i in unjudged_el for i in eids):
                # 아직 아무도 보지 않은 것을 「면접으로 확인할 시간」이라 부르면
                # 안 된다. 1단계에서 무엇으로 갈지 정해진다.
                unj += h
                for m in {m for i in eids for m in pending_of.get(i, ())}:
                    methods[m] = methods.get(m, 0) + h
            else:
                wait += h
                # 한 단위에 면접·실기가 둘 다 걸릴 수 있다. 방법별 시간은
                # 겹쳐 세되(합계가 pending 을 넘을 수 있다), 화면에서 그렇게 적는다.
                for m in {m for i in eids for m in pending_of.get(i, ())}:
                    methods[m] = methods.get(m, 0) + h
        return HourSplit(total=self.total_hours, record=rec, expert=exp,
                         unjudged=unj, pending=wait, training=train,
                         methods=methods)

    def by_unit(self) -> dict[str, list[str]]:
        """능력단위 코드 → 그 단위의 요소 목록."""
        out: dict[str, list[str]] = {}
        for x in self.elements:
            out.setdefault(x["element_id"].split("_")[0], []).append(x["element_id"])
        return out

    def credited_but_denied(self) -> list[dict]:
        """기록으로 시간은 갈음됐는데 요소는 미인정인 능력단위.

        과정평가형 자격의 편성시간이 요구시간을 갈음하면 그 단위의 시간은
        붙는다. 그런데 같은 단위의 요소를 전문가가 「담당한 적 없다」는
        진술을 근거로 미인정으로 정할 수 있다. 실측 R2026-9010 에서
        흡·배기제어장치 30시간과 휠·얼라인먼트 40시간이 그랬다.

        어느 쪽을 따를지는 정책이고 아직 정해지지 않았다. 그러니 조용히
        한쪽으로 넘기지 않고, 심사위원이 보도록 내민다.
        """
        got = self.outcome_of
        out: list[dict] = []
        for code, eids in self.by_unit().items():
            if code not in self.credited_units:
                continue
            bad = [i for i in eids if got.get(i) == "미인정"]
            if not bad:
                continue
            name = next((x["_un"] for x in self.elements
                         if x["element_id"] == eids[0]), code)
            out.append({"unit_code": code, "unit": name,
                        "hours": self.credited_units[code],
                        "n_denied": len(bad), "n_elements": len(eids)})
        return sorted(out, key=lambda x: -x["hours"])

    def recognized_hours(self) -> tuple[int, int]:
        """(인정 시간, 총 필수 시간).

        ① 기록 확인이 갈음해 준 단위는 그대로 인정이다 — 규칙이 정한 것이고
           검토 화면에 그것을 뒤집는 자리가 없다. 여기서 다시 세면 개요의
           ① 칸과 다른 말을 하게 된다 (실측 R2026-9010: 320시간 대 100시간).
        ② 나머지 단위는 그 요소가 **전부** 인정돼야 시간이 붙는다 —
           `unit_credit_rule: all_elements` (쟁점 D-7, 미확정).
        """
        got = self.outcome_of
        hours = sum(self.credited_units.values())
        for code, eids in self.by_unit().items():
            if code in self.credited_units:
                continue
            if all(got.get(i) == "인정" for i in eids):
                hours += self.hours.get(code, 0)
        return hours, self.total_hours


def _element_no(element_id: str) -> int:
    tail = (element_id or "").rsplit(".", 1)
    return int(tail[-1]) if len(tail) == 2 and tail[-1].isdigit() else 1


# 기록 확인이 「시간이 확인됐다」고 보는 판정
CREDITED_LEVELS = ("완전충족", "조정범위내")


def _decision_log(s: Session, submission_id: int) -> list[dict]:
    """판정 이력. 판정할 때마다 audit_log 에 한 줄씩 남는다.

    `final_decision` 은 한 건만 두므로(덮어씀) 여기가 유일한 이력이다.
    감사 산출물은 `최종판정_N회` 로 따로 남아 근거까지 다시 볼 수 있다.
    """
    # 이름의 「N회」로 짝을 맞춘다. 순서로 맞추면 예전에 덮어써서 빠진 것이
    # 있을 때 엉뚱한 판정에 붙는다.
    arts: dict[int, int] = {}
    for name, aid_ in s.execute(text("""
            SELECT name, id FROM artifact WHERE submission_id=:i AND stage='decide'
              AND name LIKE '최종판정%' ORDER BY id"""), {"i": submission_id}):
        num = "".join(c for c in str(name) if c.isdigit())
        if num:
            arts[int(num)] = aid_
    out: list[dict] = []
    for n, (action, actor, detail, at) in enumerate(s.execute(text("""
            SELECT action, actor, detail, created_at FROM audit_log
            WHERE entity='final_decision' AND entity_id=:i ORDER BY id"""),
            {"i": str(submission_id)})):
        d = detail if isinstance(detail, dict) else {}
        staged = d.get("검토결과") or {}
        out.append({
            "n": n + 1, "decision": action, "by": actor, "at": at,
            "hours": d.get("기록한_인정시간"),
            "calc": staged.get("인정시간"),
            "overridden": bool(d.get("hours_overridden")),
            "artifact": arts.get(n + 1),
        })
    out.reverse()                                   # 새것이 앞
    return out


def _changed_after(s: Session, submission_id: int, assessment_id: int):
    """판정 뒤에 검토 결과가 바뀌었나. 바뀌었으면 그 시각.

    판정을 기록한 뒤 면접·실기 결과가 들어오면 인정 시간이 달라지는데,
    화면이 조용하면 낡은 판정이 그대로 남는다.
    """
    at = s.execute(text("""
        SELECT decided_at FROM final_decision WHERE submission_id=:i"""),
        {"i": submission_id}).scalar()
    if at is None:
        return None
    return s.execute(text("""
        SELECT max(t) FROM (
          SELECT max(decided_at) AS t FROM remediation_result WHERE assessment_id=:a
          UNION ALL
          SELECT max(reviewed_at) FROM element_review WHERE assessment_id=:a
        ) x WHERE t > :d"""), {"a": assessment_id, "d": at}).scalar()


def _unit_artifacts(s: Session, submission_id: int) -> dict[str, int]:
    """능력단위 코드 → 그 단위를 판단한 AI 응답 원본의 artifact.id.

    산출물 이름이 `01_1506030106_1차_AI응답` 꼴이라 코드가 그대로 들어 있다.
    같은 단위를 여러 번 돌렸으면(재요청·재판정) **가장 최근 것**을 가리킨다.
    """
    out: dict[str, int] = {}
    for aid, name in s.execute(text("""
            SELECT id, name FROM artifact
            WHERE submission_id=:i AND stage='llm' ORDER BY id"""),
            {"i": submission_id}):
        for part in str(name).split("_"):
            if part.isdigit() and len(part) >= 8:
                out[part] = aid        # 뒤에 온 것이 이긴다
    return out


def _track_a_units(s: Session, submission_id: int) -> dict[str, dict]:
    """기록 확인(Track A)이 능력단위마다 남긴 줄.

    Track A 는 능력단위 하나에 한 줄을 남기고 `evidence_level` 에 판정을 적는다
    (완전충족·조정범위내·시간부족·미이수). 앞의 둘이 「확인된 시간」이고,
    개요 ① 칸이 세는 것과 같다.
    """
    aid = s.execute(text("""
        SELECT id FROM assessment WHERE submission_id=:i AND kind='time'
          AND status='done' ORDER BY id DESC LIMIT 1"""),
        {"i": submission_id}).scalar()
    if aid is None:
        return {}
    out: dict[str, dict] = {}
    for code, lv, payload in s.execute(text("""
            SELECT element_id, evidence_level, payload FROM assessment_element
            WHERE assessment_id=:a"""), {"a": aid}):
        p = dict(payload or {})
        p["verdict"] = lv
        # 무엇으로 갈음했는지 — 「이수:D03」·「자격:D01」처럼 적혀 있다
        ev = (p.get("evidence") or [{}])[0]
        src = str(ev.get("source") or "")
        p["source"] = {"이수": "훈련 이수 기록", "자격": "보유 자격 편성시간"}.get(
            src.split(":")[0], src.split(":")[0] or "")
        out[code] = p
    return out


def _credited_units(units: dict[str, dict]) -> dict[str, int]:
    """그 가운데 시간이 갈음된 것 → 요구시간."""
    return {c: int(p.get("required_hours") or 0) for c, p in units.items()
            if p.get("verdict") in CREDITED_LEVELS}


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
    ctx.unit_artifact = _unit_artifacts(s, ctx.submission_id)
    ctx.track_a_units = _track_a_units(s, ctx.submission_id)
    ctx.credited_units = _credited_units(ctx.track_a_units)
    ctx.reviews = {r["element_id"]: dict(r) for r in s.execute(text("""
        SELECT element_id, decision, note, reviewer FROM element_review
        WHERE assessment_id=:i"""), {"i": assessment_id}).mappings()}
    ctx.decision_log = _decision_log(s, ctx.submission_id)
    ctx.changed_after_decision = _changed_after(s, ctx.submission_id, assessment_id)
    ctx.decision = _one(s.execute(text("""
        SELECT decision, reason, decided_by, recognized_hours, total_hours, decided_at
        FROM final_decision WHERE submission_id=:i ORDER BY id DESC LIMIT 1"""),
        {"i": ctx.submission_id}).mappings().first())

    ctx.items = collect_items(els, names)
    apply_results(ctx.items, load_results(s, assessment_id))
    # 받지 못한 서류가 맡던 것을 면접·실기로 넘긴다. 결과를 읽은 **뒤**라야
    # 무엇이 안 들어왔는지 알 수 있으므로 여기 순서가 중요하다.
    carry_over(ctx.items)
    return ctx


def set_stage(s: Session, assessment_id: int, stage: int) -> None:
    s.execute(text("UPDATE assessment SET review_stage=:n WHERE id=:i"),
              {"n": max(1, min(5, int(stage))), "i": assessment_id})


def _one(row: Any) -> dict | None:
    return dict(row) if row else None
