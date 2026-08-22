"""Track A 심사 보고서 — 연구팀이 회람·확정한 포맷 그대로.

원본: `Data(20260812)/derived/trackA_보고서.html`
CSS·클래스명·마크업 구조·범례 문구를 그대로 옮겼다. 임의로 고치지 않는다.
바꾼 것은 「시나리오 4건을 늘어놓던 것」을 「접수 한 건」으로 좁힌 것뿐이다.

## 히트맵(가로 막대) 규칙 — 원본 그대로

- 척도는 카드 안에서 공통이다: `max(요구, 이수)` 전체 최대값.
  행마다 따로 잡으면 막대 길이를 서로 견줄 수 없다.
- 빨간 실선 = 요구시간, 점선 = −50% 하한.
- 색만으로 뜻을 전하지 않는다. 적록색약(deutan)에서 초록·빨강은 ΔE 4.1 로
  구분이 어렵다. 그래서 아이콘(●▲■○) + 상태 텍스트를 상시 표기하고,
  시간부족에는 빗금을 넣는다.
"""
from __future__ import annotations

import html
import json
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

e = lambda x: html.escape(str(x) if x is not None else "")   # noqa: E731

# 판정 → (색 class, 아이콘, 짧은 이름)
V = {"완전충족": ("good", "●", "충족"),
     "조정범위내": ("warn", "▲", "조정범위"),
     "시간부족": ("crit", "■", "시간부족"),
     "미이수": ("none", "○", "미이수")}
ORDER = ["완전충족", "조정범위내", "시간부족", "미이수"]

CSS = """*{box-sizing:border-box}
.viz{--s1:#fcfcfb;--s2:#f4f4f1;--bd:#e3e3dd;--tp:#0b0b0b;--ts:#52514e;--tm:#84837c;
 --good:#0ca30c;--warn:#fab219;--crit:#d03b3b;--none:#a9a9a2;--req:#d03b3b;
 color-scheme:light;background:var(--s1);color:var(--tp)}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])) .viz{
 --s1:#1a1a19;--s2:#232322;--bd:#3a3a38;--tp:#fff;--ts:#c3c2b7;--tm:#8f8e86;--none:#6b6b66;color-scheme:dark}}
:root[data-theme=dark] .viz{--s1:#1a1a19;--s2:#232322;--bd:#3a3a38;--tp:#fff;--ts:#c3c2b7;--tm:#8f8e86;--none:#6b6b66;color-scheme:dark}
body{margin:0;background:var(--s1)}
.viz{font:14px/1.55 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Pretendard","Malgun Gothic",sans-serif;
 max-width:1080px;margin:0 auto;padding:32px 20px 64px}
h1{font-size:26px;margin:0 0 6px;letter-spacing:-.02em}
.lead{color:var(--ts);margin:0 0 22px;font-size:14px}
.note{background:var(--s2);border:1px solid var(--bd);border-radius:10px;padding:14px 16px;margin:0 0 26px;font-size:13px;color:var(--ts)}
.note b{color:var(--tp)}
.note table{width:100%;table-layout:fixed;border-collapse:collapse;margin-top:10px;font-size:12.5px}
.note td,.note th{word-break:normal;overflow-wrap:break-word;white-space:normal}
.note th,.note td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--bd);vertical-align:top}
.note th{color:var(--tm);font-weight:600}
.card{border:1px solid var(--bd);border-radius:14px;padding:20px;margin:0 0 22px;background:var(--s1)}
.ch{margin-bottom:16px}
.tag{display:inline-block;font-size:11.5px;font-weight:700;letter-spacing:.04em;color:var(--ts);
 background:var(--s2);border:1px solid var(--bd);border-radius:999px;padding:3px 10px;margin-bottom:8px}
.ch h2{font-size:18px;margin:0 0 4px;letter-spacing:-.01em}
.arw{color:var(--tm);font-weight:400;margin:0 4px}
.sub{margin:0;font-size:12.5px;color:var(--tm)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:18px}
.kpi{background:var(--s2);border:1px solid var(--bd);border-radius:10px;padding:11px 13px}
.kpi>span{display:block;font-size:11.5px;color:var(--tm);margin-bottom:3px}
.kpi b{font-size:23px;font-weight:700;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.kpi b i{font-size:12.5px;font-weight:500;font-style:normal;color:var(--ts);margin-left:2px}
.kpi em{display:block;font-style:normal;font-size:11.5px;color:var(--tm);margin-top:2px}
.kpi.hl{border-color:var(--tm)}
.stackwrap{margin:0 0 18px}
.stack{display:flex;height:12px;border-radius:6px;overflow:hidden;background:var(--s2);gap:2px}
.sg{height:100%}
.sg.good{background:var(--good)}.sg.warn{background:var(--warn)}
.sg.crit{background:var(--crit);background-image:repeating-linear-gradient(45deg,rgba(255,255,255,.42) 0 3px,transparent 3px 7px)}
.sg.none{background:var(--none)}
.slab{margin-top:6px;font-size:11.5px;color:var(--tm)}
.slab .good{color:var(--good)}.slab .warn{color:#a06f00}.slab .crit{color:var(--crit)}.slab .none{color:var(--tm)}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])) .slab .warn{color:var(--warn)}}
:root[data-theme=dark] .slab .warn{color:var(--warn)}
.plot{display:flex;flex-direction:column;gap:2px}
.row{display:grid;grid-template-columns:minmax(150px,1.35fr) minmax(120px,2.4fr) 78px 88px;
 gap:12px;align-items:center;padding:8px 0 4px}
.nm{font-size:12.8px;line-height:1.35;min-width:0}
.code{display:block;font-size:10.5px;color:var(--tm);font-variant-numeric:tabular-nums;letter-spacing:.02em}
.track{position:relative;height:24px;background:var(--s2);border-radius:5px;overflow:visible}
.fill{position:absolute;left:0;top:0;height:100%;border-radius:0 4px 4px 0;min-width:2px}
.fill.good{background:var(--good)} .fill.warn{background:var(--warn)}
.fill.crit{background:var(--crit);background-image:repeating-linear-gradient(45deg,rgba(255,255,255,.42) 0 3px,transparent 3px 7px)}
.fill.none{background:transparent;border:1.5px dashed var(--none);border-radius:5px}
.reql{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--req);border-radius:1px}
.reqv{position:absolute;left:4px;top:-15px;font-size:10px;color:var(--req);white-space:nowrap;font-variant-numeric:tabular-nums}
.minl{position:absolute;top:2px;bottom:2px;width:0;border-left:1.5px dotted var(--tm);opacity:.75}
.hrs{text-align:right;font-size:12.5px;font-variant-numeric:tabular-nums;white-space:nowrap}
.hrs b{font-size:14.5px}.hrs span{color:var(--tm);font-size:11.5px}
.st{font-size:11.5px;white-space:nowrap;display:flex;align-items:center;gap:5px;font-weight:600}
.st i{font-style:normal;font-size:10px}
.st.good{color:var(--good)} .st.warn{color:#a06f00} .st.crit{color:var(--crit)} .st.none{color:var(--tm);font-weight:500}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])) .st.warn{color:var(--warn)}}
:root[data-theme=dark] .st.warn{color:var(--warn)}
.lgd{display:flex;flex-wrap:wrap;gap:16px;padding:13px 16px;background:var(--s2);
 border:1px solid var(--bd);border-radius:10px;margin-bottom:24px;font-size:12.5px;color:var(--ts)}
.lg{display:flex;align-items:center;gap:6px}
.sw{width:22px;height:11px;border-radius:3px;flex:none}
.sw.good{background:var(--good)}.sw.warn{background:var(--warn)}
.sw.crit{background:var(--crit);background-image:repeating-linear-gradient(45deg,rgba(255,255,255,.42) 0 3px,transparent 3px 7px)}
.sw.none{background:transparent;border:1.5px dashed var(--none)}
.sw.req{background:var(--req);width:2px;height:16px;border-radius:1px}
.sw.min{width:0;border-left:1.5px dotted var(--tm);height:16px}
.tbl{margin-top:16px;border-top:1px solid var(--bd);padding-top:12px}
.tbl summary{cursor:pointer;font-size:12.5px;color:var(--ts)}
.tw{overflow-x:auto;margin-top:10px}
table{border-collapse:collapse;width:100%;font-size:11.8px;white-space:nowrap}
th,td{padding:5px 9px;border-bottom:1px solid var(--bd);text-align:left}
th{color:var(--tm);font-weight:600}
td.n{text-align:right;font-variant-numeric:tabular-nums}
td.m{font-variant-numeric:tabular-nums;color:var(--ts)}
footer{color:var(--tm);font-size:12px;border-top:1px solid var(--bd);padding-top:16px;margin-top:8px}
.bk{display:flex;gap:9px;margin-bottom:18px;flex-wrap:wrap}
.bk a,.bk button{font:inherit;font-size:13px;padding:7px 15px;border-radius:8px;border:1px solid var(--bd);
 background:var(--s2);color:var(--ts);text-decoration:none;cursor:pointer}
@media(max-width:720px){.row{grid-template-columns:1fr;gap:4px;padding:9px 0;border-bottom:1px solid var(--bd)}
 .hrs{text-align:left}.reqv{display:none}}
@media print{.bk{display:none}.viz{max-width:none;padding:0}
 .card,.kpi,.note,.row{break-inside:avoid}}"""


def _basis(evidence: list[dict]) -> str:
    """이 능력단위의 시간이 어디서 왔는가. 원본의 「근거」 칸."""
    src = (evidence or [{}])[0].get("source") or ""
    if src.startswith("자격:"):
        return "기준값(편성기준)"
    if src.startswith("이수:"):
        return "이수증(실적)"
    return "—"


def render_track_a(s: Session, assessment_id: int) -> str:
    a = s.execute(text("""
        SELECT a.id, a.submission_id, a.rubric_version, a.overall_note, a.finished_at,
               s.case_number, s.target_program_id,
               p.official_name, p.daebunryu, p.n_units AS prog_units
        FROM assessment a JOIN submission s ON s.id=a.submission_id
        LEFT JOIN catalog_wsd_program p ON p.program_id=s.target_program_id
        WHERE a.id=:i"""), {"i": assessment_id}).mappings().one()
    els = [dict(r) for r in s.execute(text("""
        SELECT element_id, recommendation, evidence_level, verification_method,
               confidence, payload FROM assessment_element
        WHERE assessment_id=:i ORDER BY (payload->>'required_hours')::int DESC,
                                        element_id"""),
        {"i": assessment_id}).mappings()]
    std = {r[0]: r[1] for r in s.execute(text("""
        SELECT unit_code, std_hours FROM catalog_ncs_unit
        WHERE unit_code = ANY(:c)"""), {"c": [x["element_id"] for x in els]})}

    d = json.loads(a["overall_note"])
    tot, H = d["total_hours"], d["hours"]
    src, skipped = d.get("근거") or {}, d.get("갈음불가") or []
    sid = a["submission_id"]
    n_units = d["n_units"]
    n_covered = sum(1 for x in els if x["payload"]["completed_hours"] is not None)

    # 척도는 카드 안에서 공통이다 — 행마다 따로 잡으면 막대를 서로 견줄 수 없다.
    mx = max([v for x in els
              for v in (x["payload"]["required_hours"], x["payload"]["completed_hours"] or 0)]
             or [1]) or 1

    rows = ""
    for x in els:
        p, v = x["payload"], x["evidence_level"]
        cls, ico, short = V[v]
        c = p["completed_hours"] or 0
        tip = (f'{p["unit_name"]}\n요구 {p["required_hours"]}h · 하한 {p["min_hours"]}h\n'
               f'이수 {c or 0}h ({_basis(p.get("evidence"))})\n'
               f'판정 {v} / {x["confidence"]}')
        rows += f"""<div class="row" title="{e(tip)}">
  <div class="nm"><span class="code">{e(x['element_id'])}</span>{e(p['unit_name'])}</div>
  <div class="track">
    <div class="fill {cls}" style="width:{c / mx * 100:.2f}%"></div>
    <div class="minl" style="left:{p['min_hours'] / mx * 100:.2f}%"></div>
    <div class="reql" style="left:{p['required_hours'] / mx * 100:.2f}%"><span class="reqv">{p['required_hours']}h</span></div>
  </div>
  <div class="hrs"><b>{c or '–'}</b><span>/{p['required_hours']}h</span></div>
  <div class="st {cls}"><i>{ico}</i>{short}</div>
</div>"""

    seg = "".join(
        f'<div class="sg {V[k][0]}" style="width:{H[k] / tot * 100:.3f}%" title="{V[k][2]} {H[k]}시간"></div>'
        for k in ORDER if H[k])
    slab = " · ".join(f'<span class="{V[k][0]}">{V[k][2]} {H[k]}h</span>' for k in ORDER if H[k])

    trows = "".join(f"""<tr><td class=m>{e(x['element_id'])}</td><td>{e(x['payload']['unit_name'])}</td>
      <td class=n>{std.get(x['element_id']) or '–'}</td>
      <td class=n>{x['payload']['required_hours']}</td><td class=n>{x['payload']['min_hours']}</td>
      <td class=n>{x['payload']['completed_hours'] or '–'}</td>
      <td>{e(_basis(x['payload'].get('evidence')))}</td>
      <td>{e(x['evidence_level'])}</td><td>{e(x['confidence'])}</td></tr>""" for x in els)

    # 카드 머리 — 원본은 시나리오 유형을 달았다. 접수 건에서는 판정 양상으로 정한다.
    strict = d["credit_rate_strict"]
    kind = ("완전인정형" if strict >= 1 else "미인정형" if strict <= 0 else "부분인정형")
    bits = []
    if src.get("자격"):
        bits.append(f"과정평가형 자격 {src['자격']}개 단위")
    if src.get("기이수"):
        bits.append(f"훈련 이수 기록 {src['기이수']}개 단위")
    basis_line = " · ".join(bits) or "갈음할 이수 기록 없음"

    miss = ""
    if skipped:
        mrows = "".join(
            f"<tr><td>{e(x['unit_name'])}</td><td class=n>{x['required_hours']}</td>"
            f"<td class=n>{x['completed_hours'] if x['completed_hours'] is not None else '–'}</td>"
            f"<td>{e(x['doc_type'])}</td><td style='white-space:normal'>{e(x['reason'])}</td></tr>"
            for x in skipped)
        miss = f"""<details class="tbl" open><summary>이수 기록을 냈으나 시간으로 갈음되지 않은 {len(skipped)}개 단위</summary>
  <div class="tw"><table><thead><tr><th>능력단위</th><th>요구</th><th>이수</th><th>낸 자료</th><th>이유</th></tr></thead>
  <tbody>{mrows}</tbody></table></div></details>"""

    warn_n = sum(1 for x in els if x["confidence"] != "확정")
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RPL Track A 심사 보고서 — {e(a['case_number'])}</title><style>{CSS}</style></head>
<body><div class="viz">
<div class="bk"><a href="/submissions/{sid}">← 심사 개요</a>
 <a href="/cases">접수 현황</a><button onclick="print()">인쇄</button></div>

<h1>RPL Track A 심사 보고서</h1>
<p class="lead">보유 자격·기이수 훈련 기록으로 목표 종목의 능력단위별 시간 충족을 판정한다.</p>

<div class="note"><b>데이터 출처</b> — 요구시간은 고용노동부 고시 제2025-35호
 일학습병행 교육훈련기준, 이수시간은 과정평가형 편성기준의 <b>기준값</b> 또는
 지원자가 제출한 훈련이수증의 <b>실적값</b>입니다. 판단이 들어가지 않으므로
 몇 번을 돌려도 같은 값이 나옵니다.
 <br><br><b>접근성</b> — 상태색 초록·빨강은 적록색약(deutan)에서 ΔE 4.1로 구분이
 어렵습니다. 따라서 모든 막대에 <b>아이콘 + 상태 텍스트</b>를 상시 표기하고
 시간부족에는 <b>빗금</b>을 넣어, 색이 단독으로 의미를 전달하지 않도록 했습니다.
 카드 하단에 데이터 표도 제공합니다.</div>

<div class="lgd">
 <div class="lg"><span class="sw good"></span>충족 — 이수 ≥ 요구</div>
 <div class="lg"><span class="sw warn"></span>조정범위 — 요구의 50~99% (−50% 조정 적용 가능)</div>
 <div class="lg"><span class="sw crit"></span>시간부족 — 요구의 50% 미만</div>
 <div class="lg"><span class="sw none"></span>미이수 — 해당 능력단위 없음</div>
 <div class="lg"><span class="sw req"></span>요구 훈련시간</div>
 <div class="lg"><span class="sw min"></span>−50% 하한</div>
</div>

<section class="card">
 <header class="ch">
   <div class="tag">{e(a['case_number'])} · {kind}</div>
   <h2>{e(basis_line)} <span class="arw">→</span> {e(a['official_name'] or a['target_program_id'])}</h2>
   <p class="sub">{e(a['daebunryu'])} · 목표 필수능력단위 {n_units}개 / {tot}시간</p>
 </header>
 <div class="kpis">
   <div class="kpi"><span>능력단위 커버리지</span><b>{d['unit_coverage_rate'] * 100:.0f}<i>%</i></b>
     <em>{n_covered}/{n_units}개 단위가 겹침</em></div>
   <div class="kpi hl"><span>인정 시간 — 확정</span><b>{d['credit_rate_strict'] * 100:.0f}<i>%</i></b>
     <em>{H['완전충족']}h / {tot}h · 시간까지 충족</em></div>
   <div class="kpi hl"><span>인정 시간 — 조정 적용 시</span><b>{d['credit_rate_adjusted'] * 100:.0f}<i>%</i></b>
     <em>{H['완전충족'] + H['조정범위내']}h / {tot}h · −50% 조항 적용</em></div>
   <div class="kpi"><span>추가 훈련·확인 필요</span><b>{d['remaining_hours']}<i>시간</i></b>
     <em>부족 {H['시간부족']}h + 미이수 {H['미이수']}h</em></div>
 </div>
 <div class="stackwrap"><div class="stack">{seg}</div><div class="slab">{slab}</div></div>
 <div class="plot">{rows}</div>
 <details class="tbl"><summary>데이터 표로 보기</summary>
  <div class="tw"><table><thead><tr><th>능력단위코드</th><th>능력단위명</th><th>NCS표준</th>
   <th>요구시간</th><th>하한(−50%)</th><th>이수시간</th><th>근거</th><th>판정</th><th>신뢰도</th>
   </tr></thead><tbody>{trows}</tbody></table></div></details>
 {miss}
</section>

<footer>
심사번호 {e(a['case_number'])} · 심사 기준 v{e(a['rubric_version'])} ·
 계산 {a['finished_at']:%Y-%m-%d %H:%M} · 출력 {datetime.now():%Y-%m-%d %H:%M}
{"<br>과정평가형 편성시간은 기준값이며 기관이 80~150% 범위에서 편성합니다. "
 f"<b>추정</b>으로 표시된 {warn_n}건은 편성 하한으로 계산하면 판정이 바뀌므로 "
 "개인 이수증명서를 확인해야 합니다." if warn_n else ""}
<br>이 문서는 판정이 아니라 판정 근거입니다. 전체인정·부분인정·불인정은 전문가 TF가 결정합니다.
</footer></div></body></html>"""
