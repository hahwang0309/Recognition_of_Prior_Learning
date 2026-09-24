"""기이수 인정(R0)을 코드로 확정한다. AI에게 묻지 않는다.

## 왜 코드로 하는가

R0 성립 조건은 「훈련이수증에 능력단위코드·이수시간·내부평가 합격이 적혀 있는가」이고,
그 셋은 이미 `extract_prior_learning()` 이 결정론적으로 뽑아 둔다. 판단할 것이 없다.

AI 에게 맡겨 보니 실행마다 달라졌다. 같은 지원자를 세 번 돌린 결과가
R0 15 · 15 · 12 로 갈렸다. 심사에서 「같은 서류인데 결과가 다르다」는 받아들여지지 않는다.

## 부정 진술은 예외다

「그 자세 용접은 담당한 바 없습니다」 같은 진술이 어느 요소를 가리키는지는
읽어 봐야 안다. 그 판단만 AI 에게 남기고, 나머지는 여기서 확정한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PriorCredit:
    """기이수로 갈음할 수 있는 능력단위 하나."""
    unit_code: str
    unit_name: str
    required_hours: int
    completed_hours: int
    ratio: float
    evaluation: str
    fid: str
    doc_key: str
    doc_type: str
    grade: str
    source_text: str

    @property
    def hours_note(self) -> str:
        return (f"요구 {self.required_hours}시간 대비 {self.completed_hours}시간 이수"
                f" ({self.ratio:.0%})")


def eligible_units(package: dict, rubric) -> dict[str, PriorCredit]:
    """R0 요건을 충족하는 능력단위. 요건은 rubric 이 정한다.

    ① 훈련이수증에 그 능력단위가 있고
    ② 내부평가 합격이 확인되며
    ③ 이수시간이 요구시간의 하한(기본 50%) 이상
    """
    spec = rubric.recommendations["R0"]
    need_eval = spec["requires"].get("evaluation_passed", True)
    floor = spec["downgrade_if"]["completed_hours_ratio_below"]

    hours = {u["unit_code"]: u for u in package["ncs"]["units"]}
    out: dict[str, PriorCredit] = {}
    for pl in package.get("prior_learning") or []:
        u = hours.get(pl["unit_code"])
        if u is None:
            continue                                   # 목표 종목이 요구하지 않는 단위
        if need_eval and not pl.get("evaluated"):
            continue                                   # 편성표만 낸 경우가 여기서 걸린다
        req = u["required_hours"] or 0
        done = pl.get("completed_hours") or 0
        ratio = done / req if req else 0.0
        if req and ratio < floor:
            continue
        out[pl["unit_code"]] = PriorCredit(
            unit_code=pl["unit_code"], unit_name=u["unit_name"], required_hours=req,
            completed_hours=done, ratio=ratio, evaluation=pl.get("evaluation") or "",
            fid=pl["fid"], doc_key=pl.get("doc_id") or "", doc_type=pl.get("doc_type") or "",
            grade=pl.get("grade") or "B", source_text=pl.get("source_text") or "")
    return out


def held_units_for_time_check(package: dict, rubric) -> dict[str, PriorCredit]:
    """기록 확인(Track A)에 넣을 이수 단위 — 시간 하한을 **걸지 않는다**.

    하한(50%) 미만인 단위를 여기서 걸러 버리면 판정기가 그 단위를 「미이수」로 본다.
    2차 TF 는 30~50% 를 「보류」로 두고 부족 이유와 추가 증빙을 안내하기로 했으므로,
    하한 판정은 rubric.track_a.verdicts 가 하도록 전부 넘긴다.
    R0(기이수 인정) 확정에는 여전히 eligible_units() 를 쓴다.
    """
    spec = rubric.recommendations["R0"]
    need_eval = spec["requires"].get("evaluation_passed", True)
    hours = {u["unit_code"]: u for u in package["ncs"]["units"]}
    out: dict[str, PriorCredit] = {}
    for pl in package.get("prior_learning") or []:
        u = hours.get(pl["unit_code"])
        if u is None or (need_eval and not pl.get("evaluated")):
            continue
        req = u["required_hours"] or 0
        done = pl.get("completed_hours") or 0
        if not done:
            continue
        out[pl["unit_code"]] = PriorCredit(
            unit_code=pl["unit_code"], unit_name=u["unit_name"], required_hours=req,
            completed_hours=done, ratio=(done / req if req else 0.0),
            evaluation=pl.get("evaluation") or "",
            fid=pl["fid"], doc_key=pl.get("doc_id") or "", doc_type=pl.get("doc_type") or "",
            grade=pl.get("grade") or "B", source_text=pl.get("source_text") or "")
    return out


@dataclass(frozen=True)
class RejectedCredit:
    """이수 기록으로 잡히긴 했으나 시간 갈음에 쓸 수 없는 능력단위."""
    unit_code: str
    unit_name: str
    required_hours: int
    completed_hours: int | None
    reason: str
    doc_type: str


def rejected_units(package: dict, rubric) -> list[RejectedCredit]:
    """왜 갈음되지 않았는지를 남긴다.

    보고서가 「0시간」만 보여 주면 심사위원은 서류를 안 낸 것인지, 냈는데
    안 쳐 준 것인지 구분할 수 없다. 실제로 이 둘은 처리가 다르다 —
    편성표만 낸 사람에게는 이수증을 받으면 되고, 아예 없는 사람은 근거 분석으로 간다.
    """
    spec = rubric.recommendations["R0"]
    need_eval = spec["requires"].get("evaluation_passed", True)

    hours = {u["unit_code"]: u for u in package["ncs"]["units"]}
    out: list[RejectedCredit] = []
    for pl in package.get("prior_learning") or []:
        u = hours.get(pl["unit_code"])
        if u is None:
            continue                       # 목표 종목과 무관 — 굳이 보고할 것이 없다
        done = pl.get("completed_hours")
        req = u["required_hours"] or 0
        if need_eval and not pl.get("evaluated"):
            reason = ("이수시간과 평가결과가 적혀 있지 않습니다"
                      if done is None else "내부평가 합격이 확인되지 않습니다")
        else:
            # 시간 하한(50%) 미달은 더 이상 여기서 걸러내지 않는다 — 판정기가
            # 「보류」(30~50%) 또는 「시간부족」(30% 미만)으로 표시한다 (2차 TF).
            continue
        out.append(RejectedCredit(
            unit_code=pl["unit_code"], unit_name=u["unit_name"], required_hours=req,
            completed_hours=done, reason=reason, doc_type=pl.get("doc_type") or ""))
    return out


def _fragment(package: dict, fid: str) -> dict | None:
    return next((f for f in package["fragments"] if f["fid"] == fid), None)


def _period_backing(package: dict, rubric) -> tuple[list[str], list[str], str]:
    """소속·기간을 뒷받침하는 조각을 고른다. 등급 높은 자료부터."""
    order = {g: i for i, g in enumerate(rubric.grade_order)}
    cands = sorted((f for f in package["fragments"]
                    if f["stype"] in ("기재사항", "기록")),
                   key=lambda f: order.get(f["grade"], 9))
    picked, grades = [], []
    for f in cands:
        if f["grade"] not in grades:
            picked.append(f["fid"])
            grades.append(f["grade"])
        if len(picked) >= 3:
            break
    note = ("훈련·재직 기간이 " + " · ".join(sorted(set(grades))) + "등급 자료로 확인된다"
            if picked else "기간을 뒷받침하는 자료가 없다")
    return picked, sorted(set(grades)), note


def make_element(package: dict, element: dict, credit: PriorCredit,
                 rubric, period: tuple[list[str], list[str], str]) -> dict:
    """R0 요소 하나를 만든다. 검증기를 그대로 통과해야 한다.

    문장은 틀로 찍는다 — 없는 판단을 지어내지 않기 위해서다.
    적히는 것은 이수증에 실제로 있는 값(코드·시간·평가결과)뿐이다.
    """
    frag = _fragment(package, credit.fid)
    quote = (frag["text"] if frag else credit.source_text)[:300]
    ev_grade = frag["grade"] if frag else credit.grade
    pb_fids, pb_grades, pb_note = period
    ref = (element["ksa"][0]["ref"] if element.get("ksa") else "기술1")

    proves = (rubric.document_types.get("NCS기반_훈련이수증") or {}).get("proves") or {}
    proven = [d for d, v in proves.items() if v == "full"]
    missing = [d for d in rubric.dimensions if d not in proven]

    return {
        "element_id": element["element_id"],
        "element_name": element.get("element_name"),
        "unit_name": credit.unit_name,
        "evidence": [{
            "ksa_ref": ref,
            "fids": [credit.fid],
            "grade": ev_grade,
            "fit": "직접",          # NCS 기반 훈련 이수증은 국가 기준 평가를 마친 자료 — 직접 근거 (2026-09-24)
            "quote": quote,
            "why": (f"{credit.unit_name} 능력단위를 {credit.hours_note}하고 "
                    f"내부평가 {credit.evaluation} 기록이 이수증에 있다."),
        }],
        "period_backing": {"fids": pb_fids, "grades": pb_grades, "note": pb_note},
        "prior_learning": {
            "applies": True, "unit_code": credit.unit_code,
            "completed_hours": credit.completed_hours,
            "required_hours": credit.required_hours,
            "evaluation": credit.evaluation, "fid": credit.fid,
            "reason": "이수증에 능력단위코드·이수시간·내부평가 결과가 모두 적혀 있다.",
        },
        "uncovered_ksa": [],
        "remediation": [],
        "negative_statements": [],
        "evidence_level": "충분",
        "proven_dimensions": proven,
        "missing_dimensions": missing,
        "source_grades": sorted({ev_grade} | set(pb_grades)),
        "negative_grades": [],
        "recommendation": "R0",
        "recommendation_reason": (
            f"{credit.unit_name}을 {credit.hours_note}하고 내부평가 {credit.evaluation} "
            f"기록이 확인되어, 국가 기준으로 이미 평가를 마친 항목으로 본다."),
        "verification_method": "불필요",
        "qualitative_note": (
            f"이 요소가 속한 {credit.unit_name}은 훈련기관에서 "
            f"{credit.completed_hours}시간(요구 {credit.required_hours}시간)을 이수하고 "
            f"내부평가 {credit.evaluation} 판정을 받은 항목이다. "
            f"기록이 그대로 남아 있어 다시 확인하지 않는다. "
            f"현장 배치 시 첫 작업에서 한 번 살펴보는 정도면 충분하다."),
        "conflicts": [],
        "confidence": "high",
        "decided_by": "rule",          # AI 가 아니라 코드가 정했다는 표시
    }


def build_r0_elements(package: dict, rubric, *,
                      exclude: set[str] | None = None) -> tuple[list[dict], dict[str, Any]]:
    """R0 로 확정할 요소들을 만든다.

    exclude 에 든 element_id 는 만들지 않는다 — 부정 진술이 걸린 요소로,
    AI 가 읽고 판단해야 한다.
    """
    exclude = exclude or set()
    credits = eligible_units(package, rubric)
    period = _period_backing(package, rubric)
    out, skipped = [], []
    for u in package["ncs"]["units"]:
        c = credits.get(u["unit_code"])
        if c is None:
            continue
        for e in u["elements"]:
            if e["element_id"] in exclude:
                skipped.append(e["element_id"])
                continue
            out.append(make_element(package, e, c, rubric, period))
    return out, {
        "요건충족_단위": [{"코드": c.unit_code, "이름": c.unit_name,
                     "이수": c.completed_hours, "요구": c.required_hours,
                     "비율": round(c.ratio, 3), "평가": c.evaluation}
                    for c in credits.values()],
        "확정_요소": len(out),
        "부정진술로_제외": skipped,
    }
