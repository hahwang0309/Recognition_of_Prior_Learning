"""Track B 위원 페이지 — 한 지원자 = 한 쪽 (2026-09-23, 1~3차 TF 반영 · 2026-10-02 수행준거 점수).

보이는 순서: 0 머리(사례·문서) → 1 카드 3장(인정·보류·불인정 시간) → 2 능력단위 3점 정량표
→ 3 수행준거별 점수(AI 값을 위원이 고친다 → 능력단위 판정이 바뀐다) → 4 판정 파라미터.

신형(2026-10-02, 4차 TF): 단위 → 수행준거 두 층. 수행준거마다 0/1/2 점(직접 근거 2 · 간접만 1 · 없음·부정 0),
위원이 점수를 고친다. 단위 판정은 rubric track_b.unit_rule(평균 문턱, 0 조건 여부). 규칙은 coverage.unit_by_scores 하나다 —
화면 JS 는 AI 점수를 다시 세지 않고(서버가 넣어 준 값), 위원 값과 단위 규칙만 적용하며, 저장 응답의
서버 계산으로 다시 그린다(2026-09-28 「화면≠서버」 사고 재발 방지).
구형(항목 단위) 판정은 띠를 보이고 읽기만 된다 — 근거 분석을 다시 돌려야 한다.
방법론 코드(R0~R5·fid·KSA ref)는 화면에 쓰지 않는다.
"""
from __future__ import annotations

import html
import re
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from krpl_core.config import get_rubric
from services.catalog.ncs_struct import element_no as _eno_, ksa_of, pcs_of, unit_of
from services.report._shared import (STEP_CSS, TRACK_CSS, evidence_sort_key, param_table, pending, unit_rule_text,
                                     step_head, step_nav, track_chip, unit_count_text)
from services.report.doc_viewer import js_literal
from services.report.track_a_report import CSS as BASE_CSS
from services.review.coverage import (MARK_PREFIXES, element_coverage, element_scores, is_pc_format,
                                      pc_overrides, three_point, unit_verdict_of)
from services.review.time_axis import band as time_band, extract as time_extract

e = lambda x: html.escape(str(x) if x is not None else "")   # noqa: E731

BUCKET_KO = {"인정후보": "인정 후보", "추가확인": "추가 확인", "미인정": "미인정"}
VERDICT_CLS = {"인정": ("good", "●"), "보류": ("hold", "◆"), "불인정": ("crit", "■")}
BAND_CLS = {"상": "good", "중": "hold", "하": "crit"}
FIT_CLS = {"직접": "good", "간접": "hold", "부정": "crit"}


def fit_class(fit: str) -> str:
    """적합도 → 색. **어휘 밖의 값도 그린다.**

    AI 가 「간직」처럼 어휘에 없는 값을 낸 적이 있다(판정 820). 기계 검증이
    `fit_어휘` 로 잡아 재요청했지만 3회 안에 못 고쳐 그대로 저장됐고, 화면이
    `KeyError` 로 죽어 위원이 아무것도 볼 수 없었다. 자료가 이상해도 화면은
    떠야 한다 — 이상하다는 것을 눈에 보이게 하면서.
    """
    return FIT_CLS.get(fit, "crit")

EXTRA_CSS = """
.gA,.gB,.gC,.gD,.gE{display:inline-block;width:20px;height:20px;line-height:20px;text-align:center;border-radius:5px;font-size:11px;font-weight:700;color:#fff}
.gA{background:#1f6f43}.gB{background:#2e7d32}.gC{background:#c48a00}.gD{background:#c2410c}.gE{background:#7a7a72}
.tp td,.tp th{white-space:normal;vertical-align:top}
.b{display:inline-block;min-width:26px;text-align:center;border-radius:6px;padding:1px 7px;font-weight:700;font-size:12px;color:#fff}
.b.good{background:var(--good)}.b.hold{background:var(--hold)}.b.crit{background:var(--crit)}
.q td{white-space:normal;vertical-align:top}
.q .ans{font-weight:700}.q .ans.y{color:var(--good)}.q .ans.n{color:var(--crit)}.q .ans.u{color:var(--hold)}
blockquote{margin:2px 0 4px;padding:4px 10px;border-left:3px solid var(--bd);color:var(--ts);font-size:12px;white-space:normal}
.it td{white-space:normal;vertical-align:top}
.it tr.off td{color:var(--tp)}.it tr.off .st.none{color:var(--tp)}.it .why{color:var(--tp);font-size:12px}
.it tr.on td{background:rgba(12,163,12,.05)}
.it .st{display:inline-flex}
.pcs{display:inline-flex;border:1px solid var(--bd);border-radius:6px;overflow:hidden}
.pcs button{border:0;background:none;padding:2px 9px;font-size:12px;font-weight:700;cursor:pointer;color:var(--tm);border-right:1px solid var(--bd)}
.pcs button:last-child{border-right:0}
.pcs button.on{color:#fff}.pcs button.on.s2{background:var(--good)}.pcs button.on.s1{background:var(--hold)}.pcs button.on.s0{background:var(--crit)}
.pcs button[disabled]{cursor:default}
.src{display:inline-block;font-size:10.5px;color:var(--tm);border:1px solid var(--bd);border-radius:4px;padding:0 5px;margin-left:6px;vertical-align:1px}
.src.rv{color:var(--hold);border-color:var(--hold)}.src.rule{color:var(--good);border-color:var(--good)}
.pct{font-size:12.5px}
.evl{margin:0;padding:0;list-style:none}.evl li{margin:0 0 6px}
.ecap{font-size:12px;color:var(--ts);margin:8px 0 2px 2px}.ecap .lv{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.04em;color:var(--hold);border:1px solid var(--hold);border-radius:4px;padding:0 5px;margin-right:6px;vertical-align:1px}
.oldfmt{background:#fff4d6;color:#5a3d00;padding:8px 12px;border-radius:8px;font-size:12.5px;margin:0 0 10px}
.plan-pick{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12px;margin:6px 0 0}
#save{font-size:12px;color:var(--tm)}
.unit{font-weight:600}.unit small{display:block;color:var(--tm);font-weight:400;font-size:11px}
details.tbl>summary .lv{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.04em;color:var(--tm);border:1px solid var(--bd);border-radius:4px;padding:0 5px;margin-right:6px;vertical-align:1px}
details.sub2{margin:4px 0 8px 22px;padding-left:12px;border-left:2px solid var(--bd)}
details.sub2>summary{font-size:12.5px;color:var(--ts);cursor:pointer}
details.sub2>summary .lv{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.04em;color:var(--hold);border:1px solid var(--hold);border-radius:4px;padding:0 5px;margin-right:6px;vertical-align:1px}
.ft{display:inline-block;font-size:10.5px;font-weight:700;border-radius:4px;padding:0 5px;margin-left:4px;vertical-align:1px;border:1px solid}
.ft.hold{color:var(--hold);border-color:var(--hold)}.ft.crit{color:var(--crit);border-color:var(--crit)}
a.fx{color:var(--tp);text-decoration:underline dotted;text-underline-offset:2px;cursor:pointer;font-weight:600}
a.fx:hover{color:var(--hold)}
.fx .gA,.fx .gB,.fx .gC,.fx .gD,.fx .gE{width:16px;height:16px;line-height:16px;font-size:10px;margin-left:3px;vertical-align:1px}
#dv{position:fixed;top:0;right:0;width:440px;max-width:92vw;height:100vh;background:var(--sf,#fff);border-left:1px solid var(--bd);box-shadow:-6px 0 18px rgba(0,0,0,.08);z-index:50;display:none;flex-direction:column;font-size:12.5px}
.pbar{height:6px;border-radius:3px;background:var(--s2);overflow:hidden;margin:6px 0 4px;max-width:320px}
.pbar i{display:block;height:100%;width:38%;border-radius:3px;background:var(--tp);
 animation:pslide 1.1s ease-in-out infinite}
@keyframes pslide{0%{margin-left:-38%}100%{margin-left:100%}}
#subbusy{margin-left:4px}
#dv.open{display:flex}
#dv .hd{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid var(--bd)}
#dv .hd b{flex:1;font-size:13px}
#dv .hd button{border:1px solid var(--bd);background:none;border-radius:6px;padding:2px 8px;cursor:pointer;font-size:14px}
#dv .tabs{display:flex;flex-wrap:wrap;gap:4px;padding:8px 12px;border-bottom:1px solid var(--bd)}
#dv .tabs button{border:1px solid var(--bd);background:none;border-radius:6px;padding:2px 7px;cursor:pointer;font-size:11.5px;color:var(--ts)}
#dv .tabs button.on{background:var(--tp);color:#fff;border-color:var(--tp)}
#dv input{margin:8px 12px 0;padding:5px 8px;border:1px solid var(--bd);border-radius:6px;font-size:12.5px}
#dv .body{flex:1;overflow:auto;padding:8px 12px 20px}
#dv .body p{margin:0;padding:5px 6px;border-bottom:1px solid var(--bd);white-space:normal;line-height:1.45}
#dv .body p small{color:var(--tm);margin-right:6px}
#dv .body p.hit{background:#fff3b0;border-radius:4px}
#dv .body .dn{font-weight:700;margin:8px 0 2px;color:var(--ts)}
@media print{#dv{display:none!important}}
"""


def _doc_name(path: str | None, key: str) -> str:
    if not path:
        return key
    n = Path(path).name
    n = n.rsplit(".", 1)[0]
    return n[3:].replace("_", " ") if len(n) > 3 and n[2] == "_" and n[:2].isdigit() else n.replace("_", " ")


_FID = re.compile(r"D\d{2}-[SP]\d+")


def _cite(txt: str, frag_by_fid: dict, doc_by_key: dict) -> str:
    """AI 문구 속 조각 번호(D10-S11)를 「문서명 등급 “원문”」 링크로 푼다. 없는 번호는 그대로 둔다."""
    out, pos = [], 0
    for m in _FID.finditer(txt or ""):
        f = frag_by_fid.get(m.group(0))
        out.append(e(txt[pos:m.start()]))
        if f:
            d = doc_by_key.get(f["doc_key"], {})
            out.append(f"<a class='fx' data-fid='{e(f['fid'])}'>{e(_doc_name(d.get('file_path'), f['doc_key']))}"
                       f"<span class='g{e(f['grade'])}'>{e(f['grade'])}</span></a> “{e(f['text'])}”")
        else:
            out.append(e(m.group(0)))
        pos = m.end()
    out.append(e(txt[pos:] if txt else ""))
    return "".join(out)


# <script> 안에 넣는 JSON — 이스케이프는 doc_viewer 한 곳에서만 한다.
_js = js_literal


def _fno(fid: str) -> int:
    try:
        return int(fid.split("-", 1)[1][1:])
    except (IndexError, ValueError):
        return 0


def _eno(eid: str) -> int:
    try:
        return int(eid.rsplit(".", 1)[1])
    except (IndexError, ValueError):
        return 0


def render_panel(s: Session, assessment_id: int, *, readonly: bool = False) -> str:
    """readonly=True — 열람 전용(`?ro=1`). 4차 TF 체험 세션에서 위원이 자기 기기로 근거·원문을 보되
    점수·제출은 못 하게 한다(판정 입력은 진행자 화면에서 다수결로 넣는다). 점수 버튼은 보이되 눌리지 않는다."""
    rb = get_rubric()
    a = s.execute(text("""
        SELECT a.id, a.submission_id, a.rubric_version, a.model, a.finished_at,
               s.case_number, s.target_program_id, s.track, p.official_name, p.total_hours
        FROM assessment a JOIN submission s ON s.id=a.submission_id
        LEFT JOIN catalog_wsd_program p ON p.program_id=s.target_program_id
        WHERE a.id=:i"""), {"i": assessment_id}).mappings().one()
    sid = a["submission_id"]
    time_aid = s.execute(text("""SELECT id FROM assessment WHERE submission_id=:i
        AND kind='time' ORDER BY id DESC LIMIT 1"""), {"i": sid}).scalar()
    has_plan = bool(s.execute(text("""SELECT 1 FROM artifact
        WHERE assessment_id=:a AND stage='plan' LIMIT 1"""), {"a": assessment_id}).first())
    els = [dict(r) for r in s.execute(text("""
        SELECT element_id, recommendation, evidence_level, verification_method, confidence, payload
        FROM assessment_element WHERE assessment_id=:i ORDER BY element_id"""), {"i": assessment_id}).mappings()]
    reviews = {r["element_id"]: dict(r) for r in s.execute(text("""
        SELECT element_id, decision, note, excluded_evidence FROM element_review
        WHERE assessment_id=:i"""), {"i": assessment_id}).mappings()}
    docs = [dict(r) for r in s.execute(text("""
        SELECT doc_key, doc_type, grade, issuer, file_path FROM document
        WHERE submission_id=:i ORDER BY doc_key"""), {"i": sid}).mappings()]
    frags = [dict(r) for r in s.execute(text("""
        SELECT fid, doc_key, doc_type, grade, text FROM fragment WHERE submission_id=:i"""),
        {"i": sid}).mappings()]
    units_req = {r[0]: (r[1], r[2]) for r in s.execute(text("""
        SELECT unit_code, COALESCE(unit_name, unit_code), required_hours FROM catalog_wsd_required
        WHERE program_id=:p"""), {"p": a["target_program_id"]})}
    codes = list(units_req)
    ksa_all = ksa_of(s, codes)                                   # 구형(항목 단위) 요소용
    ksa_refs_all = {k: [r for r, _ in v] for k, v in ksa_all.items()}
    pc_all = pcs_of(s, codes)                                    # 신형(수행준거) — 판정 단위
    doc_by_key = {d["doc_key"]: d for d in docs}
    frag_by_fid = {f["fid"]: f for f in frags}
    submitted = (s.execute(text("SELECT progress->>'panel_submitted_at' FROM assessment WHERE id=:i"),
                           {"i": assessment_id}).scalar() or "").replace("T", " ")[:16]
    cite = lambda s_: _cite(s_, frag_by_fid, doc_by_key)   # noqa: E731
    tot = a["total_hours"] or sum(v[1] for v in units_req.values()) or 1
    axis = time_extract(frags)
    hi, lo = rb.training_hours.get("adjustment_floor", 0.5), rb.training_hours.get("hold_floor", 0.3)
    ur = rb.track_b.get("unit_rule") or {}
    acc, hold = float(ur.get("accept_mean", 1.5)), float(ur.get("hold_mean", 1.0))
    req0 = bool(ur.get("require_all_nonzero", True))
    _eno = lambda eid: _eno_(eid) or 0   # noqa: E731

    # ── 요소를 능력단위로 묶고 판정 계산 (coverage.unit_verdict_of — 다른 화면과 같은 셈) ──
    by_unit: dict[str, list[dict]] = defaultdict(list)
    for x in els:
        by_unit[unit_of(x["element_id"])].append(x)
    units = []
    for uc, (uname, req) in units_req.items():
        xs = by_unit.get(uc, [])
        marks_of = {x["element_id"]: list((reviews.get(x["element_id"]) or {}).get("excluded_evidence") or []) for x in xs}
        marks = [m for v in marks_of.values() for m in v]
        cov = unit_verdict_of(xs, rb, marks_of, uc, ksa_refs_all, pc_all, _eno)
        tp = three_point([x["payload"] for x in xs], rb, [m for m in marks if not m.startswith(MARK_PREFIXES)])
        tb, tb_note = time_band(tot, axis, rb)
        units.append({"code": uc, "name": uname, "hours": req, "els": xs, "tp": tp, "cov": cov,
                      "time": (tb, tb_note), "verdict": cov["verdict"], "fmt": cov.get("format", "ksa"),
                      "marks_of": marks_of})
    B = {"인정": 0, "보류": 0, "불인정": 0}
    for u in units:
        B[u["verdict"]] += u["hours"]
    n_old = sum(1 for x in els if not is_pc_format(x["payload"]))
    old_banner = (f"<div class='oldfmt'>이 판정의 요소 {n_old}개는 <b>옛 형식(항목 단위)</b>입니다 — 근거 분석을 다시 돌려야 "
                  f"수행준거 점수가 나옵니다. 옛 형식 요소는 읽기만 됩니다.</div>" if n_old else "")

    # ── 0 문서 표 ──
    drows = "".join(
        f"<tr><td><span class='g{e(d['grade'])}'>{e(d['grade'])}</span></td><td><a class='fx' data-doc='{e(d['doc_key'])}'>{e(_doc_name(d['file_path'], d['doc_key']))}</a></td>"
        f"<td>{e(d['doc_type'])}{' — <b>종류 지정 필요</b>' if d['doc_type'] == '기타' else ''}</td></tr>" for d in docs)

    # ── 2 단위 표 ──
    def _band_of(u) -> str:
        if u["fmt"] != "ksa":
            m = u["cov"].get("mean") or 0
            return "상" if m >= acc else "중" if m >= hold else "하"
        r = u["cov"]["ratio"]
        return "상" if r >= hi else "중" if r >= lo else "하"
    urows = ""
    for u in units:
        tp, (tb, tb_note), cov = u["tp"], u["time"], u["cov"]
        vc, vi = VERDICT_CLS[u["verdict"]]
        band = _band_of(u)
        els_ko = " · ".join(BUCKET_KO[b] for b in tp["buckets"]) if tp["buckets"] else "요소 없음"
        urows += f"""<tr data-unit="{e(u['code'])}">
 <td class="unit">{e(u['name'])}<small>{u['hours']}h · 요소 {len(u['els'])}개 · AI 참고: {e(els_ko)}</small></td>
 <td><span class="b {BAND_CLS[band]}" id="m-{e(u['code'])}">{band}</span> <small id="mc-{e(u['code'])}">{e(unit_count_text(cov))}</small></td>
 <td><span class="b {BAND_CLS[tb]}">{tb}</span> <small>{e(tb_note)}</small></td>
 <td><span class="b {BAND_CLS[tp['verify']]}">{tp['verify']}</span> <small>최고 등급 {e(tp['best_grade'] or '없음')}</small></td>
 <td><span class="st {vc}" id="v-{e(u['code'])}"><i>{vi}</i>{u['verdict']}</span></td></tr>"""

    # ── 3 수행준거별 점수 — 능력단위 › (요소 캡션) › 수행준거 행. AI 값을 위원이 고친다 ──
    def _ev_html(evs: list[dict]) -> str:
        """근거 목록 — 조각 기준으로 한 번만(같은 조각이 여러 건이면 묶음), 공신력 순 정렬 (4차 TF 의견 9·10)."""
        groups: dict[str, dict] = {}
        for ev in evs:
            fids = [f for f in (ev.get("fids") or []) if f]
            if not fids:
                continue
            key = fids[0]
            g = groups.setdefault(key, {"ev": ev, "n": 0, "fits": []})
            g["n"] += 1
            fit = ev.get("fit") or "직접"
            if fit not in g["fits"]:
                g["fits"].append(fit)
        rows = []
        for key, g in groups.items():
            ev = g["ev"]
            f = frag_by_fid.get(key, {})
            d = doc_by_key.get(key[:3], {})
            fit = ev.get("fit") or "직접"
            rows.append((evidence_sort_key(f.get("grade") or ev.get("grade"), f.get("doc_type") or d.get("doc_type"), fit), key, g, f, d))
        rows.sort(key=lambda r: r[0])
        out = []
        for _, key, g, f, d in rows:
            ev = g["ev"]
            fit = ev.get("fit") or "직접"
            badge = ("" if fit == "직접" else
                     f" <span class='ft {fit_class(fit)}'>{e(fit)}{'' if fit in FIT_CLS else ' ⚠ 알 수 없는 값'}</span>")
            more = f" <small style='color:var(--tm)'>· 이 조각이 {g['n']}곳</small>" if g["n"] > 1 else ""
            out.append(f"<li><small><a class='fx' data-fid='{e(key)}'>{e(_doc_name(d.get('file_path'), key[:3]))}"
                       f"<span class='g{e(f.get('grade') or ev.get('grade') or '')}'>{e(f.get('grade') or ev.get('grade') or '')}</span></a>{badge}{more}</small>"
                       f"<blockquote>{e(ev.get('quote', ''))}</blockquote><small style='color:var(--tm)'>{cite(ev.get('why', ''))}</small></li>")
        return f"<ul class='evl'>{''.join(out)}</ul>" if out else "<span class='why'>근거 없음</span>"

    ev_json = []
    items_html = ""
    for u in units:
        vc, vi = VERDICT_CLS[u["verdict"]]
        cov = u["cov"]
        head = (f"<span class='lv'>능력단위</span><b>{e(u['name'])}</b> — {u['hours']}h · "
                f"<span id='h-{e(u['code'])}'>{e(unit_count_text(cov))}</span> · "
                f"<span class='st {vc}' id='hv-{e(u['code'])}' style='display:inline-flex'><i>{vi}</i>{u['verdict']}</span>")
        inner = ""
        for x in u["els"]:
            p = x["payload"]
            eid = x["element_id"]
            ename = p.get("element_name") or eid
            marks = u["marks_of"].get(eid, [])
            if not is_pc_format(p):
                inner += _legacy_element(u, x, marks, ksa_all, cite, doc_by_key)
                continue
            pcs = pc_all.get((u["code"], _eno(eid)), [])
            rows_ = element_scores(p, pcs, marks, rb)
            ov = pc_overrides(marks)
            by_ref: dict[str, list[dict]] = defaultdict(list)
            for ev in p.get("evidence") or []:
                if isinstance(ev, dict) and ev.get("pc_ref"):
                    by_ref[ev["pc_ref"]].append(ev)
            unc_note = {(uu.get("ref") if isinstance(uu, dict) else uu): (uu.get("note", "") if isinstance(uu, dict) else "")
                        for uu in (p.get("uncovered_pc") or [])}
            trs = ""
            for r in rows_:
                ai_score, _ = (r["score"], r["src"]) if r["src"] != "reviewer" else (
                    next((q["score"] for q in element_scores(p, [pc for pc in pcs if pc["ref"] == r["ref"]], (), rb)), 0), "ai")
                src_badge = ("<span class='src rv'>위원</span>" if r["src"] == "reviewer" else
                             "<span class='src rule'>기록</span>" if r["src"] == "rule" else "<span class='src'>AI</span>")
                btns = "".join(f"<button type='button' class='{'on ' if r['score'] == n else ''}s{n}' data-eid='{e(eid)}' data-ref='{e(r['ref'])}' data-n='{n}'"
                               f"{' disabled' if readonly else ''}>{n}</button>" for n in (0, 1, 2))
                body_ = _ev_html(by_ref.get(r["ref"], [])) if by_ref.get(r["ref"]) else (
                    f"<span class='why'>{cite(unc_note.get(r['ref'], '')) or '근거 없음'}</span>")
                trs += f"""<tr class="{'on' if r['score'] >= 1 else 'off'}" id="pr-{e(eid)}-{e(r['ref'])}">
 <td class="c" style="white-space:nowrap"><span class="pcs" data-ai="{ai_score}">{btns}</span>{src_badge}</td>
 <td class="pct">{e(r['text'])}</td>
 <td>{body_}</td></tr>"""
                ev_json_pc = None
            n1 = sum(1 for r in rows_ if r["score"] >= 1)
            inner += f"""<div class="ecap"><span class="lv">요소</span>{e(ename)} <small>— 수행준거 <span id="ec-{e(eid)}">{n1}</span>/{len(rows_)} ≥1</small></div>
<div class="tw"><table class="it"><thead><tr><th style="width:150px">점수</th><th style="width:36%">수행준거</th><th>근거 (문서 · 원문 · AI 이유)</th></tr></thead><tbody>{trs}</tbody></table></div>"""
            ev_json.append({"eid": eid, "unit": u["code"],
                            "pcs": [{"ref": r["ref"], "ai": (r["score"] if r["src"] != "reviewer" else
                                                            next((q["score"] for q in element_scores(p, [pc for pc in pcs if pc["ref"] == r["ref"]], (), rb)), 0)),
                                     "src": r["src"]} for r in rows_],
                            "ov": ov})
        items_html += f"""<details class="tbl" {'open' if u['verdict'] != '불인정' else ''}><summary>{head}</summary>{inner or "<p class='sub'>요소 정보 없음</p>"}</details>"""

    # ── 5 파라미터 ──
    r6 = rb.rules.get("R6_recency", {})
    params = [
        ("점수를 누가 정하나",
         "AI 가 수행준거마다 근거를 붙이고 점수가 규칙으로 정해집니다. 위원이 0·1·2 를 눌러 고치면 위원 값이 우선합니다",
         "4차 TF(2026-09-30) 합의", False),
        ("수행준거 점수",
         "2 = 직접 근거(그 일을 했다는 것을 그대로 보여 줌)가 1건 이상 · "
         "1 = 간접 근거(관련은 있으나 증명은 못 함)만 있음 · "
         "0 = 근거 없음 또는 못 한다·안 해봤다는 본인 진술",
         "2026-10-02 결정 — 존재 기준(근거가 많아도 내려가지 않음)", True),
        ("능력단위 판정",
         unit_rule_text(rb),
         "4차 TF 직후 합의(0 없음 · 1.5/1.0)에서 2026-10-04 조정 — 5차에서 확정", pending(rb, "track_b.unit_rule.accept_mean")),
        ("인정되면 몇 시간",
         "그 능력단위의 요구시간 전체. 수행준거에는 시간이 매겨져 있지 않아 충족 여부로만 판단합니다",
         "NCS 원자료 확인 · 설계안", False),
        ("보류 단위는 어떻게",
         "점수가 2 가 아닌 수행준거만 확인합니다 — 0 은 외부평가 실기, 1 은 면접. 제출할 때 포함할 단위를 고를 수 있습니다",
         "2026-10-02 설계 · 4차 TF 의견 14", True),
        ("실기", "RPL 단계에서는 보지 않고 외부평가에 맡깁니다",
         "3차 TF", pending(rb, "track_b.practical_to_external")),
        ("문서 등급",
         "A 공적 증빙 · B 기관 발급 · C 산출물·기록 · D 제3자 진술 · E 본인 진술 "
         "(정부인정 사업주자격증과 직무능력인정서는 A). 근거는 등급 → 문서 종류 신뢰 순으로 보입니다",
         "증거평가기준 · 3차 TF · 4차 TF 의견 9", False),
        ("자료의 최신성",
         f"{r6.get('years', {}).get('default', 5)}년까지 인정 (전기·전자·정보통신은 {r6.get('years', {}).get('fast_changing', 3)}년)",
         "증거평가기준", pending(rb, "rules.R6_recency")),
        ("교육시간 / 요구시간",
         "문서에서 읽은 교육시간을 종목 총 요구시간과 견준 참고값입니다. 판정에는 쓰지 않습니다",
         "표시용 — 시간은 Track A 가 셉니다", True),
    ]

    units_json = [{"code": u["code"], "hours": u["hours"], "els": [x["element_id"] for x in u["els"] if is_pc_format(x["payload"])],
                   "fixed": u["verdict"] if u["fmt"] == "ksa" else None} for u in units]
    fr_json = [{"fid": f["fid"], "doc": f["doc_key"], "name": _doc_name(doc_by_key.get(f["doc_key"], {}).get("file_path"), f["doc_key"]),
                "grade": f["grade"], "text": f["text"]} for f in sorted(frags, key=lambda f: (f["doc_key"], _fno(f["fid"])))]
    dn_json = [{"doc": d["doc_key"], "name": _doc_name(d["file_path"], d["doc_key"]), "grade": d["grade"]} for d in docs]
    hold_units = [u for u in units if u["verdict"] == "보류"]
    plan_pick = ("<input type='hidden' name='plan_units_sent' value='1'><div class='plan-pick' id='plan-pick'>"
                 + "".join(f"<label><input type='checkbox' name='plan_units' value='{e(u['code'])}' checked> {e(u['name'])}</label>" for u in hold_units)
                 + "</div>")

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RPL Track B 위원 페이지 — {e(a['case_number'])}</title><style>{BASE_CSS}{EXTRA_CSS}{TRACK_CSS}{STEP_CSS}</style></head>
<body><div class="viz">
<div class="bk"><a href="/submissions/{sid}">← 심사 개요</a><button onclick="print()">인쇄</button></div>
{step_head("panel", "RPL Track B 심사 보고서", track="B",
           nav=step_nav(sid, time_aid, True, track="B", ev_aid=assessment_id,
                        has_plan=has_plan))}
<p class="sub" style="margin:0 0 10px">이 건의 접수 구분: {track_chip(a['track'], full=True)}
 <span style="margin-left:6px">— 위 제목의 「Track B」는 판정 종류(근거 분석)입니다.</span></p>
{old_banner}
<div style="margin:0 0 10px;display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap"><span id="save"></span>
<form method="post" action="/assessments/{assessment_id}/panel/submit" id="submit-f" style="margin:0;display:none;flex-direction:column">
<div><button type="submit" class="go">제출 → 확인 계획</button>
<span class="sub" style="margin-left:8px">{('마지막 제출 ' + e(submitted) + ' · <a href="/assessments/' + str(assessment_id) + '/plan">계획 보기</a>') if submitted else '점수 검토를 마치면 누릅니다'}</span></div>
<div class="sub" style="margin-top:4px">확인 계획에 포함할 보류 단위 (체크를 풀면 계획에서 뺍니다):</div>{plan_pick}</form>
<div id="subbusy" hidden><div class="pbar"><i></i></div>
 <span class="sub">제출 중 — 판정을 기록하고 <b>확인 계획 문안</b>을 만듭니다. 보류 단위가 있으면 AI 1회, 10~30초 걸립니다. 이 화면을 닫지 마십시오.</span></div></div>

<section class="card">
 <header class="ch">
   <div class="tag">{e(a['case_number'])}</div>
   <h2>{e(a['official_name'] or a['target_program_id'])}(비NCS 이력 · 근거 분석)</h2>
   <p class="sub">필수능력단위 {len(units)}개 · {tot}시간 · 요소 {len(els)}개 · 제출 문서 {len(docs)}건</p>
 </header>
 <div class="kpis">
   <div class="kpi hl"><span>인정</span><b><span id="k-rec">{B['인정']}</span><i>h · <span id="k-recp">{B['인정'] / tot * 100:.0f}</span>%</i></b><em>{'0 없고 ' if req0 else ''}평균 {acc:.1f} 이상 · 요구시간 전체</em></div>
   <div class="kpi hl hold"><span>보류</span><b><span id="k-hold">{B['보류']}</span><i>h · <span id="k-holdp">{B['보류'] / tot * 100:.0f}</span>%</i></b><em>평균 {hold:.1f}~{acc:.1f} · 확인 계획 대상</em></div>
   <div class="kpi hl crit"><span>불인정</span><b><span id="k-rej">{B['불인정']}</span><i>h · <span id="k-rejp">{B['불인정'] / tot * 100:.0f}</span>%</i></b><em>{'0 이 있거나 ' if req0 else ''}평균 {hold:.1f} 미만 · 훈련 이수</em></div>
 </div>
 <div class="stackwrap"><div class="stack">
  <div class="sg good" style="width:{B['인정'] / tot * 100:.3f}%" id="sg-good" title="인정"></div>
  <div class="sg hold" style="width:{B['보류'] / tot * 100:.3f}%" id="sg-hold" title="보류"></div>
  <div class="sg crit" style="width:{B['불인정'] / tot * 100:.3f}%" id="sg-crit" title="불인정"></div></div>
  <div class="slab"><span class="good">인정 <span id="sl-good">{B['인정']}</span>h</span> · <span class="hold">보류 <span id="sl-hold">{B['보류']}</span>h</span> · <span class="crit">불인정 <span id="sl-crit">{B['불인정']}</span>h</span></div></div>

 <div class="tw"><table class="tp"><thead><tr><th>능력단위</th><th>내용 일치성</th><th>교육시간/요구시간</th><th>검증가능성</th><th>판정</th></tr></thead>
 <tbody>{urows}</tbody></table></div>
 <p class="sub" style="margin-top:6px">판정은 수행준거 점수로 정해집니다 — {unit_rule_text(rb, short=True)}. 아래에서 점수를 고치면 다시 계산됩니다.</p>

 <details class="tbl"><summary>제출 문서 {len(docs)}건</summary>
 <div class="tw"><table><thead><tr><th>등급</th><th>문서</th><th>종류</th></tr></thead><tbody>{drows}</tbody></table></div></details>
</section>

<section class="card"><header class="ch"><h2>수행준거별 점수(위원 판정 필요)</h2>
<p class="sub">2 = 직접 근거 있음 · 1 = 간접 근거만 · 0 = 근거 없음 또는 부정 진술. 위원이 누르면 위원 값이 우선합니다. 문서명을 누르면 원문이 열립니다.</p></header>
{items_html}</section>

<footer>
{param_table(params)}
<p style="margin-top:10px">심사번호 {e(a['case_number'])} · 기준 v{e(a['rubric_version'])} · 분석 모델 {e(a['model'])} · 계산 {(a['finished_at'] or datetime.now()):%Y-%m-%d %H:%M} · 최종 판정은 전문가 TF가 한다.</p>
</footer></div>
<aside id="dv"><div class="hd"><b id="dv-t">제출 문서</b><button id="dv-x" title="닫기 (Esc)">×</button></div>
<div class="tabs" id="dv-tabs"></div><input id="dv-q" placeholder="낱말로 찾기 (모든 문서)"><div class="body" id="dv-b"></div></aside>
<script>
(function(){{
 var AID={assessment_id}, RO={1 if readonly else 0}, TOT={tot}, ACC={acc}, HOLD={hold}, REQ0={1 if req0 else 0}, UNITS={_js(units_json)}, ELS={_js(ev_json)};
 var $=function(i){{return document.getElementById(i)}};
 var FR={_js(fr_json)}, DN={_js(dn_json)};
 var dv=$('dv'), dvB=$('dv-b'), dvQ=$('dv-q'), dvTabs=$('dv-tabs'), curDoc=null;
 function esc(s){{return String(s).replace(/[&<>"]/g,function(c){{return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]}})}}
 function dvRender(doc, hit){{
   curDoc=doc; dvQ.value='';
   dvTabs.querySelectorAll('button').forEach(function(b){{b.className=b.dataset.doc===doc?'on':''}});
   var d=DN.filter(function(x){{return x.doc===doc}})[0]; $('dv-t').textContent=d?d.name+' ('+d.grade+')':'제출 문서';
   dvB.innerHTML=FR.filter(function(f){{return f.doc===doc}}).map(function(f){{
     return '<p data-fid="'+f.fid+'"'+(f.fid===hit?' class="hit"':'')+'>'+esc(f.text)+'</p>'}}).join('');
   var h=dvB.querySelector('p.hit'); if(h) h.scrollIntoView({{block:'center'}}); else dvB.scrollTop=0;
 }}
 function dvSearch(q){{
   q=q.trim().toLowerCase(); if(!q){{ if(curDoc) dvRender(curDoc); return; }}
   dvTabs.querySelectorAll('button').forEach(function(b){{b.className=''}}); $('dv-t').textContent='찾기: '+q;
   var last=null, out='';
   FR.forEach(function(f){{ if(f.text.toLowerCase().indexOf(q)<0) return;
     if(f.doc!==last){{ out+='<div class="dn">'+esc(f.name)+' ('+f.grade+')</div>'; last=f.doc; }}
     out+='<p data-fid="'+f.fid+'">'+esc(f.text)+'</p>'; }});
   dvB.innerHTML=out||'<p>없음</p>'; dvB.scrollTop=0;
 }}
 var dvSrc=null;
 function dvOpen(doc, fid, src){{
   if(dv.className==='open' && dvSrc===src){{ dv.className=''; dvSrc=null; return; }}
   dvSrc=src; dv.className='open'; dvRender(doc, fid); }}
 dvTabs.innerHTML=DN.map(function(d){{return '<button data-doc="'+d.doc+'">'+esc(d.name)+' ('+d.grade+')</button>'}}).join('');
 dvTabs.addEventListener('click', function(ev){{ var b=ev.target.closest('button'); if(b) dvRender(b.dataset.doc); }});
 dvQ.addEventListener('input', function(){{ dvSearch(dvQ.value); }});
 $('dv-x').addEventListener('click', function(){{ dv.className=''; dvSrc=null; }});
 document.addEventListener('keydown', function(ev){{ if(ev.key==='Escape'){{ dv.className=''; dvSrc=null; }} }});
 document.querySelectorAll('a.fx').forEach(function(a){{ a.addEventListener('click', function(ev){{
   ev.preventDefault(); var fid=a.dataset.fid; dvOpen(fid?fid.slice(0,3):a.dataset.doc, fid||null, a); }}); }});

 // ── 수행준거 점수 — AI 값은 서버가 넣어 준 것(ELS[].pcs[].ai). 여기서는 위원 값(ov)만 얹고 단위 규칙을 적용한다.
 var byEid={{}}; ELS.forEach(function(x){{byEid[x.eid]=x; x.ov=x.ov||{{}};}});
 var byUnit={{}}; UNITS.forEach(function(u){{byUnit[u.code]=u}});
 function score(x, pc){{ return (pc.ref in x.ov) ? x.ov[pc.ref] : pc.ai; }}
 // coverage.unit_by_scores 와 같은 규칙: (REQ0 이면 0 이 있을 때 불인정) · 평균 ≥ACC 인정 · ≥HOLD 보류
 function unitCalc(u){{
   if(u.fixed) return {{v:u.fixed, n:0, nz:0, mean:0}};
   var n=0, sum=0, zero=0;
   u.els.forEach(function(e){{ var x=byEid[e]; if(!x) return; x.pcs.forEach(function(pc){{ var s_=score(x,pc); n++; sum+=s_; if(s_===0) zero++; }}); }});
   var mean=n?sum/n:0, v;
   if(!n||(REQ0&&zero)) v='불인정'; else if(mean>=ACC) v='인정'; else if(mean>=HOLD) v='보류'; else v='불인정';
   return {{v:v, n:n, nz:n-zero, mean:mean}};
 }}
 var VC={{'인정':['good','●'],'보류':['hold','◆'],'불인정':['crit','■']}};
 function paint(u, k){{
   ['v-','hv-'].forEach(function(p){{ var st=$(p+u.code); if(st){{ st.className='st '+VC[k.v][0]; st.innerHTML='<i>'+VC[k.v][1]+'</i>'+k.v; }} }});
   if(u.fixed) return;
   var band=k.mean>=ACC?'상':k.mean>=HOLD?'중':'하';
   var m=$('m-'+u.code); if(m){{ m.textContent=band; m.className='b '+({{'상':'good','중':'hold','하':'crit'}})[band]; }}
   var txt='수행준거 '+k.nz+'/'+k.n+' ≥1 · 평균 '+k.mean.toFixed(2);
   var mc=$('mc-'+u.code); if(mc) mc.textContent=txt;
   var h=$('h-'+u.code); if(h) h.textContent=txt;
   u.els.forEach(function(e){{ var x=byEid[e], ec=$('ec-'+e); if(x&&ec) ec.textContent=x.pcs.filter(function(pc){{return score(x,pc)>=1}}).length; }});
 }}
 function recalc(){{
   var B={{'인정':0,'보류':0,'불인정':0}};
   UNITS.forEach(function(u){{ var k=unitCalc(u); B[k.v]+=u.hours; paint(u,k); }});
   var pct=function(v){{return Math.round(v/TOT*100)}};
   $('k-rec').textContent=B['인정']; $('k-recp').textContent=pct(B['인정']);
   $('k-hold').textContent=B['보류']; $('k-holdp').textContent=pct(B['보류']);
   $('k-rej').textContent=B['불인정']; $('k-rejp').textContent=pct(B['불인정']);
   $('sg-good').style.width=(B['인정']/TOT*100)+'%'; $('sg-hold').style.width=(B['보류']/TOT*100)+'%'; $('sg-crit').style.width=(B['불인정']/TOT*100)+'%';
   $('sl-good').textContent=B['인정']; $('sl-hold').textContent=B['보류']; $('sl-crit').textContent=B['불인정'];
   // 확인 계획 단위 선택 — 보류 단위만 보인다
   var pick=$('plan-pick'); if(pick){{ var html=''; UNITS.forEach(function(u){{ if(unitCalc(u).v==='보류') html+='<label><input type="checkbox" name="plan_units" value="'+u.code+'" checked> '+esc(byUnit[u.code].name||u.code)+'</label>'; }}); if(pick.dataset.rendered!==html){{ pick.innerHTML=html; pick.dataset.rendered=html; }} }}
 }}
 UNITS.forEach(function(u){{ var tr=document.querySelector('tr[data-unit="'+u.code+'"] .unit'); u.name=tr?tr.childNodes[0].textContent:u.code; }});
 var canSave = !RO && location.protocol.indexOf('http')===0, queue=Promise.resolve();
 if(canSave) $('submit-f').style.display='flex';
 if(RO){{
   document.body.insertAdjacentHTML('afterbegin', '<div style="position:sticky;top:0;z-index:50;background:#fff4d6;color:#5a3d00;padding:8px 16px;font-size:13px;border-bottom:1px solid #e8c98a">열람 전용 화면 — 근거와 원문(문서명 클릭)은 볼 수 있지만 점수·제출은 되지 않습니다. 판정은 설문으로 냅니다.</div>');
 }}
 $('submit-f').addEventListener('submit', function(){{
   var b=$('submit-f').querySelector('button[type=submit]');
   b.disabled=true; b.textContent='제출 중…';
   $('subbusy').hidden=false;
 }});
 function note(msg, ok){{ $('save').textContent=msg; $('save').style.color= ok?'var(--good)':'var(--crit)'; }}
 function setRow(eid, ref, n, src){{
   var tr=$('pr-'+eid+'-'+ref); if(!tr) return;
   tr.className=n>=1?'on':'off';
   tr.querySelectorAll('.pcs button').forEach(function(b){{ b.className=(parseInt(b.dataset.n)===n?'on ':'')+'s'+b.dataset.n; }});
   var sb=tr.querySelector('.src'); if(sb){{ sb.className='src'+(src==='reviewer'?' rv':src==='rule'?' rule':''); sb.textContent=src==='reviewer'?'위원':src==='rule'?'기록':'AI'; }}
 }}
 function applyServer(resp){{
   // 서버가 다시 센 단위 판정으로 그린다 — 화면 계산과 어긋나면 서버가 맞다
   var u=byUnit[resp.unit_code]; if(!u||!resp.unit) return;
   var k={{v:resp.unit.verdict, n:resp.unit.n_total||0, nz:resp.unit.n_covered||0, mean:resp.unit.mean||0}};
   paint(u,k);
 }}
 document.querySelectorAll('.pcs button').forEach(function(b){{
   b.addEventListener('click', function(ev){{
     if(RO){{ ev.preventDefault(); note('열람 전용 화면 — 판정 입력은 설문으로', false); return; }}
     var eid=b.dataset.eid, ref=b.dataset.ref, n=parseInt(b.dataset.n), x=byEid[eid]; if(!x) return;
     var pc=x.pcs.filter(function(p){{return p.ref===ref}})[0]; if(!pc) return;
     if(n===pc.ai) delete x.ov[ref]; else x.ov[ref]=n;
     setRow(eid, ref, n, n===pc.ai?pc.src:'reviewer');
     recalc();
     if(!canSave){{ note('브라우저 계산만 (서버 없음 — 저장 안 됨)', false); return; }}
     note('저장 중…', true);
     queue=queue.then(function(){{
       return fetch('/assessments/'+AID+'/elements/'+encodeURIComponent(eid)+'/pc',
         {{method:'POST',headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{ref:ref, score:n, reviewer:null}})}})
        .then(function(r){{ if(!r.ok) throw new Error(r.status); return r.json(); }})
        .then(function(d){{ applyServer(d); note('저장됨', true); }})
        .catch(function(err){{ note('저장 실패 — '+err.message, false); }});
     }});
   }}, true);
 }});
 recalc();
}})();
</script></body></html>"""


def _legacy_element(u: dict, x: dict, marks: list, ksa_all: dict, cite, doc_by_key: dict) -> str:
    """구형(항목 단위) 요소 — 읽기 전용으로 보인다. 근거 분석을 다시 돌리면 신형이 된다."""
    p = x["payload"]
    eid = x["element_id"]
    ename = p.get("element_name") or eid
    ex = {m for m in marks if not m.startswith(MARK_PREFIXES)}
    added = {m[len("add:"):] for m in marks if m.startswith("add:")}
    refs = ksa_all.get((u["code"], _eno_(eid) or 0), [])
    by_ref: dict[str, list[dict]] = defaultdict(list)
    for ev in p.get("evidence") or []:
        if ev.get("ksa_ref") and ev.get("fids"):
            by_ref[ev["ksa_ref"]].append(ev)
    unc_note = {(uu.get("ref") if isinstance(uu, dict) else uu): (uu.get("note", "") if isinstance(uu, dict) else "")
                for uu in (p.get("uncovered_ksa") or [])}
    if not refs:
        refs = [(r, "") for r in list(by_ref) + [r for r in unc_note if r not in by_ref]]
    n_cov, _, _ = element_coverage(p, marks, [r for r, _ in refs])
    rows = ""
    for ref, ktxt in refs:
        evs = by_ref.get(ref, [])
        fit_of = lambda ev: ev.get("fit") or "직접"   # noqa: E731
        direct = [ev for ev in evs if fit_of(ev) == "직접"]
        src = "".join(
            f"<div><small><a class='fx' data-fid='{e(ev['fids'][0])}'>{e(_doc_name(doc_by_key.get(ev['fids'][0][:3], {}).get('file_path'), ev['fids'][0][:3]))}"
            f"<span class='g{e(ev.get('grade') or '')}'>{e(ev.get('grade') or '')}</span></a>"
            f"{'' if fit_of(ev) == '직접' else f' <span class=&quot;ft {fit_class(fit_of(ev))}&quot;>{e(fit_of(ev))}{'' if fit_of(ev) in FIT_CLS else ' ⚠ 알 수 없는 값'}</span>'}</small>"
            f"<blockquote>{e(ev.get('quote', ''))}</blockquote><small style='color:var(--tm)'>{cite(ev.get('why', ''))}</small></div>"
            for ev in evs).replace("&quot;", '"')
        live = [ev for ev in direct if any(f not in ex for f in ev["fids"])]
        on = bool(live) or ref in added
        label = "인정" if live else ("위원 인정" if on else ("제외됨" if direct else "불인정"))
        body = src if evs else f"<span class='why'>{cite(unc_note.get(ref, ''))}</span>"
        rows += f"""<tr class="{'on' if on else 'off'}">
 <td><span class="st {'good' if on else ('crit' if direct else 'none')}"><i>{'●' if on else '○'}</i>{label}</span></td>
 <td>{e(ref[:2])} {e(ref[2:])} <small>{e(ktxt)}</small></td>
 <td>{body}</td></tr>"""
    return f"""<details class="sub2"><summary><span class="lv">요소 · 옛 형식</span><b>{e(ename)}</b> <small>— 항목 {n_cov}/{len(refs)} 인정 (읽기 전용)</small></summary>
<div class="tw"><table class="it"><thead><tr><th style="width:80px">판단</th><th style="width:34%">항목</th><th>근거 (문서 · 원문 · AI 이유)</th></tr></thead><tbody>{rows}</tbody></table></div></details>"""
