"""근거 커버리지와 위원용 묶음 — 한 곳에서 계산한다.

전에는 `evidence_report.py`·`track_b_review.py` 가 각자 `len(evidence)/(len(evidence)+len(uncovered_ksa))`
를 세고 있었다. 위원이 근거를 「인정 불가」로 빼면 그 값이 바뀌어야 하므로 excluded 를 받는 함수 하나로 모은다.

용어(위원 화면): 요소 권고 R0·R1 → 인정 후보, R2·R3·R4 → 추가 확인, R5 → 미인정.
능력단위 판정은 rubric.final_decision.unit_credit_rule 을 따른다(all_elements: 요소 전부 인정 후보여야 인정).
"""
from __future__ import annotations

from typing import Any, Iterable


ADD = "add:"       # 위원이 근거 없는 항목을 직접 인정한 표시: "add:기술3"
Q = "q:"           # 위원의 질문 가/부 답: "q:1:가" — 기록만, 커버리지에 안 쓴다
S = "s:"           # 위원의 3점 척도: "s:match:상" — 기록만, 커버리지에 안 쓴다


def covered_refs(payload: dict[str, Any], excluded: Iterable[str] = (),
                 all_refs: Iterable[str] | None = None) -> set[str]:
    """인정된 항목 ref 집합 — element_coverage 와 같은 규칙. 계획 페이지가 「미확인 항목」을 고를 때 쓴다."""
    marks = set(excluded or ())
    ex = {m for m in marks if not m.startswith((ADD, Q, S))}
    added = {m[len(ADD):] for m in marks if m.startswith(ADD)}
    covered: set[str] = set()
    refs: set[str] = set(all_refs or ())
    for ev in payload.get("evidence") or []:
        ref = ev.get("ksa_ref")
        if not ref:
            continue
        refs.add(ref)
        if (ev.get("fit") or "직접") == "직접" and [f for f in (ev.get("fids") or []) if f not in ex]:
            covered.add(ref)
    for u in payload.get("uncovered_ksa") or []:
        ref = u.get("ref") if isinstance(u, dict) else u
        if ref:
            refs.add(ref)
    return covered | ((added & refs) if refs else added)


def element_coverage(payload: dict[str, Any], excluded: Iterable[str] = (),
                     all_refs: Iterable[str] | None = None) -> tuple[int, int, float]:
    """(인정된 항목 수, 항목 전체 수, 비율).

    excluded 에는 뺀 근거의 fid · 위원이 직접 인정한 항목 "add:<ref>" · 기록용 표시("q:", "s:")가 섞여 온다.
    항목 전체는 catalog(all_refs)가 있으면 그것, 없으면 근거+미확인 항목의 합집합.
    같은 항목에 근거가 둘이면 하나로 센다. 근거를 빼도 다른 근거가 남아 있으면 인정이다.
    근거의 `fit`(직접|간접|부정, 2026-09-24): **직접만 인정**으로 센다. fit 이 없는 옛 결과는 직접으로 본다.
    """
    marks = set(excluded or ())
    ex = {m for m in marks if not m.startswith((ADD, Q, S))}
    added = {m[len(ADD):] for m in marks if m.startswith(ADD)}
    covered: set[str] = set()
    refs: set[str] = set(all_refs or ())
    for ev in payload.get("evidence") or []:
        ref = ev.get("ksa_ref")
        if not ref:
            continue
        refs.add(ref)
        if (ev.get("fit") or "직접") == "직접" and [f for f in (ev.get("fids") or []) if f not in ex]:
            covered.add(ref)
    for u in payload.get("uncovered_ksa") or []:
        ref = u.get("ref") if isinstance(u, dict) else u
        if ref:
            refs.add(ref)
    covered |= (added & refs) if refs else added
    total = len(refs)
    return len(covered), total, (len(covered) / total if total else 0.0)


def element_bucket(payload: dict[str, Any], rubric, excluded: Iterable[str] = ()) -> str:
    """요소 하나의 위원용 묶음: 인정후보 | 추가확인 | 미인정.

    권고(R0~R5)를 rubric.track_b.display_buckets 로 접는다. 위원이 근거를 빼서 커버리지가
    서류 인정 하한 아래로 내려가면 인정 후보에서 추가 확인으로 내린다(규칙 재계산, LLM 재호출 없음).
    """
    tb = getattr(rubric, "track_b", None) or {}
    buckets: dict[str, list[str]] = (tb or {}).get("display_buckets") or {
        "인정후보": ["R0", "R1"], "추가확인": ["R2", "R3", "R4"], "미인정": ["R5"]}
    rec = payload.get("recommendation") or "R5"
    b = next((k for k, v in buckets.items() if rec in v), "미인정")
    if b == "인정후보" and rec != "R0":
        floor = (rubric.recommendations.get("R1", {}).get("requires") or {}).get("ksa_coverage_min")
        if floor is not None:
            _, _, ratio = element_coverage(payload, excluded)
            if ratio < floor:
                b = "추가확인"
    return b


def unit_verdict(buckets: list[str]) -> str:
    """요소 묶음들 → 능력단위 판정(인정|보류|불인정). all_elements 규칙."""
    if not buckets:
        return "불인정"
    if all(b == "인정후보" for b in buckets):
        return "인정"
    if any(b == "미인정" for b in buckets):
        return "불인정"
    return "보류"


GRADE_BAND = {"A": "상", "B": "상", "C": "중", "D": "하", "E": "하"}


def three_point(elements: list[dict[str, Any]], rubric, excluded: Iterable[str] = ()) -> dict[str, Any]:
    """능력단위 하나의 3점 정량표 행. elements 는 그 단위의 요소 payload 목록.

    내용 일치성: 요소 커버리지 평균 (≥adjustment_floor 상 · ≥hold_floor 중 · 그 밖 하). 부정 진술이 있으면 표시.
    검증가능성: 근거 중 최고 등급 (A·B 상 · C 중 · D·E·없음 하).
    시간·기간 축은 문서에서 읽어 따로 붙인다(time_axis).
    """
    th = rubric.training_hours
    hi, lo = th.get("adjustment_floor", 0.5), th.get("hold_floor", 0.3)
    covs = [element_coverage(p, excluded) for p in elements]
    ratio = sum(c[2] for c in covs) / len(covs) if covs else 0.0
    n_cov, n_tot = sum(c[0] for c in covs), sum(c[1] for c in covs)
    match = "상" if ratio >= hi else "중" if ratio >= lo else "하"
    negative = False    # 부정 진술 기준 삭제 (2026-09-23)
    order = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
    ex = set(excluded or ())
    grades = [ev.get("grade") for p in elements for ev in (p.get("evidence") or [])
              if ev.get("grade") and any(f not in ex for f in (ev.get("fids") or []))]
    best = min(grades, key=lambda g: order.get(g, 9)) if grades else None
    verify = GRADE_BAND.get(best, "하") if best else "하"
    bks = [element_bucket(p, rubric, excluded) for p in elements]
    return {"match": match, "coverage": ratio, "n_covered": n_cov, "n_total": n_tot,
            "negative": negative, "verify": verify, "best_grade": best,
            "buckets": bks, "verdict": unit_verdict(bks)}


def neg_key(element_id: str, fid: str) -> str:
    """부정 진술을 「적용 안 함」으로 푼 표시. excluded_evidence 목록에 근거 fid 와 함께 저장한다."""
    return f"neg:{element_id}:{fid}"


def element_ratio(element_id: str, payload: dict[str, Any], excluded: Iterable[str] = ()) -> tuple[float, bool]:
    """(커버리지, 부정 진술 적용 여부). 2026-09-23 결정: **한 것만 매칭한다** — 부정 진술은 판정에 쓰지 않는다.
    두 번째 값은 항상 False (호출부 호환용)."""
    return element_coverage(payload, set(excluded or ()))[2], False


def unit_by_coverage(elements: list[tuple[str, dict[str, Any]]], rubric, excluded: Iterable[str] = (),
                     refs_of: dict[str, Iterable[str]] | None = None) -> dict[str, Any]:
    """능력단위 판정을 **인정된 항목**으로 낸다 (2026-09-23, 위원 검토 방식).

    elements: [(element_id, payload)]. 항목 인정 = AI 가 근거를 붙였고 위원이 빼지 않은 것 + 위원이 직접 인정한 것.
    요소 커버리지 평균이 adjustment_floor(50%) 이상 → 인정, hold_floor(30%) 이상 → 보류, 그 밖 → 불인정.
    위원의 3점 척도·질문 답("s:", "q:")은 기록만 하고 판정에 쓰지 않는다(3차 TF: 방식은 4차에서 결정).
    AI 권고(R0~R5)는 쓰지 않는다.
    """
    th = rubric.training_hours
    hi, lo = th.get("adjustment_floor", 0.5), th.get("hold_floor", 0.3)
    # excluded 는 요소별 dict(eid → 표시 목록) 또는 모든 요소에 같이 적용할 목록.
    # 위원의 「직접 인정」(add:)은 요소마다 다르므로 dict 로 주는 것이 맞다 — 목록으로 주면 다른 요소로 새어 나간다.
    ex_of = excluded if isinstance(excluded, dict) else {eid: list(excluded or ()) for eid, _ in elements}
    rs = [element_coverage(p, ex_of.get(eid, ()), (refs_of or {}).get(eid)) for eid, p in elements]
    n_cov, n_tot = sum(r[0] for r in rs), sum(r[1] for r in rs)
    ratio = sum(r[2] for r in rs) / len(rs) if rs else 0.0
    verdict = "인정" if rs and ratio >= hi else "보류" if ratio >= lo else "불인정"
    return {"ratio": ratio, "verdict": verdict, "n_covered": n_cov, "n_total": n_tot}
