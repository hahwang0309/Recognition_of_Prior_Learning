"""근거 커버리지와 위원용 묶음 — 한 곳에서 계산한다.

전에는 `evidence_report.py`·`track_b_review.py` 가 각자 `len(evidence)/(len(evidence)+len(uncovered_ksa))`
를 세고 있었다. 위원이 근거를 「인정 불가」로 빼면 그 값이 바뀌어야 하므로 excluded 를 받는 함수 하나로 모은다.

용어(위원 화면): 요소 권고 R0·R1 → 인정 후보, R2·R3·R4 → 추가 확인, R5 → 미인정.
능력단위 판정은 rubric.final_decision.unit_credit_rule 을 따른다(all_elements: 요소 전부 인정 후보여야 인정).
"""
from __future__ import annotations

from typing import Any, Iterable


ADD = "add:"       # 위원이 근거 없는 항목을 직접 인정한 표시: "add:기술3" (구형·항목 단위)
Q = "q:"           # 위원의 질문 가/부 답: "q:1:가" — 기록만, 커버리지에 안 쓴다
S = "s:"           # 위원의 3점 척도: "s:match:상" — 기록만, 커버리지에 안 쓴다
PC = "pc:"         # 위원이 수행준거 점수를 고친 표시: "pc:준거3=1" (신형, 2026-10-02)
MARK_PREFIXES = (ADD, Q, S, PC)


# ───────────────────────── 수행준거 점수 (신형, 2026-10-02) ─────────────────────────
#
# 4차 TF: 판정 단위를 KSA 항목에서 수행준거로. 수행준거마다 0/1/2 점.
#   존재 기준 — 직접 근거 1건↑ → 2 · 직접 없고 간접만 → 1 · 없음 → 0 · 부정 진술 → 0.
#   위원이 "pc:<ref>=<n>" 표시로 덮어쓴다. 기이수(decided_by: rule) 요소는 전부 2.
# 능력단위 — 0 인 수행준거가 있으면 불인정 · 전부 ≥1 이고 평균 ≥ accept_mean(1.5) 인정 ·
#   ≥ hold_mean(1.0) 보류 · 미만 불인정. 값은 rubric.track_b.pc_scoring / unit_rule.
# 신형에서 fid 제외 표시(구형 「근거 부적합」)는 쓰지 않는다 — 점수를 고치면 된다.


def is_pc_format(payload: dict[str, Any]) -> bool:
    """신형(수행준거) 요소인가. `schema: "pc"` 표시가 기준이다 — 근거가 없는 R5 요소는
    evidence 로는 구분할 수 없으므로 반드시 이 표시를 찍어 둔다(_store·prior_credit)."""
    if (payload or {}).get("schema") == "pc":
        return True
    return any(isinstance(ev, dict) and ev.get("pc_ref") for ev in (payload or {}).get("evidence") or [])


def pc_overrides(marks: Iterable[str]) -> dict[str, int]:
    """{"준거3": 1} — "pc:준거3=1" 표시를 푼다. 잘못된 값은 무시한다."""
    out: dict[str, int] = {}
    for m in marks or ():
        if isinstance(m, str) and m.startswith(PC) and "=" in m:
            ref, _, v = m[len(PC):].partition("=")
            if v.strip() in ("0", "1", "2"):
                out[ref.strip()] = int(v)
    return out


def _pc_cfg(rubric) -> tuple[dict, dict]:
    tb = getattr(rubric, "track_b", None) or {}
    sc = dict(tb.get("pc_scoring") or {})
    ur = dict(tb.get("unit_rule") or {})
    sc.setdefault("direct", 2); sc.setdefault("indirect", 1); sc.setdefault("none", 0)
    sc.setdefault("negative_overrides", True)
    ur.setdefault("require_all_nonzero", True); ur.setdefault("accept_mean", 1.5); ur.setdefault("hold_mean", 1.0)
    return sc, ur


def pc_score(payload: dict[str, Any], ref: str, marks: Iterable[str] = (), rubric=None) -> tuple[int, str]:
    """수행준거 하나의 (점수, 출처). 출처: reviewer | rule | ai.

    알 수 없는 fit 값은 간접으로 본다(화면은 「알 수 없는 값」을 따로 표시한다).
    """
    from krpl_core.config import get_rubric
    sc, _ = _pc_cfg(rubric or get_rubric())
    ov = pc_overrides(marks)
    if ref in ov:
        return ov[ref], "reviewer"
    if (payload or {}).get("decided_by") == "rule":
        return sc["direct"], "rule"
    direct = indirect = negative = 0
    for ev in (payload or {}).get("evidence") or []:
        if not isinstance(ev, dict) or ev.get("pc_ref") != ref:
            continue
        fit = ev.get("fit") or "직접"
        if fit == "직접":
            direct += 1
        elif fit == "부정":
            negative += 1
        else:
            indirect += 1
    if negative and sc["negative_overrides"]:
        return sc["none"], "ai"
    if direct:
        return sc["direct"], "ai"
    if indirect:
        return sc["indirect"], "ai"
    return sc["none"], "ai"


def element_scores(payload: dict[str, Any], pcs: list[dict], marks: Iterable[str] = (),
                   rubric=None) -> list[dict[str, Any]]:
    """요소의 수행준거마다 [{ref, text, score, src, n_direct, n_indirect, n_negative}]."""
    from krpl_core.config import get_rubric
    rb = rubric or get_rubric()
    out = []
    for pc in pcs or []:
        ref = pc["ref"]
        cnt = {"직접": 0, "간접": 0, "부정": 0}
        for ev in (payload or {}).get("evidence") or []:
            if isinstance(ev, dict) and ev.get("pc_ref") == ref:
                fit = ev.get("fit") or "직접"
                cnt["직접" if fit == "직접" else "부정" if fit == "부정" else "간접"] += 1
        score, src = pc_score(payload, ref, marks, rb)
        out.append({"ref": ref, "text": pc.get("text", ""), "score": score, "src": src,
                    "n_direct": cnt["직접"], "n_indirect": cnt["간접"], "n_negative": cnt["부정"]})
    return out


def unit_by_scores(elements: list[tuple[str, dict[str, Any]]], rubric,
                   marks_of: dict[str, Iterable[str]] | None = None,
                   pcs_of: dict[str, list[dict]] | None = None) -> dict[str, Any]:
    """능력단위 판정 — 수행준거 점수 규칙 (2026-10-02).

    `marks_of` 는 반드시 요소별 dict 다 — 수행준거 번호가 요소마다 다시 시작하므로
    평탄한 목록을 받으면 한 요소의 "pc:준거1=0" 이 다른 요소로 샌다.
    돌려주는 키는 구형 `unit_by_coverage` 와 호환: ratio(=평균÷2) · n_covered(=점수≥1 수) · n_total(=수행준거 수).
    """
    if marks_of is not None and not isinstance(marks_of, dict):
        raise TypeError("marks_of 는 {element_id: marks} dict 여야 한다")
    _, ur = _pc_cfg(rubric)
    scores: list[dict] = []
    for eid, p in elements:
        for row in element_scores(p, (pcs_of or {}).get(eid, []), (marks_of or {}).get(eid, ()), rubric):
            scores.append({"eid": eid, **row})
    n = len(scores)
    vals = [r["score"] for r in scores]
    mean = sum(vals) / n if n else 0.0
    n_zero = sum(1 for v in vals if v == 0)
    n_full = sum(1 for v in vals if v == 2)
    if not n:
        verdict = "불인정"
    elif ur["require_all_nonzero"] and n_zero:
        verdict = "불인정"
    elif mean >= ur["accept_mean"]:
        verdict = "인정"
    elif mean >= ur["hold_mean"]:
        verdict = "보류"
    else:
        verdict = "불인정"
    mean_r = round(mean, 3)
    return {"verdict": verdict, "mean": mean_r, "n_pc": n, "n_zero": n_zero,
            "n_nonzero": n - n_zero, "n_full": n_full, "scores": scores,
            "ratio": mean_r / 2 if n else 0.0, "n_covered": n - n_zero, "n_total": n, "format": "pc"}



def covered_refs(payload: dict[str, Any], excluded: Iterable[str] = (),
                 all_refs: Iterable[str] | None = None) -> set[str]:
    """인정된 항목 ref 집합 — element_coverage 와 같은 규칙. 계획 페이지가 「미확인 항목」을 고를 때 쓴다."""
    if is_pc_format(payload):
        return _pc_covered_refs(payload, excluded, all_refs)
    marks = set(excluded or ())
    ex = {m for m in marks if not m.startswith(MARK_PREFIXES)}
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


def pc_refs_of(payload: dict[str, Any], all_refs: Iterable[str] | None = None) -> list[str]:
    """신형 요소의 수행준거 참조 전체 — 카탈로그(all_refs)가 있으면 그것, 없으면 근거+미확보의 합집합(번호순)."""
    refs: list[str] = list(all_refs or ())
    seen = set(refs)
    for ev in payload.get("evidence") or []:
        r = ev.get("pc_ref") if isinstance(ev, dict) else None
        if r and r not in seen:
            seen.add(r); refs.append(r)
    for u in payload.get("uncovered_pc") or []:
        r = u.get("ref") if isinstance(u, dict) else u
        if r and r not in seen:
            seen.add(r); refs.append(r)
    return refs


def _pc_covered_refs(payload, excluded=(), all_refs=None) -> set[str]:
    """신형: 점수 ≥1 인 수행준거. 구형 함수들이 신형 payload 를 받아도 뜻이 통하게 한다."""
    return {r for r in pc_refs_of(payload, all_refs) if pc_score(payload, r, excluded)[0] >= 1}


def element_coverage(payload: dict[str, Any], excluded: Iterable[str] = (),
                     all_refs: Iterable[str] | None = None) -> tuple[int, int, float]:
    """(인정된 항목 수, 항목 전체 수, 비율).

    excluded 에는 뺀 근거의 fid · 위원이 직접 인정한 항목 "add:<ref>" · 기록용 표시("q:", "s:")가 섞여 온다.
    항목 전체는 catalog(all_refs)가 있으면 그것, 없으면 근거+미확인 항목의 합집합.
    같은 항목에 근거가 둘이면 하나로 센다. 근거를 빼도 다른 근거가 남아 있으면 인정이다.
    근거의 `fit`(직접|간접|부정, 2026-09-24): **직접만 인정**으로 센다. fit 이 없는 옛 결과는 직접으로 본다.
    """
    if is_pc_format(payload):
        refs_pc = pc_refs_of(payload, all_refs)
        cov = _pc_covered_refs(payload, excluded, all_refs)
        return len(cov), len(refs_pc), (len(cov) / len(refs_pc) if refs_pc else 0.0)
    marks = set(excluded or ())
    ex = {m for m in marks if not m.startswith(MARK_PREFIXES)}
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


def element_verdict(payload: dict[str, Any], excluded: Iterable[str] = (),
                    all_refs: Iterable[str] | None = None,
                    rubric=None) -> tuple[bool, int, int, float]:
    """요소 판정 — (인정 여부, 인정 항목, 전체 항목, 비율). **이분법이다.**

    항목이 요소의 50% 이상 인정되면 그 요소 **전체**를 인정한다. 요소·항목에는
    시간이 없으므로(NCS 원자료 확인) 시간으로 환산할 길이 없고, 설계안도
    「시간 대신 능력단위요소 충족 여부」로 적고 있다.
    """
    from krpl_core.config import get_rubric
    rb = rubric or get_rubric()
    hi = rb.training_hours.get("adjustment_floor", 0.5)
    cov, tot, ratio = element_coverage(payload, excluded, all_refs)
    return (bool(tot) and ratio >= hi), cov, tot, ratio


def unit_by_coverage(elements: list[tuple[str, dict[str, Any]]], rubric, excluded: Iterable[str] = (),
                     refs_of: dict[str, Iterable[str]] | None = None) -> dict[str, Any]:
    """능력단위 판정 — **두 단계 게이트** (2026-09-24).

        ① 요소: 항목 인정 비율 ≥ 50%  →  그 요소 전체 인정
        ② 단위: 인정 요소 비율 ≥ 50%  →  인정 · ≥ 30% → 보류 · 미만 → 불인정

    항목 인정 = AI 가 **직접** 근거를 붙였고 위원이 빼지 않은 것 + 위원이 직접 인정한 것.
    위원의 3점 척도·질문 답("s:", "q:")은 기록만 하고 판정에 쓰지 않는다.

    예전에는 요소별 비율의 **평균**으로 단위를 판정했다. 항목이 3개인 요소와 20개인
    요소가 같은 무게를 가져 적은 쪽이 과대 반영됐다(4차 자료 표 9 #3).

    `n_covered`·`n_total` 은 이제 **요소 수**다 — 화면도 그렇게 읽어야 한다.
    """
    th = rubric.training_hours
    hi, lo = th.get("adjustment_floor", 0.5), th.get("hold_floor", 0.3)
    # excluded 는 요소별 dict(eid → 표시 목록) 또는 모든 요소에 같이 적용할 목록.
    # 위원의 「직접 인정」(add:)은 요소마다 다르므로 dict 로 주는 것이 맞다 — 목록으로 주면 다른 요소로 새어 나간다.
    ex_of = excluded if isinstance(excluded, dict) else {eid: list(excluded or ()) for eid, _ in elements}
    oks = [element_verdict(p, ex_of.get(eid, ()), (refs_of or {}).get(eid), rubric)[0]
           for eid, p in elements]
    n_cov, n_tot = sum(1 for x in oks if x), len(oks)
    ratio = n_cov / n_tot if n_tot else 0.0
    verdict = "인정" if n_tot and ratio >= hi else "보류" if ratio >= lo else "불인정"
    return {"ratio": ratio, "verdict": verdict, "n_covered": n_cov, "n_total": n_tot}


def unit_verdicts(s, assessment_id: int) -> list[dict[str, Any]]:
    """근거 분석 판정 하나의 **능력단위별 판정**. 위원 검토 반영분까지.

    위원 페이지가 화면 안에서 세던 것을 꺼냈다. 면제 결과도 같은 값을 써야
    하는데, 각자 세면 두 화면이 다른 시간을 말한다 — 실제로 그런 일이 네 군데
    있었다(README). 화면을 그리는 데 필요한 부속(문서·조각·시간축)은 빼고
    판정에 필요한 것만 낸다.

    돌려주는 것: [{code, name, hours, verdict, ratio, n_covered, n_total}]
    """
    from collections import defaultdict
    from sqlalchemy import text
    from krpl_core.config import get_rubric
    from services.catalog.ncs_struct import element_no as _eno_, ksa_of, pcs_of, unit_of

    rb = get_rubric()
    prog = s.execute(text("""SELECT sub.target_program_id FROM assessment a
        JOIN submission sub ON sub.id = a.submission_id WHERE a.id=:i"""),
        {"i": assessment_id}).scalar()
    units_req = {r[0]: (r[1], r[2]) for r in s.execute(text("""
        SELECT unit_code, COALESCE(unit_name, unit_code), required_hours
        FROM catalog_wsd_required WHERE program_id=:p"""), {"p": prog})}
    if not units_req:
        return []

    els = [dict(r) for r in s.execute(text("""
        SELECT element_id, payload FROM assessment_element WHERE assessment_id=:i"""),
        {"i": assessment_id}).mappings()]
    reviews = {r[0]: {"excluded_evidence": r[1]} for r in s.execute(text("""
        SELECT element_id, excluded_evidence FROM element_review WHERE assessment_id=:i"""),
        {"i": assessment_id})}

    codes = list(units_req)
    ksa_all = {k: [r for r, _ in v] for k, v in ksa_of(s, codes).items()}
    pc_all = pcs_of(s, codes)
    _eno = lambda eid: _eno_(eid) or 0   # noqa: E731

    by_unit: dict[str, list[dict]] = defaultdict(list)
    for x in els:
        by_unit[unit_of(x["element_id"])].append(x)

    out = []
    for uc, (uname, req) in units_req.items():
        xs = by_unit.get(uc, [])
        marks_of = {x["element_id"]: list((reviews.get(x["element_id"]) or {}).get("excluded_evidence") or [])
                    for x in xs}
        out.append({"code": uc, "name": uname, "hours": req,
                    **unit_verdict_of(xs, rb, marks_of, uc, ksa_all, pc_all, _eno)})
    return out


def unit_verdict_of(xs: list[dict], rb, marks_of: dict, uc: str, ksa_all: dict, pc_all: dict,
                    eno) -> dict[str, Any]:
    """단위 하나의 판정 — 형식에 따라 신형(수행준거 점수) 또는 구형(항목 커버리지).

    `format`: pc | ksa | mixed. mixed(재분석으로 구형 요소가 섞임)는 신형 요소만으로 계산하고
    화면이 띠를 보인다. 패널·계획·면제 화면이 모두 이 함수를 거쳐야 한다 — 각자 세면 어긋난다.
    """
    pc_xs = [x for x in xs if is_pc_format(x["payload"])]
    if pc_xs:
        pcs_by = {x["element_id"]: pc_all.get((uc, eno(x["element_id"])), []) for x in pc_xs}
        r = unit_by_scores([(x["element_id"], x["payload"]) for x in pc_xs], rb,
                           {x["element_id"]: marks_of.get(x["element_id"], []) for x in pc_xs}, pcs_by)
        r["format"] = "pc" if len(pc_xs) == len(xs) else "mixed"
        return r
    refs_of = {x["element_id"]: ksa_all.get((uc, eno(x["element_id"])), []) for x in xs}
    r = unit_by_coverage([(x["element_id"], x["payload"]) for x in xs], rb, marks_of, refs_of)
    r["format"] = "ksa"
    return r
