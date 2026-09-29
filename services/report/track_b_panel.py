"""Track B 위원 페이지 — 한 지원자 = 한 쪽 (2026-09-23, 1~3차 TF 반영).

보이는 순서: 0 머리(사례·문서) → 1 카드 3장(인정·보류·불인정 시간) → 2 능력단위 3점 정량표
→ 3 항목별 인정 여부(AI 판단을 위원이 뒤집는다 → 능력단위 판정이 바뀐다) → 4 판정 파라미터.

능력단위 판정은 위원 판정 라디오가 아니라 **인정된 항목의 비율**에서 나온다.
항목 인정 = AI 가 근거를 붙였고 위원이 빼지 않은 것 + 근거가 없어도 위원이 직접 인정한 것.
방법론 코드(R0~R5·fid·KSA ref)는 화면에 쓰지 않는다. 근거 보고서·검토 화면은 감사·상세용으로 남는다.
위원의 수정은 브라우저에서 즉시 재계산하고, 서버가 있으면 요소별 검토 API(excluded_evidence)에 저장한다.
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
from services.report._shared import (STEP_CSS, TRACK_CSS, param_table, pending,
                                     step_head, step_nav, track_chip)
from services.report.doc_viewer import js_literal
from services.report.track_a_report import CSS as BASE_CSS
from services.review.coverage import ADD, Q, S, element_coverage, three_point, unit_by_coverage
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
    체크·제출은 못 하게 한다(판정 입력은 진행자 화면에서 다수결로 넣는다). 체크박스는 보이되 눌리지 않는다."""
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
    # 항목(지식·기술·태도) 전체 — catalog 기준. (unit, element_no) → [(ref, text)]
    ksa_all: dict[tuple, list[tuple[str, str]]] = defaultdict(list)
    _seen: set[tuple] = set()
    for r in s.execute(text("""
        SELECT unit_code, element_no, ksa_type, ksa_no, ksa_text FROM catalog_ncs_ksa
        WHERE unit_code = ANY(:u) ORDER BY unit_code, element_no, ksa_type, ksa_no, pc_no"""), {"u": list(units_req)}):
        k = (r[0], r[1], f"{r[2]}{r[3]}")
        if k in _seen:          # 같은 항목이 수행준거마다 반복된다 — 한 번만
            continue
        _seen.add(k)
        ksa_all[(r[0], r[1])].append((k[2], r[4]))
    doc_by_key = {d["doc_key"]: d for d in docs}
    frag_by_fid = {f["fid"]: f for f in frags}
    submitted = (s.execute(text("SELECT progress->>'panel_submitted_at' FROM assessment WHERE id=:i"),
                           {"i": assessment_id}).scalar() or "").replace("T", " ")[:16]
    cite = lambda s_: _cite(s_, frag_by_fid, doc_by_key)   # noqa: E731
    tot = a["total_hours"] or sum(v[1] for v in units_req.values()) or 1
    axis = time_extract(frags)
    hi, lo = rb.training_hours.get("adjustment_floor", 0.5), rb.training_hours.get("hold_floor", 0.3)

    # ── 요소를 능력단위로 묶고 판정 계산 ──
    by_unit: dict[str, list[dict]] = defaultdict(list)
    for x in els:
        by_unit[x["element_id"].split("_", 1)[0]].append(x)
    units = []
    for uc, (uname, req) in units_req.items():
        xs = by_unit.get(uc, [])
        marks_of = {x["element_id"]: list((reviews.get(x["element_id"]) or {}).get("excluded_evidence") or []) for x in xs}
        marks = [m for v in marks_of.values() for m in v]
        refs_of = {x["element_id"]: [r for r, _ in ksa_all.get((uc, _eno(x["element_id"])), [])] for x in xs}
        cov = unit_by_coverage([(x["element_id"], x["payload"]) for x in xs], rb, marks_of, refs_of)
        tp = three_point([x["payload"] for x in xs], rb, [m for m in marks if not m.startswith((ADD, Q, S))])
        tb, tb_note = time_band(tot, axis, rb)
        units.append({"code": uc, "name": uname, "hours": req, "els": xs, "tp": tp, "cov": cov,
                      "time": (tb, tb_note), "verdict": cov["verdict"]})
    B = {"인정": 0, "보류": 0, "불인정": 0}
    for u in units:
        B[u["verdict"]] += u["hours"]

    # ── 0 문서 표 ──
    drows = "".join(
        f"<tr><td><span class='g{e(d['grade'])}'>{e(d['grade'])}</span></td><td><a class='fx' data-doc='{e(d['doc_key'])}'>{e(_doc_name(d['file_path'], d['doc_key']))}</a></td>"
        f"<td>{e(d['doc_type'])}{' — <b>종류 지정 필요</b>' if d['doc_type'] == '기타' else ''}</td></tr>" for d in docs)

    # ── 2 단위 표 (위원 판정 라디오 없음 — 판정은 항목 인정에서 나온다) ──
    urows = ""
    for u in units:
        tp, (tb, tb_note), cov = u["tp"], u["time"], u["cov"]
        vc, vi = VERDICT_CLS[u["verdict"]]
        band = "상" if cov["ratio"] >= hi else "중" if cov["ratio"] >= lo else "하"
        els_ko = " · ".join(BUCKET_KO[b] for b in tp["buckets"]) if tp["buckets"] else "요소 없음"
        urows += f"""<tr data-unit="{e(u['code'])}">
 <td class="unit">{e(u['name'])}<small>{u['hours']}h · 요소 {len(u['els'])}개 · AI 참고: {e(els_ko)}</small></td>
 <td><span class="b {BAND_CLS[band]}" id="m-{e(u['code'])}">{band}</span> <small id="mc-{e(u['code'])}">요소 {cov['n_covered']}/{cov['n_total']} 인정 ({cov['ratio']:.0%})</small></td>
 <td><span class="b {BAND_CLS[tb]}">{tb}</span> <small>{e(tb_note)}</small></td>
 <td><span class="b {BAND_CLS[tp['verify']]}">{tp['verify']}</span> <small>최고 등급 {e(tp['best_grade'] or '없음')}</small></td>
 <td><span class="st {vc}" id="v-{e(u['code'])}"><i>{vi}</i>{u['verdict']}</span></td></tr>"""

    # ── 4 항목별 인정 여부 — 능력단위 › 요소 › 항목. AI 판단을 위원이 뒤집는다 ──
    ev_json = []
    items_html = ""
    for u in units:
        vc, vi = VERDICT_CLS[u["verdict"]]
        cov = u["cov"]
        head = (f"<span class='lv'>능력단위</span><b>{e(u['name'])}</b> — {u['hours']}h · 요소 <span id='h-{e(u['code'])}'>{cov['n_covered']}/{cov['n_total']}</span> 인정 · "
                f"<span class='st {vc}' id='hv-{e(u['code'])}' style='display:inline-flex'><i>{vi}</i>{u['verdict']}</span>")
        inner = ""
        for x in u["els"]:
            p = x["payload"]
            eid = x["element_id"]
            ename = p.get("element_name") or eid
            marks = set((reviews.get(eid) or {}).get("excluded_evidence") or [])
            ex = {m for m in marks if not m.startswith((ADD, Q, S))}
            added = {m[len(ADD):] for m in marks if m.startswith(ADD)}
            refs = ksa_all.get((u["code"], _eno(eid)), [])
            by_ref: dict[str, list[dict]] = defaultdict(list)
            for ev in p.get("evidence") or []:
                if ev.get("ksa_ref") and ev.get("fids"):
                    by_ref[ev["ksa_ref"]].append(ev)
            unc_note = {(uu.get("ref") if isinstance(uu, dict) else uu): (uu.get("note", "") if isinstance(uu, dict) else "")
                        for uu in (p.get("uncovered_ksa") or [])}
            if not refs:   # catalog 에 없으면 근거·미확인 항목으로
                refs = [(r, "") for r in list(by_ref) + [r for r in unc_note if r not in by_ref]]
            c_ai = len([r for r, _ in refs if by_ref.get(r)])
            n_cov, _, _ = element_coverage(p, marks, [r for r, _ in refs])
            rows = ""
            for ref, ktxt in refs:
                evs = by_ref.get(ref, [])
                kind = ref[:2]
                fit_of = lambda ev: ev.get("fit") or "직접"   # noqa: E731  (옛 결과는 fit 없음 → 직접)
                direct = [ev for ev in evs if fit_of(ev) == "직접"]
                src = "".join(
                    f"<div><small><a class='fx' data-fid='{e(ev['fids'][0])}'>{e(_doc_name(doc_by_key.get(ev['fids'][0][:3], {}).get('file_path'), ev['fids'][0][:3]))}"
                    f"<span class='g{e(ev.get('grade') or '')}'>{e(ev.get('grade') or '')}</span></a>"
                    f"{'' if fit_of(ev) == '직접' else f' <span class=&quot;ft {fit_class(fit_of(ev))}&quot;>{e(fit_of(ev))}{'' if fit_of(ev) in FIT_CLS else ' ⚠ 알 수 없는 값'}</span>'}</small>"
                    f"<blockquote>{e(ev.get('quote', ''))}</blockquote><small style='color:var(--tm)'>{cite(ev.get('why', ''))}</small></div>"
                    for ev in evs).replace("&quot;", '"')
                if direct:
                    # 직접 근거 있음 → 인정. 위원은 「근거 부적합」으로 뺄 수 있다
                    live = [ev for ev in direct if any(f not in ex for f in ev["fids"])]
                    fids = sorted({f for ev in direct for f in ev["fids"]})
                    on = bool(live)
                    rows += f"""<tr class="{'on' if on else 'off'}">
 <td><span class="st {'good' if on else 'crit'}"><i>{'●' if on else '○'}</i>{'인정' if on else '제외됨'}</span></td>
 <td>{e(kind)} {e(ref[2:])} <small>{e(ktxt)}</small></td>
 <td>{src}</td>
 <td class="c" style="white-space:nowrap"><label><input type="checkbox" data-kind="ex" data-eid="{e(eid)}" data-ref="{e(ref)}" data-fids="{e(','.join(fids))}" {'checked' if not on else ''}> 근거 부적합</label></td></tr>"""
                else:
                    note_ = unc_note.get(ref, "")
                    # 간접 근거만 있으면 불인정이되 위원이 보고 인정할 수 있다. 부정 진술만 있거나 근거가 없으면 볼 것이 없다 — 체크란 없음
                    reviewable = any(fit_of(ev) == "간접" for ev in evs)
                    on = reviewable and ref in added
                    ctl = (f"""<label><input type="checkbox" data-kind="add" data-eid="{e(eid)}" data-ref="{e(ref)}" {'checked' if on else ''}> 위원 인정</label>"""
                           if reviewable else "")
                    body = src if evs else f"<span class='why'>{cite(note_)}</span>"
                    rows += f"""<tr class="{'on' if on else 'off'}">
 <td><span class="st {'good' if on else 'none'}"><i>{'●' if on else '○'}</i>{'위원 인정' if on else '불인정'}</span></td>
 <td>{e(kind)} {e(ref[2:])} <small>{e(ktxt)}</small></td>
 <td>{body}</td>
 <td class="c" style="white-space:nowrap">{ctl}</td></tr>"""
            # 「AI 몇 개」는 지웠다(2026-09-24) — 위원이 볼 것은 **지금 몇 개가 인정돼
            # 있나**이지, AI 가 처음에 몇 개를 붙였나가 아니다. 그 수가 옆에 있으면
            # 위원의 판단을 AI 쪽으로 끌어당긴다.
            inner += f"""<details class="sub2" {'open' if c_ai else ''}><summary><span class="lv">요소</span><b>{e(ename)}</b> <small>— 항목 <span id="ec-{e(eid)}">{n_cov}</span>/{len(refs)} 인정</small></summary>
<div class="tw"><table class="it"><thead><tr><th style="width:80px">판단</th><th style="width:34%">항목</th><th>근거 (문서 · 원문 · AI 이유)</th><th style="width:120px">위원 수정</th></tr></thead><tbody>{rows}</tbody></table></div></details>"""
            ev_json.append({"eid": eid, "unit": u["code"], "refs": [r for r, _ in refs],
                            "ev": [{"ref": ev.get("ksa_ref"), "fids": ev.get("fids") or []} for ev in (p.get("evidence") or []) if (ev.get("fit") or "직접") == "직접"],
                            "marks": sorted(marks)})
        items_html += f"""<details class="tbl" {'open' if u['verdict'] != '불인정' else ''}><summary>{head}</summary>{inner or "<p class='sub'>요소 정보 없음</p>"}</details>"""

    # ── 5 파라미터 ──
    r1 = rb.recommendations["R1"]["requires"]
    r6 = rb.rules.get("R6_recency", {})
    params = [
        ("항목을 누가 인정하나",
         "AI 가 먼저 근거를 붙이고, 위원이 「근거 부적합」으로 빼거나 「위원 인정」으로 더합니다. "
         "AI 가 정하는 것은 1차이고 마지막은 위원입니다",
         "3차 TF 이후 협의 — 깎아 가는 방식", False),
        ("근거 적합도",
         "직접(그 일을 했다는 것을 그대로 보여 줌) → 인정 · "
         "간접(관련은 있으나 증명은 못 함) → 인정 안 됨, 위원이 보고 인정할 수 있음 · "
         "부정(못 한다·안 해봤다는 본인 진술) → 인정 안 됨",
         "2026-09-24 결정", False),
        ("요소 인정", f"한 요소 안에서 인정된 항목이 {hi:.0%} 이상이면 그 요소를 인정합니다",
         "2026-09-24 결정 — Track A 인정선과 같은 값", True),
        ("능력단위 판정",
         f"인정된 요소가 {hi:.0%} 이상이면 인정 · {lo:.0%} 이상이면 보류 · 그 미만은 불인정",
         "2026-09-24 결정 — 예전에는 요소별 비율의 평균이었습니다", True),
        ("인정되면 몇 시간",
         "그 능력단위의 요구시간 전체. 요소·항목에는 시간이 매겨져 있지 않아 "
         "충족 여부로만 판단합니다",
         "NCS 원자료 확인 · 설계안", False),
        ("보류 단위는 어떻게",
         "인정되지 못한 요소만 시험·면접·외부평가로 확인합니다. 이미 인정된 요소는 확인하지 않습니다",
         "2026-09-24 설계", True),
        ("실기", "RPL 단계에서는 보지 않고 외부평가에 맡깁니다",
         "3차 TF", pending(rb, "track_b.practical_to_external")),
        ("문서 등급",
         "A 공적 증빙 · B 기관 발급 · C 산출물·기록 · D 제3자 진술 · E 본인 진술 "
         "(정부인정 사업주자격증과 직무능력인정서는 A)",
         "증거평가기준 · 3차 TF", False),
        ("자료의 최신성",
         f"{r6.get('years', {}).get('default', 5)}년까지 인정 (전기·전자·정보통신은 {r6.get('years', {}).get('fast_changing', 3)}년)",
         "증거평가기준", pending(rb, "rules.R6_recency")),
        ("교육시간 / 요구시간",
         "문서에서 읽은 교육시간을 종목 총 요구시간과 견준 참고값입니다. "
         "판정에는 쓰지 않습니다",
         "표시용 — 시간은 Track A 가 셉니다", True),
    ]


    units_json = [{"code": u["code"], "hours": u["hours"], "els": [x["element_id"] for x in u["els"]]} for u in units]

    fr_json = [{"fid": f["fid"], "doc": f["doc_key"], "name": _doc_name(doc_by_key.get(f["doc_key"], {}).get("file_path"), f["doc_key"]),
                "grade": f["grade"], "text": f["text"]} for f in sorted(frags, key=lambda f: (f["doc_key"], _fno(f["fid"])))]
    dn_json = [{"doc": d["doc_key"], "name": _doc_name(d["file_path"], d["doc_key"]), "grade": d["grade"]} for d in docs]

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
<div style="margin:0 0 10px;display:flex;gap:12px;align-items:center;flex-wrap:wrap"><span id="save"></span>
<form method="post" action="/assessments/{assessment_id}/panel/submit" id="submit-f" style="margin:0;display:none">
<button type="submit" class="go">제출 → 확인 계획</button>
<span class="sub" style="margin-left:8px">{('마지막 제출 ' + e(submitted) + ' · <a href="/assessments/' + str(assessment_id) + '/plan">계획 보기</a>') if submitted else '항목 검토를 마치면 누릅니다'}</span></form>
<div id="subbusy" hidden><div class="pbar"><i></i></div>
 <span class="sub">제출 중 — 판정을 기록하고 <b>확인 계획 문안</b>을 만듭니다. AI 1회, 10~30초 걸립니다. 이 화면을 닫지 마십시오.</span></div></div>

<section class="card">
 <header class="ch">
   <div class="tag">{e(a['case_number'])}</div>
   <h2>{e(a['official_name'] or a['target_program_id'])}(비NCS 이력 · 근거 분석)</h2>
   <p class="sub">필수능력단위 {len(units)}개 · {tot}시간 · 요소 {len(els)}개 · 제출 문서 {len(docs)}건</p>
 </header>
 <div class="kpis">
   <div class="kpi hl"><span>인정</span><b><span id="k-rec">{B['인정']}</span><i>h · <span id="k-recp">{B['인정'] / tot * 100:.0f}</span>%</i></b><em>인정 항목 50% 이상인 단위 · 요구시간 전체</em></div>
   <div class="kpi hl hold"><span>보류</span><b><span id="k-hold">{B['보류']}</span><i>h · <span id="k-holdp">{B['보류'] / tot * 100:.0f}</span>%</i></b><em>30~50% · 아래 항목별 인정으로 판단</em></div>
   <div class="kpi hl crit"><span>불인정</span><b><span id="k-rej">{B['불인정']}</span><i>h · <span id="k-rejp">{B['불인정'] / tot * 100:.0f}</span>%</i></b><em>30% 미만 · 훈련 이수</em></div>
 </div>
 <div class="stackwrap"><div class="stack">
  <div class="sg good" style="width:{B['인정'] / tot * 100:.3f}%" id="sg-good" title="인정"></div>
  <div class="sg hold" style="width:{B['보류'] / tot * 100:.3f}%" id="sg-hold" title="보류"></div>
  <div class="sg crit" style="width:{B['불인정'] / tot * 100:.3f}%" id="sg-crit" title="불인정"></div></div>
  <div class="slab"><span class="good">인정 <span id="sl-good">{B['인정']}</span>h</span> · <span class="hold">보류 <span id="sl-hold">{B['보류']}</span>h</span> · <span class="crit">불인정 <span id="sl-crit">{B['불인정']}</span>h</span></div></div>

 <div class="tw"><table class="tp"><thead><tr><th>능력단위</th><th>내용 일치성</th><th>교육시간/요구시간</th><th>검증가능성</th><th>판정</th></tr></thead>
 <tbody>{urows}</tbody></table></div>
 <p class="sub" style="margin-top:6px">판정은 인정된 항목의 비율로 정해집니다(50% 이상 인정, 30% 이상 보류). 아래에서 근거를 빼거나 항목을 직접 인정하면 다시 계산됩니다.</p>

 <details class="tbl"><summary>제출 문서 {len(docs)}건</summary>
 <div class="tw"><table><thead><tr><th>등급</th><th>문서</th><th>종류</th></tr></thead><tbody>{drows}</tbody></table></div></details>
</section>

<section class="card"><header class="ch"><h2>항목별 인정 여부(위원 판정 필요)</h2></header>
{items_html}</section>

<footer>
{param_table(params)}
<p style="margin-top:10px">심사번호 {e(a['case_number'])} · 기준 v{e(a['rubric_version'])} · 분석 모델 {e(a['model'])} · 계산 {(a['finished_at'] or datetime.now()):%Y-%m-%d %H:%M} · 최종 판정은 전문가 TF가 한다.</p>
</footer></div>
<aside id="dv"><div class="hd"><b id="dv-t">제출 문서</b><button id="dv-x" title="닫기 (Esc)">×</button></div>
<div class="tabs" id="dv-tabs"></div><input id="dv-q" placeholder="낱말로 찾기 (모든 문서)"><div class="body" id="dv-b"></div></aside>
<script>
(function(){{
 var AID={assessment_id}, RO={1 if readonly else 0}, TOT={tot}, HI={hi}, LO={lo}, UNITS={_js(units_json)}, ELS={_js(ev_json)};
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
 var byEid={{}}; ELS.forEach(function(x){{byEid[x.eid]=x; x.m={{}}; x.marks.forEach(function(k){{x.m[k]=1}})}});
 var byUnit={{}}; UNITS.forEach(function(u){{byUnit[u.code]=u}});
 function cov(x){{
   var covd={{}}; x.ev.forEach(function(ev){{ if(!ev.ref) return; if(ev.fids.some(function(f){{return !x.m[f]}})) covd[ev.ref]=1; }});
   x.refs.forEach(function(r){{ if(x.m['add:'+r]) covd[r]=1; }});
   var t=x.refs.length, c=Object.keys(covd).filter(function(r){{return x.refs.indexOf(r)>=0}}).length;
   return {{c:c,t:t,ratio:t?c/t:0}};
 }}
 // 두 단계 문턱 — services/review/coverage.py unit_by_coverage 와 같은 규칙.
 // ① 요소: 항목 인정 비율 ≥ HI → 요소 인정  ② 단위: 인정 요소 비율 ≥ HI 인정 · ≥ LO 보류 · 미만 불인정
 function unitCalc(u){{
   var ok=0,t=u.els.length; u.els.forEach(function(e){{var k=cov(byEid[e]); if(k.t&&k.ratio>=HI) ok++;}});
   var ratio=t?ok/t:0;
   var v=(t&&ratio>=HI)?'인정':ratio>=LO?'보류':'불인정';
   return {{c:ok,t:t,ratio:ratio,v:v}};
 }}
 var VC={{'인정':['good','●'],'보류':['hold','◆'],'불인정':['crit','■']}};
 function recalc(){{
   var B={{'인정':0,'보류':0,'불인정':0}};
   UNITS.forEach(function(u){{
     var k=unitCalc(u); B[k.v]+=u.hours;
     ['v-','hv-'].forEach(function(p){{ var st=$(p+u.code); if(st){{ st.className='st '+VC[k.v][0]; st.innerHTML='<i>'+VC[k.v][1]+'</i>'+k.v; }} }});
     var band=k.ratio>=HI?'상':k.ratio>=LO?'중':'하';
     var m=$('m-'+u.code); if(m){{ m.textContent=band; m.className='b '+({{'상':'good','중':'hold','하':'crit'}})[band]; }}
     var mc=$('mc-'+u.code); if(mc) mc.textContent='요소 '+k.c+'/'+k.t+' 인정 ('+Math.round(k.ratio*100)+'%)';
     var h=$('h-'+u.code); if(h) h.textContent=k.c+'/'+k.t;
     u.els.forEach(function(e){{ var ec=$('ec-'+e); if(ec) ec.textContent=cov(byEid[e]).c; }});
   }});
   var pct=function(v){{return Math.round(v/TOT*100)}};
   $('k-rec').textContent=B['인정']; $('k-recp').textContent=pct(B['인정']);
   $('k-hold').textContent=B['보류']; $('k-holdp').textContent=pct(B['보류']);
   $('k-rej').textContent=B['불인정']; $('k-rejp').textContent=pct(B['불인정']);
   $('sg-good').style.width=(B['인정']/TOT*100)+'%'; $('sg-hold').style.width=(B['보류']/TOT*100)+'%'; $('sg-crit').style.width=(B['불인정']/TOT*100)+'%';
   $('sl-good').textContent=B['인정']; $('sl-hold').textContent=B['보류']; $('sl-crit').textContent=B['불인정'];
 }}
 var canSave = !RO && location.protocol.indexOf('http')===0, queue=Promise.resolve();
 if(canSave) $('submit-f').style.display='inline-flex';
 if(RO){{
   // 열람 전용: 체크박스는 그대로 보이되 클릭이 상태를 바꾸지 못하게 capture 단계에서 막는다
   document.querySelectorAll('table.it input[type=checkbox]').forEach(function(cb){{
     cb.addEventListener('click', function(ev){{ ev.preventDefault(); note('열람 전용 화면 — 판정 입력은 설문으로', false); }}, true);
     cb.title='열람 전용';
   }});
   document.body.insertAdjacentHTML('afterbegin', '<div style="position:sticky;top:0;z-index:50;background:#fff4d6;color:#5a3d00;padding:8px 16px;font-size:13px;border-bottom:1px solid #e8c98a">열람 전용 화면 — 근거와 원문(문서명 클릭)은 볼 수 있지만 체크·제출은 되지 않습니다. 판정은 설문으로 냅니다.</div>');
 }}
 // 제출은 AI 1회를 부른다(10~30초). 아무 표시가 없으면 「멈췄다·에러났다」로 읽힌다.
 // 폼은 그대로 보내고 화면만 「도는 중」으로 바꾼다.
 $('submit-f').addEventListener('submit', function(){{
   var b=$('submit-f').querySelector('button');
   b.disabled=true; b.textContent='제출 중…';
   $('subbusy').hidden=false;
 }});
 function note(msg, ok){{ $('save').textContent=msg; $('save').style.color= ok?'var(--good)':'var(--crit)'; }}
 function saveEl(eid){{
   var x=byEid[eid]; if(!x) return;
   if(!canSave){{ note('브라우저 계산만 (서버 없음 — 저장 안 됨)', false); return; }}
   note('저장 중…', true);
   var unit=byUnit[x.unit]; var v=unit?unitCalc(unit).v:'보류';
   queue=queue.then(function(){{
     return fetch('/assessments/'+AID+'/elements/'+encodeURIComponent(eid)+'/review',
       {{method:'POST',headers:{{'Content-Type':'application/json'}},
         body:JSON.stringify({{decision:v, reviewer:null, excluded_evidence:Object.keys(x.m)}})}})
      .then(function(r){{ if(!r.ok) throw new Error(r.status); note('저장됨', true); }})
      .catch(function(err){{ note('저장 실패 — '+err.message, false); }});
   }});
 }}
 document.querySelectorAll('table.it input[type=checkbox]').forEach(function(cb){{
   cb.addEventListener('change', function(){{
     var x=byEid[cb.dataset.eid]; if(!x) return;
     var tr=cb.closest('tr'), st=tr.querySelector('.st');
     if(cb.dataset.kind==='ex'){{
       cb.dataset.fids.split(',').forEach(function(f){{ if(cb.checked) x.m[f]=1; else delete x.m[f]; }});
       tr.className=cb.checked?'off':'on'; st.className='st '+(cb.checked?'crit':'good'); st.innerHTML='<i>'+(cb.checked?'○':'●')+'</i>'+(cb.checked?'제외됨':'인정');
     }} else {{
       if(cb.checked) x.m['add:'+cb.dataset.ref]=1; else delete x.m['add:'+cb.dataset.ref];
       tr.className=cb.checked?'on':'off'; st.className='st '+(cb.checked?'good':'none'); st.innerHTML='<i>'+(cb.checked?'●':'○')+'</i>'+(cb.checked?'위원 인정':'불인정');
     }}
     recalc(); saveEl(x.eid);
   }});
 }});
 recalc();
}})();
</script></body></html>"""
