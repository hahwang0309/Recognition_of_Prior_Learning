"""위원 판정 「제출」 → 보류 단위 확인 계획 (시험 · 시연/구현 · 면접).  2026-09-24

흐름: panel 에서 위원이 항목별 인정/근거 부적합을 마치고 제출하면
  ① 위원 표시를 반영해 단위 판정을 다시 내고(artifact stage='panel')
  ② 보류 단위의 미확인 항목만 모아 방법을 배정하고(코드 규칙)
  ③ AI 1회로 면접 질문·시연 과제 문안을 받아(artifact stage='plan')
  ④ /assessments/{aid}/plan 이 그린다.

방법 배정은 코드가 한다 — 지식 → 시험(config/exams.yaml 에 그 세분류 시험이 있을 때, 없으면 면접) ·
기술 → 시연·구현 · 태도 → 면접. AI 는 문안(질문·과제·시험 범위)만 쓴다.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.orm import Session

from krpl_core.audit import AuditStore, audit_root
from krpl_core.config import CONFIG_DIR, get_model_profile, get_rubric
from krpl_core.llm import LLMClient, LLMError, Turn, get_client
from services.review.coverage import (ADD, Q, S, covered_refs, element_verdict,
                                      unit_by_coverage)

METHODS = ("시험", "시연·구현", "면접")
KIND_KO = {"지식": "지식", "기술": "기술", "태도": "태도"}
DEMO_LADDER = [                       # 부담 낮은 순. 대면 실기는 3차 TF 대로 외부평가에 맡긴다
    ("산출물 제출", "본인이 만든 도면·모델·문서·사진·영상을 내고, 작성 과정을 설명하는 짧은 메모를 붙인다"),
    ("화상 시연", "화면을 공유하며 30분 안에 지정 과제의 일부를 직접 해 보인다"),
    ("과제 구현", "기한(예: 1주) 안에 지정 과제를 만들어 제출하고, 제출물로 확인한다"),
    ("대면 실기", "RPL 단계에서는 하지 않는다 — 외부평가에서 확인 (3차 TF)"),
]


# ── 시험 목록 ──────────────────────────────────────────────────────────────
def load_exams(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """config/exams.yaml → {세분류코드: {name, exams:[{name, provider, url, scope, note}]}}."""
    p = path or (CONFIG_DIR / "exams.yaml")
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict) and str(k)[:8].isdigit()}


def exams_for(unit_code: str, exams: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return list((exams.get(unit_code[:8]) or {}).get("exams") or [])


# ── 방법 배정 (코드 규칙) ──────────────────────────────────────────────────
def assign(items: list[dict[str, Any]], has_exam: bool) -> dict[str, list[dict[str, Any]]]:
    """미확인 항목을 시험 / 시연·구현 / 면접으로 나눈다. 항목 dict 에 method 를 써 넣고 묶음도 돌려준다."""
    out: dict[str, list[dict[str, Any]]] = {m: [] for m in METHODS}
    for it in items:
        kind = it.get("kind")
        if kind == "지식":
            m = "시험" if has_exam else "면접"
        elif kind == "기술":
            m = "시연·구현"
        else:
            m = "면접"
        it["method"] = m
        out[m].append(it)
    return out


# ── 보류 단위와 미확인 항목 ────────────────────────────────────────────────
def unit_status(s: Session, assessment_id: int) -> dict[str, Any]:
    """위원 표시를 반영한 단위별 판정과, 단위마다 미확인 항목 목록.

    panel 과 같은 계산(unit_by_coverage · covered_refs). 돌려주는 것:
    {aid, sid, case_number, program, official_name, total_hours,
     buckets:{인정,보류,불인정}, units:[{code,name,hours,verdict,ratio,n_covered,n_total,
     elements:[{eid,name}], items:[{eid,element,ref,kind,name,fit_seen,quotes[],prior[]}]}]}
    """
    rb = get_rubric()
    a = s.execute(text("""
        SELECT a.id, a.submission_id, s.case_number, s.target_program_id, p.official_name, p.total_hours
        FROM assessment a JOIN submission s ON s.id=a.submission_id
        LEFT JOIN catalog_wsd_program p ON p.program_id=s.target_program_id
        WHERE a.id=:i"""), {"i": assessment_id}).mappings().one()
    els = [dict(r) for r in s.execute(text("""
        SELECT element_id, payload FROM assessment_element WHERE assessment_id=:i ORDER BY element_id"""),
        {"i": assessment_id}).mappings()]
    reviews = {r["element_id"]: list(r["excluded_evidence"] or []) for r in s.execute(text("""
        SELECT element_id, excluded_evidence FROM element_review WHERE assessment_id=:i"""),
        {"i": assessment_id}).mappings()}
    units_req = {r[0]: (r[1], r[2]) for r in s.execute(text("""
        SELECT unit_code, COALESCE(unit_name, unit_code), required_hours FROM catalog_wsd_required
        WHERE program_id=:p"""), {"p": a["target_program_id"]})}
    ksa_all: dict[tuple, list[tuple[str, str]]] = defaultdict(list)
    seen: set[tuple] = set()
    for r in s.execute(text("""
        SELECT unit_code, element_no, ksa_type, ksa_no, ksa_text FROM catalog_ncs_ksa
        WHERE unit_code = ANY(:u) ORDER BY unit_code, element_no, ksa_type, ksa_no, pc_no"""), {"u": list(units_req)}):
        k = (r[0], r[1], f"{r[2]}{r[3]}")
        if k in seen:
            continue
        seen.add(k)
        ksa_all[(r[0], r[1])].append((k[2], r[4]))

    by_unit: dict[str, list[dict]] = defaultdict(list)
    for x in els:
        by_unit[x["element_id"].split("_", 1)[0]].append(x)
    units, buckets = [], {"인정": 0, "보류": 0, "불인정": 0}
    for uc, (uname, req) in units_req.items():
        xs = by_unit.get(uc, [])
        marks_of = {x["element_id"]: reviews.get(x["element_id"], []) for x in xs}
        refs_of = {x["element_id"]: [r for r, _ in ksa_all.get((uc, _eno(x["element_id"])), [])] for x in xs}
        cov = unit_by_coverage([(x["element_id"], x["payload"]) for x in xs], rb, marks_of, refs_of)
        items, elements = [], []
        for x in xs:
            eid, p = x["element_id"], x["payload"]
            ename = p.get("element_name") or eid
            elements.append({"eid": eid, "name": ename})
            refs = ksa_all.get((uc, _eno(eid)), [])
            # 요소가 인정(항목 ≥50%)이면 확인할 것이 없다 — 통째로 건너뛴다.
            # 예전에는 보류 단위의 미확인 항목을 전부 모아, 이미 인정된 요소의
            # 나머지 항목까지 시험·면접·실기로 내밀었다.
            el_ok, _, _, _ = element_verdict(p, marks_of[eid], [r for r, _ in refs], rb)
            elements[-1]["ok"] = el_ok
            if el_ok:
                continue
            done = covered_refs(p, marks_of[eid], [r for r, _ in refs])
            ex = {m for m in marks_of[eid] if not m.startswith((ADD, Q, S))}
            evs_by_ref: dict[str, list[dict]] = defaultdict(list)
            for ev in p.get("evidence") or []:
                if ev.get("ksa_ref"):
                    evs_by_ref[ev["ksa_ref"]].append(ev)
            prior = p.get("remediation") or []
            for ref, ktxt in refs:
                if ref in done:
                    continue
                evs = evs_by_ref.get(ref, [])
                fits = sorted({ev.get("fit") or "직접" for ev in evs})
                quotes = [ev.get("quote", "") for ev in evs
                          if (ev.get("fit") or "직접") != "부정" and any(f not in ex for f in (ev.get("fids") or []))]
                items.append({"eid": eid, "element": ename, "ref": ref, "kind": ref[:2], "name": ktxt,
                              "fit_seen": fits, "quotes": [q for q in quotes if q][:2],
                              "prior": [{"method": r.get("method"), "item": r.get("item"),
                                         "oral_check": r.get("oral_check") or []}
                                        for r in prior if ref in (r.get("ksa_refs") or [])]})
        buckets[cov["verdict"]] += req
        units.append({"code": uc, "name": uname, "hours": req, "verdict": cov["verdict"], "ratio": cov["ratio"],
                      "n_covered": cov["n_covered"], "n_total": cov["n_total"],
                      "n_open_elements": sum(1 for x in elements if not x.get("ok")),
                      "elements": elements, "items": items})
    return {"aid": assessment_id, "sid": a["submission_id"], "case_number": a["case_number"],
            "program": a["target_program_id"], "official_name": a["official_name"],
            "total_hours": a["total_hours"] or sum(v[1] for v in units_req.values()) or 1,
            "buckets": buckets, "units": units}


def _eno(eid: str) -> int:
    try:
        return int(eid.rsplit(".", 1)[1])
    except (IndexError, ValueError):
        return 0


# ── AI 1회: 문안 ───────────────────────────────────────────────────────────
def _prompt(name: str) -> str:
    return (CONFIG_DIR / "prompts" / f"{name}.md").read_text(encoding="utf-8")


def perf_criteria(s: Session, codes: list[str], per_unit: int = 12) -> dict[str, list[dict[str, str]]]:
    """능력단위별 수행준거 원문. **실기 주제는 여기서 나온다.**

    NCS 원자료의 「…할 수 있다」가 그대로 실기 과제다. 지어낸 과제와 구별하려고
    AI 에게 근거로 쓴 원문을 그대로 옮기게 하고, 나중에 기계가 대조한다.
    단위마다 상한을 둔다 — 전부 부으면 프롬프트가 요구사항보다 자료로 가득 찬다.
    """
    out: dict[str, list[dict[str, str]]] = {c: [] for c in codes}
    if not codes:
        return out
    for r in s.execute(text("""
        SELECT p.unit_code, COALESCE(e.element_name, '') AS element, p.pc_text
        FROM catalog_ncs_pc p
        LEFT JOIN catalog_ncs_element e
          ON e.unit_code = p.unit_code AND e.element_no = p.element_no
        WHERE p.unit_code = ANY(:c) AND COALESCE(p.pc_text, '') <> ''
        ORDER BY p.unit_code, p.element_no, p.pc_no"""), {"c": list(codes)}):
        if len(out.get(r[0], [])) < per_unit:
            out.setdefault(r[0], []).append({"element": r[1], "text": r[2]})
    return out


def build_plan_input(st: dict[str, Any], exams: dict[str, dict[str, Any]],
                     pc: dict[str, list[dict[str, str]]] | None = None) -> dict[str, Any]:
    """보류 단위만. 항목은 「무엇을 물어야 하나」의 목록이고, 수행준거가 실기의 뼈대다.

    예전에는 항목마다 문안을 받아 화면에 하나씩 늘어놓았다. 위원이 그대로 들고
    쓸 수 없는 형태라, 지금은 **면접 질문지 한 벌과 실기 주제 3~5개**를 받는다.
    """
    pc = pc or {}
    units = []
    for u in st["units"]:
        if u["verdict"] != "보류":
            continue
        ex = exams_for(u["code"], exams)
        groups = assign(u["items"], bool(ex))
        units.append({
            "code": u["code"], "name": u["name"], "hours": u["hours"],
            "n_uncovered": len(u["items"]), "n_total": u["n_total"],
            "counts": {m: len(groups[m]) for m in METHODS},
            # 확인 대상 요소 — 「어느 단위의 어느 요소를 확인하는가」가 화면에
            # 보여야 한다. 위원이 그것을 모르면 질문·과제가 어디에 쓰이는지 알 수 없다.
            "open_elements": [{"eid": x["eid"], "name": x["name"]}
                              for x in u["elements"] if not x.get("ok")],
            "pc": pc.get(u["code"]) or [],
            "items": [{"ref": it["ref"], "kind": it["kind"], "name": it["name"],
                       "element": it["element"], "quotes": it["quotes"]}
                      for m in METHODS for it in groups[m]],
        })
    return {"case_number": st["case_number"],
            "program": st["official_name"] or st["program"], "units": units}


def _norm(x: str) -> str:
    return re.sub(r"\s+", "", x or "")


def _check(plan: dict[str, Any], inp: dict[str, Any]) -> list[str]:
    """AI 가 낸 문안이 쓸 만한지 기계가 본다. 판정이 아니라 형식과 근거의 대조다."""
    errs: list[str] = []
    codes = {u["code"] for u in inp["units"]}
    pcs = {u["code"]: [_norm(x["text"]) for x in (u.get("pc") or [])] for u in inp["units"]}

    iv = plan.get("interview") or {}
    if not iv.get("opening"):
        errs.append("면접 질문지에 도입 질문이 없다")
    seen = set()
    for sec in (iv.get("sections") or []):
        code = sec.get("unit")
        if code not in codes:
            errs.append(f"없는 단위의 면접 절: {code!r}")
            continue
        seen.add(code)
        qs = [q for q in (sec.get("questions") or []) if (q.get("q") or "").strip()]
        if not qs:
            errs.append(f"{code}: 면접 질문이 없다")
        for q in qs:
            head = (q.get("q") or "")[:20]
            if not q.get("answer_points"):
                errs.append(f"{code}: 「{head}…」에 답변 요지가 없다")
            if not (q.get("follow_up") or "").strip():
                errs.append(f"{code}: 「{head}…」에 후속 질문이 없다")
    for code in codes - seen:
        errs.append(f"면접 절 누락: {code}")

    pr = plan.get("practical") or []
    if not 3 <= len(pr) <= 5:
        errs.append(f"실기 주제는 3~5개여야 한다 (지금 {len(pr)}개)")
    used: set[str] = set()
    for i, x in enumerate(pr, 1):
        if not (x.get("title") or "").strip():
            errs.append(f"실기 {i}: 주제 이름이 없다")
        bad = [c for c in (x.get("units") or []) if c not in codes]
        if bad:
            errs.append(f"실기 {i}: 없는 단위 {bad}")
        basis = _norm(x.get("basis") or "")
        if not basis:
            errs.append(f"실기 {i}: 근거 수행준거가 없다")
        elif not any(basis in p or p in basis
                     for c in (x.get("units") or codes) for p in pcs.get(c, [])):
            errs.append(f"실기 {i}: 근거가 수행준거 원문과 다르다 — 원문을 그대로 옮겨라")
        elif basis in used:
            errs.append(f"실기 {i}: 앞의 주제와 같은 수행준거를 쓴다")
        else:
            used.add(basis)
        if not x.get("criteria"):
            errs.append(f"실기 {i}: 평가 관점이 없다")
    return errs


def ask_plan(inp: dict[str, Any], client: LLMClient | None = None, profile_name: str = "trackb_plan") -> dict[str, Any]:
    """AI 1회(실패 시 1회 재요청). 돌려주는 것: {plan, errors, usage}. 실패해도 마지막 산출물을 돌려준다."""
    if not inp["units"]:
        return {"plan": {"units": []}, "errors": [], "usage": {}}
    profile = get_model_profile(profile_name)
    client = client or get_client(profile)
    sysblocks = [_prompt("trackb_plan")]
    msgs = [{"role": "user", "content": json.dumps(inp, ensure_ascii=False)}]
    plan, errs, usage = {"units": []}, ["호출 전"], {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "tries": 0}
    for _ in range(2):
        r = client.complete(Turn(system=sysblocks, messages=msgs, purpose="plan"), profile)
        usage["cost_usd"] += r.cost_usd; usage["input_tokens"] += r.input_tokens
        usage["output_tokens"] += r.output_tokens; usage["tries"] += 1
        try:
            plan = r.json()
        except LLMError as e:
            errs = [f"JSON 해석 실패: {e}"]
        else:
            errs = _check(plan, inp)
        if not errs:
            break
        msgs = msgs + [{"role": "assistant", "content": r.text},
                       {"role": "user", "content": "아래를 고쳐 전체 JSON 을 다시 내라:\n- " + "\n- ".join(errs)}]
    return {"plan": plan, "errors": errs, "usage": usage}


# ── 제출 ───────────────────────────────────────────────────────────────────
def submit(s: Session, assessment_id: int, reviewer: str | None = None,
           client: LLMClient | None = None) -> dict[str, Any]:
    """위원 판정 제출: 단위 판정 스냅샷(stage panel) + 확인 계획(stage plan). 계획 dict 를 돌려준다."""
    st = unit_status(s, assessment_id)
    exams = load_exams()
    now = datetime.now()
    store = AuditStore(s, st["case_number"], st["sid"], assessment_id)
    seq = 1 + (s.execute(text("""
        SELECT COALESCE(MAX(seq),0) FROM artifact WHERE assessment_id=:a AND stage='panel'"""),
        {"a": assessment_id}).scalar() or 0)
    snap = {"submitted_at": now.isoformat(timespec="seconds"), "reviewer": reviewer,
            "buckets": st["buckets"], "total_hours": st["total_hours"],
            "units": [{k: u[k] for k in ("code", "name", "hours", "verdict", "ratio", "n_covered", "n_total")}
                      | {"n_uncovered": len(u["items"])} for u in st["units"]]}
    store.write("panel", "위원판정_제출", snap, seq=seq,
                note=f"인정 {st['buckets']['인정']}h · 보류 {st['buckets']['보류']}h · 불인정 {st['buckets']['불인정']}h")
    hold_codes = [u["code"] for u in st["units"] if u["verdict"] == "보류"]
    inp = build_plan_input(st, exams, perf_criteria(s, hold_codes))
    empty = {"plan": {"interview": {}, "practical": []}, "errors": [], "usage": {}}
    ai = ask_plan(inp, client) if inp["units"] else empty
    plan = {"submitted_at": snap["submitted_at"], "reviewer": reviewer, "buckets": st["buckets"],
            "total_hours": st["total_hours"], "program": st["official_name"] or st["program"],
            "units": [{k: u[k] for k in ("code", "name", "hours", "verdict", "n_covered", "n_total")} for u in st["units"]],
            "input": inp, "ai": ai["plan"], "ai_errors": ai["errors"], "usage": ai["usage"],
            "exams": {u["code"]: exams_for(u["code"], exams) for u in inp["units"]}}
    u = ai["usage"]
    store.write("plan", "확인계획", plan, seq=seq,
                note=(f"보류 {len(inp['units'])}단위 · AI {u.get('tries', 0)}회 · ${u.get('cost_usd', 0):.3f}"
                      + (f" · 검증 오류 {len(ai['errors'])}" if ai["errors"] else "")))
    s.execute(text("""
        UPDATE assessment SET progress = COALESCE(progress,'{}'::jsonb) || CAST(:p AS jsonb) WHERE id=:i"""),
        {"i": assessment_id, "p": json.dumps({"panel_submitted_at": snap["submitted_at"], "panel_seq": seq})})
    # Track B 는 ③ 확인 계획에서 끝난다. 여기까지 왔는데 접수가 「확인 필요」에
    # 남아 있으면, 할 일 목록은 할 것이 있다고 하는데 화면에는 할 것이 없다.
    s.execute(text("UPDATE submission SET status='decided' WHERE id=:i"), {"i": st["sid"]})
    return plan


def latest_plan(s: Session, assessment_id: int) -> dict[str, Any] | None:
    row = s.execute(text("""
        SELECT path FROM artifact WHERE assessment_id=:a AND stage='plan' ORDER BY seq DESC, id DESC LIMIT 1"""),
        {"a": assessment_id}).first()
    if row is None:
        return None
    p = audit_root() / row[0]
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def last_submitted(s: Session, assessment_id: int) -> str | None:
    row = s.execute(text("SELECT progress->>'panel_submitted_at' FROM assessment WHERE id=:i"),
                    {"i": assessment_id}).first()
    return row[0] if row else None


_ = re  # (정규식은 아직 안 쓴다 — 시험 범위 매칭을 붙일 자리)
