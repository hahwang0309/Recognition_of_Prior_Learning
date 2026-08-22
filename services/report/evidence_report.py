"""② 근거 분석 보고서 — 제출 자료에서 무엇이 확인됐나. 읽기 전용.

## 왜 검토 화면과 나누는가

검토 화면은 요소 서른 몇 개를 늘어놓고 가·부를 묻는다. 읽으려면 버튼이 거슬리고,
판단하려면 근거를 하나씩 펼쳐야 한다. 「뭘 보고 뭘 판단하는지 모르겠다」가 여기서 나온다.

심사위원은 읽고 나서 판단한다. 그래서 읽는 자리를 따로 둔다.
이 보고서는 능력단위 단위로 묶어 서술하고, 시간으로 환산해 보여 준다.
읽고 나면 「어디가 쟁점인지」를 알고 검토 화면으로 간다.

인쇄해서 회의에 가져갈 수 있어야 한다. 그래서 접거나 눌러야 보이는 것을 두지 않는다.
"""
from __future__ import annotations

import html
import json
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.report.layout import REC, page

e = lambda x: html.escape(str(x) if x is not None else "")   # noqa: E731

# 지원자가 직접 나와야 하는 확인 — 부담이 크므로 따로 센다.
FACE = {"R2", "R3"}

CSS = """
.acts{display:flex;gap:9px;margin-bottom:18px;flex-wrap:wrap}
.acts a,.acts button{font-size:13px;padding:7px 15px;border-radius:7px;
 border:1px solid var(--bd);background:var(--s1);color:var(--ts);display:inline-block}
.acts a:hover{border-color:var(--tm);text-decoration:none}
.acts a.go{background:var(--tp);color:var(--s1);border-color:transparent;font-weight:600}

.lead{background:var(--s2);border:1px solid var(--bd);border-radius:10px;
 padding:15px 18px;margin-bottom:18px;font-size:14.5px;line-height:1.75}
.lead b{font-variant-numeric:tabular-nums}
.lead p{margin:0 0 8px}.lead p:last-child{margin:0}
.lead .d{color:var(--tm);font-size:12.8px}

/* 권고 분포 — 숫자만 늘어놓지 않고 폭으로 보여 준다. */
.mix{display:flex;height:13px;border-radius:7px;overflow:hidden;gap:2px;
 background:var(--s3);margin:12px 0 7px}
.mix i{display:block}
.mixleg{display:flex;flex-wrap:wrap;gap:13px;font-size:12px;color:var(--ts)}
.mixleg span{display:flex;align-items:center;gap:6px}
.mixleg em{width:10px;height:10px;border-radius:3px;font-style:normal}

.look{border:1px solid var(--no);border-left-width:3px;border-radius:9px;
 background:var(--s2);padding:13px 16px;margin-bottom:10px}
.look .t{font-size:13.2px;font-weight:600;margin-bottom:4px}
.look .t span{font-weight:400;color:var(--tm);font-size:11.5px;margin-left:7px}
.look .b{font-size:12.8px;color:var(--ts);line-height:1.6}
.look q{color:var(--tp);font-style:italic}

/* 능력단위 한 덩어리 */
.unit{border:1px solid var(--bd);border-radius:11px;background:var(--s1);
 margin-bottom:13px;overflow:hidden;break-inside:avoid}
.unit>.h{background:var(--s2);border-bottom:1px solid var(--bd);padding:11px 16px;
 display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.unit>.h b{font-size:14.5px}
.unit>.h .hh{font-size:12.5px;color:var(--tm);font-variant-numeric:tabular-nums}
.unit>.h .tags{margin-left:auto;display:flex;gap:5px;flex-wrap:wrap}
.unit>.body{padding:12px 16px}
.say{font-size:13px;line-height:1.75;color:var(--ts);margin:0 0 11px}
.gap{font-size:12.3px;color:var(--tm);margin:0 0 10px}
.gap b{color:var(--no);font-weight:600}
.unit table{font-size:12.3px}
.unit th{font-size:11px}
.settled{font-size:12.8px;color:var(--ts);margin:0}
.unit .q{display:block;color:var(--tm);font-size:11.5px;line-height:1.5;
 margin-top:2px;font-style:italic}

.tag{display:inline-block;font-size:10.5px;padding:1.5px 8px;border-radius:10px;
 white-space:nowrap;font-weight:600}
.tag.r0{background:var(--r0);color:var(--r0-fg)}
.tag.r1{background:var(--r1);color:var(--r1-fg)}
.tag.r2{background:var(--r2);color:var(--r2-fg)}
.tag.r3{background:var(--r3);color:var(--r3-fg)}
.tag.r4{background:var(--r4);color:var(--r4-fg)}
.tag.r5{background:var(--r5);color:var(--r5-fg)}
.rule{display:inline-block;font-size:10.5px;padding:1.5px 7px;border-radius:10px;
 background:var(--s3);color:var(--tm);white-space:nowrap}
.look .g{font-size:10.5px;color:var(--tm)}
.todo{background:var(--s2);border:1px solid var(--bd);border-radius:8px;
 padding:10px 14px;margin:0 0 11px}
.todo .t{font-size:11.5px;color:var(--tm);margin-bottom:5px}
.todo ul{margin:0;padding-left:17px;font-size:12.5px;line-height:1.6}
.todo li{margin-bottom:5px}
.todo .alt{font-size:11px;color:var(--ok)}
.todo .q{display:block;color:var(--tm);font-size:11.5px;line-height:1.5;font-style:italic}
"""


def _side(v) -> tuple[str, str]:
    """상충의 한쪽 — 모양이 건마다 다르다.

    형식 제약을 걸지 않았으므로 `{"gist":..,"grade":..}` 로 올 때도 있고
    그냥 문장으로 올 때도 있다. 보고서가 그것 때문에 멈추면 안 된다.
    """
    if isinstance(v, dict):
        return str(v.get("gist") or v.get("note") or ""), str(v.get("grade") or "")
    return (str(v) if v else ""), ""


def _recbar(counts: dict[str, int], total: int) -> str:
    seg = "".join(
        f'<i class="tag {REC[k][0]}" style="width:{counts[k] / total * 100:.2f}%" '
        f'title="{REC[k][1]} {counts[k]}건"></i>'
        for k in ["R0", "R1", "R2", "R3", "R4", "R5"] if counts.get(k))
    leg = "".join(
        f'<span><em class="tag {REC[k][0]}"></em>{REC[k][1]} <b>{counts[k]}</b></span>'
        for k in ["R0", "R1", "R2", "R3", "R4", "R5"] if counts.get(k))
    return f'<div class="mix">{seg}</div><div class="mixleg">{leg}</div>'


def render_evidence(s: Session, assessment_id: int) -> str:
    a = s.execute(text("""
        SELECT a.id, a.submission_id, a.rubric_version, a.model, a.attempts,
               a.cost_usd, a.finished_at, a.overall_note,
               s.case_number, s.target_program_id, p.official_name, p.total_hours
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
        return page("근거 분석 보고서", "<h1>결과가 비어 있습니다</h1>", here="/cases")

    # 능력단위·요소 이름은 **기준에 있는 값**이다. AI 가 받아 적어 준 것에 기대면
    # 안 된다 — 실제로 판정 4건 중 2건은 33·30개 요소 전부에서 이름이 빠져 있었고,
    # 화면에 코드만 떴다. 여기서 카탈로그를 찾는다.
    names = {r[0]: (r[1], r[2]) for r in s.execute(text("""
        SELECT element_id, unit_name, element_name FROM catalog_ncs_element
        WHERE element_id = ANY(:ids)"""), {"ids": [x["element_id"] for x in els]})}

    # 능력단위별 요구시간 — 시간 대조 결과에서 그대로 가져온다. 두 보고서가 같은 숫자를 쓴다.
    hours = {r[0]: r[1] for r in s.execute(text("""
        SELECT unit_code, required_hours FROM catalog_wsd_required
        WHERE program_id=:p"""), {"p": a["target_program_id"]})}
    credited = {r[0] for r in s.execute(text("""
        SELECT element_id FROM assessment_element ae
        JOIN assessment t ON t.id=ae.assessment_id
        WHERE t.submission_id=:i AND t.kind='time'
          AND ae.evidence_level IN ('완전충족','조정범위내')"""), {"i": sid})}

    # ── 능력단위로 묶는다 ──
    units: dict[str, dict] = {}
    for x in els:
        p = x["payload"]
        code = x["element_id"].split("_")[0]
        un, en = names.get(x["element_id"], (None, None))
        x["_un"], x["_en"] = un or p.get("unit_name") or code, en or p.get("element_name") or ""
        u = units.setdefault(code, {
            "code": code, "name": x["_un"],
            "hours": hours.get(code, 0), "els": [], "counts": {},
            "gaps": set(), "says": [], "todo": []})
        u["els"].append(x)
        u["counts"][x["recommendation"]] = u["counts"].get(x["recommendation"], 0) + 1
        for g in p.get("uncovered_ksa") or []:
            u["gaps"].add(g["ref"] if isinstance(g, dict) else str(g))
        for r in p.get("remediation") or []:
            u["todo"].append(r)
        if p.get("qualitative_note"):
            u["says"].append(p["qualitative_note"])

    counts: dict[str, int] = {}
    for x in els:
        counts[x["recommendation"]] = counts.get(x["recommendation"], 0) + 1
    n_face = sum(v for k, v in counts.items() if k in FACE)
    n_rule = sum(1 for x in els if x["payload"].get("decided_by") == "rule")
    alt = sum(1 for x in els if x["recommendation"] in FACE and x["payload"].get("remediation"))

    # 쟁점이 걸린 시간 — 능력단위 단위로 센다(요소가 아니라).
    open_h = sum(u["hours"] for u in units.values()
                 if any(x["recommendation"] in FACE or x["recommendation"] == "R5"
                        for x in u["els"]) and u["code"] not in credited)

    # ── 눈여겨볼 것 ──
    # 요소마다 세면 같은 이야기가 되풀이된다. 실제로 「파이프 용접은 담당한 바
    # 없습니다」 한 줄이 요소 3개에 그대로 붙어 14건으로 부풀었다.
    # 심사위원이 판단할 단위는 능력단위이므로 거기서 한 번만 말한다.
    issues: dict[str, dict] = {}
    for x in els:
        p = x["payload"]
        code = x["element_id"].split("_")[0]
        seen_here: list[str] = []
        for c in p.get("conflicts") or []:
            if not isinstance(c, dict):
                seen_here.append(f"<b>자료끼리 어긋납니다</b> — {e(c)}")
                continue
            line = f"<b>자료끼리 어긋납니다</b> — {e(c.get('topic') or '')}"
            for lbl, key in (("채택", "adopted"), ("물림", "rejected")):
                gist, grade = _side(c.get(key))
                if gist:
                    g = f' <span class="g">{e(grade)}등급</span>' if grade else ""
                    line += f"<br>{lbl}: <q>{e(gist)}</q>{g}"
            if c.get("note"):
                line += f"<br>{e(c['note'])}"
            seen_here.append(line)
        for n in p.get("negative_statements") or []:
            q = (n.get("quote") or n.get("text") or "") if isinstance(n, dict) else str(n)
            line = f"<b>「하지 않았다」는 진술이 있습니다</b><br><q>{e(q)}</q>"
            if isinstance(n, dict) and n.get("note"):
                line += f"<br>{e(n['note'])}"
            seen_here.append(line)
        if p.get("needs_expert_review"):
            seen_here.append("<b>판단이 갈릴 수 있습니다</b> — 전문가 확인이 표시됐습니다.")
        if not seen_here:
            continue
        it = issues.setdefault(code, {"name": x["_un"], "lines": [], "els": set(),
                                      "recs": set()})
        it["els"].add(x["element_id"])
        it["recs"].add(x["recommendation"])
        for ln in seen_here:
            if ln not in it["lines"]:
                it["lines"].append(ln)

    look = ""
    for code, it in sorted(issues.items(),
                           key=lambda kv: -hours.get(kv[0], 0)):
        recs = " · ".join(REC[r][1] for r in sorted(it["recs"]))
        look += (f'<div class="look"><div class="t">{e(it["name"])}'
                 f'<span>{hours.get(code, 0)}시간 · 항목 {len(it["els"])}개 · {e(recs)}</span>'
                 f'</div><div class="b">{"<br>".join(it["lines"])}</div></div>')
    if look:
        look = (f'<h2>눈여겨볼 것 <small>능력단위 {len(issues)}개</small></h2>'
                f'<p class="sub">자료끼리 어긋나거나, 본인이 「하지 않았다」고 적었거나, '
                f'판단이 갈릴 수 있는 곳입니다. 요구 시간이 큰 것부터 놓았습니다.</p>{look}')

    # ── 능력단위별 ──
    blocks = ""
    for u in sorted(units.values(), key=lambda x: (-x["hours"], x["code"])):
        tags = "".join(f'<span class="tag {REC[k][0]}">{REC[k][1]} {v}</span>'
                       for k, v in sorted(u["counts"].items()))
        say = max(u["says"], key=len) if u["says"] else ""
        gaps = (f'<p class="gap">근거가 닿지 않은 항목 <b>{len(u["gaps"])}개</b> — '
                f'{e(" · ".join(sorted(u["gaps"])))}</p>' if u["gaps"] else "")
        todo = ""
        if u["todo"]:
            seen: set[str] = set()
            items = ""
            for r in u["todo"]:
                if not isinstance(r, dict):
                    continue
                key = r.get("item") or ""
                if key in seen:
                    continue
                seen.add(key)
                alt = (f' <span class="alt">서류로 갈음 가능 — {e(r["alt_document"])}</span>'
                       if r.get("alt_document") else "")
                items += (f'<li><b>{e(r.get("method") or "")}</b> · {e(key)}{alt}'
                          f'<span class="q">{e(r.get("reason") or "")}</span></li>')
            todo = f'<div class="todo"><div class="t">이 단위를 채우려면</div><ul>{items}</ul></div>'

        done = ('<span class="rule">시간 대조로 이미 확인됨</span>'
                if u["code"] in credited else "")

        # 이수 기록으로 전부 확정된 단위는 요소마다 같은 인용문이 되풀이된다.
        # 다섯 줄이 한 글자도 다르지 않은 표를 심사위원이 읽을 이유가 없다.
        # 판단할 것이 없다고 한 줄로 말하고, 눈은 아래 단위로 보낸다.
        all_rule = all(x["payload"].get("decided_by") == "rule" for x in u["els"])
        if all_rule:
            nm = " · ".join(x["_en"] or x["element_id"] for x in u["els"])
            src = ((u["els"][0]["payload"].get("evidence") or [{}])[0].get("quote") or "")
            table = (f'<p class="settled">요소 {len(u["els"])}개가 모두 이수 기록으로 '
                     f'확정됐습니다 — 다시 확인하지 않습니다.'
                     f'<span class="q">{e(nm)}</span>'
                     + (f'<span class="q">근거 — {e(src)}</span>' if src else "")
                     + '</p>')
        else:
            rows, last_q = "", None
            for x in u["els"]:
                p2 = x["payload"]
                q = ((p2.get("evidence") or [{}])[0].get("quote") or "")
                mark = ('<span class="rule">기록으로 확정</span>'
                        if p2.get("decided_by") == "rule" else "")
                # 같은 인용문이 이어지면 한 번만 적는다.
                qh = f'<span class="q">{e(q[:150])}</span>' if q and q != last_q else ""
                last_q = q or last_q
                rows += (f'<tr><td>{e(x["_en"] or x["element_id"])}{mark}{qh}</td>'
                         f'<td><span class="tag {REC[x["recommendation"]][0]}">'
                         f'{e(REC[x["recommendation"]][1])}</span></td>'
                         f'<td>{e(x["verification_method"])}</td>'
                         f'<td>{e(x["evidence_level"])}</td></tr>')
            table = ('<table><thead><tr><th>항목</th><th>판단</th><th>확인 방법</th>'
                     f'<th>근거 충분도</th></tr></thead><tbody>{rows}</tbody></table>')
        blocks += f"""<div class="unit">
 <div class="h"><b>{e(u['name'])}</b>
  <span class="hh">{u['hours']}시간 · 항목 {len(u['els'])}개</span>
  <span class="tags">{done}{tags}</span></div>
 <div class="body">
  {f'<p class="say">{e(say)}</p>' if say else ''}
  {gaps}
  {todo}
  {table}
 </div></div>"""

    docs = s.execute(text("SELECT count(*) FROM document WHERE submission_id=:i"),
                     {"i": sid}).scalar_one()
    frags = s.execute(text("SELECT count(*) FROM fragment WHERE submission_id=:i"),
                      {"i": sid}).scalar_one()
    cost = f" · 비용 ${float(a['cost_usd']):.2f}" if a["cost_usd"] else ""

    face_line = (f"지원자가 직접 나와야 하는 확인은 <b>{n_face}건</b>입니다."
                 + (f" 그중 {alt}건은 서류로 갈음할 길을 함께 적었습니다." if alt else "")
                 if n_face else "지원자가 직접 나와야 하는 확인은 없습니다.")

    body = f"""<div class="acts noprint">
 <a href="/submissions/{sid}">← 심사 개요</a>
 <a href="/submissions/{sid}/report/time">시간 대조 보고서</a>
 <button onclick="print()">인쇄</button>
 <a class="go" href="/assessments/{a['id']}/review">검토하기</a></div>

<h1>근거 분석 보고서</h1>
<p class="sub">심사번호 {e(a['case_number'])} · 목표 종목
 {e(a['official_name'] or a['target_program_id'])} · 총 필수 {a['total_hours']}시간</p>

<div class="lead">
 <p>제출 자료 <b>{docs}건</b>({frags}개 조각)을 읽고 능력단위 <b>{len(units)}개</b>의
  <b>{len(els)}개 항목</b>을 판단했습니다.</p>
 <p>{face_line} 아직 확정되지 않아 이 자료로 다투는 시간은
  <b>{open_h}시간</b>입니다.</p>
 {_recbar(counts, len(els))}
 <p class="d">이 중 <b>{n_rule}개 항목</b>은 이수 기록에서 곧바로 확정된 것이라
  판단이 들어가지 않았습니다. 나머지 {len(els) - n_rule}개가 검토 대상입니다.</p>
</div>

{look}

<h2>능력단위별</h2>
<p class="sub">요구 시간이 큰 것부터 놓았습니다. 시간이 큰 단위의 판단이
 인정 시간에 그만큼 크게 영향을 줍니다.</p>
{blocks}

<div class="acts noprint" style="margin-top:22px">
 <a class="go" href="/assessments/{a['id']}/review">검토하기 — 항목별 가·부 정하기</a></div>

<footer>
심사 기준 v{e(a['rubric_version'])} · 분석 {e(a['model'])} · 호출 {a['attempts']}회{cost} ·
 완료 {a['finished_at']:%Y-%m-%d %H:%M} · 출력 {datetime.now():%Y-%m-%d %H:%M}<br>
여기 적힌 것은 <b>기계가 낸 의견</b>입니다. 인용은 모두 제출 자료의 원문과 대조했습니다.
전체·부분·불인정은 전문가가 결정합니다.
</footer>"""
    return page(f"근거 분석 보고서 — {a['case_number']}", body, css=CSS, here="/cases")
