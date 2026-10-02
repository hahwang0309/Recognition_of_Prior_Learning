"""② 근거 분석 — 추가 인정이 필요한 단위를 **문서별 근거**로 본다.

## 이 화면이 답하는 질문 하나

> 시간이 모자란 능력단위를, 어느 문서가 얼마나 뒷받침하는가?

그래서 싣는 것은 셋뿐이다.

1. 대상 — 추가 인정이 필요한 능력단위 (이미 50% 이상인 단위는 뺀다)
2. 히트맵 — 세로 능력단위 × 가로 제출문서, 근거 조각이 많을수록 진하게
3. 문서별 근거 조각 — 인용 · 그 조각이 뒷받침하는 단위 · 원문 열기

**능력단위별로 모아 보는 것은 다음 단계(③ 전문가 검토)에서 한다.** 여기서 한 번,
거기서 또 한 번 같은 것을 늘어놓으면 어느 쪽을 봐야 할지 알 수 없다.

## 뺀 것

보완계획·능력단위요소별 판정 근거·KSA 커버리지·권고(R0~R5) 집계는 싣지 않는다.
판단에 쓰이는 자리가 따로 있고, 여기 같이 두면 볼 것이 많아 정작 근거를 못 읽는다.
연구팀 회람본 원본은 `docs/formats/trackB_보고서.html` 에 문서로 남아 있다.
앱 화면으로는 더 그리지 않는다 — 단계줄이 옛 화면을 가리키는 사고가 났다.
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.report._shared import STEP_CSS, step_head, step_nav
from services.report.doc_viewer import (VIEWER_CSS, VIEWER_HTML, VIEWER_JS,
                                        js_literal, viewer_data)
from services.report.track_a_report import CSS
from services.review.coverage import unit_verdicts
from services.review.unit_hours import unit_evidence, unit_gaps

e = lambda x: html.escape(str(x) if x is not None else "")   # noqa: E731

FOCUS_CSS = """
.hm{border-collapse:separate;border-spacing:2px}
.hm th{font-size:11.5px;font-weight:600;color:var(--ts);padding:2px 4px;vertical-align:bottom}
.hm th.doc{width:108px;max-width:108px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
 text-align:center;padding:4px 6px;font-weight:600}
.hm th.doc.sum{width:52px;max-width:52px}
.hm th.unit{text-align:left;white-space:normal;max-width:230px;font-weight:400;color:var(--tp)}
.hm th.unit small{display:block;color:var(--tm);font-size:11px}
.hm td{height:30px;text-align:center;border-radius:5px;font-size:12px;
 font-variant-numeric:tabular-nums;background:var(--s2);color:var(--tm)}
.hm td.v{color:#fff;font-weight:600}
.hm td.neg{outline:2px solid var(--crit);outline-offset:-2px}
.hm td.z{background:transparent;color:transparent}
.hm td.sum{background:transparent;color:var(--tp);font-weight:700}
.hm-lg{display:flex;gap:10px;align-items:center;font-size:11.5px;color:var(--tm);margin:10px 0 0}
.hm-lg i{display:inline-block;width:22px;height:11px;border-radius:3px}
.doc-c{border:1px solid var(--bd);border-radius:12px;padding:14px 16px;margin:0 0 12px}
.doc-c>h3{margin:0 0 2px;font-size:15px}
.doc-c>h3 span{font-weight:400;font-size:12px;color:var(--tm);margin-left:6px}
.doc-c>.n{margin:0 0 10px;font-size:12px;color:var(--tm)}
.ev{margin:0 0 10px;padding-left:9px;border-left:3px solid var(--bd)}
.ev.dir{border-left-color:var(--good)} .ev.ind{border-left-color:var(--warn)}
.ev.neg{border-left-color:var(--crit);background:#fff6f5;border-radius:0 6px 6px 0;padding:4px 8px 4px 9px}
.ev q{display:block;line-height:1.5}
.ev .m{font-size:11.5px;color:var(--tm);margin-top:3px}
.ev .fit{font-weight:700;margin-right:6px}
.ev .u{color:var(--tp)}
.none{color:var(--tm);font-size:13px}
"""


@dataclass(frozen=True)
class _BUnit:
    """Track B 의 한 줄. 화면이 읽는 이름만 Track A 의 UnitGap 과 맞춘다."""
    unit_code: str
    unit_name: str
    required: int
    ratio_final: float
    n_covered: int
    n_total: int
    verdict: str
    completed: int = 0
    to_pass: int = 0
    pc: bool = False          # 신형(수행준거 점수) 판정이면 True — 문구만 다르다


def _cell(n: int, mx: int) -> str:
    """조각 수 → 진하기. 0 은 빈칸으로 둔다 — 없는 것을 굳이 그리지 않는다."""
    if not n:
        return '<td class="z">·</td>'
    a = 0.18 + 0.82 * (n / mx if mx else 1)
    return (f'<td class="v" style="background:rgba(27,94,163,{a:.2f})" '
            f'title="근거 {n}건">{n}</td>')


def render_evidence_focus(s: Session, submission_id: int) -> str:
    sub = s.execute(text("""
        SELECT s.id, s.case_number, s.target_program_id, s.track, p.official_name
        FROM submission s LEFT JOIN catalog_wsd_program p ON p.program_id=s.target_program_id
        WHERE s.id=:i"""), {"i": submission_id}).mappings().one()
    time_aid = s.execute(text("""SELECT id FROM assessment WHERE submission_id=:i
        AND kind='time' ORDER BY id DESC LIMIT 1"""), {"i": submission_id}).scalar()
    has_plan = bool(s.execute(text("""SELECT 1 FROM artifact a JOIN assessment x ON x.id=a.assessment_id
        WHERE x.submission_id=:i AND a.stage='plan' LIMIT 1"""), {"i": submission_id}).first())
    ev_aid = s.execute(text("""SELECT a.id FROM assessment a
        WHERE a.submission_id=:i AND a.kind='evidence'
          AND a.status IN ('done','manual_review')
          AND EXISTS (SELECT 1 FROM assessment_element x WHERE x.assessment_id=a.id)
        ORDER BY a.id DESC LIMIT 1"""), {"i": submission_id}).scalar()

    is_b = (sub["track"] or "A").upper() == "B"
    if is_b:
        # Track B 에는 기록 확인이 없다. 「추가 인정이 필요한 단위」는 아직 항목
        # 근거로 인정되지 않은 단위다 — 위원이 근거를 더 봐야 하는 것들.
        verds = {u["code"]: u for u in unit_verdicts(s, ev_aid)} if ev_aid else {}
        gaps = []
        for u in verds.values():
            if u["verdict"] == "인정":
                continue
            gaps.append(_BUnit(u["code"], u["name"], u["hours"], u["ratio"], u["n_covered"], u["n_total"],
                               u["verdict"], pc=u.get("format", "ksa") != "ksa"))
    else:
        gaps = unit_gaps(s, time_aid) if time_aid else []
    by_unit = unit_evidence(s, submission_id, [g.unit_code for g in gaps]) if gaps else {}
    fr_json, dn_json = viewer_data(s, submission_id)
    doc_of = {f["fid"]: f["doc"] for f in fr_json}
    dn_by_key = {d["doc"]: d for d in dn_json}

    # 조각을 문서별로 다시 묶는다 — 이 화면의 축은 문서다.
    per_doc: dict[str, list[dict]] = {}
    grid: dict[tuple[str, str], int] = {}
    neg: set[tuple[str, str]] = set()
    for g in gaps:
        for it in by_unit.get(g.unit_code, []):
            fid = (it["fids"] or [None])[0]
            doc = doc_of.get(fid or "", "?")
            per_doc.setdefault(doc, []).append({**it, "unit": g.unit_name, "fid": fid})
            grid[(g.unit_code, doc)] = grid.get((g.unit_code, doc), 0) + 1
            if it["fit"] == "부정":
                neg.add((g.unit_code, doc))

    docs = [d for d in dn_json if d["doc"] in per_doc]
    mx = max(grid.values(), default=0)
    n_ev = sum(len(v) for v in per_doc.values())

    if not gaps:
        body = ('<section class="card"><p class="none">추가 인정이 필요한 능력단위가 없습니다 — '
                '모든 단위가 이수 기록만으로 인정선을 넘었습니다.</p></section>')
    elif not n_ev:
        body = ('<section class="card"><p class="none">'
                + ("근거 분석 결과가 없습니다. 심사 개요에서 근거 분석을 시작하세요."
                   if ev_aid is None else
                   "분석은 돌았지만 이 단위들을 뒷받침하는 근거 조각이 없습니다.")
                + '</p></section>')
    else:
        head = "".join(f'<th class="doc" title="{e(d["name"])} · {e(d["grade"])}등급">'
                       f'{e(d["name"])}</th>' for d in docs)
        rows = ""
        for g in gaps:
            cells = "".join(
                _cell(grid.get((g.unit_code, d["doc"]), 0), mx).replace(
                    '<td class="v"', '<td class="v neg"'
                    if (g.unit_code, d["doc"]) in neg else '<td class="v"')
                for d in docs)
            tot = sum(grid.get((g.unit_code, d["doc"]), 0) for d in docs)
            meta = (f'요구 {g.required}h · {"수행준거" if getattr(g, "pc", False) else "요소"} {g.n_covered}/{g.n_total} {"≥1" if getattr(g, "pc", False) else "인정"} '
                    f'({g.ratio_final:.0%}) · {g.verdict}' if is_b else
                    f'요구 {g.required}h · 이수 {g.completed or 0}h '
                    f'({g.ratio_final:.0%}) · 인정선까지 +{g.to_pass}h')
            rows += (f'<tr><th class="unit">{e(g.unit_name)}'
                     f'<small>{meta}</small></th>'
                     f'{cells}<td class="sum">{tot}</td></tr>')

        cards = ""
        for d in docs:
            items = per_doc[d["doc"]]
            inner = ""
            for it in sorted(items, key=lambda x: {"부정": 0, "직접": 1, "간접": 2}.get(x["fit"], 3)):
                cls = {"부정": "neg", "간접": "ind"}.get(it["fit"], "dir")
                src = (f'<a class="fx" data-fid="{e(it["fid"])}">원문</a>'
                       if it["fid"] else "")
                inner += (f'<div class="ev {cls}"><q>{e(it["quote"])}</q>'
                          f'<div class="m"><span class="fit">{e(it["fit"])}</span>'
                          f'<span class="u">{e(it["unit"])}</span> · {src}</div></div>')
            cards += (f'<div class="doc-c"><h3>{e(d["name"])}'
                      f'<span>{e(d["grade"])}등급 · {e(d["type"])}</span></h3>'
                      f'<p class="n">근거 {len(items)}건</p>{inner}</div>')

        body = f"""<section class="card">
 <header class="ch"><h2>어느 문서가 어느 단위를 뒷받침하나</h2>
 <p class="sub">칸이 진할수록 그 문서에서 나온 근거가 많습니다. 빨간 테두리는 부정 진술이
 섞여 있다는 뜻입니다 — 먼저 보십시오.</p></header>
 <div class="tw"><table class="hm"><thead><tr><th class="unit"></th>{head}<th class="doc sum">합계</th></tr></thead>
  <tbody>{rows}</tbody></table></div>
 <div class="hm-lg"><span>근거 적음</span>
  <i style="background:rgba(27,94,163,.25)"></i><i style="background:rgba(27,94,163,.55)"></i>
  <i style="background:rgba(27,94,163,1)"></i><span>많음</span></div>
</section>

<section class="card">
 <header class="ch"><h2>문서별 근거 조각 {n_ev}건</h2>
 <p class="sub">인용을 눌러 원문을 확인하십시오. 능력단위별로 모아 보는 것은 다음 단계인
 전문가 검토 화면에서 합니다.</p></header>
 {cards}
</section>"""

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>② 근거 분석 — {e(sub['case_number'])}</title>
<style>{CSS}{VIEWER_CSS}{STEP_CSS}{FOCUS_CSS}</style></head>
<body><div class="viz">
<div class="bk"><a href="/submissions/{submission_id}">← 심사 개요</a>
 <button onclick="print()">인쇄</button></div>

{step_head("evidence", "RPL Track B 심사 보고서" if is_b else "RPL Track A 심사 보고서",
           track=sub['track'] or 'A',
           nav=step_nav(submission_id, time_aid, ev_aid is not None,
                        track=sub['track'] or 'A', ev_aid=ev_aid, has_plan=has_plan))}
<p class="sub" style="margin:0 0 16px">{e(sub['case_number'])} ·
 {e(sub['official_name'] or sub['target_program_id'])} ·
 추가 인정이 필요한 단위 <b>{len(gaps)}개</b> · 근거 <b>{n_ev}건</b> ·
 제출 문서 <b>{len(docs)}건</b>
</p>

{body}

<footer><p>심사번호 {e(sub['case_number'])} · 작성 {datetime.now():%Y-%m-%d %H:%M} ·
 최종 판정은 전문가 TF가 한다.</p></footer>
</div>
{VIEWER_HTML}
<script>
(function(){{
 var $=function(i){{return document.getElementById(i)}};
 var FR={js_literal(fr_json)}, DN={js_literal(dn_json)};
{VIEWER_JS}
}})();
</script></body></html>"""
