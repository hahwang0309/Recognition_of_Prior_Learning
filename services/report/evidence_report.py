"""Track B 심사 보고서 — 연구팀이 회람·확정한 포맷 그대로.

원본: `Data(20260812)/derived/trackB_보고서.html` (docs/formats/ 에 보존)
CSS·클래스명·마크업 구조·범례·아이콘을 그대로 옮겼다. 임의로 고치지 않는다.
원본은 지원자 4명을 한 문서에 늘어놓은 설계 시안이고, 앱은 접수 한 건을 그린다.

## 세 장 구성 (원본 그대로)

  Ⅰ. 히트맵        가로축 능력단위 · 세로축 능력단위요소 · 칸 색은 권고 구분
  Ⅱ. 보완계획      중복 항목은 병합. 서류로 대체 가능한 것은 면접·실기에서 제외 가능
  Ⅲ. 능력단위요소별 판정 근거

읽기 전용이다. 판단 입력은 전문가 검토 화면이 맡는다.
"""
from __future__ import annotations

import html
import json
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.catalog import label_of, labels
from services.report.layout import page

e = lambda x: html.escape(str(x) if x is not None else "")   # noqa: E731

# 권고 → (class, 아이콘, 이름, 부연). 원본의 아이콘·색을 그대로 쓴다.
REC = {"R0": ("r0", "★", "기이수 인정", "이미 평가를 마침"),
       "R1": ("r1", "●", "서류 인정", "낸 서류로 판단"),
       "R2": ("r2", "▲", "면접확인", "화상면접"),
       "R3": ("r3", "■", "실기확인", "대면실기·시연"),
       "R4": ("r4", "◆", "추가서류", "서류 보완 후 재판단"),
       "R5": ("r5", "○", "미인정", "훈련 이수 필요")}
RORDER = ["R0", "R1", "R2", "R3", "R4", "R5"]

# 보완 방법 → (class, 아이콘, 제목, 항목 열 이름). 원본의 배치·색을 그대로 쓴다.
PLAN = [("추가서류", "m3", "📄", "추가서류로 해소", "요청 서류"),
        ("면접",     "m1", "💬", "면접으로 확인",   "질문"),
        ("실기",     "m2", "🔧", "실기로 확인",     "과제"),
        ("훈련",     "m4", "📚", "훈련 이수 필요",  "훈련 항목")]

CSS = """*{box-sizing:border-box}
:root{--s1:#fcfcfb;--s2:#f4f4f1;--s3:#ebebe6;--bd:#e0e0da;--tp:#0b0b0b;--ts:#4a4a46;--tm:#84837c;
 --r0:#1a5fb4;--r1:#0ca30c;--r2:#fab219;--r3:#d03b3b;--r4:#2a78d6;--r5:#a9a9a2;
 --m1:#b8860b;--m2:#c0392b;--m3:#2a78d6;--m4:#7a5cb8}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--s1:#1a1a19;--s2:#232322;--s3:#2c2c2a;--bd:#3a3a38;--tp:#fff;--ts:#c3c2b7;--tm:#8f8e86;--r5:#6b6b66;--m1:#fab219}}
body{margin:0;background:var(--s1);color:var(--tp);font:14px/1.6 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",Pretendard,"Malgun Gothic",sans-serif}
.wrap{max-width:1120px;margin:0 auto;padding:32px 20px 80px}
h1{font-size:26px;margin:0 0 6px}.lead{color:var(--ts);margin:0 0 22px}
.note{background:var(--s2);border:1px solid var(--bd);border-radius:10px;padding:14px 16px;margin-bottom:22px;font-size:13px;color:var(--ts)}
.note b{color:var(--tp)}
.nav{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px}
.nav a,.nav button{padding:7px 13px;border:1px solid var(--bd);border-radius:999px;text-decoration:none;
 color:var(--ts);font:inherit;font-size:13px;background:var(--s2);cursor:pointer}
.nav a.go{background:var(--tp);color:var(--s1);border-color:transparent;font-weight:600}
.app{border-top:2px solid var(--bd);padding-top:26px;margin-top:14px}
.app h2{font-size:21px;margin:0 0 4px}
.tp{font-size:12px;font-weight:500;color:var(--ts);background:var(--s3);border-radius:999px;padding:2px 9px;vertical-align:middle}
.arw{color:var(--tm);font-weight:400}.sub{color:var(--tm);font-size:12.5px;margin:0 0 14px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(132px,1fr));gap:8px;margin-bottom:10px}
.kpi{background:var(--s2);border:1px solid var(--bd);border-left-width:4px;border-radius:8px;padding:8px 11px}
.kpi span{display:block;font-size:11px;color:var(--tm)}.kpi b{font-size:21px}
.kpi em{display:block;font-style:normal;font-size:10.5px;color:var(--tm)}
.kpi.r0{border-left-color:var(--r0)}.kpi.r1{border-left-color:var(--r1)}.kpi.r2{border-left-color:var(--r2)}.kpi.r3{border-left-color:var(--r3)}
.kpi.r4{border-left-color:var(--r4)}.kpi.r5{border-left-color:var(--r5)}
.stack{display:flex;height:9px;border-radius:5px;overflow:hidden;gap:2px;background:var(--s2);margin-bottom:16px}
.sg.r0{background:var(--r0)}.sg.r1{background:var(--r1)}.sg.r2{background:var(--r2)}.sg.r3{background:var(--r3)}.sg.r4{background:var(--r4)}.sg.r5{background:var(--r5)}
h3.big{font-size:17px;margin:32px 0 12px;padding-bottom:7px;border-bottom:2px solid var(--bd)}
h3.big small{font-weight:400;color:var(--tm);font-size:12px}
h4{font-size:14px;margin:22px 0 8px}h4 small{font-weight:400;color:var(--tm);font-size:11.5px}
h4.m4{color:var(--m4)}h4.m1{color:var(--m1)}h4.m2{color:var(--m2)}h4.m3{color:var(--m3)}
h5{font-size:12px;color:var(--tm);margin:14px 0 6px}
.hmw{overflow-x:auto;margin-bottom:8px;border:1px solid var(--bd);border-radius:9px;padding:10px}
.hm{border-collapse:separate;border-spacing:3px;width:auto;min-width:100%}
.hm th{padding:4px 6px;font-size:11px;color:var(--tm);font-weight:600;text-align:center;vertical-align:bottom}
.hm th.rl{text-align:right;white-space:nowrap;font-size:10.5px;padding-right:8px}
.un{font-size:11.5px;color:var(--tp);font-weight:600;max-width:110px;line-height:1.25}
.uh{font-size:10px;color:var(--tm);font-variant-numeric:tabular-nums}
.hc{width:112px;height:46px;border-radius:6px;padding:4px 6px;vertical-align:middle;
 font-size:10.5px;line-height:1.25;color:#fff;overflow:hidden}
.hc.empty{background:transparent}
.hc.none{background:var(--s2)}
.hc.r0{background:var(--r0)}.hc.r1{background:var(--r1)}.hc.r2{background:#a06f00}
.hc.r3{background:var(--r3)}.hc.r4{background:var(--r4)}.hc.r5{background:var(--r5)}
.hi{font-size:9px;opacity:.85;margin-right:3px}
.hn{display:inline}
.psum{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin-bottom:6px}
.psum div{background:var(--s2);border:1px solid var(--bd);border-radius:8px;padding:10px 12px;text-align:center}
.psum b{display:block;font-size:24px}.psum span{font-size:11.5px;color:var(--tm)}
.psum .hl{border-color:var(--m3);background:rgba(42,120,214,.07)}
table{width:100%;border-collapse:collapse;font-size:12.5px}
table.docs{margin-bottom:6px}
table.docs th,table.docs td{padding:5px 9px;border-bottom:1px solid var(--bd);text-align:left}
th{color:var(--tm);font-weight:600}td.c,th:first-child{text-align:center}
table.plan{border:1px solid var(--bd);border-radius:8px;overflow:hidden;margin-bottom:6px}
table.plan th{background:var(--s2);padding:7px 10px;border-bottom:1px solid var(--bd);text-align:left;font-size:11.5px}
table.plan td{padding:9px 10px;border-bottom:1px solid var(--bd);vertical-align:top}
table.plan tr:last-child td{border-bottom:none}
.num{color:var(--tm);font-variant-numeric:tabular-nums}
.it{font-size:12.8px;width:44%}
.tgt{font-size:11.5px;color:var(--ts);width:34%}
.tg{color:var(--tp)}.kr{color:var(--tm);font-size:11px}
.more{color:var(--tm);font-size:11px;margin-top:2px}
.alt{margin-top:5px;font-size:11.5px;color:var(--m3);background:rgba(42,120,214,.08);border-radius:5px;padding:4px 7px}
.gA,.gB,.gC,.gD,.gE{display:inline-block;min-width:18px;text-align:center;border-radius:4px;padding:1px 5px;font-size:11px;font-weight:700;color:#fff}
.gA{background:#1a5fb4}.gB{background:#2a78d6}.gC{background:#0ca30c}.gD{background:#e08b28}.gE{background:#8a8a85}
.el{border:1px solid var(--bd);border-radius:8px;margin-bottom:5px;border-left-width:4px}
.el.r0{border-left-color:var(--r0)}.el.r1{border-left-color:var(--r1)}.el.r2{border-left-color:var(--r2)}.el.r3{border-left-color:var(--r3)}
.el.r4{border-left-color:var(--r4)}.el.r5{border-left-color:var(--r5)}
.el summary{cursor:pointer;padding:9px 12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.badge{font-size:11px;font-weight:700;padding:2px 8px;border-radius:5px;color:#fff;white-space:nowrap}
.badge i{font-style:normal;margin-right:3px}
.badge.r0{background:var(--r0)}.badge.r1{background:var(--r1)}.badge.r2{background:#a06f00}.badge.r3{background:var(--r3)}
.badge.r4{background:var(--r4)}.badge.r5{background:var(--r5)}
.en{font-weight:600;font-size:13.5px}.meta{font-size:11.5px;color:var(--tm);margin-left:auto}
.body{padding:6px 14px 16px;border-top:1px solid var(--bd)}
.qn{font-size:13px;color:var(--tp);background:var(--s2);border-radius:7px;padding:10px 12px;margin:10px 0}
.reason,.dims{font-size:12.5px;color:var(--ts);margin:8px 0}
.reason b,.dims b,.pb b{color:var(--tp);margin-right:5px}
.miss{color:var(--r3)}
.pb{font-size:12px;color:var(--ts);background:var(--s3);border-radius:6px;padding:7px 10px;margin:8px 0}
.gs{font-weight:700;color:var(--m3)}
.ev{background:var(--s2);border-radius:7px;padding:8px 11px;margin-bottom:5px}
.evh{font-size:12.5px;display:flex;gap:7px;align-items:baseline;flex-wrap:wrap}
.kt{color:var(--ts)}.src{font-size:11px;margin-left:auto;color:#fff;padding:1px 6px;border-radius:4px}
.ev blockquote{margin:5px 0 3px;padding-left:10px;border-left:2px solid var(--tm);font-size:12.8px}
.why{font-size:11.5px;color:var(--tm)}
.rm{border-left:3px solid var(--bd);padding:7px 10px;margin-bottom:5px;font-size:12.5px;background:var(--s2);border-radius:0 6px 6px 0}
.rm.m4{border-left-color:var(--m4)}.rm.m1{border-left-color:var(--m1)}.rm.m2{border-left-color:var(--m2)}.rm.m3{border-left-color:var(--m3)}
.mb{font-size:11px;font-weight:700;margin-right:6px}
.neg{background:#fdecec;border-radius:6px;padding:6px 10px;margin-bottom:4px;font-size:12.5px;color:#8c1d1d}
.con{background:#fff6e5;border-radius:6px;padding:6px 10px;margin-bottom:4px;font-size:12.5px;color:#7a4b00}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]) .neg{background:#3a1f1f;color:#f0b4b4}
 :root:not([data-theme=light]) .con{background:#3a2f1a;color:#f0d5a0}}
.fid{font-variant-numeric:tabular-nums;color:var(--tm);font-size:11px}
.none{color:var(--tm);font-size:12px}
.overall{background:var(--s2);border:1px solid var(--bd);border-radius:9px;padding:14px 16px;margin-top:22px;font-size:13px;color:var(--ts)}
.overall b{color:var(--tp)}.overall p{margin:6px 0 0}
.lgd{display:flex;flex-wrap:wrap;gap:14px;padding:12px 15px;background:var(--s2);border:1px solid var(--bd);border-radius:9px;margin-bottom:20px;font-size:12.5px;color:var(--ts)}
.lg{display:flex;align-items:center;gap:6px}.sw{width:20px;height:10px;border-radius:3px}
.sw.r0{background:var(--r0)}.sw.r1{background:var(--r1)}.sw.r2{background:var(--r2)}.sw.r3{background:var(--r3)}.sw.r4{background:var(--r4)}.sw.r5{background:var(--r5)}
@media(max-width:720px){.meta{margin-left:0;width:100%}.it,.tgt{width:auto}}
@media print{.nav{display:none}.wrap{max-width:none;padding:0}
 .el{break-inside:avoid}details{display:block}details>summary{list-style:none}
 .hmw{break-inside:avoid}table.plan tr{break-inside:avoid}}"""


def _grade(g: str | None) -> str:
    g = (g or "").strip().upper()[:1]
    return f'<span class="g{g}">{e(g)}</span>' if g in "ABCDE" else ""


def _side(v) -> tuple[str, str]:
    """상충의 한쪽 — 모양이 건마다 다르다. 보고서가 그것 때문에 멈추면 안 된다."""
    if isinstance(v, dict):
        return str(v.get("gist") or v.get("note") or ""), str(v.get("grade") or "")
    return (str(v) if v else ""), ""


def _heatmap(units: list[dict], cells: dict[tuple[str, int], dict], max_no: int) -> str:
    """Ⅰ. 히트맵 — 가로축 능력단위 · 세로축 요소 번호(큰 번호가 위)."""
    head = "".join(f'<th><div class="un">{e(u["name"])}</div>'
                   f'<div class="uh">{u["hours"]}h</div></th>' for u in units)
    body = ""
    for no in range(max_no, 0, -1):
        tds = ""
        for u in units:
            x = cells.get((u["code"], no))
            if x is None:
                tds += '<td class="hc empty"></td>'
                continue
            cls, ico, name, _ = REC[x["recommendation"]]
            n_gap = len(x["payload"].get("uncovered_ksa") or [])
            tip = (f'{x["_en"]} — {x["recommendation"]} {name}'
                   + (f' / 미확보 KSA {n_gap}개' if n_gap else ''))
            tds += (f'<td class="hc {cls}" title="{e(tip)}">'
                    f'<span class="hi">{ico}</span><span class="hn">{e(x["_en"])}</span></td>')
        body += f'<tr><th class="rl">요소 {no}</th>{tds}</tr>'
    return (f'<div class="hmw"><table class="hm"><thead><tr><th class="rl"></th>{head}</tr>'
            f'</thead><tbody>{body}</tbody></table></div>')


def _plan(els: list[dict], lab: dict[tuple[str, str], str] | None = None
          ) -> tuple[str, dict[str, int]]:
    """Ⅱ. 보완계획 — 같은 항목은 병합해 대상 요소와 KSA 를 모은다.

    같은 「안전보건교육 이수확인서 한 건」이 요소 열 곳에 걸리는 일이 흔하다.
    요소마다 따로 적으면 지원자가 열 번 준비해야 하는 것처럼 보인다.
    """
    lab = lab or {}
    groups: dict[str, dict[str, dict]] = {m: {} for m, *_ in PLAN}
    for x in els:
        for r in x["payload"].get("remediation") or []:
            if not isinstance(r, dict):
                continue
            m = r.get("method") or ""
            if m not in groups:
                continue
            key = (r.get("item") or "").strip()
            if not key:
                continue
            g = groups[m].setdefault(key, {"item": key, "alt": r.get("alt_document"),
                                           "reason": r.get("reason"), "targets": []})
            if not g["alt"] and r.get("alt_document"):
                g["alt"] = r["alt_document"]
            g["targets"].append({"unit": x["_un"], "el": x["_en"],
                                 "eid": x["element_id"],
                                 "ksa": r.get("ksa_refs") or []})

    counts = {m: len(v) for m, v in groups.items()}
    alt_total = sum(1 for v in groups.values() for g in v.values() if g.get("alt"))
    psum = (f'<div class="psum">'
            f'<div><b>{counts["추가서류"]}</b><span>추가서류</span></div>'
            f'<div><b>{counts["면접"]}</b><span>면접 질문</span></div>'
            f'<div><b>{counts["실기"]}</b><span>실기 과제</span></div>'
            f'<div class="hl"><b>{alt_total}</b><span>서류로 대체 가능</span></div></div>')

    out = psum
    for m, cls, ico, title, col in PLAN:
        items = list(groups[m].values())
        if not items:
            continue
        n_el = sum(len(g["targets"]) for g in items)
        n_ksa = sum(len(t["ksa"]) for g in items for t in g["targets"])
        n_alt = sum(1 for g in items if g.get("alt"))
        rows = ""
        for i, g in enumerate(sorted(items, key=lambda z: -len(z["targets"])), 1):
            tg = ""
            for t in g["targets"][:6]:
                ksa = "·".join(t["ksa"])
                # 확정 포맷은 이 칸에 번호만 넣는다(폭이 좁다). 이름은 툴팁으로
                # 붙인다 — 「지식5」만 봐서는 무엇을 채우라는 것인지 알 수 없다.
                names = " · ".join(
                    f"{r} {n}" for r in t["ksa"]
                    if (n := label_of(lab, t.get("eid", ""), r)))
                tg += (f'<span class="tg">{e(t["unit"])} › {e(t["el"])}</span> '
                       f'<span class="kr" title="{e(names)}">{e(ksa)}</span><br>')
            if len(g["targets"]) > 6:
                tg += f'<div class="more">외 {len(g["targets"]) - 6}개 요소</div>'
            alt = (f'<div class="alt">↳ 대체서류 제출 시 면제: {e(g["alt"])}</div>'
                   if g.get("alt") else "")
            rows += (f'<tr><td class="c num">{i}</td>'
                     f'<td class="it">{e(g["item"])}{alt}</td>'
                     f'<td class="tgt">{tg}</td>'
                     f'<td class="c">{len(g["targets"])}</td>'
                     f'<td class="c">{sum(len(t["ksa"]) for t in g["targets"])}</td></tr>')
        out += (f'<h4 class="{cls}">{ico} {title} <small>고유 {len(items)}항목 · '
                f'대상 요소 {n_el}건 · KSA {n_ksa}개 · 서류대체 가능 {n_alt}항목</small></h4>'
                f'<table class="plan {cls}"><thead><tr><th>#</th><th>{col}</th>'
                f'<th>대상 능력단위요소</th><th>요소</th><th>KSA</th></tr></thead>'
                f'<tbody>{rows}</tbody></table>')
    return out, counts


def _element(x: dict, frags: dict[str, str],
             lab: dict[tuple[str, str], str] | None = None) -> str:
    """Ⅲ. 요소 하나 — 원본의 details.el 구조 그대로."""
    p, lab = x["payload"], lab or {}
    eid = x["element_id"]
    cls, ico, name, _ = REC[x["recommendation"]]
    n_ksa_all = len(p.get("uncovered_ksa") or []) + len(p.get("evidence") or [])
    meta = " · ".join(filter(None, [
        x["evidence_level"],
        f'KSA {len(p.get("evidence") or [])}/{n_ksa_all}' if n_ksa_all else "",
        "·".join(p.get("source_grades") or []),
        x["verification_method"]]))

    b = ""
    if qn := p.get("qualitative_note"):
        b += f'<p class="qn">{e(qn)}</p>'
    if rr := p.get("recommendation_reason"):
        b += f'<p class="reason"><b>권고 사유</b> {e(rr)}</p>'
    prov, miss = p.get("proven_dimensions") or [], p.get("missing_dimensions") or []
    if prov or miss:
        b += ('<p class="dims"><b>증명됨</b> ' + e(" · ".join(prov) or "없음")
              + (f'&nbsp;<b>비어있음</b> <span class="miss">{e(" · ".join(miss))}</span>'
                 if miss else "") + "</p>")
    pb = p.get("period_backing") or {}
    if pb.get("note"):
        b += (f'<div class="pb"><b>소속·기간 보증</b> '
              f'<span class="gs">{e("·".join(pb.get("grades") or []))}</span> '
              f'<span class="fid">{e(",".join(pb.get("fids") or []))}</span>'
              f'<div>{e(pb["note"])}</div></div>')

    if ev := p.get("evidence"):
        b += f"<h5>증거 {len(ev)}건</h5>"
        for v in ev:
            g = (v.get("grade") or "").strip().upper()[:1]
            fids = ",".join(v.get("fids") or [])
            doc = next((frags.get(f) for f in (v.get("fids") or []) if frags.get(f)), "")
            ref = v.get("ksa_ref") or ""
            b += (f'<div class="ev"><div class="evh"><b>{e(ref)}</b> '
                  f'<span class="kt">{e(label_of(lab, eid, ref))}</span>'
                  f'<span class="src g{g}">{e(g)}{" · " + e(doc) if doc else ""}'
                  f'{" · " + e(fids) if fids else ""}</span></div>'
                  f'<blockquote>{e(v.get("quote"))}</blockquote>'
                  f'<div class="why">{e(v.get("why"))}</div></div>')

    for n in p.get("negative_statements") or []:
        q = (n.get("quote") or n.get("text") or "") if isinstance(n, dict) else str(n)
        note = n.get("note") if isinstance(n, dict) else ""
        b += f'<div class="neg">「{e(q)}」{f" — {e(note)}" if note else ""}</div>'
    for c in p.get("conflicts") or []:
        if not isinstance(c, dict):
            b += f'<div class="con">{e(c)}</div>'
            continue
        ad, ag = _side(c.get("adopted"))
        rj, rg = _side(c.get("rejected"))
        line = f'<b>{e(c.get("topic") or "자료 간 차이")}</b>'
        if ad:
            line += f'<br>채택 {e(ag)} — {e(ad)}'
        if rj:
            line += f'<br>기각 {e(rg)} — {e(rj)}'
        if c.get("note"):
            line += f'<br>{e(c["note"])}'
        b += f'<div class="con">{line}</div>'

    for r in p.get("remediation") or []:
        if not isinstance(r, dict):
            continue
        mcls = next((c for m, c, *_ in PLAN if m == r.get("method")), "")
        oral = (f'<br><span class="why">구술 확인: {e(" / ".join(r["oral_check"]))}</span>'
                if r.get("oral_check") else "")
        alt = (f'<div class="alt">↳ 대체서류 제출 시 면제: {e(r["alt_document"])}</div>'
               if r.get("alt_document") else "")
        b += (f'<div class="rm {mcls}"><span class="mb">{e(r.get("method"))}</span>'
              f'{e(r.get("item"))}<br><span class="why">{e(r.get("reason"))}</span>'
              f'{oral}{alt}</div>')

    return (f'<details class="el {cls}"><summary>'
            f'<span class="badge {cls}"><i>{ico}</i>{x["recommendation"]}</span>'
            f'<span class="en">{e(x["_en"])}</span>'
            f'<span class="meta">{e(meta)}</span></summary>'
            f'<div class="body">{b}</div></details>')


def render_evidence(s: Session, assessment_id: int) -> str:
    a = s.execute(text("""
        SELECT a.id, a.submission_id, a.rubric_version, a.model, a.attempts,
               a.cost_usd, a.finished_at, a.overall_note,
               s.case_number, s.target_program_id, s.note,
               p.official_name, p.total_hours
        FROM assessment a JOIN submission s ON s.id=a.submission_id
        LEFT JOIN catalog_wsd_program p ON p.program_id=s.target_program_id
        WHERE a.id=:i"""), {"i": assessment_id}).mappings().one()
    sid = a["submission_id"]

    els = [dict(r) for r in s.execute(text("""
        SELECT element_id, recommendation, evidence_level, verification_method,
               confidence, payload FROM assessment_element
        WHERE assessment_id=:i ORDER BY element_id"""),
        {"i": assessment_id}).mappings()]
    if not els:
        return "<!doctype html><html lang=ko><body><h1>결과가 비어 있습니다</h1></body></html>"

    # 이름·요소 번호는 **기준에 있는 값**이다. AI 가 받아 적어 준 것에 기대면 안 된다 —
    # 판정 4건 중 2건은 요소 전부에서 이름이 빠져 화면에 코드만 떴다.
    meta = {r[0]: (r[1], r[2], r[3]) for r in s.execute(text("""
        SELECT element_id, unit_name, element_name, element_no
        FROM catalog_ncs_element WHERE element_id = ANY(:i)"""),
        {"i": [x["element_id"] for x in els]})}
    hours = {r[0]: r[1] for r in s.execute(text("""
        SELECT unit_code, required_hours FROM catalog_wsd_required
        WHERE program_id=:p"""), {"p": a["target_program_id"]})}
    # 「기술1」이 무슨 기술인지. 원본 확정본도 .kt 칸에 이 이름을 넣는다.
    lab = labels(s, [x["element_id"] for x in els])
    docs = [dict(r) for r in s.execute(text("""
        SELECT doc_type, grade, issuer, issued_on FROM document
        WHERE submission_id=:i ORDER BY grade, doc_key"""), {"i": sid}).mappings()]
    frags = {r[0]: r[1] for r in s.execute(text("""
        SELECT fid, doc_type FROM fragment WHERE submission_id=:i"""), {"i": sid})}
    n_frag = len(frags)

    cells: dict[tuple[str, int], dict] = {}
    units: dict[str, dict] = {}
    max_no = 1
    for x in els:
        code = x["element_id"].split("_")[0]
        un, en, no = meta.get(x["element_id"], (None, None, None))
        p = x["payload"]
        x["_un"] = un or p.get("unit_name") or code
        x["_en"] = en or p.get("element_name") or x["element_id"]
        no = no or (int(x["element_id"].rsplit(".", 1)[-1])
                    if "." in x["element_id"] and x["element_id"].rsplit(".", 1)[-1].isdigit()
                    else 1)
        u = units.setdefault(code, {"code": code, "name": x["_un"],
                                    "hours": hours.get(code, 0), "els": []})
        u["els"].append(x)
        cells[(code, no)] = x
        max_no = max(max_no, no)

    ordered = sorted(units.values(), key=lambda u: (-u["hours"], u["code"]))
    counts: dict[str, int] = {}
    for x in els:
        counts[x["recommendation"]] = counts.get(x["recommendation"], 0) + 1

    kpis = "".join(
        f'<div class="kpi {REC[k][0]}"><span>{REC[k][2]}</span><b>{counts[k]}</b>'
        f'<em>{REC[k][3]}</em></div>' for k in RORDER if counts.get(k))
    stack = "".join(
        f'<div class="sg {REC[k][0]}" style="width:{counts[k] / len(els) * 100:.2f}%" '
        f'title="{REC[k][2]} {counts[k]}"></div>' for k in RORDER if counts.get(k))
    legend = "".join(f'<div class="lg"><span class="sw {REC[k][0]}"></span>'
                     f'{k} {REC[k][2]} — {REC[k][3]}</div>' for k in RORDER)

    drows = "".join(
        f'<tr><td class="c">{_grade(d["grade"])}</td><td>{e(d["doc_type"])}</td>'
        f'<td>{e(d["issuer"] or "—")}</td>'
        f'<td class="c">{d["issued_on"] or "—"}</td></tr>' for d in docs)

    plan_html, _ = _plan(els, lab)

    detail = ""
    for u in ordered:
        cards = "".join(_element(x, frags, lab) for x in
                        sorted(u["els"], key=lambda z: z["element_id"]))
        detail += (f'<div class="ug"><h4>{e(u["name"])} '
                   f'<small>{u["hours"]}시간 · 요소 {len(u["els"])}개</small></h4>{cards}</div>')

    note = json.loads(a["overall_note"]) if a["overall_note"] else {}
    overall = note.get("overall_note") or note.get("소견") or ""
    overall_html = (f'<div class="overall"><b>전반 소견</b><p>{e(overall)}</p></div>'
                    if overall else "")
    cost = f" · 비용 ${float(a['cost_usd']):.2f}" if a["cost_usd"] else ""

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RPL Track B 심사 보고서 — {e(a['case_number'])}</title><style>{CSS}</style></head>
<body><div class="wrap">
<div class="nav"><a href="/submissions/{sid}">← 심사 개요</a>
 <a href="/submissions/{sid}/report/time">Track A 보고서</a>
 <button onclick="print()">인쇄</button>
 <a class="go" href="/assessments/{a['id']}/review">전문가 검토로</a></div>

<h1>RPL Track B 심사 보고서</h1>
<p class="lead">제출 자료에서 뽑은 근거로 능력단위요소별 인정 여부와 보완 방법을 낸다.</p>

<div class="note"><b>이 문서는 판정이 아니라 판정 근거입니다.</b> 여기 적힌 것은
 기계가 낸 의견이고, 인용은 모두 제출 자료의 원문과 대조했습니다.
 전체인정·부분인정·불인정은 전문가가 결정합니다.
 <br><br><b>보는 순서</b> — Ⅰ 히트맵으로 어디가 비었는지 훑고, Ⅱ 보완계획으로
 지원자가 무엇을 더 하면 되는지 보고, Ⅲ 에서 개별 판단의 근거를 확인하십시오.</div>

<div class="lgd">{legend}</div>

<section class="app">
 <h2>{e(a['case_number'])} <span class="tp">{e(a['note'] or '선행학습 인정 신청')}</span>
  <span class="arw">→</span> {e(a['official_name'] or a['target_program_id'])}</h2>
 <p class="sub">능력단위 {len(units)}개 · 요소 {len(els)}개 ·
  제출 문서 {len(docs)}건 · 증거 조각 {n_frag}개 · 총 필수 {a['total_hours']}시간</p>
 <div class="kpis">{kpis}</div>
 <div class="stack">{stack}</div>
 <table class="docs"><thead><tr><th>등급</th><th>제출 문서</th><th>발급</th><th>발급일</th>
  </tr></thead><tbody>{drows}</tbody></table>

 <h3 class="big">Ⅰ. 히트맵 <small>가로축 능력단위 · 세로축 능력단위요소 · 칸 색은 권고 구분</small></h3>
 {_heatmap(ordered, cells, max_no)}

 <h3 class="big">Ⅱ. 보완계획 <small>중복 항목은 병합. 서류로 대체 가능한 것은 면접·실기에서 제외 가능</small></h3>
 {plan_html}

 <h3 class="big">Ⅲ. 능력단위요소별 판정 근거 <small>(항목을 눌러 펼치기)</small></h3>
 {detail}
 {overall_html}
</section>

<footer class="note" style="margin-top:26px">
심사번호 {e(a['case_number'])} · 심사 기준 v{e(a['rubric_version'])} ·
 분석 {e(a['model'])} · 호출 {a['attempts']}회{cost} ·
 완료 {a['finished_at']:%Y-%m-%d %H:%M} · 출력 {datetime.now():%Y-%m-%d %H:%M}
</footer></div></body></html>"""
