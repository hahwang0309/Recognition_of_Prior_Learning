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

from krpl_core.config import get_rubric

e = lambda x: html.escape(str(x) if x is not None else "")   # noqa: E731

# 판정 → (색 class, 아이콘, 짧은 이름)
V = {"완전충족": ("good", "●", "인정"),      # 100% 이상
     "조정범위내": ("good", "●", "인정"),     # 50~99% — −50% 조정 조항으로 요구시간 전체 인정. 표시는 하나로

     "보류": ("hold", "◆", "보류"),
     "시간부족": ("crit", "■", "불인정"),     # 30% 미만
     "미이수": ("none", "○", "불인정")}       # 코드 불일치
ORDER = ["완전충족", "조정범위내", "보류", "시간부족", "미이수"]
# 2차 TF(2026-09-21): 결과는 인정 / 보류 / 불인정 시간 세 묶음으로 보인다.
BUCKETS = [("인정", "good", "인정 — 요구시간 전체 감면 (50% 이상)"),
           ("보류", "hold", "보류 — 30~50%, 추가 증빙 후 위원 판단"),
           ("불인정", "crit", "불인정 — 30% 미만 또는 능력단위 없음")]

CSS = """*{box-sizing:border-box}
.viz{--s1:#fcfcfb;--s2:#f4f4f1;--bd:#e3e3dd;--tp:#0b0b0b;--ts:#52514e;--tm:#84837c;
 --good:#0ca30c;--warn:#fab219;--hold:#3b6fd0;--crit:#d03b3b;--none:#a9a9a2;--req:#d03b3b;
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
.kpi.hl:first-child b{color:var(--good)}.kpi.hold b{color:var(--hold)}.kpi.crit b{color:var(--crit)}
.hold-tbl td{white-space:normal;vertical-align:top}.hold-tbl .chk{white-space:nowrap}.chk label{margin-right:8px}
.hold-tbl .ok{color:var(--good)}.hold-tbl .no{color:var(--tm)}
.stackwrap{margin:0 0 18px}
.stack{display:flex;height:12px;border-radius:6px;overflow:hidden;background:var(--s2);gap:2px}
.sg{height:100%}
.sg.good{background:var(--good)}.sg.warn{background:var(--warn)}.sg.hold{background:var(--hold);background-image:repeating-linear-gradient(-45deg,rgba(255,255,255,.35) 0 3px,transparent 3px 7px)}
.sg.crit{background:var(--crit);background-image:repeating-linear-gradient(45deg,rgba(255,255,255,.42) 0 3px,transparent 3px 7px)}
.sg.none{background:var(--none)}
.slab{margin-top:6px;font-size:11.5px;color:var(--tm)}
.slab .good{color:var(--good)}.slab .warn{color:#a06f00}.slab .hold{color:var(--hold)}.slab .crit{color:var(--crit)}.slab .none{color:var(--tm)}
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
.fill.hold{background:var(--hold);background-image:repeating-linear-gradient(-45deg,rgba(255,255,255,.35) 0 3px,transparent 3px 7px)}
.fill.crit{background:var(--crit);background-image:repeating-linear-gradient(45deg,rgba(255,255,255,.42) 0 3px,transparent 3px 7px)}
.fill.none{background:transparent;border:1.5px dashed var(--none);border-radius:5px}
.fill.cred{background:var(--good);opacity:.22;border-radius:0 4px 4px 0}
.hrs em{display:block;font-style:normal;font-size:11px;color:var(--good);font-weight:600}.hrs em.z{color:var(--tm);font-weight:500}
.reql{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--req);border-radius:1px}
.reqv{position:absolute;left:4px;top:-15px;font-size:10px;color:var(--req);white-space:nowrap;font-variant-numeric:tabular-nums}
.minl{position:absolute;top:2px;bottom:2px;width:0;border-left:1.5px dotted var(--tm);opacity:.75}
.hrs{text-align:right;font-size:12.5px;font-variant-numeric:tabular-nums;white-space:nowrap}
.hrs b{font-size:14.5px}.hrs span{color:var(--tm);font-size:11.5px}
.st{font-size:11.5px;white-space:nowrap;display:flex;align-items:center;gap:5px;font-weight:600}
.st i{font-style:normal;font-size:10px}
.st.good{color:var(--good)} .st.warn{color:#a06f00} .st.hold{color:var(--hold)} .st.crit{color:var(--crit)} .st.none{color:var(--tm);font-weight:500}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])) .st.warn{color:var(--warn)}}
:root[data-theme=dark] .st.warn{color:var(--warn)}
.lgd{display:flex;flex-wrap:wrap;gap:16px;padding:13px 16px;background:var(--s2);
 border:1px solid var(--bd);border-radius:10px;margin-bottom:24px;font-size:12.5px;color:var(--ts)}
.lg{display:flex;align-items:center;gap:6px}
.sw{width:22px;height:11px;border-radius:3px;flex:none}
.sw.good{background:var(--good)}.sw.warn{background:var(--warn)}
.sw.hold{background:var(--hold);background-image:repeating-linear-gradient(-45deg,rgba(255,255,255,.35) 0 3px,transparent 3px 7px)}
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
    if not src:
        return "—"
    if src.startswith("이수:"):
        return "이수증(실적)"
    # 자격 편성기준은 source 에 자격 ID 가 그대로 온다 (catalog.held_units)
    return f"기준값(편성기준 · {src.removeprefix('자격:')})"


def render_track_a(s: Session, assessment_id: int) -> str:
    reviews = {r[0]: r[1] for r in s.execute(text(
        "SELECT element_id, decision FROM element_review WHERE assessment_id=:i"), {"i": assessment_id})}
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
    H.setdefault("보류", 0)
    B = d.get("bucket_hours") or {"인정": H["완전충족"] + H["조정범위내"], "보류": H["보류"],
                                  "불인정": H["시간부족"] + H["미이수"]}
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
        credited = p["required_hours"] if v in ("완전충족", "조정범위내") else 0
        tip = (f'{p["unit_name"]}\n요구 {p["required_hours"]}h · 하한 {p["min_hours"]}h\n'
               f'이수 {c or 0}h ({_basis(p.get("evidence"))}) · 인정 {credited}h\n'
               f'판정 {short} / {x["confidence"]}')
        rows += f"""<div class="row" title="{e(tip)}">
  <div class="nm"><span class="code">{e(x['element_id'])}</span>{e(p['unit_name'])}</div>
  <div class="track">
    <div class="fill cred" style="width:{credited / mx * 100:.2f}%"></div>
    <div class="fill {cls}" style="width:{c / mx * 100:.2f}%"></div>
    <div class="minl" style="left:{p['min_hours'] / mx * 100:.2f}%"></div>
    <div class="reql" style="left:{p['required_hours'] / mx * 100:.2f}%"><span class="reqv">{p['required_hours']}h</span></div>
  </div>
  <div class="hrs"><b>{c or '–'}</b><span>/{p['required_hours']}h</span><em class="{'' if credited else 'z'}">인정 {credited}h</em></div>
  <div class="st {cls}"><i>{ico}</i>{short}</div>
</div>"""

    seg = "".join(
        f'<div class="sg {cls}" style="width:{B[b] / tot * 100:.3f}%" id="sg-{cls}" title="{b}"></div>'
        for b, cls, _ in BUCKETS)
    slab = " · ".join(f'<span class="{cls}">{b} <span id="sl-{cls}">{B[b]}</span>h</span>' for b, cls, _ in BUCKETS)

    trows = "".join(f"""<tr><td class=m>{e(x['element_id'])}</td><td>{e(x['payload']['unit_name'])}</td>
      <td class=n>{std.get(x['element_id']) or '–'}</td>
      <td class=n>{x['payload']['required_hours']}</td><td class=n>{x['payload']['min_hours']}</td>
      <td class=n>{x['payload']['completed_hours'] or '–'}</td>
      <td>{e(_basis(x['payload'].get('evidence')))}</td>
      <td>{e(V[x['evidence_level']][2])}{' (100%)' if x['evidence_level']=='완전충족' else ''}</td><td>{e(x['confidence'])}</td></tr>""" for x in els)

    # 카드 머리 — 원본은 시나리오 유형을 달았다. 접수 건에서는 판정 양상으로 정한다.
    # 이력 유형 — 목표 종목 옆 괄호. 자격이 있으면 과정평가형, 없으면 훈련이수증만.
    basis_kind = "과정평가형" if src.get("자격") else ("NCS 훈련이수" if src.get("기이수") else "이수 기록 없음")

    # ── 보류 단위 — 왜 부족한지, 무엇으로 보완할 수 있는지, 이미 낸 것은 무엇인지 (2차 TF) ──
    rb_ta = get_rubric().track_a
    hold_evi = list(rb_ta.get("hold_evidence") or [])
    submitted = set(d.get("제출문서") or [])
    holds = [x for x in els if x["evidence_level"] == "보류"]
    hold_sec = ""
    if holds:
        hrows = ""
        for x in holds:
            p = x["payload"]
            c = p["completed_hours"] or 0
            need = p["min_hours"] - c
            evi = "".join(
                f'<div class="{"ok" if k in submitted else "no"}">{"✓" if k in submitted else "–"} {e(k)}'
                f'{" (제출됨)" if k in submitted else ""}</div>' for k in hold_evi)
            hrows += f"""<tr><td>{e(x['element_id'])}<br>{e(p['unit_name'])}</td>
      <td class=n>{p['required_hours']}h</td><td class=n>{c}h ({p['ratio'] * 100:.0f}%)</td>
      <td>{e(_basis(p.get('evidence')))}</td>
      <td>하한 {p['min_hours']}h까지 <b>{need}h</b> 부족.<br>50% 이상이면 {p['required_hours']}h 전체 인정</td>
      <td>{evi}</td>
      <td class="chk"><label><input type="radio" name="dec-{e(x['element_id'])}" value="인정" data-code="{e(x['element_id'])}" data-hours="{p['required_hours']}" {'checked' if reviews.get(x['element_id']) == '인정' else ''}> 인정</label><label><input type="radio" name="dec-{e(x['element_id'])}" value="불인정" data-code="{e(x['element_id'])}" data-hours="{p['required_hours']}" {'checked' if reviews.get(x['element_id']) == '불인정' else ''}> 불인정</label></td></tr>"""
        hold_sec = f"""<details class="tbl" open><summary>보류 {len(holds)}개 단위 — 부족 이유와 추가 증빙 (위원 판단란 포함)</summary>
  <div class="tw"><table class="hold-tbl"><thead><tr><th>능력단위</th><th>요구</th><th>이수</th><th>근거</th>
   <th>부족 이유</th><th>보완 가능한 추가 증빙</th><th>위원 판정</th></tr></thead><tbody>{hrows}</tbody></table></div>
  <p id="final" class="sub" style="margin-top:10px;font-size:13.5px;color:var(--tp)"><b>위원 판정 결과</b> — 보류 {len(holds)}개 단위 중 <span id="f-undec">{len(holds)}</span>개 미결 ·
   최종 인정 <b><span id="f-rec">{B['인정']}</span>h (<span id="f-recp">{B['인정'] / tot * 100:.0f}</span>%)</b> · 불인정 <b><span id="f-rej">{B['불인정']}</span>h</b>
   <span class="sub">(이 화면에서만 계산됩니다. 저장은 심사 개요 화면의 최종 판정에서 합니다)</span></p>
  <p class="sub" style="margin-top:8px">보류 구간(30~50%)은 2차 TF 제안이며 미확정입니다. 대안인 「자격 단위 인정」(국가 검정 자격은 코드 일치 단위를
  시간과 무관하게 인정)을 적용하면 인정 시간은 <b>{B['인정'] + B['보류']}h ({(B['인정'] + B['보류']) / tot * 100:.0f}%)</b>가 됩니다.</p>
  </details>"""

    miss = ""
    if skipped:
        mrows = "".join(
            f"<tr><td>{e(x['unit_name'])}</td><td class=n>{x['required_hours']}</td>"
            f"<td class=n>{x['completed_hours'] if x['completed_hours'] is not None else '–'}</td>"
            f"<td>{e(x['doc_type'])}</td><td style='white-space:normal'>{e(x['reason'])}</td></tr>"
            for x in skipped)
        miss = f"""<details class="tbl" open><summary>이수 기록을 냈으나 시간 확인에 쓰지 못한 {len(skipped)}개 단위 (평가결과 미기재 등)</summary>
  <div class="tw"><table><thead><tr><th>능력단위</th><th>요구</th><th>이수</th><th>낸 자료</th><th>이유</th></tr></thead>
  <tbody>{mrows}</tbody></table></div></details>"""

    warn_n = sum(1 for x in els if x["confidence"] != "확정")

    # ── 판정 파라미터 — rubric 값 그대로. 위원이 논의로 바꿀 수 있도록 근거·상태를 붙인다 ──
    rb = get_rubric()
    th = rb.training_hours
    pend = {p.key for p in rb.pending_decisions}
    rng = th.get("cbq_composition_range") or {}
    def _st(pending: bool) -> str:
        return "TF 결정 필요" if pending else "현행 규칙"
    hold_pending = "track_a.verdicts.보류" in pend
    params = [
        ("인정선", f"이수시간 ≥ 요구시간의 {th['adjustment_floor']:.0%}",
         "선이수인정 운영매뉴얼 · 고시 「−50% 조정 가능」", _st(False)),
        ("인정 시간", "그 단위 요구시간 전체 (이수시간이 아님)", "운영매뉴얼 · 2차 TF 확인", _st(False)),
        ("보류 구간", f"요구시간의 {th.get('hold_floor', 0.30):.0%} 이상 ~ {th['adjustment_floor']:.0%} 미만",
         "2차 TF 제안 (대안: 자격 단위 인정)", _st(hold_pending)),
        ("불인정", f"{th.get('hold_floor', 0.30):.0%} 미만 또는 코드 불일치", "2차 TF 제안", _st(hold_pending)),
        ("보류 시 추가 증빙", " · ".join(rb_ta.get("hold_evidence") or []),
         "2차 TF (학습경험기술서·현장교사 확인서·작업일지)", _st(True)),
        ("이수시간", "자격 편성기준에 적힌 시간(기준값)과 이수증에 적힌 시간(실적값)이 둘 다 있으면 큰 쪽",
         "App 설계 — 자격을 땄으면 편성기준만큼 배운 것으로 본다", _st(True)),
        ("추정 표시", f"이수증 없이 기준값으로 판정한 단위는, 기관이 편성기준의 최소({rng.get('min', 0.8):.0%})로 편성했어도 같은 판정인지 확인. 다르면 「추정」— 이수증 요구 (이 건 {warn_n}건)",
         "과정평가형 편성 허용범위 {0:.0%}~{1:.0%}".format(rng.get('min', 0.8), rng.get('max', 1.5)), _st(False)),
    ]
    param_rows = "".join(
        f"<tr><td>{e(k)}</td><td>{e(v)}</td><td>{e(src_)}</td>"
        f"<td>{'<b>' + st + '</b>' if st == 'TF 결정 필요' else st}</td><td style='min-width:160px'></td></tr>"
        for k, v, src_, st in params)
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RPL Track A 심사 보고서 — {e(a['case_number'])}</title><style>{CSS}</style></head>
<body><div class="viz">
<div class="bk"><a href="/submissions/{sid}">← 심사 개요</a>
 <a href="/cases">접수 현황</a><button onclick="print()">인쇄</button></div>

<h1>RPL Track A 심사 보고서</h1>
<div style="margin:0 0 10px"><span id="save" style="font-size:12px;color:var(--tm)"></span></div>
<section class="card">
 <header class="ch">
   <div class="tag">{e(a['case_number'])}</div>
   <h2>{e(a['official_name'] or a['target_program_id'])}({e(basis_kind)})</h2>
   <p class="sub">필수능력단위 {n_units}개 · {tot}시간 · 코드 일치 {n_covered}개</p>
 </header>
 <div class="kpis">
   <div class="kpi hl"><span>인정</span><b><span id="k-rec">{B['인정']}</span><i>h · <span id="k-recp">{B['인정'] / tot * 100:.0f}</span>%</i></b>
     <em><span id="k-recn">{d['by_verdict'].get('완전충족', 0) + d['by_verdict'].get('조정범위내', 0)}</span>개 단위 · 요구시간 전체 감면</em></div>
   <div class="kpi hl hold"><span>보류</span><b><span id="k-hold">{B['보류']}</span><i>h · <span id="k-holdp">{B['보류'] / tot * 100:.0f}</span>%</i></b>
     <em><span id="k-holdn">{d['by_verdict'].get('보류', 0)}</span>개 단위 · 아래 표에서 판단</em></div>
   <div class="kpi hl crit"><span>불인정</span><b><span id="k-rej">{B['불인정']}</span><i>h · <span id="k-rejp">{B['불인정'] / tot * 100:.0f}</span>%</i></b>
     <em><span id="k-rejn">{d['by_verdict'].get('시간부족', 0) + d['by_verdict'].get('미이수', 0)}</span>개 단위 · 훈련 이수</em></div>
 </div>
 <div class="stackwrap"><div class="stack">{seg}</div><div class="slab">{slab}</div></div>
 <div class="plot">{rows}</div>
 {hold_sec}
 <details class="tbl"><summary>데이터 표로 보기</summary>
  <div class="tw"><table><thead><tr><th>능력단위코드</th><th>능력단위명</th><th>NCS표준</th>
   <th>요구시간</th><th>하한(−50%)</th><th>이수시간</th><th>근거</th><th>판정</th><th>신뢰도</th>
   </tr></thead><tbody>{trows}</tbody></table></div></details>
 {miss}
</section>

<footer>
<h3 style="font-size:14px;margin:0 0 8px;color:var(--tp)">판정 파라미터 — 위원 논의로 수정 가능</h3>
<div class="tw"><table class="hold-tbl"><thead><tr><th>항목</th><th>현재값</th><th>근거</th><th>구분</th><th>수정 의견</th></tr></thead>
<tbody>{param_rows}</tbody></table></div>
<p style="margin-top:10px">심사번호 {e(a['case_number'])} · 기준 v{e(a['rubric_version'])} · 계산 {a['finished_at']:%Y-%m-%d %H:%M} · 최종 판정은 전문가 TF가 한다.</p>
</footer></div>
<script>
(function(){{
  var TOT={tot}, R0={B['인정']}, H0={B['보류']}, J0={B['불인정']}, N0={d['by_verdict'].get('완전충족', 0) + d['by_verdict'].get('조정범위내', 0)}, NH={len(holds)}, NJ0={d['by_verdict'].get('시간부족', 0) + d['by_verdict'].get('미이수', 0)};
  var $=function(i){{return document.getElementById(i)}};
  function status(code, cls, ico, txt, hours){{
    var rows=document.querySelectorAll('.row'); for(var i=0;i<rows.length;i++){{
      var c=rows[i].querySelector('.code'); if(!c||c.textContent!==code) continue;
      var st=rows[i].querySelector('.st'), f=rows[i].querySelector('.fill:not(.cred)'), cr=rows[i].querySelector('.fill.cred'), em=rows[i].querySelector('.hrs em');
      st.className='st '+cls; st.innerHTML='<i>'+ico+'</i>'+txt; f.className='fill '+cls;
      var req=rows[i].querySelector('.reql').style.left; cr.style.width=(cls==='good')?req:'0%';
      em.textContent='인정 '+(cls==='good'?hours:0)+'h'; em.className=(cls==='good')?'':'z'; }}
  }}
  function recalc(){{
    var rec=R0, rej=J0, hold=H0, nrec=N0, nrej=NJ0, undec=NH;
    var rs=document.querySelectorAll('input[type=radio][data-code]:checked');
    for(var i=0;i<rs.length;i++){{ var h=+rs[i].dataset.hours; hold-=h; undec--;
      if(rs[i].value==='인정'){{rec+=h;nrec++;status(rs[i].dataset.code,'good','●','인정',h)}}
      else{{rej+=h;nrej++;status(rs[i].dataset.code,'crit','■','불인정',h)}} }}
    var all=document.querySelectorAll('input[type=radio][data-code]'); var seen={{}};
    for(var k=0;k<all.length;k++){{ var cd=all[k].dataset.code; if(seen[cd]) continue; seen[cd]=1;
      if(!document.querySelector('input[name="dec-'+cd+'"]:checked')) status(cd,'hold','◆','보류',0); }}
    var pct=function(v){{return Math.round(v/TOT*100)}};
    $('k-rec').textContent=rec; $('k-recp').textContent=pct(rec); $('k-recn').textContent=nrec;
    $('k-hold').textContent=hold; $('k-holdp').textContent=pct(hold); $('k-holdn').textContent=undec;
    $('k-rej').textContent=rej; $('k-rejp').textContent=pct(rej); $('k-rejn').textContent=nrej;
    $('sg-good').style.width=(rec/TOT*100)+'%'; $('sg-hold').style.width=(hold/TOT*100)+'%'; $('sg-crit').style.width=(rej/TOT*100)+'%';
    $('sl-good').textContent=rec; $('sl-hold').textContent=hold; $('sl-crit').textContent=rej;
    if($('f-rec')){{ $('f-rec').textContent=rec; $('f-recp').textContent=pct(rec); $('f-rej').textContent=rej; $('f-undec').textContent=undec; }}
  }}
  var AID={assessment_id}, canSave=location.protocol.indexOf('http')===0;
  function note(msg, ok){{ var s=$('save'); if(!s) return; s.textContent=msg; s.style.color= ok?'var(--good)':'var(--crit)'; }}
  var queue=Promise.resolve();
  function save(r){{
    if(!canSave){{ note('브라우저 계산만 (서버 없음 — 저장 안 됨)', false); return; }}
    note('저장 중…', true);
    queue = queue.then(function(){{
      return fetch('/assessments/'+AID+'/elements/'+encodeURIComponent(r.dataset.code)+'/review',
        {{method:'POST',headers:{{'Content-Type':'application/json'}},
          body:JSON.stringify({{decision:r.value, reviewer:null}})}})
       .then(function(x){{ if(!x.ok) throw new Error(x.status); note('저장됨', true); }})
       .catch(function(err){{ note('저장 실패 — '+err.message, false); }});
    }});
  }}
  var inputs=document.querySelectorAll('input[type=radio][data-code]');
  for(var i=0;i<inputs.length;i++) inputs[i].addEventListener('change',function(ev){{ recalc(); save(ev.target); }});
  recalc();
}})();
</script></body></html>"""
