"""Track A 심사 보고서 (HTML). 판정 결과를 사람이 읽는 형태로."""
from __future__ import annotations

import html
import json
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

V = {"완전충족": ("v1", "●"), "조정범위내": ("v2", "▲"),
     "시간부족": ("v3", "■"), "미이수": ("v4", "○")}
e = lambda x: html.escape(str(x) if x is not None else "")

CSS = """*{box-sizing:border-box}
:root{--s1:#fcfcfb;--s2:#f4f4f1;--bd:#e0e0da;--tp:#0b0b0b;--ts:#4a4a46;--tm:#84837c;
 --v1:#0ca30c;--v2:#fab219;--v3:#d03b3b;--v4:#a9a9a2;--req:#d03b3b}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--s1:#1a1a19;--s2:#232322;
 --bd:#3a3a38;--tp:#fff;--ts:#c3c2b7;--tm:#8f8e86;--v4:#6b6b66}}
body{margin:0;background:var(--s1);color:var(--tp);
 font:14px/1.6 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",Pretendard,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:32px 20px 64px}
h1{font-size:24px;margin:0 0 4px}.sub{color:var(--tm);font-size:12.5px;margin:0 0 22px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:9px;margin-bottom:14px}
.kpi{background:var(--s2);border:1px solid var(--bd);border-radius:9px;padding:10px 13px}
.kpi span{display:block;font-size:11.5px;color:var(--tm)}
.kpi b{font-size:23px;font-variant-numeric:tabular-nums}
.kpi b i{font-size:12px;font-style:normal;color:var(--ts);margin-left:2px}
.kpi em{display:block;font-style:normal;font-size:11px;color:var(--tm);margin-top:2px}
.stack{display:flex;height:11px;border-radius:6px;overflow:hidden;gap:2px;background:var(--s2);margin-bottom:6px}
.sg.v1{background:var(--v1)}.sg.v2{background:var(--v2)}.sg.v3{background:var(--v3)}.sg.v4{background:var(--v4)}
.slab{font-size:11.5px;color:var(--tm);margin-bottom:22px}
h2{font-size:15px;margin:24px 0 10px}
.row{display:grid;grid-template-columns:minmax(140px,1.3fr) minmax(110px,2.2fr) 84px 96px;
 gap:12px;align-items:center;padding:8px 0 4px}
.nm{font-size:12.8px;line-height:1.35}
.code{display:block;font-size:10.5px;color:var(--tm);font-variant-numeric:tabular-nums}
.track{position:relative;height:24px;background:var(--s2);border-radius:5px}
.fill{position:absolute;left:0;top:0;height:100%;border-radius:0 4px 4px 0;min-width:2px}
.fill.v1{background:var(--v1)}.fill.v2{background:var(--v2)}
.fill.v3{background:var(--v3);background-image:repeating-linear-gradient(45deg,rgba(255,255,255,.42) 0 3px,transparent 3px 7px)}
.fill.v4{background:transparent;border:1.5px dashed var(--v4);border-radius:5px}
.reql{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--req)}
.reqv{position:absolute;left:4px;top:-15px;font-size:10px;color:var(--req);white-space:nowrap}
.minl{position:absolute;top:2px;bottom:2px;border-left:1.5px dotted var(--tm);opacity:.7}
.hrs{text-align:right;font-size:12.5px;font-variant-numeric:tabular-nums;white-space:nowrap}
.hrs b{font-size:14.5px}.hrs span{color:var(--tm);font-size:11.5px}
.st{font-size:11.5px;font-weight:600;white-space:nowrap}
.st.v1{color:var(--v1)}.st.v2{color:#a06f00}.st.v3{color:var(--v3)}.st.v4{color:var(--tm)}
.warn{display:block;font-size:10.5px;color:var(--v3);font-weight:400}
.lgd{display:flex;flex-wrap:wrap;gap:14px;padding:11px 14px;background:var(--s2);
 border:1px solid var(--bd);border-radius:9px;margin-bottom:18px;font-size:12.5px;color:var(--ts)}
.lg{display:flex;align-items:center;gap:6px}.sw{width:20px;height:10px;border-radius:3px}
.sw.v1{background:var(--v1)}.sw.v2{background:var(--v2)}
.sw.v3{background:var(--v3);background-image:repeating-linear-gradient(45deg,rgba(255,255,255,.42) 0 3px,transparent 3px 7px)}
.sw.v4{background:transparent;border:1.5px dashed var(--v4)}
.sw.req{background:var(--req);width:2px;height:16px}.sw.min{border-left:1.5px dotted var(--tm);height:16px}
table{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px}
th,td{padding:6px 9px;border-bottom:1px solid var(--bd);text-align:left}
th{color:var(--tm);font-weight:600}td.n{text-align:right;font-variant-numeric:tabular-nums}
footer{color:var(--tm);font-size:11.5px;border-top:1px solid var(--bd);padding-top:14px;margin-top:26px}
@media(max-width:680px){.row{grid-template-columns:1fr;gap:4px;border-bottom:1px solid var(--bd)}
 .hrs{text-align:left}.reqv{display:none}}"""


def render_track_a(s: Session, assessment_id: int) -> str:
    a = s.execute(text("""
        SELECT a.id, a.rubric_version, a.model, a.overall_note, a.finished_at,
               s.case_number, s.target_program_id, p.official_name, p.daebunryu
        FROM assessment a JOIN submission s ON s.id=a.submission_id
        LEFT JOIN catalog_wsd_program p ON p.program_id=s.target_program_id
        WHERE a.id=:i"""), {"i": assessment_id}).mappings().one()
    els = [dict(r) for r in s.execute(text("""
        SELECT element_id, recommendation, evidence_level, verification_method,
               confidence, payload FROM assessment_element
        WHERE assessment_id=:i ORDER BY (payload->>'required_hours')::int DESC"""),
        {"i": assessment_id}).mappings()]
    d = json.loads(a["overall_note"])
    tot, H = d["total_hours"], d["hours"]

    mx = max((x["payload"]["required_hours"], x["payload"]["completed_hours"] or 0)
             for x in els)
    mx = max(max(p) for p in [mx]) if els else 1

    rows = ""
    for x in els:
        p, v = x["payload"], x["evidence_level"]
        cls, ico = V[v]
        c = p["completed_hours"] or 0
        warn = "" if x["confidence"] == "확정" else f'<span class="warn">⚠ {e(x["confidence"])}</span>'
        rows += f"""<div class="row" title="{e(p['unit_name'])} — 요구 {p['required_hours']}h · 하한 {p['min_hours']}h · 이수 {c or '-'}h">
  <div class="nm"><span class="code">{e(x['element_id'])}</span>{e(p['unit_name'])}</div>
  <div class="track">
    <div class="fill {cls}" style="width:{c/mx*100:.2f}%"></div>
    <div class="minl" style="left:{p['min_hours']/mx*100:.2f}%"></div>
    <div class="reql" style="left:{p['required_hours']/mx*100:.2f}%"><span class="reqv">{p['required_hours']}h</span></div>
  </div>
  <div class="hrs"><b>{c or '–'}</b><span>/{p['required_hours']}h</span></div>
  <div class="st {cls}">{ico} {e(v)} · {e(x['recommendation'])}{warn}</div>
</div>"""

    seg = "".join(f'<div class="sg {V[k][0]}" style="width:{H[k]/tot*100:.3f}%" title="{k} {H[k]}시간"></div>'
                  for k in ["완전충족", "조정범위내", "시간부족", "미이수"] if H[k])
    slab = " · ".join(f"{k} {H[k]}h" for k in H if H[k])
    trows = "".join(f"""<tr><td>{e(x['element_id'])}</td><td>{e(x['payload']['unit_name'])}</td>
        <td class=n>{x['payload']['required_hours']}</td><td class=n>{x['payload']['min_hours']}</td>
        <td class=n>{x['payload']['completed_hours'] or '–'}</td>
        <td class=n>{f"{x['payload']['ratio']:.2f}" if x['payload']['ratio'] else '–'}</td>
        <td>{e(x['evidence_level'])}</td><td>{e(x['recommendation'])}</td>
        <td>{e(x['verification_method'])}</td><td>{e(x['confidence'])}</td></tr>""" for x in els)

    warn_n = sum(1 for x in els if x["confidence"] != "확정")
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RPL Track A 심사 보고서 — {e(a['case_number'])}</title><style>{CSS}</style></head><body><div class="wrap">
<h1>RPL Track A 심사 보고서</h1>
<p class="sub">심사번호 {e(a['case_number'])} · 목표 종목 {e(a['official_name'] or a['target_program_id'])}
 ({e(a['daebunryu'])}) · 총 필수 {tot}시간 · 능력단위 {d['n_units']}개</p>

<div class="kpis">
 <div class="kpi"><span>능력단위 커버리지</span><b>{d['unit_coverage_rate']*100:.0f}<i>%</i></b>
   <em>{sum(1 for x in els if x['payload']['completed_hours'] is not None)}/{d['n_units']}개 보유</em></div>
 <div class="kpi"><span>인정 시간 — 확정</span><b>{d['credit_rate_strict']*100:.0f}<i>%</i></b>
   <em>{H['완전충족']}h / {tot}h</em></div>
 <div class="kpi"><span>인정 시간 — 조정 적용</span><b>{d['credit_rate_adjusted']*100:.0f}<i>%</i></b>
   <em>{H['완전충족']+H['조정범위내']}h · −50% 조항</em></div>
 <div class="kpi"><span>추가 확인·훈련</span><b>{d['remaining_hours']}<i>시간</i></b>
   <em>부족 {H['시간부족']}h + 미이수 {H['미이수']}h</em></div>
</div>
<div class="stack">{seg}</div><div class="slab">{slab}</div>

<div class="lgd">
 <div class="lg"><span class="sw v1"></span>완전충족 — 이수 ≥ 요구 (R0)</div>
 <div class="lg"><span class="sw v2"></span>조정범위내 — 요구의 50~99% (R0)</div>
 <div class="lg"><span class="sw v3"></span>시간부족 — 50% 미만 (R2 면접)</div>
 <div class="lg"><span class="sw v4"></span>미이수 (R5 훈련)</div>
 <div class="lg"><span class="sw req"></span>요구시간</div>
 <div class="lg"><span class="sw min"></span>−50% 하한</div>
</div>

<h2>능력단위별 시간 충족</h2>{rows}

<h2>상세</h2>
<table><thead><tr><th>코드</th><th>능력단위</th><th>요구</th><th>하한</th><th>이수</th><th>비율</th>
<th>판정</th><th>권고</th><th>확인방법</th><th>신뢰도</th></tr></thead><tbody>{trows}</tbody></table>

<footer>
기준 v{e(a['rubric_version'])} · 판정 {e(a['model'])} · 생성 {datetime.now():%Y-%m-%d %H:%M}<br>
과정평가형 편성시간은 기준값이며 기관이 80~150% 범위에서 편성한다.
신뢰도가 <b>추정</b>인 {warn_n}건은 편성 하한에서 판정이 바뀌므로 개인 이수증명서 확인이 필요하다.<br>
이 문서는 판정이 아니라 판정 근거다. 전체인정·부분인정·불인정은 전문가 TF가 결정한다.
</footer></div></body></html>"""
