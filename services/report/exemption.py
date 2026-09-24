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

from services.report._shared import STEP_CSS, TRACK_CSS, step_head, step_nav, track_chip
from services.report.layout import e
from services.report.track_a_report import CSS
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
"""


def render_exemption(s: Session, assessment_id: int) -> str:
    """기록 확인 판정 하나의 면제 결과."""
    a = s.execute(text("""
        SELECT a.id, a.submission_id, a.rubric_version, a.overall_note, a.finished_at,
               s.case_number, s.target_program_id, s.track, p.official_name
        FROM assessment a JOIN submission s ON s.id=a.submission_id
        LEFT JOIN catalog_wsd_program p ON p.program_id=s.target_program_id
        WHERE a.id=:i"""), {"i": assessment_id}).mappings().one()
    els = [dict(r) for r in s.execute(text("""
        SELECT element_id, evidence_level, payload FROM assessment_element
        WHERE assessment_id=:i ORDER BY (payload->>'required_hours')::int DESC, element_id"""),
        {"i": assessment_id}).mappings()]
    d = json.loads(a["overall_note"])
    tot = d["total_hours"]
    sid = a["submission_id"]

    gap_by_code = {g.unit_code: g for g in unit_gaps(s, assessment_id)}
    has_ev = evidence_aid(s, sid) is not None

    rows, ex_full, ex_part, rest = "", 0, 0, 0
    n_full = n_part = 0
    for x in els:
        p, v, code = x["payload"], x["evidence_level"], x["element_id"]
        req = p["required_hours"]
        if v in FULL:
            hours, why = req, f"이수 기록 {p['completed_hours'] or 0}h — 요구시간 전체 면제"
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
        rest += req - hours
        cls = "" if hours else " class=none"
        rows += (f"<tr{cls}><td>{e(p['unit_name'])}</td><td class=n>{req}h</td>"
                 f"<td class=n><b>{hours}h</b></td>"
                 f"<td class=n>{req - hours or '–'}</td>"
                 f"<td class=src>{e(why)}</td></tr>")

    granted = ex_full + ex_part
    pct = granted / tot * 100 if tot else 0
    bar = (f'<i class="r" style="width:{ex_full / tot * 100 if tot else 0:.2f}%"></i>'
           f'<i class="x" style="width:{ex_part / tot * 100 if tot else 0:.2f}%"></i>'
           f'<i class="t" style="width:{rest / tot * 100 if tot else 0:.2f}%"></i>')

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>면제 결과 — {e(a['case_number'])}</title><style>{CSS}{EX_CSS}{TRACK_CSS}{STEP_CSS}</style></head>
<body><div class="viz">
<div class="bk"><a href="/submissions/{sid}">← 심사 개요</a>
 <button onclick="print()">인쇄</button></div>

{step_head("final", "면제 결과",
           nav=step_nav(sid, assessment_id, has_ev))}
<p class="sub">{e(a['case_number'])} · {e(a['official_name'] or a['target_program_id'])} ·
 필수 훈련 {tot}시간 · 접수 구분 {track_chip(a['track'], full=True)}</p>

<section class="card">
 <div class="ex-sum">
  <div><span>면제되는 시간</span><b>{granted}h</b> <span>{pct:.0f}% · {n_full + n_part}개 단위</span></div>
  <div><span>기록으로 확정</span><b>{ex_full}h</b> <span>{n_full}개 단위</span></div>
  <div><span>위원 판단 포함</span><b>{ex_part}h</b> <span>{n_part}개 단위</span></div>
  <div><span>남은 훈련</span><b>{rest}h</b> <span>{100 - pct:.0f}%</span></div>
 </div>
 <div class="ex-bar">{bar}</div>

 <div class="tw"><table class="ex-tbl"><thead><tr>
  <th>능력단위</th><th>요구</th><th>면제</th><th>남은 훈련</th><th>근거</th>
 </tr></thead><tbody>{rows}</tbody></table></div>

 <p class="sub" style="margin-top:10px">인정시간(이수 + 위원 인정)이 요구시간의 50% 이상인
 능력단위는 <b>요구시간 전체</b>가 면제됩니다 — 훈련기준의 「−50%까지 조정 가능」 조항입니다.
 못 미치면 면제는 0h 이고 그 시간만큼 훈련이 남습니다. 최종 판정은 전문가 TF가 합니다.</p>
</section>

<footer><p>심사번호 {e(a['case_number'])} · 기준 v{e(a['rubric_version'])} ·
 작성 {datetime.now():%Y-%m-%d %H:%M} · 최종 판정은 전문가 TF가 한다.</p></footer>
</div></body></html>"""
