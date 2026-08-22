"""① 시간 대조 보고서 — 기록으로 확인되는 이수 시간.

## 무엇을 말하는 보고서인가

「목표 종목이 요구하는 시간」과 「이미 이수한 것이 확인된 시간」을 능력단위별로 맞대 본다.
판단이 들어가지 않는다. 이수증에 적힌 숫자를 그대로 견주는 것뿐이다.
그래서 몇 번을 돌려도 같은 값이 나온다.

## 0시간일 때가 오히려 중요하다

「0시간」만 보여 주면 심사위원은 서류를 안 낸 것인지, 냈는데 안 쳐 준 것인지
구분할 수 없다. 그 둘은 다음에 할 일이 다르다 — 편성표만 낸 사람에게는
이수증을 받으면 되고, 아예 없는 사람은 근거 분석으로 간다.
그래서 갈음되지 않은 단위는 이유까지 적는다.
"""
from __future__ import annotations

import html
import json
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.report.layout import REC, page

# 판정 이름 → (색 class, 기호, 심사위원이 읽을 말)
V = {"완전충족":   ("v1", "●", "이수 시간이 요구를 채웁니다"),
     "조정범위내": ("v2", "▲", "요구의 절반은 넘습니다"),
     "시간부족":   ("v3", "■", "요구의 절반에 못 미칩니다"),
     "미이수":     ("v4", "○", "이수 기록이 없습니다")}
e = lambda x: html.escape(str(x) if x is not None else "")   # noqa: E731

CSS = """
:root{--v1:#0a8a0a;--v2:#c98a00;--v3:#d03b3b;--v4:#8d8d86;--req:#d03b3b}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--v4:#7a7a74}}
.lead{background:var(--s2);border:1px solid var(--bd);border-radius:10px;
 padding:15px 18px;margin-bottom:20px;font-size:14.5px;line-height:1.7}
.lead b{font-size:19px;font-variant-numeric:tabular-nums}
.lead .d{color:var(--tm);font-size:12.8px;display:block;margin-top:6px}
.stack{display:flex;height:13px;border-radius:7px;overflow:hidden;gap:2px;
 background:var(--s3);margin:12px 0 6px}
.sg.v1{background:var(--v1)}.sg.v2{background:var(--v2)}
.sg.v3{background:var(--v3)}.sg.v4{background:var(--v4);opacity:.45}
.rowh{display:grid;grid-template-columns:minmax(150px,1.4fr) minmax(120px,2.2fr) 92px 150px;
 gap:12px;font-size:11.5px;color:var(--tm);padding:0 0 5px;border-bottom:1px solid var(--bd)}
.urow{display:grid;grid-template-columns:minmax(150px,1.4fr) minmax(120px,2.2fr) 92px 150px;
 gap:12px;align-items:center;padding:9px 0 5px;border-bottom:1px solid var(--bd)}
.nm{font-size:12.8px;line-height:1.35}
.code{display:block;font-size:10.5px;color:var(--tm);font-variant-numeric:tabular-nums}
.track{position:relative;height:24px;background:var(--s3);border-radius:5px}
.fill{position:absolute;left:0;top:0;height:100%;border-radius:0 4px 4px 0;min-width:2px}
.fill.v1{background:var(--v1)}.fill.v2{background:var(--v2)}
.fill.v3{background:var(--v3);background-image:repeating-linear-gradient(45deg,rgba(255,255,255,.42) 0 3px,transparent 3px 7px)}
.fill.v4{background:transparent;border:1.5px dashed var(--v4);border-radius:5px}
.reql{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--req)}
.reqv{position:absolute;left:4px;top:-15px;font-size:10px;color:var(--req);white-space:nowrap}
.minl{position:absolute;top:2px;bottom:2px;border-left:1.5px dotted var(--tm);opacity:.7}
.hrs{text-align:right;font-size:12.5px;font-variant-numeric:tabular-nums;white-space:nowrap}
.hrs b{font-size:15px}.hrs span{color:var(--tm);font-size:11.5px}
.vd{font-size:11.5px;font-weight:600;white-space:nowrap}
.vd.v1{color:var(--v1)}.vd.v2{color:#a06f00}.vd.v3{color:var(--v3)}.vd.v4{color:var(--tm)}
.vd em{display:block;font-style:normal;font-weight:400;font-size:10.5px;color:var(--tm)}
.warn{display:block;font-size:10.5px;color:var(--v3);font-weight:400}
.lgd{display:flex;flex-wrap:wrap;gap:14px;padding:11px 14px;background:var(--s2);
 border:1px solid var(--bd);border-radius:9px;margin:16px 0 6px;font-size:12.5px;color:var(--ts)}
.lg{display:flex;align-items:center;gap:6px}.sw{width:20px;height:10px;border-radius:3px}
.sw.v1{background:var(--v1)}.sw.v2{background:var(--v2)}
.sw.v3{background:var(--v3);background-image:repeating-linear-gradient(45deg,rgba(255,255,255,.42) 0 3px,transparent 3px 7px)}
.sw.v4{background:transparent;border:1.5px dashed var(--v4)}
.sw.req{background:var(--req);width:2px;height:16px}.sw.min{border-left:1.5px dotted var(--tm);height:16px}
.acts{display:flex;gap:9px;margin:22px 0 4px}
.acts a,.acts button{font-size:13px;padding:7px 15px;border-radius:7px;
 border:1px solid var(--bd);background:var(--s1);color:var(--ts);display:inline-block}
.acts a.go{background:var(--tp);color:var(--s1);border-color:transparent;font-weight:600}
@media(max-width:680px){.rowh{display:none}
 .urow{grid-template-columns:1fr;gap:4px}.hrs{text-align:left}.reqv{display:none}}
"""


def render_track_a(s: Session, assessment_id: int) -> str:
    a = s.execute(text("""
        SELECT a.id, a.submission_id, a.rubric_version, a.overall_note, a.finished_at,
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
    src, skipped = d.get("근거") or {}, d.get("갈음불가") or []
    sid = a["submission_id"]

    mx = max([p for x in els
              for p in (x["payload"]["required_hours"], x["payload"]["completed_hours"] or 0)]
             or [1]) or 1

    # ── 한 줄 요약 ──
    ok_h = H["완전충족"] + H["조정범위내"]
    bits = []
    if src.get("자격"):
        bits.append(f"과정평가형 자격 {src['자격']}개 단위")
    if src.get("기이수"):
        bits.append(f"훈련 이수 기록 {src['기이수']}개 단위")
    if bits:
        lead = (f"{' 과 '.join(bits)}에서 <b>{ok_h}</b>시간이 확인됐습니다. "
                f"총 필수 {tot}시간의 <b>{ok_h / tot:.0%}</b>입니다.")
    else:
        lead = (f"요구 시간을 갈음할 이수 기록이 확인되지 않았습니다. "
                f"총 필수 <b>{tot}</b>시간이 그대로 남습니다.")
    detail = (f"남은 {tot - ok_h}시간은 제출 자료로 따져 보거나(근거 분석), "
              f"훈련으로 채워야 합니다." if tot - ok_h else "요구 시간이 모두 채워졌습니다.")

    rows = ""
    for x in els:
        p, v = x["payload"], x["evidence_level"]
        cls, ico, say = V[v]
        c = p["completed_hours"] or 0
        warn = "" if x["confidence"] == "확정" else f'<span class="warn">⚠ {e(x["confidence"])}</span>'
        rows += f"""<div class="urow">
  <div class="nm"><span class="code">{e(x['element_id'])}</span>{e(p['unit_name'])}</div>
  <div class="track">
    <div class="fill {cls}" style="width:{c / mx * 100:.2f}%"></div>
    <div class="minl" style="left:{p['min_hours'] / mx * 100:.2f}%"></div>
    <div class="reql" style="left:{p['required_hours'] / mx * 100:.2f}%"><span class="reqv">{p['required_hours']}h</span></div>
  </div>
  <div class="hrs"><b>{c or '–'}</b><span>/{p['required_hours']}h</span></div>
  <div class="vd {cls}">{ico} {e(say)}<em>{e(REC[x['recommendation']][1])}</em>{warn}</div>
</div>"""

    seg = "".join(
        f'<div class="sg {V[k][0]}" style="width:{H[k] / tot * 100:.3f}%" title="{k} {H[k]}시간"></div>'
        for k in ["완전충족", "조정범위내", "시간부족", "미이수"] if H[k])
    slab = " · ".join(f"{V[k][2]} {H[k]}시간" for k in H if H[k])

    miss = ""
    if skipped:
        mrows = "".join(
            f"<tr><td>{e(x['unit_name'])}</td><td class=n>{x['required_hours']}시간</td>"
            f"<td class=n>{x['completed_hours'] if x['completed_hours'] is not None else '–'}</td>"
            f"<td>{e(x['doc_type'])}</td><td>{e(x['reason'])}</td></tr>" for x in skipped)
        miss = f"""<h2>이수 기록을 냈으나 시간으로 갈음되지 않은 {len(skipped)}개 단위</h2>
<p class="sub">이수증에 적혀 있어야 할 것이 빠졌거나, 시간이 하한에 못 미칩니다.
 보완 서류를 받으면 이 단위들은 다시 대조됩니다.</p>
<table><thead><tr><th>능력단위</th><th>요구</th><th>이수</th><th>낸 자료</th><th>이유</th></tr></thead>
<tbody>{mrows}</tbody></table>"""

    trows = "".join(f"""<tr><td>{e(x['element_id'])}</td><td>{e(x['payload']['unit_name'])}</td>
        <td class=n>{x['payload']['required_hours']}</td><td class=n>{x['payload']['min_hours']}</td>
        <td class=n>{x['payload']['completed_hours'] or '–'}</td>
        <td class=n>{f"{x['payload']['ratio']:.0%}" if x['payload']['ratio'] else '–'}</td>
        <td>{e(x['evidence_level'])}</td><td>{e(REC[x['recommendation']][1])}</td>
        <td>{e(x['confidence'])}</td></tr>""" for x in els)

    warn_n = sum(1 for x in els if x["confidence"] != "확정")
    hold = ("<br>과정평가형 편성시간은 기준값이며 기관이 80~150% 범위에서 편성합니다. "
            f"<b>추정</b>으로 표시된 {warn_n}건은 편성 하한으로 계산하면 판정이 바뀌므로 "
            "개인 이수증명서를 확인해야 합니다." if warn_n else "")

    body = f"""<div class="acts noprint">
 <a href="/submissions/{sid}">← 심사 개요</a>
 <button onclick="print()">인쇄</button></div>
<h1>시간 대조 보고서</h1>
<p class="sub">심사번호 {e(a['case_number'])} · 목표 종목
 {e(a['official_name'] or a['target_program_id'])} ({e(a['daebunryu'])}) ·
 총 필수 {tot}시간 · 능력단위 {d['n_units']}개</p>

<div class="lead">{lead}
 <div class="stack">{seg}</div>
 <span class="d">{slab}</span>
 <span class="d">{detail}</span></div>

<div class="lgd">
 <div class="lg"><span class="sw v1"></span>이수 ≥ 요구</div>
 <div class="lg"><span class="sw v2"></span>요구의 50~99%</div>
 <div class="lg"><span class="sw v3"></span>요구의 50% 미만</div>
 <div class="lg"><span class="sw v4"></span>이수 기록 없음</div>
 <div class="lg"><span class="sw req"></span>요구시간</div>
 <div class="lg"><span class="sw min"></span>인정 하한</div>
</div>

<h2>능력단위별 시간</h2>
<div class="rowh"><div>능력단위</div><div>이수 대비 요구</div>
 <div style="text-align:right">시간</div><div>판정</div></div>
{rows}

{miss}

<h2>표로 보기</h2>
<table><thead><tr><th>코드</th><th>능력단위</th><th>요구</th><th>하한</th><th>이수</th>
<th>비율</th><th>판정</th><th>다음</th><th>확실성</th></tr></thead><tbody>{trows}</tbody></table>

<footer>
심사 기준 v{e(a['rubric_version'])} · 계산 {a['finished_at']:%Y-%m-%d %H:%M} ·
 출력 {datetime.now():%Y-%m-%d %H:%M}{hold}<br>
이 문서는 판정이 아니라 판정 근거입니다. 전체·부분·불인정은 전문가가 결정합니다.
</footer>"""
    return page(f"시간 대조 보고서 — {a['case_number']}", body, css=CSS, here="/cases")
