"""전문가 검토 다섯 단계 화면.

  1 인정 여부 검토   판단이 필요한 요소에 가·부를 정한다
  2 추가 서류        서류를 더 받으면 풀리는 것
  3 면접             확인할 것 + 질문지 (인쇄 가능)
  4 실기             확인할 것 + 과제 목록
  5 최종 결과        무엇이 얼마나 인정됐고 무엇 때문인지

종합 현황 대시보드(Track B 보고서의 히트맵까지)는 **모든 단계 위에** 붙는다.
단계를 넘길 때마다 사람이 정한 것으로 갈아입는다 — 항목에 통과를 찍어도
그것이 전체에서 무슨 뜻인지 보이지 않으면 찍을 이유가 없다.

질문지의 「목적」과 「응답에 담겨야 할 것」은 AI 에게 다시 묻지 않는다.
목적은 그 항목의 `reason`, 담겨야 할 것은 대상 KSA 의 고시 원문 이름이다.
둘 다 이미 있는 값이므로 만들어 낼 이유가 없다.
"""
from __future__ import annotations

from datetime import datetime

from services.catalog import label_of, pretty_ref
from services.report import dash
from services.report.layout import e, page
from services.review import STAGES, ReviewContext
from services.review.stages import Item, METHOD_OF_STAGE

# 단계 → (아이콘, 항목 열 이름, 결과를 무엇이라 부르나)
LOOK = {2: ("📄", "요청 서류", "받았나"),
        3: ("💬", "면접 항목", "통과했나"),
        4: ("🔧", "실기 과제", "통과했나")}
RESULT_WORDS = {2: ("받음", "못 받음", "미실시"),
                3: ("통과", "미통과", "미실시"),
                4: ("통과", "미통과", "미실시")}

CSS = dash.CSS + """
.steps{display:flex;gap:0;margin-bottom:20px;flex-wrap:wrap}
.steps a,.steps span{flex:1 1 0;min-width:104px;padding:9px 12px;font-size:12.3px;
 border:1px solid var(--bd);border-right:0;background:var(--s2);color:var(--tm);
 text-decoration:none;position:relative;line-height:1.35}
.steps>*:first-child{border-radius:9px 0 0 9px}
.steps>*:last-child{border-right:1px solid var(--bd);border-radius:0 9px 9px 0}
.steps b{display:block;font-size:12.8px;color:var(--ts)}
.steps .on{background:var(--tp);border-color:var(--tp)}
.steps .on b,.steps .on{color:var(--s1)}
.steps .done{background:var(--s1)}
.steps .done b{color:var(--tp)}
.steps .skip{opacity:.55}
.steps em{font-style:normal;font-size:11px}

.hd2{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:2px}
.hd2 h1{margin:0;font-size:21px}
.why2{background:var(--s2);border:1px solid var(--bd);border-left:3px solid var(--ac);
 border-radius:9px;padding:11px 15px;margin-bottom:16px;font-size:12.8px;color:var(--ts)}
.why2 b{color:var(--tp)}

.item{border:1px solid var(--bd);border-radius:10px;margin-bottom:10px;overflow:hidden}
.item>.h{padding:12px 15px;background:var(--s2);border-bottom:1px solid var(--bd)}
.item>.h .t{font-size:13.5px;font-weight:600;line-height:1.5}
.item>.h .m{font-size:11.5px;color:var(--tm);margin-top:4px}
.item>.b{padding:12px 15px}
.item.pass{border-color:var(--ok)}
.item.fail{border-color:var(--no)}
.blk2{margin-bottom:11px}
.blk2>.t{font-size:11.3px;color:var(--tm);margin-bottom:4px}
.qs{margin:0;padding-left:18px;font-size:13px;line-height:1.65}
.qs li{margin-bottom:5px}
.must{display:flex;flex-wrap:wrap;gap:5px}
.must span{font-size:11.5px;padding:2px 8px;border-radius:5px;background:var(--s3);color:var(--ts)}
.must b{font-weight:600;color:var(--tp)}
.tgts{font-size:12px;color:var(--ts);line-height:1.6}
.tgts .u{color:var(--tp);font-weight:600}
.alt2{font-size:12px;color:var(--ac);background:rgba(43,110,166,.09);
 border-radius:6px;padding:7px 10px;margin-top:6px}
.pick{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:10px;
 padding-top:10px;border-top:1px solid var(--bd)}
.pick button{font-size:12.5px;padding:6px 14px}
.pick button.on{background:var(--tp);color:var(--s1);border-color:transparent;font-weight:600}
.pick input{flex:1;min-width:160px;font-size:12.5px;padding:6px 10px}
.pick .saved{font-size:11.5px;color:var(--ok);min-width:52px}

.bar3{position:sticky;bottom:0;background:var(--s2);border-top:1px solid var(--bd);
 margin:22px -20px -80px;padding:12px 20px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.bar3 .st{font-size:12.8px;color:var(--ts);flex:1;min-width:200px}
.bar3 .st b{font-size:16px;color:var(--tp);font-variant-numeric:tabular-nums}
.bar3 a,.bar3 button{font-size:13px;padding:8px 18px;border-radius:8px;
 border:1px solid var(--bd);background:var(--s1);color:var(--ts);text-decoration:none}
.bar3 a.go{background:var(--tp);color:var(--s1);border-color:transparent;font-weight:600}

table.fin{width:100%;border-collapse:collapse;font-size:12.5px}
table.fin th{font-size:11px;color:var(--tm);text-align:left;padding:6px 9px;
 border-bottom:1px solid var(--bd);white-space:nowrap}
table.fin td{padding:8px 9px;border-bottom:1px solid var(--bd);vertical-align:top}
table.fin .u{font-weight:600}
table.fin .why{display:block;font-size:11.5px;color:var(--tm);line-height:1.5;margin-top:2px}
.tag2{font-size:11px;font-weight:700;padding:2px 8px;border-radius:5px;color:#fff;white-space:nowrap}
.tag2.ok{background:var(--dok)}.tag2.no{background:var(--dno)}
.tag2.wait{background:var(--s3);color:var(--ts)}
.empty2{color:var(--tm);font-size:13px;padding:18px 0}
@media print{.steps,.bar3,.pick,.crumb{display:none}}
"""


def _steps(ctx: ReviewContext, here: int) -> str:
    out = ""
    for st in ctx.states:
        cls = "on" if st.n == here else ("skip" if st.skipped else
                                         ("done" if st.complete else ""))
        if st.skipped:
            note = "해당 없음"
        elif st.n == 5:
            note = "인정 결과"
        else:
            note = f"{st.done}/{st.total}"
        inner = f'<b>{st.n}. {e(st.title)}</b><em>{e(note)}</em>'
        out += (f'<span class="{cls}">{inner}</span>' if st.n == here else
                f'<a class="{cls}" href="/assessments/{ctx.assessment_id}/review/{st.n}">{inner}</a>')
    return f'<div class="steps">{out}</div>'


def _dashboard(ctx: ReviewContext) -> str:
    """종합 현황 — 첫 단계부터 **결과 색**으로 그린다.

    1단계에서 권고 색으로 그렸더니, 아무도 판단하지 않았는데 아래 막대는
    「인정 190시간」이라고 말해 서로 어긋나 보였다. 이수 기록으로 확정된
    요소는 시작부터 인정이므로 처음부터 그렇게 칠하는 것이 맞다.
    기계가 낸 권고 분포는 Track B 보고서에 있다.
    """
    units, cells, max_no = ctx.grid()
    got, tot = ctx.recognized_hours()
    n_wait = sum(1 for v in ctx.outcome_of.values() if v == "대기")
    sub = (f"능력단위 {len(units)}개 · 요소 {ctx.n_elements}개 · "
           f"총 필수 {ctx.total_hours}시간 · 지금까지 인정 {got}시간")
    note = ("칸 색은 <b>지금까지 정해진 결과</b>입니다. 단계를 넘길 때마다 갱신됩니다."
            + (f" 회색 {n_wait}칸이 아직 정해지지 않았습니다." if n_wait else ""))
    return dash.render(
        title=f"{ctx.case_number} · {ctx.program_name}", sub=sub,
        units=units, cells=cells, max_no=max_no, n_elements=ctx.n_elements,
        rec_counts=ctx.rec_counts, outcome_of=ctx.outcome_of, note=note)


def _targets(it: Item) -> str:
    by_unit: dict[str, list[str]] = {}
    for t in it.targets:
        by_unit.setdefault(t["unit"], []).append(t["element"])
    rows = "".join(
        f'<div><span class="u">{e(u)}</span> — {e(" · ".join(sorted(set(v))))}</div>'
        for u, v in by_unit.items())
    return f'<div class="tgts">{rows}</div>'


def _must_cover(it: Item, ctx: ReviewContext) -> str:
    """응답에 담겨야 할 것 — 대상 KSA 의 고시 원문 이름.

    AI 에게 다시 묻지 않는다. 이 항목이 채우기로 한 KSA 가 곧 「담겨야 할 것」이다.
    """
    seen: dict[str, str] = {}
    for t in it.targets:
        for r in t["ksa"]:
            if r not in seen:
                seen[r] = label_of(ctx.ksa, t["eid"], r)
    if not seen:
        return ""
    chips = "".join(
        f'<span><b>{e(pretty_ref(r))}</b>{" " + e(n) if n else ""}</span>'
        for r, n in seen.items())
    return (f'<div class="blk2"><div class="t">응답에 담겨야 할 것 '
            f'— 이 {len(seen)}가지가 확인되면 인정됩니다</div>'
            f'<div class="must">{chips}</div></div>')


def _item_card(it: Item, ctx: ReviewContext, stage: int) -> str:
    ico, _, verb = LOOK[stage]
    words = RESULT_WORDS[stage]
    cls = "pass" if it.result == "통과" else ("fail" if it.result == "미통과" else "")

    body = ""
    if it.reason:
        body += f'<div class="blk2"><div class="t">왜 이 방법인가</div>{e(it.reason)}</div>'
    if it.oral_check:
        qs = "".join(f"<li>{e(q)}</li>" for q in it.oral_check)
        body += (f'<div class="blk2"><div class="t">질문 {len(it.oral_check)}개</div>'
                 f'<ol class="qs">{qs}</ol></div>')
    body += _must_cover(it, ctx)
    body += f'<div class="blk2"><div class="t">이것이 풀리면 인정되는 것</div>{_targets(it)}</div>'
    if it.alt_document:
        body += (f'<div class="alt2">↳ 대체서류 제출 시 면제: {e(it.alt_document)}</div>')

    btns = "".join(
        f'<button class="{"on" if it.result == r else ""}" data-r="{e(r)}" '
        f'onclick="mark(this)">{e(w)}</button>'
        for r, w in zip(("통과", "미통과", "미실시"), words))
    stamp = (f'{e(it.decided_by or "")} {it.decided_at:%Y-%m-%d}'
             if it.decided_at else "")

    return f"""<div class="item {cls}" data-k="{e(it.key)}" data-m="{e(it.method)}">
 <div class="h"><div class="t">{ico} {e(it.item)}</div>
  <div class="m">능력단위 {it.n_units}개 · 요소 {it.n_elements}개 · KSA {it.n_ksa}개
   &nbsp;{e(" · ".join(it.units[:3]))}{" 외" if len(it.units) > 3 else ""}</div></div>
 <div class="b">{body}
  <div class="pick" data-item="{e(it.item)}">
   <span style="font-size:12.3px;color:var(--tm)">{e(verb)}</span>
   {btns}
   <input placeholder="비고 (선택)" value="{e(it.note or '')}"
          onchange="mark(this.closest('.pick').querySelector('button.on'))">
   <span class="saved">{stamp}</span>
  </div></div>
</div>"""


# ── 단계별 본문 ───────────────────────────────────────────────────

def _stage_judge(ctx: ReviewContext) -> str:
    left = len(ctx.judge_pool) - ctx.n_judged
    if not ctx.judge_pool:
        return ('<div class="empty2">판단이 필요한 요소가 없습니다. '
                '모두 이수 기록으로 확정됐습니다.</div>')
    return f"""<div class="why2">
 <b>제출 자료만으로 판단할 수 있는 것을 먼저 정합니다.</b>
 요소 {ctx.n_elements}개 가운데 <b>{len(ctx.judge_pool)}개</b>가 대상이고,
 나머지는 이수 기록으로 확정돼 확인만 하면 됩니다.
 지금 <b>{left}개</b> 남았습니다.
 <br>여기서 <b>조건부인정</b>으로 두신 것이 다음 단계(서류·면접·실기)로 넘어갑니다.
</div>
<p style="font-size:13px">아래 「검토 화면 열기」에서 요소별로 정하신 뒤 돌아오십시오.</p>
<p><a class="go" style="display:inline-block;font-size:13px;padding:9px 20px;
 border-radius:8px;background:var(--tp);color:var(--s1);font-weight:600"
 href="/assessments/{ctx.assessment_id}/review">검토 화면 열기 ({left}개 남음)</a></p>"""


def _stage_items(ctx: ReviewContext, stage: int) -> str:
    method = METHOD_OF_STAGE[stage]
    group = ctx.items.get(method) or []
    if not group:
        return (f'<div class="empty2">{method}(으)로 확인할 것이 없습니다. '
                f'이 단계는 건너뜁니다.</div>')
    ico, col, _ = LOOK[stage]
    n_el = sum(i.n_elements for i in group)
    n_alt = sum(1 for i in group if i.alt_document)
    done = sum(1 for i in group if i.done)
    extra = (f" 그중 <b>{n_alt}개</b>는 대체서류를 내면 면제됩니다." if n_alt else "")
    lead = {
        2: "서류를 더 받으면 풀리는 것입니다. 지원자에게 요청하고, 받으면 「받음」으로 표시하십시오.",
        3: "화상면접으로 확인할 것입니다. 질문지를 인쇄해 가져가시고, 끝나면 결과를 표시하십시오.",
        4: "대면 실기로 확인할 것입니다. 과제 목록을 인쇄해 가져가시고, 끝나면 결과를 표시하십시오.",
    }[stage]
    cards = "".join(_item_card(i, ctx, stage) for i in group)
    return f"""<div class="why2"><b>{lead}</b>
 {ico} <b>{len(group)}개 항목</b>이 요소 {n_el}개에 걸려 있습니다.{extra}
 중복은 병합했습니다 — 같은 서류·질문을 여러 번 받지 않습니다.
 <br>지금 {done}/{len(group)}개 처리했습니다.
</div>{cards}"""


def _stage_final(ctx: ReviewContext) -> str:
    got, tot = ctx.recognized_hours()
    oc = sorted(ctx.outcomes, key=lambda o: (-ctx.hours.get(o.unit_code, 0),
                                             o.unit_code, o.element_id))
    n = {k: sum(1 for o in oc if o.decision == k) for k in ("인정", "미인정", "대기")}
    rows = ""
    last = None
    for o in oc:
        head = ""
        if o.unit_code != last:
            last = o.unit_code
            head = (f'<tr><td colspan="3" style="background:var(--s2);font-size:11.5px;'
                    f'color:var(--tm)">{e(o.unit)} · {ctx.hours.get(o.unit_code, 0)}시간</td></tr>')
        cls = {"인정": "ok", "미인정": "no"}.get(o.decision, "wait")
        rows += head + (
            f'<tr><td>{e(o.element)}</td>'
            f'<td><span class="tag2 {cls}">{e(o.decision)}</span></td>'
            f'<td><span class="why">{e(" · ".join(o.basis))}</span></td></tr>')

    waiting = ("<b>아직 정해지지 않은 것이 있습니다.</b> 앞 단계로 돌아가 마저 정하시면 "
               "이 표가 갱신됩니다." if n["대기"] else
               "모든 요소가 정해졌습니다.")
    return f"""<div class="why2">
 인정 시간 <b>{got}시간</b> / 총 필수 {tot}시간
 ({got / tot * 100:.0f}%) &nbsp;·&nbsp;
 요소 인정 {n['인정']} · 미인정 {n['미인정']} · 대기 {n['대기']}
 <br>{waiting}
 <br><span style="color:var(--tm)">능력단위 시간은 그 단위의 요소가 <b>전부</b>
 인정돼야 붙습니다. 이 방식은 아직 확정되지 않았습니다(쟁점 D-7).</span>
</div>
<table class="fin"><thead><tr><th>능력단위요소</th><th>결과</th>
 <th>무엇 때문에</th></tr></thead><tbody>{rows}</tbody></table>"""


def render_stage(ctx: ReviewContext, stage: int) -> str:
    stage = max(1, min(5, int(stage)))
    title = next(t for n, _, t, _ in STAGES if n == stage)
    hint = next(h for n, _, _, h in STAGES if n == stage)

    if stage == 1:
        body = _stage_judge(ctx)
    elif stage in METHOD_OF_STAGE:
        body = _stage_items(ctx, stage)
    else:
        body = _stage_final(ctx)

    nxt = min(5, stage + 1)
    prev = max(1, stage - 1)
    got, tot = ctx.recognized_hours()
    nav = (f'<a href="/assessments/{ctx.assessment_id}/review/{prev}">← 이전</a>'
           if stage > 1 else "")
    if stage < 5:
        nav += (f'<a class="go" href="/assessments/{ctx.assessment_id}/review/{nxt}">'
                f'다음 단계 →</a>')
    else:
        nav += (f'<a class="go" href="/submissions/{ctx.submission_id}">심사 개요로</a>')

    inner = f"""<div class="crumb" style="font-size:12.5px;margin-bottom:12px;
 display:flex;gap:14px;flex-wrap:wrap">
 <a href="/submissions/{ctx.submission_id}">← 심사 개요</a>
 <a href="/submissions/{ctx.submission_id}/report/evidence">Track B 보고서</a>
 <a href="/assessments/{ctx.assessment_id}/review">요소별 검토 화면</a>
 <button onclick="print()" style="font-size:12.5px;padding:3px 12px">인쇄</button>
</div>
<div class="hd2"><h1>{stage}. {e(title)}</h1>
 <span style="color:var(--tm);font-size:12.5px">{e(hint)}</span></div>
<p class="sub">{e(ctx.case_number)} · {e(ctx.program_name)}</p>

{_dashboard(ctx)}
{_steps(ctx, stage)}
{body}

<div class="bar3"><div class="st">인정 시간 <b>{got}</b>/{tot}시간
 &nbsp;·&nbsp; 단계 {stage}/5</div>{nav}</div>

<footer style="margin-top:26px">심사 기준 v{e(ctx.rubric_version)} ·
 출력 {datetime.now():%Y-%m-%d %H:%M}<br>
이 화면은 판정이 아니라 판정의 근거입니다. 인정 여부는 보시는 분이 정하십니다.
</footer>"""

    scripts = """<script>
const AID = %d;
async function mark(btn) {
  if (!btn) return;
  const box = btn.closest('.pick'), card = btn.closest('.item');
  const note = box.querySelector('input').value;
  box.querySelectorAll('button').forEach(b => b.classList.toggle('on', b === btn));
  const saved = box.querySelector('.saved');
  saved.textContent = '저장 중…';
  const r = await fetch(`/assessments/${AID}/remediation`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({key: card.dataset.k, method: card.dataset.m,
                          item: box.dataset.item, result: btn.dataset.r, note})});
  if (!r.ok) { saved.textContent = '실패'; return; }
  const d = await r.json();
  saved.textContent = d.stamp || '저장됨';
  card.classList.toggle('pass', btn.dataset.r === '통과');
  card.classList.toggle('fail', btn.dataset.r === '미통과');
}
</script>""" % ctx.assessment_id

    return page(f"{stage}. {title} — {ctx.case_number}", inner,
                css=CSS, here="/cases", scripts=scripts)
