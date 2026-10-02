"""Track B 확인 계획 페이지 — 위원 제출 뒤 보류 단위를 어떻게 확정할지 제안 (2026-09-24).

보이는 순서: 0 머리(사례·제출 시각·인정/보류/불인정 카드) → 1 인정·불인정 단위 한 줄씩 →
2 보류 단위마다 시험 / 시연·구현 / 면접 세 블록 → 3 판정 파라미터.
제안이지 확정이 아니다. 결과 입력은 기존 5단계 화면(remediation_result)이 맡는다.
"""
from __future__ import annotations

import html
import re
from collections import Counter
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from krpl_core.config import get_rubric
from services.report._shared import unit_count_text
from services.report._shared import param_table, pending
from services.report.track_a_report import CSS as BASE_CSS
from services.review.plan import DEMO_LADDER, METHODS, latest_plan, exams_for, load_exams
from services.report._shared import STEP_CSS, step_head, step_nav

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

.iv{border-left:3px solid var(--bd);padding-left:12px;margin:0 0 14px}
.iv h4{margin:0 0 6px;font-size:14px}
.iv h4 small{display:block;font-weight:400;font-size:12px;color:var(--tm);margin-top:2px}
.q{margin:0 0 10px}
.q .qq{margin:0;font-size:13.5px;font-weight:600}
.q .fu{margin:3px 0 0;font-size:12.5px;color:var(--ts)}
ul.ap{margin:4px 0 0 18px;padding:0;font-size:12.5px;color:var(--tm)}
ul.ap li{margin:1px 0}
.pt{border:1px solid var(--bd);border-radius:10px;padding:12px 14px;margin:0 0 10px}
.pt h4{margin:0 0 4px;font-size:14px}
.pt h4 small{display:block;font-weight:400;font-size:12px;color:var(--tm);margin-top:2px}
.pt .basis{margin:0 0 6px;font-size:12px;color:var(--ts);border-left:2px solid var(--good);padding-left:8px}
.pt .dl{margin:4px 0 0;font-size:12.5px;color:var(--tm)}
.dim{color:var(--tm)}
.tgt{margin:8px 0 0;font-size:12.5px;color:var(--ts)}
"""


def render_plan(s: Session, assessment_id: int) -> str:
    rb = get_rubric()
    a = s.execute(text("""
        SELECT a.id, a.submission_id, s.case_number, s.target_program_id, p.official_name
        FROM assessment a JOIN submission s ON s.id=a.submission_id
        LEFT JOIN catalog_wsd_program p ON p.program_id=s.target_program_id
        WHERE a.id=:i"""), {"i": assessment_id}).mappings().one()
    plan = latest_plan(s, assessment_id)
    time_aid = s.execute(text("""SELECT id FROM assessment WHERE submission_id=:i
        AND kind='time' ORDER BY id DESC LIMIT 1"""), {"i": a["submission_id"]}).scalar()
    head = f"""<div class="bk"><a href="/submissions/{a['submission_id']}">← 심사 개요</a><button onclick="print()">인쇄</button></div>
{step_head("plan", "RPL Track B 확인 계획", track="B",
           nav=step_nav(a["submission_id"], time_aid, True, track="B",
                        ev_aid=assessment_id, has_plan=plan is not None))}"""
    if plan is None:
        return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>확인 계획 — {e(a['case_number'])}</title>
<style>{BASE_CSS}{CSS}{STEP_CSS}</style></head><body><div class="viz pl">{head}
<section class="card"><header class="ch"><div class="tag">{e(a['case_number'])}</div><h2>{e(a['official_name'] or a['target_program_id'])}</h2>
<p class="sub">아직 위원 판정이 제출되지 않았습니다. <a href="/assessments/{assessment_id}/panel">위원 페이지</a>에서 항목별 인정을 마치고 「제출」을 누르면 여기에 확인 계획이 만들어집니다.</p></header></section>
</div></body></html>"""

    B, tot = plan["buckets"], plan["total_hours"] or 1
    try:
        when = datetime.fromisoformat(plan["submitted_at"]).strftime("%Y-%m-%d %H:%M")
    except (KeyError, ValueError):
        when = "?"
    ai = plan.get("ai") or {}
    inp_by = {u["code"]: u for u in plan["input"]["units"]}
    is_old = "units" in ai and "interview" not in ai      # 옛 스키마(항목별 문안) 저장본

    # ── 1 인정·불인정 한 줄씩 ──
    ok = [u for u in plan["units"] if u["verdict"] == "인정"]
    no = [u for u in plan["units"] if u["verdict"] == "불인정"]
    hold = [u for u in plan["units"] if u["verdict"] == "보류"]
    lines = ""
    if ok:
        lines += "<h3>인정 단위 — 요구시간 전체 인정</h3>" + "".join(
            f"<p class='one'><span class='st good'>●</span> {e(u['name'])} — {u['hours']}h · {unit_count_text(u)}</p>" for u in ok)
    if no:
        lines += "<h3>불인정 단위 — 훈련 이수</h3>" + "".join(
            f"<p class='one'><span class='st crit'>■</span> {e(u['name'])} — {u['hours']}h · {unit_count_text(u)}</p>" for u in no)

    # ── 2 보류 단위 요약 — 표 하나. 항목을 하나씩 늘어놓지 않는다 ──
    if hold:
        rows = ""
        for u in hold:
            u_in = inp_by.get(u["code"]) or {}
            # 옛 저장본에는 counts 가 없다 — 그때는 항목마다 method 가 박혀 있었으므로
            # 거기서 센다. 안 그러면 「시험 0 · 면접 0」이 떠 사실과 다르게 읽힌다.
            c = u_in.get("counts") or Counter(
                it.get("method") for it in (u_in.get("items") or []) if it.get("method"))
            rows += (f"<tr><td>{e(u['name'])}</td><td class=n>{u['hours']}h</td>"
                     f"<td class=n>{u['n_covered']}/{u['n_total']}</td>"
                     f"<td class=src>{e(' · '.join(x['name'] for x in (u_in.get('open_elements') or [])) or '–')}</td>"
                     f"<td class=n>{u_in.get('n_uncovered', 0)}</td>"
                     f"<td class=src>시험 {c.get('시험', 0)} · 면접 {c.get('면접', 0)} · 실기 {c.get('시연·구현', 0)}</td></tr>")
        hold_html = f"""<section class="card"><header class="ch"><h2>보류 단위 {len(hold)}개 — 아래 방법으로 확인</h2>
<p class="sub">서류만으로는 인정선에 못 미친 단위입니다. <b>이미 인정된 요소는 확인하지 않습니다</b> —
 인정되지 못한 요소의 미확인 항목만 아래 방법으로 확인합니다.</p></header>
<div class="tw"><table><thead><tr><th>능력단위</th><th>요구</th><th>인정 요소</th><th>확인 대상 요소</th><th>미확인 항목</th><th>확인 방법</th></tr></thead>
<tbody>{rows}</tbody></table></div></section>"""
    else:
        hold_html = "<section class='card'><p class='sub'>보류 단위가 없습니다. 인정 단위는 요구시간 전체를 인정하고, 불인정 단위는 훈련으로 이수합니다.</p></section>"

    # ── 3 시험 — 출제기준 표만 ──
    seen_ex, ex_rows = set(), ""
    for u in hold:
        for x in exams_for(u["code"], load_exams()):
            key = (x.get("name"), x.get("url"))
            if key in seen_ex:
                continue
            seen_ex.add(key)
            link = (f"<a href='{e(x['url'])}' target='_blank' rel='noopener'>열기</a>"
                    if x.get("url") else "<span class='dim'>링크 미확인</span>")
            ex_rows += (f"<tr><td>{e(x.get('name'))}</td><td>{e(x.get('provider') or '')}</td>"
                        f"<td>{e(x.get('scope') or '')}</td><td>{link}</td></tr>")
    # 어느 단위의 어느 요소에 걸린 지식을 보는지 적는다 — 시험 표만 두면
    # 이 시험이 무엇을 확인하는 것인지 알 수 없다.
    know = ""
    for u in hold:
        u_in = inp_by.get(u["code"]) or {}
        by_el: dict[str, int] = {}
        for it in (u_in.get("items") or []):
            if it.get("kind") == "지식":
                by_el[it.get("element") or "?"] = by_el.get(it.get("element") or "?", 0) + 1
        if by_el:
            know += (f"<p class='tgt'><b>{e(u['name'])}</b> · "
                     + " · ".join(f"{e(k)} 지식 {v}개" for k, v in by_el.items()) + "</p>")

    exam_html = (f"""<section class="card"><header class="ch"><h2>1. 시험 — 지식 확인</h2>
<p class="sub">아래 출제기준으로 범위를 정하고 문항을 마련합니다. 필기 기출문제는 큐넷이 공개하지 않습니다(기술사만).</p></header>
<div class="tw"><table class="ex"><thead><tr><th>시험</th><th>주관</th><th>범위</th><th>링크</th></tr></thead>
<tbody>{ex_rows}</tbody></table></div>{know}</section>""" if ex_rows else
        """<section class="card"><header class="ch"><h2>1. 시험 — 지식 확인</h2></header>
<p class="warn">이 분야에 등록된 시험이 없습니다 → 지식 항목도 아래 면접으로 확인합니다.</p></section>""")

    # ── 4 면접 — 반구조화 질문지 한 벌 ──
    def _q(q):
        pts = "".join(f"<li>{e(x)}</li>" for x in (q.get("answer_points") or []))
        fu = (f"<p class='fu'>↳ {e(q.get('follow_up'))}</p>" if q.get("follow_up") else "")
        return (f"<div class='q'><p class='qq'>{e(q.get('q'))}</p>"
                f"{f'<ul class=ap>{pts}</ul>' if pts else ''}{fu}</div>")

    iv = ai.get("interview") or {}
    if iv.get("sections"):
        name_of = {u["code"]: u["name"] for u in plan["units"]}
        body = ""
        if iv.get("opening"):
            body += "<div class='iv'><h4>도입</h4>" + "".join(
                f"<div class='q'><p class='qq'>{e(x)}</p></div>" for x in iv["opening"]) + "</div>"
        for sec in iv["sections"]:
            qs = "".join(_q(q) for q in (sec.get("questions") or []))
            u_in = inp_by.get(sec.get("unit")) or {}
            els = " · ".join(x["name"] for x in (u_in.get("open_elements") or []))
            body += (f"<div class='iv'><h4>{e(name_of.get(sec.get('unit'), sec.get('unit')))}"
                     f"<small>{e(sec.get('focus') or '')}"
                     f"{f' — 확인 대상 요소: {e(els)}' if els else ''}</small></h4>{qs}</div>")
        if iv.get("closing"):
            body += "<div class='iv'><h4>마무리</h4>" + "".join(
                f"<div class='q'><p class='qq'>{e(x)}</p></div>" for x in iv["closing"]) + "</div>"
        iv_html = f"""<section class="card"><header class="ch"><h2>2. 면접 — 반구조화 질문지</h2>
<p class="sub">뼈대는 정해 두고 대답에 따라 파고듭니다. <b>↳</b> 는 대답이 얕을 때 이어서 물을 것입니다. 화상 면접.</p></header>
{body}</section>"""
    else:
        iv_html = ""

    # ── 5 외부평가(대면 실기) — 맨 아래 ──
    pr = ai.get("practical") or []
    if pr:
        name_of = {u["code"]: u["name"] for u in plan["units"]}
        cards = ""
        # 근거 수행준거가 어느 요소의 것인지는 입력에서 찾는다 — AI 에게 더 묻지 않는다.
        # **같은 문장이 여러 요소에 반복된다**(실측: 「설계목표와 의도를 이해할 수
        # 있다」가 2D·3D 표현하기 양쪽에). 그래서 단위별로 키를 나누고, 그래도 둘
        # 이상이면 요소를 단정하지 않는다 — 틀린 요소를 적는 것보다 안 적는 편이 낫다.
        el_of: dict[tuple[str, str], set[str]] = {}
        for u_in in plan["input"]["units"]:
            for x in (u_in.get("pc") or []):
                key = (u_in["code"], re.sub(r"\s+", "", x.get("text") or ""))
                el_of.setdefault(key, set()).add(x.get("element") or "")
        for k, x in enumerate(pr, 1):
            codes = x.get("units") or []
            us = " · ".join(name_of.get(c, c) for c in codes)
            basis = re.sub(r"\s+", "", x.get("basis") or "")
            els = {n for c in codes for n in el_of.get((c, basis), set()) if n}
            if len(els) == 1:
                us = f"{us} › {els.pop()}" if us else us
            crit = "".join(f"<li>{e(c)}</li>" for c in (x.get("criteria") or []))
            cards += f"""<div class='pt'><h4>{k}. {e(x.get('title'))}<small>{e(us)}</small></h4>
<p class='basis'>근거 수행준거 — {e(x.get('basis'))}</p>
<p>{e(x.get('task'))}</p>
<p class='dl'>제출물: {e(x.get('deliverable') or '—')}{f" · 제안 소요 {x['minutes']}분" if x.get('minutes') else ''}</p>
{f'<ul class=ap>{crit}</ul>' if crit else ''}</div>"""
        pr_html = f"""<section class="card"><header class="ch"><h2>3. 외부평가(대면 실기) — 실기 주제 {len(pr)}개</h2>
<p class="sub">RPL 단계에서 실기를 직접 보지 않습니다(3차 TF). 외부평가 기관에 넘길 주제이며 소요 시간은 제안입니다.</p></header>
{cards}</section>"""
    else:
        pr_html = ""

    if is_old:
        hold_html += """<section class="card"><p class="warn">이 확인 계획은 옛 형식(항목별 문안)으로 만들어졌습니다.
면접 질문지와 실기 주제로 다시 만들려면 위원 페이지에서 <b>제출</b>을 한 번 더 누르십시오.</p></section>"""

    errs = plan.get("ai_errors") or []
    usage = plan.get("usage") or {}
    params = [
        ("요소 인정", "한 요소 안에서 인정된 항목이 50% 이상이면 그 요소를 인정합니다",
         "2026-09-24 결정 — Track A 인정선과 같은 값", False),
        ("능력단위 판정", "인정된 요소가 50% 이상이면 인정 · 30% 이상이면 보류 · 그 미만은 불인정",
         "2026-09-24 결정", True),
        ("확인 대상", "보류 단위 가운데 인정되지 못한 요소만 봅니다. 이미 인정된 요소는 확인하지 않습니다",
         "2026-09-24 설계", True),
        ("인정되면 몇 시간", "그 능력단위의 요구시간 전체. 요소·항목에는 시간이 매겨져 있지 않습니다",
         "NCS 원자료 확인 · 설계안", False),
        ("무엇을 무엇으로 확인하나",
         "지식은 시험(그 분야 시험이 없으면 면접) · 기술은 외부평가 대면 실기 · 태도는 면접",
         "2026-09-24 설계", True),
        ("시험 문항",
         "출제기준으로 범위만 정합니다. 기능사·산업기사·기사 필기 기출문제는 공개되지 않아(기술사만) "
         "문항은 따로 마련해야 합니다",
         "2026-09-24 큐넷 확인", True),
        ("실기", "RPL 단계에서는 보지 않습니다. 외부평가 기관에 넘길 주제 3~5개를 제안만 합니다",
         "3차 TF", pending(rb, "track_b.practical_to_external")),
        ("면접 질문지",
         "뼈대만 정해 두고 대답에 따라 파고드는 형식입니다 — 도입, 능력단위별 질문 2~3개"
         "(답변 요지와 후속 질문 포함), 마무리. 문안은 고쳐 쓰셔도 됩니다",
         "2026-09-24 설계", False),
        ("실기 주제의 근거",
         "NCS 수행준거 원문에서 가져옵니다. 원문과 다르면 기계가 되돌려 보내므로 "
         "지어낸 과제가 섞이지 않습니다",
         "2026-09-24 설계", False),
    ]

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>RPL Track B 확인 계획 — {e(a['case_number'])}</title><style>{BASE_CSS}{CSS}{STEP_CSS}</style></head>
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
{exam_html}
{iv_html}
{pr_html}
{("<p class='warn'>AI 문안 검증 오류 " + str(len(errs)) + "건 — 해당 항목은 위원이 직접 작성합니다.</p>") if errs else ""}
<footer>{param_table(params)}
<p style="margin-top:10px">심사번호 {e(a['case_number'])} · 문안 생성 {usage.get('tries', 0)}회 · ${usage.get('cost_usd', 0):.3f} · 최종 판정은 전문가 TF가 한다.</p></footer>
</div></body></html>"""
