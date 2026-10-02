"""면제 결과 — 무엇이 얼마나 인정됐고, 무슨 훈련이 남았나.

심사의 끝에 지원자·기관이 보는 한 장이다. 「인정 시간」은 곧 **훈련 면제 시간**
이므로, 단위마다 그 시간이 어디서 왔는지(기록이냐 위원 판단이냐)를 밝힌다.

셈은 `services/review/unit_hours.py` 것을 그대로 쓴다 — 여기서 다시 세면
위원 페이지와 갈라진다.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from krpl_core.config import get_rubric
from services.report._shared import STEP_CSS, TRACK_CSS, step_head, step_nav, track_chip, unit_count_text
from services.report.layout import e
from services.report.track_a_report import CSS
from services.review.coverage import unit_verdicts
from services.review.unit_hours import evidence_aid, unit_gaps

FULL = ("완전충족", "조정범위내")

EX_CSS = """
.ex-sum{display:flex;gap:18px;flex-wrap:wrap;margin:12px 0 16px}
.ex-sum div{border:1px solid var(--bd);border-radius:10px;padding:10px 16px;min-width:150px}
.ex-sum span{display:block;font-size:12px;color:var(--tm)}
.ex-sum b{font-size:22px}
.ex-tbl td,.ex-tbl th{vertical-align:top}
.ex-tbl .src{font-size:11.5px;color:var(--tm)}
.ex-tbl tr.none td{color:var(--tm)}
.ex-bar{display:flex;height:16px;border-radius:8px;overflow:hidden;border:1px solid var(--bd);margin:4px 0 14px}
.ex-bar i{display:block}
.ex-bar .r{background:#16a765}
.ex-bar .x{background:#4a86e8}
.ex-bar .t{background:#e6e6e6}
.decide .drow{display:flex;gap:18px;flex-wrap:wrap;align-items:center;margin:0 0 10px}
.decide label{font-size:13px}
.decide select,.decide input,.decide textarea{font:inherit;font-size:13px;padding:5px 8px;
 border:1px solid var(--bd);border-radius:6px;margin-left:6px}
.decide .dfull{display:block}
.decide .dfull textarea{display:block;width:100%;margin:4px 0 0}
.decide .one{margin:0 0 4px;font-size:14px}
.decide #dnote{font-size:12px;color:var(--tm)}
.dim{color:var(--tm)}
"""


def render_exemption(s: Session, assessment_id: int) -> str:
    """면제 결과 — 무엇이 얼마나 면제되고 훈련이 얼마나 남았나.

    트랙에 따라 합산 출처가 다르다. **셈을 새로 만들지 않고** 각 트랙이 이미
    쓰는 함수를 읽기만 한다.

        Track A   unit_hours.unit_gaps()      이수 + 위원 인정 → 50% 게이트
        Track B   coverage.unit_verdicts()    항목 → 요소 → 능력단위 (같은 문턱값)

    두 경우 모두 **인정된 단위는 요구시간 전체**가 면제된다.
    """
    a = s.execute(text("""
        SELECT a.id, a.kind, a.submission_id, a.rubric_version, a.finished_at,
               s.case_number, s.target_program_id, s.track, p.official_name, p.total_hours
        FROM assessment a JOIN submission s ON s.id=a.submission_id
        LEFT JOIN catalog_wsd_program p ON p.program_id=s.target_program_id
        WHERE a.id=:i"""), {"i": assessment_id}).mappings().one()
    sid = a["submission_id"]
    is_b = (a["track"] or "A").upper() == "B"
    ev_aid = evidence_aid(s, sid)
    time_aid = s.execute(text("""SELECT id FROM assessment WHERE submission_id=:i
        AND kind='time' ORDER BY id DESC LIMIT 1"""), {"i": sid}).scalar()

    # 단위 목록은 **종목의 필수 능력단위**에서 온다. 기록 확인 판정의 요소에서
    # 가져오면 Track B 처럼 기록 확인을 돌리지 않는 건은 표가 통째로 빈다.
    req = [dict(r) for r in s.execute(text("""
        SELECT unit_code, COALESCE(unit_name, unit_code) AS unit_name, required_hours
        FROM catalog_wsd_required WHERE program_id=:p
        ORDER BY required_hours DESC, unit_code"""),
        {"p": a["target_program_id"]}).mappings()]
    tot = a["total_hours"] or sum(x["required_hours"] for x in req) or 1

    # 기록 확인 결과는 있을 때만 읽는다.
    rec_of = {r[0]: (r[1], r[2]) for r in s.execute(text("""
        SELECT element_id, evidence_level, payload FROM assessment_element
        WHERE assessment_id=:i"""), {"i": time_aid})} if time_aid else {}

    gap_by_code = ({} if is_b or not time_aid else
                   {g.unit_code: g for g in unit_gaps(s, time_aid)})
    b_by_code = {u["code"]: u for u in unit_verdicts(s, ev_aid)} if (is_b and ev_aid) else {}
    has_ev = ev_aid is not None
    has_plan = bool(ev_aid) and bool(s.execute(text(
        "SELECT 1 FROM artifact WHERE assessment_id=:a AND stage='plan' LIMIT 1"),
        {"a": ev_aid}).first())

    rows, ex_full, ex_part, rest = "", 0, 0, 0
    n_full = n_part = 0
    for u in req:
        code, req_h = u["unit_code"], u["required_hours"]
        v, p = rec_of.get(code, (None, {}))
        if is_b:
            # Track B 는 기록이 아니라 항목 근거로 판정한다.
            b = b_by_code.get(code)
            if b is None:
                hours, why = 0, "근거 분석에 이 단위가 없습니다 — 훈련 필요"
            elif b["verdict"] == "인정":
                hours = req_h
                why = f"{unit_count_text(b)} → 인정, 요구시간 전체 면제"
            else:
                hours = 0
                why = f"{unit_count_text(b)} — {b['verdict']}"
            ex_part += hours
            n_part += 1 if hours else 0
        elif v in FULL:
            hours, why = req_h, f"이수 기록 {p.get('completed_hours') or 0}h — 요구시간 전체 면제"
            ex_full += hours
            n_full += 1
        else:
            # 면제는 합산이 아니라 게이트다 — 인정시간이 요구의 50% 이상이면 요구시간 전체.
            g = gap_by_code.get(code)
            hours = g.credited if g else 0
            if g is None:
                why = "인정 근거 없음 — 훈련 필요"
            elif g.passes:
                why = (f"이수 {g.record}h + 위원 인정 {g.granted}h = {g.counted}h "
                       f"({g.ratio_final:.0%}) → 인정선 통과, 요구시간 전체 면제")
            else:
                why = (f"이수 {g.record}h + 위원 인정 {g.granted}h = {g.counted}h "
                       f"({g.ratio_final:.0%}) — 인정선({g.floor:.0%}) 미달, 훈련 필요")
            ex_part += hours
            n_part += 1 if hours else 0
        rest += req_h - hours
        cls = "" if hours else " class=none"
        rows += (f"<tr{cls}><td>{e(u['unit_name'])}</td><td class=n>{req_h}h</td>"
                 f"<td class=n><b>{hours}h</b></td>"
                 f"<td class=n>{req_h - hours or '–'}</td>"
                 f"<td class=src>{e(why)}</td></tr>")

    granted = ex_full + ex_part
    pct = granted / tot * 100 if tot else 0

    # ── 최종 판정 기록 ──────────────────────────────────────────────
    # 여기가 마지막 화면인데 할 수 있는 것이 없어, 끝난 건이 「기록 전」에 머물러
    # 홈의 할 일에 계속 떴다. 기록 수단은 Track B 5단계 화면에만 있었다.
    dec = s.execute(text("""SELECT decision, recognized_hours, reason, decided_by
        FROM final_decision WHERE submission_id=:i"""), {"i": sid}).mappings().first()
    rb = get_rubric()
    th = rb.final_decision["thresholds"]
    rate = granted / tot if tot else 0
    suggest = ("전체인정" if rate >= th["전체인정"]
               else "불인정" if rate <= th["불인정"] else "부분인정")
    if dec:
        decide_html = f"""<section class="card decide"><header class="ch"><h2>최종 판정 — 기록됨</h2></header>
 <p class="one"><b>{e(dec['decision'])}</b> · 인정 {dec['recognized_hours']}시간 ·
  {e(dec['decided_by'] or '심사위원 합의')}</p>
 <p class="sub">{e(dec['reason'] or '')}</p></section>"""
    else:
        opts = "".join(f'<option{" selected" if d == suggest else ""}>{e(d)}</option>'
                       for d in rb.final_decision["decisions"])
        decide_html = f"""<section class="card decide" id="decide">
 <header class="ch"><h2>최종 판정 기록</h2>
 <p class="sub">시스템이 정하지 않습니다. 위 표를 보고 <b>심사위원들이 합의한 결론</b>을 적습니다.
  인정 시간은 계산값 <b>{granted}시간</b>이 들어가 있고, 바꾸시면 그 차이가 기록에 함께 남습니다.</p></header>
 <div class="drow">
  <label>판정 <select id="dec">{opts}</select></label>
  <label>인정 시간 <input id="dh" type="number" min="0" max="{tot}" value="{granted}">
   <span class="dim">/ {tot}시간</span></label>
 </div>
 <label class="dfull">판정 사유
  <textarea id="dr" rows="3" placeholder="무엇을 무엇으로 인정했는지 현장 언어로 적으십시오."></textarea></label>
 <div class="act-row"><span id="dnote"></span>
  <button id="dgo" class="go">판정 기록</button></div></section>"""

    bar = (f'<i class="r" style="width:{ex_full / tot * 100 if tot else 0:.2f}%"></i>'
           f'<i class="x" style="width:{ex_part / tot * 100 if tot else 0:.2f}%"></i>'
           f'<i class="t" style="width:{rest / tot * 100 if tot else 0:.2f}%"></i>')

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>면제 결과 — {e(a['case_number'])}</title><style>{CSS}{EX_CSS}{TRACK_CSS}{STEP_CSS}</style></head>
<body><div class="viz">
<div class="bk"><a href="/submissions/{sid}">← 심사 개요</a>
 <button onclick="print()">인쇄</button></div>

{step_head("final", "면제 결과", track=a['track'] or 'A',
           nav=step_nav(sid, time_aid, has_ev, track=a['track'] or 'A',
                        ev_aid=ev_aid, has_plan=has_plan))}
<p class="sub">{e(a['case_number'])} · {e(a['official_name'] or a['target_program_id'])} ·
 필수 훈련 {tot}시간 · 접수 구분 {track_chip(a['track'], full=True)}</p>

<section class="card">
 <div class="ex-sum">
  <div><span>면제되는 시간</span><b>{granted}h</b> <span>{pct:.0f}% · {n_full + n_part}개 단위</span></div>
  <div><span>{'근거로 인정' if is_b else '기록으로 확정'}</span><b>{ex_part if is_b else ex_full}h</b>
   <span>{n_part if is_b else n_full}개 단위</span></div>
  {'' if is_b else f'<div><span>위원 판단 포함</span><b>{ex_part}h</b> <span>{n_part}개 단위</span></div>'}
  <div><span>남은 훈련</span><b>{rest}h</b> <span>{100 - pct:.0f}%</span></div>
 </div>
 <div class="ex-bar">{bar}</div>

 <div class="tw"><table class="ex-tbl"><thead><tr>
  <th>능력단위</th><th>요구</th><th>면제</th><th>남은 훈련</th><th>근거</th>
 </tr></thead><tbody>{rows}</tbody></table></div>

 <p class="sub" style="margin-top:10px">{'요소별 인정 항목 비율의 평균이 50% 이상인' if is_b else '인정시간(이수 + 위원 인정)이 요구시간의 50% 이상인'}
 능력단위는 <b>요구시간 전체</b>가 면제됩니다 — 훈련기준의 「−50%까지 조정 가능」 조항입니다.
 못 미치면 면제는 0h 이고 그 시간만큼 훈련이 남습니다. 최종 판정은 전문가 TF가 합니다.</p>
</section>

{decide_html}

<footer><p>심사번호 {e(a['case_number'])} · 기준 v{e(a['rubric_version'])} ·
 작성 {datetime.now():%Y-%m-%d %H:%M} · 최종 판정은 전문가 TF가 한다.</p></footer>
</div>
<script>
(function(){{
 var g=document.getElementById('dgo'); if(!g) return;
 var $=function(i){{return document.getElementById(i)}};
 g.addEventListener('click', function(){{
   var body={{assessment_id:{assessment_id}, decision:$('dec').value,
             recognized_hours:+$('dh').value, reason:$('dr').value||null,
             decided_by:null, allow_incomplete:true}};
   $('dnote').textContent='기록 중…';
   fetch('/submissions/{sid}/decision', {{method:'POST',
     headers:{{'Content-Type':'application/json'}}, body:JSON.stringify(body)}})
    .then(function(r){{ if(!r.ok) return r.json().then(function(j){{throw new Error(j.detail||r.status)}});
                        return r.json(); }})
    .then(function(){{ location.reload(); }})
    .catch(function(e){{ $('dnote').textContent='기록 실패 — '+e.message; }});
 }});
}})();
</script></body></html>"""
