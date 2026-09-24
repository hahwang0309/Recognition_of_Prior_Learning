"""Track B 확인 계획 페이지 — 위원 제출 뒤 보류 단위를 어떻게 확정할지 제안 (2026-09-24).

보이는 순서: 0 머리(사례·제출 시각·인정/보류/불인정 카드) → 1 인정·불인정 단위 한 줄씩 →
2 보류 단위마다 시험 / 시연·구현 / 면접 세 블록 → 3 판정 파라미터.
제안이지 확정이 아니다. 결과 입력은 기존 5단계 화면(remediation_result)이 맡는다.
"""
from __future__ import annotations

import html
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from krpl_core.config import get_rubric
from services.report._shared import param_table, pending
from services.report.track_a_report import CSS as BASE_CSS
from services.review.plan import DEMO_LADDER, METHODS, latest_plan

e = lambda x: html.escape(str(x) if x is not None else "")   # noqa: E731

VERDICT_CLS = {"인정": ("good", "●"), "보류": ("hold", "◆"), "불인정": ("crit", "■")}
CSS = """
.pl h3{font-size:15px;margin:18px 0 6px}
.pl .m{border:1px solid var(--bd);border-radius:10px;padding:12px 14px;margin:10px 0;background:var(--s2)}
.pl .m h4{margin:0 0 8px;font-size:13.5px}
.pl .m h4 small{font-weight:500;color:var(--tm);margin-left:6px}
.pl .it{margin:8px 0 0;padding:8px 0 0;border-top:1px dashed var(--bd)}
.pl .it b{font-size:12.8px}
.pl .it .el{color:var(--tm);font-size:11.5px;margin-left:6px}
.pl ol,.pl ul{margin:4px 0 0 18px;padding:0;font-size:12.5px}
.pl li{margin:2px 0;white-space:normal}
.pl .ap{color:var(--ts);font-size:11.5px;margin:1px 0 4px 14px}
.pl .lad li b{color:var(--tp)}
.pl .st{display:inline-flex;align-items:center;gap:4px;font-weight:700;font-size:12px}
.pl .st.good{color:var(--good)}.pl .st.hold{color:var(--hold)}.pl .st.crit{color:var(--crit)}
.pl table.ex td{white-space:normal;vertical-align:top}
.pl .warn{color:var(--crit);font-size:12px}
.pl .one{font-size:12.8px;margin:2px 0}
"""


def render_plan(s: Session, assessment_id: int) -> str:
    rb = get_rubric()
    a = s.execute(text("""
        SELECT a.id, a.submission_id, s.case_number, s.target_program_id, p.official_name
        FROM assessment a JOIN submission s ON s.id=a.submission_id
        LEFT JOIN catalog_wsd_program p ON p.program_id=s.target_program_id
        WHERE a.id=:i"""), {"i": assessment_id}).mappings().one()
    plan = latest_plan(s, assessment_id)
    head = f"""<div class="bk"><a href="/submissions/{a['submission_id']}">← 심사 개요</a><a href="/assessments/{assessment_id}/panel">위원 페이지</a><button onclick="print()">인쇄</button></div>
<h1>RPL Track B 확인 계획</h1>"""
    if plan is None:
        return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>확인 계획 — {e(a['case_number'])}</title>
<style>{BASE_CSS}{CSS}</style></head><body><div class="viz pl">{head}
<section class="card"><header class="ch"><div class="tag">{e(a['case_number'])}</div><h2>{e(a['official_name'] or a['target_program_id'])}</h2>
<p class="sub">아직 위원 판정이 제출되지 않았습니다. <a href="/assessments/{assessment_id}/panel">위원 페이지</a>에서 항목별 인정을 마치고 「제출」을 누르면 여기에 확인 계획이 만들어집니다.</p></header></section>
</div></body></html>"""

    B, tot = plan["buckets"], plan["total_hours"] or 1
    try:
        when = datetime.fromisoformat(plan["submitted_at"]).strftime("%Y-%m-%d %H:%M")
    except (KeyError, ValueError):
        when = "?"
    ai_by = {u.get("code"): {(it.get("eid"), it.get("ref")): it for it in (u.get("items") or [])}
             for u in (plan.get("ai") or {}).get("units") or []}
    _ai = lambda ai, it: ai.get((it.get("eid"), it["ref"]), {})   # noqa: E731  (같은 번호가 요소마다 있으므로 요소로 구분)
    inp_by = {u["code"]: u for u in plan["input"]["units"]}

    # ── 1 인정·불인정 한 줄씩 ──
    ok = [u for u in plan["units"] if u["verdict"] == "인정"]
    no = [u for u in plan["units"] if u["verdict"] == "불인정"]
    hold = [u for u in plan["units"] if u["verdict"] == "보류"]
    lines = ""
    if ok:
        lines += "<h3>인정 단위 — 요구시간 전체 인정</h3>" + "".join(
            f"<p class='one'><span class='st good'>●</span> {e(u['name'])} — {u['hours']}h · 항목 {u['n_covered']}/{u['n_total']}</p>" for u in ok)
    if no:
        lines += "<h3>불인정 단위 — 훈련 이수</h3>" + "".join(
            f"<p class='one'><span class='st crit'>■</span> {e(u['name'])} — {u['hours']}h · 항목 {u['n_covered']}/{u['n_total']}</p>" for u in no)

    # ── 2 보류 단위 ──
    def _items(u_in, method):
        return [it for it in u_in["items"] if it["method"] == method]

    def _exam_block(u_in, ai):
        its = _items(u_in, "시험")
        if not its:
            return ""
        exams = plan.get("exams", {}).get(u_in["code"]) or []
        if exams:
            rows = "".join(
                f"<tr><td>{e(x.get('name'))}</td><td>{e(x.get('provider'))}</td><td>{e(x.get('scope'))}</td>"
                f"<td>{('<a href=&quot;' + e(x['url']) + '&quot; target=&quot;_blank&quot;>열기</a>') if x.get('url') else '<span class=&quot;warn&quot;>링크 미확인</span>'}"
                f"{(' · ' + e(x['note'])) if x.get('note') else ''}</td></tr>" for x in exams).replace("&quot;", '"')
            tbl = f"<div class='tw'><table class='ex'><thead><tr><th>시험</th><th>주관</th><th>범위</th><th>링크</th></tr></thead><tbody>{rows}</tbody></table></div>"
        else:
            tbl = "<p class='warn'>이 분야에 등록된 온라인 시험이 없습니다 → 아래 면접으로 확인합니다.</p>"
        body = "".join(
            f"<div class='it'><b>{e(it['kind'])} {e(it['ref'][2:])} {e(it['name'])}</b><span class='el'>— {e(it['element'])}</span>"
            + ("<ul>" + "".join(f"<li>{e(t)}</li>" for t in (_ai(ai, it).get('topics') or [])) + "</ul>"
               if _ai(ai, it).get('topics') else "<p class='ap'>시험 범위 문안 없음 — 위원 지정</p>")
            + "</div>" for it in its)
        return f"<div class='m'><h4>시험<small>지식 항목 {len(its)}개 · 국가기술자격 필기 출제기준으로 범위를 정하고 문항으로 확인</small></h4>{tbl}{body}</div>"

    def _demo_block(u_in, ai):
        its = _items(u_in, "시연·구현")
        if not its:
            return ""
        ladder = "<ol class='lad'>" + "".join(f"<li><b>{e(k)}</b> — {e(v)}</li>" for k, v in DEMO_LADDER) + "</ol>"
        body = ""
        for it in its:
            t = _ai(ai, it).get("task") or {}
            prior = [p for p in it.get("prior") or [] if p.get("method") == "실기" and p.get("item")]
            body += f"<div class='it'><b>{e(it['kind'])} {e(it['ref'][2:])} {e(it['name'])}</b><span class='el'>— {e(it['element'])}</span>"
            if t.get("title"):
                body += (f"<ul><li><b>{e(t['title'])}</b>" + (f" — 제출물: {e(t.get('deliverable'))}" if t.get("deliverable") else "")
                         + (f" ({t['minutes']}분)" if t.get("minutes") else "") + "</li>"
                         + "".join(f"<li class='ap'>확인점: {e(c)}</li>" for c in t.get("criteria") or []) + "</ul>")
            else:
                body += "<p class='ap'>과제 문안 없음 — 위원 지정</p>"
            for p in prior[:1]:
                body += f"<p class='ap'>앞선 분석의 실기 과제: {e(p['item'])}</p>"
            body += "</div>"
        return f"<div class='m'><h4>시연·구현<small>기술 항목 {len(its)}개 · 부담이 낮은 순서로 제안, 대면 실기는 외부평가</small></h4>{ladder}{body}</div>"

    def _iv_block(u_in, ai):
        its = _items(u_in, "면접")
        if not its:
            return ""
        body = ""
        for it in its:
            qs = [q for q in (_ai(ai, it).get("questions") or []) if q.get("q")]
            prior_q = [q for p in it.get("prior") or [] for q in (p.get("oral_check") or [])]
            body += f"<div class='it'><b>{e(it['kind'])} {e(it['ref'][2:])} {e(it['name'])}</b><span class='el'>— {e(it['element'])}</span>"
            if qs:
                body += "<ol>" + "".join(
                    f"<li>{e(q['q'])}" + ("".join(f"<div class='ap'>· {e(x)}</div>" for x in q.get("answer_points") or [])) + "</li>"
                    for q in qs) + "</ol>"
            else:
                body += "<p class='ap'>질문 생성 실패 — 위원 작성</p>"
            for q in prior_q[:2]:
                body += f"<p class='ap'>앞선 분석의 질문: {e(q)}</p>"
            body += "</div>"
        return f"<div class='m'><h4>면접<small>{len(its)}개 항목 · 화상 면접, 항목당 질문 2~3개</small></h4>{body}</div>"

    hold_html = ""
    for u in hold:
        u_in = inp_by.get(u["code"])
        if u_in is None:
            continue
        ai = ai_by.get(u["code"], {})
        n = {m: len(_items(u_in, m)) for m in METHODS}
        hold_html += f"""<section class="card"><header class="ch"><h2><span class="st hold">◆</span> {e(u['name'])} — {u['hours']}h</h2>
<p class="sub">서류로 인정된 항목 {u['n_covered']}/{u['n_total']} · 미확인 {u_in['n_uncovered']}개 → 시험 {n['시험']} · 시연·구현 {n['시연·구현']} · 면접 {n['면접']}</p></header>
{_exam_block(u_in, ai)}{_demo_block(u_in, ai)}{_iv_block(u_in, ai)}</section>"""
    if not hold:
        hold_html = "<section class='card'><p class='sub'>보류 단위가 없습니다. 인정 단위는 요구시간 전체를 인정하고, 불인정 단위는 훈련으로 이수합니다.</p></section>"

    errs = plan.get("ai_errors") or []
    usage = plan.get("usage") or {}
    params = [
        ("방법 배정", "지식 → 시험(분야에 등록된 시험이 있을 때, 없으면 면접) · 기술 → 시연·구현 · 태도 → 면접", "2026-09-24 설계", True),
        ("시험 목록", "config/exams.yaml — NCS 세분류별 출제기준(큐넷). 필기 기출문제는 큐넷이 공개하지 않아(기술사만) 온라인 문제은행은 없음 — 문항 출처를 정해야 함", "2026-09-24 큐넷 확인", True),
        ("시연·구현 순서", " → ".join(k for k, _ in DEMO_LADDER), "rubric remediation.burden_order · 3차 TF(실기는 외부평가)", pending(rb, "track_b.practical_to_external")),
        ("면접 질문", "항목당 2~3개, AI 문안 · 위원 수정 가능", "2026-09-24", False),
    ]
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>RPL Track B 확인 계획 — {e(a['case_number'])}</title><style>{BASE_CSS}{CSS}</style></head>
<body><div class="viz pl">{head}
<section class="card">
 <header class="ch"><div class="tag">{e(a['case_number'])}</div><h2>{e(plan.get('program') or a['official_name'] or a['target_program_id'])}</h2>
 <p class="sub">위원 판정 제출 {when}{(' · ' + e(plan['reviewer'])) if plan.get('reviewer') else ''} · 이 페이지는 보류 단위를 확정하기 위한 <b>제안</b>입니다.</p></header>
 <div class="kpis">
   <div class="kpi hl"><span>인정</span><b>{B['인정']}<i>h · {B['인정'] / tot * 100:.0f}%</i></b><em>요구시간 전체 인정</em></div>
   <div class="kpi hl hold"><span>보류</span><b>{B['보류']}<i>h · {B['보류'] / tot * 100:.0f}%</i></b><em>아래 방법으로 확인</em></div>
   <div class="kpi hl crit"><span>불인정</span><b>{B['불인정']}<i>h · {B['불인정'] / tot * 100:.0f}%</i></b><em>훈련 이수</em></div>
 </div>
 {lines}
</section>
{hold_html}
{("<p class='warn'>AI 문안 검증 오류 " + str(len(errs)) + "건 — 해당 항목은 위원이 직접 작성합니다.</p>") if errs else ""}
<footer>{param_table(params)}
<p style="margin-top:10px">심사번호 {e(a['case_number'])} · 문안 생성 {usage.get('tries', 0)}회 · ${usage.get('cost_usd', 0):.3f} · 최종 판정은 전문가 TF가 한다.</p></footer>
</div></body></html>"""
