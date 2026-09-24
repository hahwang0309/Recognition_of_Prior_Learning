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

from krpl_core.config import get_rubric
from services.catalog import label_of, pretty_ref
from services.report import dash
from services.report.layout import e, page
from services.review import STAGES, ReviewContext
from services.review.stages import Item, METHOD_OF_STAGE
from services.review.ledger import PATHS, build as ledger_of

# 단계 → (아이콘, 항목 열 이름, 결과를 무엇이라 부르나)
LOOK = {2: ("📄", "요청 서류", "받았나"),
        3: ("💬", "면접 항목", "통과했나"),
        4: ("🔧", "실기 과제", "통과했나")}
# 단계마다 고를 수 있는 결과 — (저장값, 버튼 글, 그러면 무슨 일이 일어나나)
#
# 2단계에 「미실시」를 두었더니 그것이 무엇인지 아무도 몰랐다. 서류는 받았거나
# 못 받았거나 둘 중 하나다. 「요청하지 않음」은 아직 아무것도 안 누른 상태와
# 같으므로 따로 둘 이유가 없다. 3·4단계의 「안 함」은 다르다 — 면접을 보지
# 않기로 정하는 것은 실제 판단이다.
# 단계마다 사람이 하는 일 — (저장값, 버튼 글, 그러면 무슨 일이 일어나나)
#
# 「받음/못 받음/미실시」 셋을 두었더니 이런 말을 들었다 — 「파일 올리면
# 받은 거고 아니면 못 받은 건데 왜 일일이 체크하나」. 맞다. 손대는 것은
# **된 것 하나**뿐이고, 안 한 것은 단계를 마감할 때 한꺼번에 정해진다.
#
# 2단계에는 버튼이 아예 없다 — 파일을 올리는 것이 곧 「받음」이다.
CHOICES: dict[int, list[tuple[str, str, str]]] = {
    2: [],
    3: [("통과", "확인됨", "응답으로 확인됐습니다 — 대상 요소가 인정됩니다")],
    4: [("통과", "확인됨", "실기로 확인됐습니다 — 대상 요소가 인정됩니다")],
}
# 마감할 때 손대지 않은 것이 받는 값
CLOSE_WORD = {1: "AI 권고대로", 2: "못 받음", 3: "미통과", 4: "미통과"}
# 「무엇이 확인되면 인정되나」를 부르는 말. 서류를 받는 자리에 「응답」은 맞지 않는다.
COVER_TITLE = {2: "이 서류로 확인되어야 할 것",
               3: "응답에 담겨야 할 것",
               4: "실기에서 확인할 것"}

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
.newtag{display:inline-block;font-size:10.5px;font-weight:600;margin-left:7px;
 padding:1px 7px;border-radius:9px;background:var(--wn,#c2870a);color:#fff;
 vertical-align:2px}
.blk2.carried{border-left:3px solid var(--wn,#c2870a);padding-left:10px}
.blk2.carried .cr{margin-bottom:7px}
.blk2.carried .src{font-size:11.5px;color:var(--tm);margin-bottom:3px}
/* ── 인정 원장 ── */
.lhead{display:flex;align-items:baseline;gap:16px;flex-wrap:wrap;margin:4px 0 12px}
.lhead .big{font-size:15px;color:var(--ts)}
.lhead .big b{font-size:34px;font-variant-numeric:tabular-nums;color:var(--tp)}
.lhead .big em{font-style:normal;color:var(--tm);font-size:15px;margin-left:3px}
.lhead .big span{margin-left:8px;font-size:15px;color:var(--tm)}
.lhead .sub2{font-size:12.5px;color:var(--tm)}
.lbar{display:flex;height:18px;border-radius:9px;overflow:hidden;background:var(--s3)}
.lbar i{display:block}
.lleg{display:flex;gap:15px;flex-wrap:wrap;font-size:12px;color:var(--ts);margin:8px 0 16px}
.lleg i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;
 vertical-align:-1px}
.lleg b{font-variant-numeric:tabular-nums}
/* 색은 **막대 조각과 범례 조각에만** 먹인다. 클래스를 그대로 두었더니
   같은 클래스를 단 블록 전체가 통째로 칠해져 글씨가 안 보였다. */
.lbar i.p-rec,.lleg i.p-rec{background:#2f7d4f}
.lbar i.p-doc,.lleg i.p-doc{background:#5aa06f}
.lbar i.p-oral,.lleg i.p-oral{background:#3d6fb4}
.lbar i.p-prac,.lleg i.p-prac{background:#7a5cc0}
.lbar i.p-train,.lleg i.p-train{background:#b4232a}
.lbar i.p-none,.lleg i.p-none{background:#b9b7b0}
.lb{margin-bottom:18px;border:1px solid var(--bd);border-radius:10px;overflow:hidden}
.lb>h3{margin:0;padding:10px 14px;font-size:13.5px;background:var(--s2);
 border-bottom:1px solid var(--bd);display:flex;align-items:baseline;gap:9px;flex-wrap:wrap}
.lb>h3 b{font-size:16px;font-variant-numeric:tabular-nums}
.lb>h3 small{font-weight:400;color:var(--tm);font-size:11.8px}
.lb.p-rec>h3{border-left:4px solid #2f7d4f}.lb.p-doc>h3{border-left:4px solid #5aa06f}
.lb.p-oral>h3{border-left:4px solid #3d6fb4}.lb.p-prac>h3{border-left:4px solid #7a5cc0}
.lb.p-train>h3{border-left:4px solid #b4232a}.lb.p-none>h3{border-left:4px solid #b9b7b0}
.lb table{margin:0}
.lb .mm{font-size:11px;color:var(--tm);margin-left:6px}
.lflag{margin-top:5px;font-size:11.8px;color:var(--ts);padding:6px 9px;border-radius:6px;
 background:var(--s3);border-left:3px solid var(--wn,#c2870a)}
.decide{margin:22px 0 8px;border:1px solid var(--ac);border-radius:10px;padding:15px 17px;
 background:var(--s2)}
.decide h3{margin:0 0 3px;font-size:14.5px}
.decide .sub{margin:0 0 12px}
.drow{display:flex;gap:14px;flex-wrap:wrap;align-items:center;margin-bottom:10px}
.drow label,.dfull{font-size:12.3px;color:var(--tm);display:flex;align-items:center;gap:7px}
.dfull{display:block;margin-bottom:10px}
.decide select,.decide input,.decide textarea{font:inherit;font-size:13px;padding:5px 9px;
 border:1px solid var(--bd);border-radius:6px;background:var(--s1);color:var(--tp)}
.decide input#dh{width:96px;text-align:right;font-variant-numeric:tabular-nums}
.decide textarea{width:100%;margin-top:5px;line-height:1.6}
.decide button{font-size:13.5px;padding:8px 20px;border-radius:8px;border:0;
 background:var(--tp);color:var(--s1);font-weight:600;cursor:pointer}
.dmsg{font-size:12.3px;color:var(--tm)}
.dmsg.ok{color:var(--ok,#0ca30c);font-weight:600}
.dmsg.no{color:var(--no,#b4232a);font-weight:600}
.dlog{margin-top:14px;border-top:1px solid var(--bd);padding-top:10px}
.dlog>summary{cursor:pointer;font-size:12.5px;color:var(--ac)}
.dlog table{margin-top:8px}
.dlog .dim{color:var(--tm);font-size:11.3px}
@media print{.decide button,.dmsg{display:none}}
.src{margin-top:5px;font-size:11.3px;color:var(--tm)}
.src a{color:var(--ac)}
@media print{.src{display:none}}
.todo{margin:7px 0 0;padding-left:19px;line-height:1.75}
.els{margin-top:18px}
.els>summary{cursor:pointer;font-size:13px;color:var(--ac);padding:6px 0}
@media print{.els[open]{display:block}}
.clash{display:inline-block;margin-top:8px;font-size:12.4px;color:var(--ts);
 padding:8px 11px;border-radius:7px;background:var(--s3);
 border-left:3px solid var(--wn,#c2870a)}
.noeff{font-size:12px;color:var(--tm);margin-top:9px;padding:7px 10px;
 border-radius:7px;background:var(--s3)}
.noeff em{font-style:normal}
.saved.warn{color:var(--no,#b4232a);font-weight:600}
.bar3.lit{outline:2px solid var(--ac);outline-offset:-2px;transition:outline .2s}
.means{font-size:11.6px;color:var(--tm);margin-top:6px;line-height:1.6}
.means b{color:var(--ts)}
.noq{font-size:12.3px;color:var(--ts);padding:8px 11px;border-radius:7px;
 background:var(--s3);border-left:3px solid var(--wn,#c2870a);margin-bottom:11px}
.noq em{font-style:normal;color:var(--tm)}
.closebox{margin-top:18px;border:1px solid var(--ac);border-radius:10px;padding:14px 16px;
 background:var(--s2)}
.closebox .t{font-size:13.5px;font-weight:600;margin-bottom:4px}
.closebox p{margin:0 0 11px;font-size:12.5px;color:var(--ts);line-height:1.65}
.closebox button{font-size:13.5px;padding:8px 18px;border-radius:8px;border:0;
 background:var(--tp);color:var(--s1);font-weight:600;cursor:pointer}
.closed{margin-top:18px;font-size:12.5px;color:var(--tm);padding:11px 14px;
 border-radius:9px;background:var(--s2)}
.rstate{font-size:11.5px;padding:2px 9px;border-radius:11px;margin-left:4px}
.rstate.ok{background:var(--ok,#0ca30c);color:#fff}
.rstate.no{background:var(--s3);color:var(--ts)}
@media print{.closebox{display:none}}
.ntc{font-size:12.8px;padding:10px 14px;border-radius:9px;margin-bottom:14px}
.ntc.ok{background:var(--s2);border-left:3px solid var(--ok);color:var(--ts)}
.ntc.wait{background:var(--s2);border-left:3px solid var(--ac);color:var(--ts)}
@media print{.ntc{display:none}}
.recv{margin-top:11px;padding:10px 12px;border:1px dashed var(--bd);
 border-radius:8px;background:var(--s2);font-size:12.5px}
.recv .t{font-size:11.8px;color:var(--tm);margin-bottom:6px}
.recv input[type=file]{font-size:12px;max-width:100%}
.recv select{font-size:12px;padding:3px 6px;margin:0 6px}
.recv button{font-size:12.5px;padding:4px 13px}
.recv .n{font-size:11.5px;color:var(--tm);margin-top:6px}
.moved{font-size:12.2px;color:var(--ts);margin-top:9px;padding:7px 10px;
 border-radius:7px;background:var(--s2);border-left:3px solid var(--wn,#c2870a)}
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

/* ── 인쇄 — 심사위원이 들고 앉아 서명하는 종이 ──
   화면에서 누르는 것(버튼·입력칸·링크)은 종이에서 쓸모가 없다. 대신
   판정·시간·근거·서명란이 남는다. 표가 쪽 사이에서 잘리지 않게 한다. */
@media print{
 @page{margin:14mm 12mm}
 body{background:#fff;color:#000;font-size:10.5pt}
 .dash,.moot,.recv,.means,.noeff,.item .b .blk2:has(.qs){}
 .decide select,.decide input,.decide textarea{border:0;padding:0;background:transparent}
 .decide{border:1px solid #999;background:#fff;break-inside:avoid}
 .decide .sub{display:none}
 .lb,.decide,.dlog,table{break-inside:avoid}
 .lb>h3{background:#f2f2f2}
 tr{break-inside:avoid}
 thead{display:table-header-group}
 .els{break-before:page}
 .els>summary{list-style:none;font-size:12pt;font-weight:600;color:#000}
 .lbar{border:1px solid #999}
 .signrow{display:flex;gap:30px;margin-top:16px;font-size:10.5pt}
 .signrow div{flex:1;border-top:1px solid #000;padding-top:5px}
}
.signrow{display:none}
@media print{.signrow{display:flex}}
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


def _must_cover(it: Item, ctx: ReviewContext, stage: int) -> str:
    """무엇이 확인되면 인정되나 — 대상 KSA 의 고시 원문 이름.

    AI 에게 다시 묻지 않는다. 이 항목이 채우기로 한 KSA 가 곧 그것이다.
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
    return (f'<div class="blk2"><div class="t">{e(COVER_TITLE[stage])} '
            f'— 이 {len(seen)}가지가 확인되면 인정됩니다</div>'
            f'<div class="must">{chips}</div></div>')


def _carried(it: Item, ctx: ReviewContext) -> str:
    """받지 못한 서류에서 넘어온 확인거리.

    2단계에서 「못 받음」을 찍으면 그 서류가 맡던 KSA 가 여기로 온다.
    무엇이 왜 늘었는지 적지 않으면 심사위원은 질문지가 바뀐 줄도 모른다.
    """
    if not it.carried:
        return ""
    rows = ""
    for c in it.carried:
        seen: dict[str, str] = {}
        for r in c["ksa"]:
            if r not in seen:
                seen[r] = label_of(ctx.ksa, c["eid"], r)
        chips = "".join(f'<span><b>{e(pretty_ref(r))}</b>'
                        f'{" " + e(n) if n else ""}</span>' for r, n in seen.items())
        rows += (f'<div class="cr"><div class="src">서류 「{e(_short(c["from"], 46))}」'
                 f' — {e(c["result"])}</div><div class="must">{chips}</div></div>')
    return (f'<div class="blk2 carried"><div class="t">서류를 받지 못해 '
            f'여기서 함께 확인할 것 — {len(it.carried)}건</div>{rows}</div>')


def _short(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + "…"


def _receive_form(it: Item, ctx: ReviewContext) -> str:
    """2단계 항목에 서류를 붙이는 자리.

    「받음」 토글만 있으면 서류에 무엇이 적혀 있는지 아무도 읽지 않는다.
    파일을 올리면 조각으로 수집되고, 그 서류가 풀려던 요소만 다시 판정해
    면접·실기 항목과 질문지가 새 자료를 반영한다.
    """
    if it.result == "통과":
        return ('<div class="moved">↳ 받은 서류를 반영해 <b>다시 판정했습니다.</b>'
                ' 아래 3·4단계 항목이 그 결과입니다.</div>')
    n = len({t["eid"] for t in it.targets})
    back = ('<div class="n">지금은 면접·실기로 넘어가 있습니다. 서류를 받아 올리시면 '
            '넘긴 것을 거두고 이 서류로 다시 판정합니다.</div>'
            if it.superseded else "")
    types = "".join(f'<option value="{e(k)}">{e(k)}</option>'
                    for k in get_rubric().document_types)
    return f"""<form class="recv" method="post" enctype="multipart/form-data"
 action="/assessments/{ctx.assessment_id}/items/{e(it.key)}/document">
 <div class="t">서류를 받으셨으면 여기에 올리십시오</div>{back}
 <input type="file" name="file" required>
 <select name="doc_type"><option value="">종류 — 파일 이름으로 자동</option>{types}</select>
 <button type="submit">올리고 다시 판정</button>
 <div class="n">올리면 이 항목은 「받음」으로 기록되고, 걸린 요소 {n}개를
  다시 판정합니다. 6~30분 걸립니다.</div>
</form>"""


def _no_effect(it: Item, ctx: ReviewContext) -> str:
    """이 항목을 무엇으로 찍어도 결과가 안 바뀌면 그렇다고 적는다.

    대상 요소가 이미 다 정해졌으면(1단계 인정·불인정, 또는 훈련 항목이
    걸려 있어 확인으로 풀리지 않음) 여기서 무엇을 눌러도 인정 시간이
    달라지지 않는다. 그것을 말해 주지 않으면 「저장이 안 된다」로 읽힌다.
    """
    got = ctx.outcome_of
    if any(got.get(t["eid"]) == "대기" for t in it.targets):
        return ""
    why: list[str] = []
    for o in ctx.outcomes:
        if any(t["eid"] == o.element_id for t in it.targets) and o.basis:
            b = o.basis[0]
            if b not in why:
                why.append(b)
    return (f'<div class="noeff">이 항목은 <b>결과를 바꾸지 못합니다</b> — '
            f'대상 요소가 이미 정해졌습니다.'
            + (f' <em>{e(" · ".join(why[:2]))}</em>' if why else "")
            + ' 되돌리려면 1단계에서 해당 요소를 <b>조건부인정</b>으로 바꾸십시오.</div>')


def _item_card(it: Item, ctx: ReviewContext, stage: int) -> str:
    ico, _, verb = LOOK[stage]
    cls = "pass" if it.result == "통과" else ("fail" if it.result == "미통과" else "")
    tag = ('<span class="newtag">서류 미제출로 추가됨</span>'
           if it.from_missing_document else "")

    body = ""
    if it.reason:
        body += f'<div class="blk2"><div class="t">왜 이 방법인가</div>{e(it.reason)}</div>'
    if it.oral_check:
        qs = "".join(f"<li>{e(q)}</li>" for q in it.oral_check)
        lbl = "실기 중 구술로 묻는 질문" if stage == 4 else "질문"
        body += (f'<div class="blk2"><div class="t">{lbl} {len(it.oral_check)}개</div>'
                 f'<ol class="qs">{qs}</ol></div>')
    elif stage == 3:
        # 질문 없는 면접 항목은 무엇을 물어야 할지 알 수 없다. 감추지 않는다.
        body += ('<div class="noq">이 항목에는 <b>질문이 만들어지지 않았습니다.</b> '
                 '아래 「응답에 담겨야 할 것」을 보고 직접 물으십시오. '
                 '<em>지침을 고쳤으니 새로 도는 판정부터는 질문이 붙습니다.</em></div>')
    body += _must_cover(it, ctx, stage)
    body += _carried(it, ctx)
    body += _no_effect(it, ctx)
    body += f'<div class="blk2"><div class="t">이것이 풀리면 인정되는 것</div>{_targets(it)}</div>'
    if it.alt_document:
        body += (f'<div class="alt2">↳ 대체서류 제출 시 면제: {e(it.alt_document)}</div>')
    if stage == 2:
        # 넘어간 서류라도 올릴 자리는 남긴다 — 뒤늦게 받으면 되돌아온다.
        body += _receive_form(it, ctx)
    if it.superseded:
        # 못 받은 서류. 이 항목 하나 때문에 요소가 미인정이 되지는 않는다.
        n = len({t["eid"] for t in it.targets})
        body += (f'<div class="moved">↳ 이 서류가 맡던 것은 <b>면접·실기로 넘겼습니다</b>'
                 f' — 요소 {n}개. 3·4단계에서 함께 확인합니다.</div>')

    choices = list(CHOICES[stage])
    btns = "".join(
        f'<button class="{"on" if it.result == r else ""}" data-r="{e(r)}" '
        f'title="{e(why)}" onclick="mark(this)">{e(w)}</button>'
        for r, w, why in choices)
    # 지금 무엇으로 되어 있나 — 통과가 아니면 왜 그런지 한 줄
    state = ""
    if it.result and it.result != "통과":
        state = (f'<span class="rstate no">{e(it.result)}</span>'
                 + (f'<span class="dim"> {e(it.note)}</span>' if it.note else ""))
    elif it.result == "통과":
        state = '<span class="rstate ok">통과</span>'
    means = "".join(f'<div><b>{e(w)}</b> — {e(why)}</div>' for _, w, why in choices)
    stamp = (f'{e(it.decided_by or "저장됨")} {it.decided_at:%Y-%m-%d}'
             if it.decided_at else "")

    # 버튼이 없는 단계(2단계)에는 찍는 줄 자체를 두지 않는다. 비고만 남으면
    # 「결과를 먼저 고르십시오」라는 막다른 길이 생긴다 — 고를 것이 없다.
    pick = ""
    if btns:
        pick = f"""<div class="pick" data-item="{e(it.item)}">
   <span style="font-size:12.3px;color:var(--tm)">{e(verb)}</span>
   {btns}{state}
   <input placeholder="비고 (선택)" value="{e(it.note or '')}"
          onchange="mark(this.closest('.pick').querySelector('button.on'),
                         this.closest('.pick'))">
   <span class="saved">{stamp}</span>
  </div>
  <div class="means">{means}</div>"""
    elif state:
        pick = f'<div class="pick">{state}<span class="saved">{stamp}</span></div>'

    return f"""<div class="item {cls}" data-k="{e(it.key)}" data-m="{e(it.method)}">
 <div class="h"><div class="t">{ico} {e(it.item)}{tag}</div>
  <div class="m">능력단위 {it.n_units}개 · 요소 {it.n_elements}개 · KSA {it.n_ksa}개
   &nbsp;{e(" · ".join(it.units[:3]))}{" 외" if len(it.units) > 3 else ""}</div></div>
 <div class="b">{body}
  {pick}</div>
</div>"""


# ── 단계별 본문 ───────────────────────────────────────────────────

def _close_box(ctx: ReviewContext, stage: int) -> str:
    """단계 마감. 손대지 않은 것을 기본값으로 확정한다.

    항목마다 찍게 하는 대신 단계마다 한 번 누른다. 이 버튼이 사람의
    서명이다 — 무엇을 그대로 채택했는지 감사 기록에 남는다.
    """
    from services.review.close import DEFAULT_OF
    if stage == 1:
        left = [x for x in ctx.judge_pool if x["element_id"] not in ctx.reviews]
        what = "요소"
        detail = ""
        if left:
            n: dict[str, int] = {}
            for x in left:
                w = DEFAULT_OF.get(x["recommendation"] or "", "조건부인정")
                n[w] = n.get(w, 0) + 1
            detail = " · ".join(f"{k} {v}개" for k, v in sorted(n.items()))
    else:
        live, _ = ctx.split_items(METHOD_OF_STAGE[stage])
        left = [i for i in live if not i.done]
        what = "항목"
        detail = f"{CLOSE_WORD[stage]}으로 확정"
    if not left:
        return ('<div class="closed">이 단계는 손댈 것이 남아 있지 않습니다. '
                '다음 단계로 넘어가셔도 됩니다.</div>')
    word = CLOSE_WORD[stage]
    return f"""<section class="closebox">
 <div class="t">아직 정하지 않은 {what} <b>{len(left)}개</b></div>
 <p>마감하면 이 {what}들은 <b>{e(word)}</b> 확정됩니다{f" — {e(detail)}" if detail else ""}.
  이미 정하신 것은 그대로 둡니다.</p>
 <button class="go" id="close{stage}" onclick="closeStage({stage})">
  {stage}단계 마감 — 남은 {len(left)}개를 {e(word)} 확정</button>
 <span id="closemsg" class="dmsg"></span>
</section>"""


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
 href="/assessments/{ctx.assessment_id}/review">검토 화면 열기 ({left}개 남음)</a></p>
{_close_box(ctx, 1)}"""


def _stage_items(ctx: ReviewContext, stage: int) -> str:
    method = METHOD_OF_STAGE[stage]
    group, moot = ctx.split_items(method)
    # 1단계에서 이미 인정·불인정으로 정해진 요소에 붙은 항목은 무엇을 찍어도
    # 결과가 달라지지 않는다. 세지 않되, 왜 안 세는지는 보여 준다.
    moot_block = ""
    if moot:
        cards = "".join(_item_card(i, ctx, stage) for i in moot)
        moot_block = (
            f'<details class="moot" style="margin-top:18px"><summary>'
            f'결과가 더 바뀌지 않는 항목 {len(moot)}개 — 대상 요소가 1단계에서 '
            f'이미 정해졌습니다</summary>'
            f'<p style="font-size:12.5px;color:var(--tm)">필요하면 확인하셔도 되지만, '
            f'결과를 표시해도 인정 시간은 달라지지 않습니다. '
            f'되돌리려면 1단계에서 해당 요소를 <b>조건부인정</b>으로 바꾸십시오.</p>'
            f'{cards}</details>')
    if not group:
        return (f'<div class="empty2">{method}(으)로 확인할 것이 없습니다. '
                f'이 단계는 건너뜁니다.</div>{moot_block}')
    ico, col, _ = LOOK[stage]
    n_el = sum(i.n_elements for i in group)
    n_alt = sum(1 for i in group if i.alt_document)
    done = sum(1 for i in group if i.done)
    extra = (f" 그중 <b>{n_alt}개</b>는 대체서류를 내면 면제됩니다." if n_alt else "")
    lead = {
        2: ("서류를 더 받으면 풀리는 것입니다. 지원자에게 요청하고, <b>받았으면 파일을 "
            "올리고, 못 받았으면 「못 받음」을 누르십시오.</b> 아무것도 안 누르면 그 "
            "요소는 「아직 정해지지 않음」으로 남아 3·4단계로 넘어가지 않습니다."),
        3: "화상면접으로 확인할 것입니다. 질문지를 인쇄해 가져가시고, 끝나면 결과를 표시하십시오.",
        4: "대면 실기로 확인할 것입니다. 과제 목록을 인쇄해 가져가시고, 끝나면 결과를 표시하십시오.",
    }[stage]
    cards = "".join(_item_card(i, ctx, stage) for i in group)
    return f"""<div class="why2"><b>{lead}</b>
 {ico} <b>{len(group)}개 항목</b>이 요소 {n_el}개에 걸려 있습니다.{extra}
 중복은 병합했습니다 — 같은 서류·질문을 여러 번 받지 않습니다.
 <br>지금 {done}/{len(group)}개 처리했습니다.
</div>{cards}{moot_block}{_close_box(ctx, stage)}"""


def _where(o, ctx: ReviewContext) -> int:
    """이 요소가 대기인 이유를 풀려면 몇 단계로 가야 하나."""
    if o.reviewer_decision is None:
        return 1
    for st, method in ((2, "추가서류"), (3, "면접"), (4, "실기")):
        for it in ctx.items.get(method) or []:
            if not it.done and any(t["eid"] == o.element_id for t in it.targets):
                return st
    return 1


# ── 5단계: 최종 결과 ──────────────────────────────────────────────
#
# 예전에는 요소 서른 줄짜리 표 하나뿐이었다. 근거는 되지만 종합이 아니다.
# 심사위원이 서명 직전에 알고 싶은 것은 「420시간이 어디로 갔나」다.

PATH_CLS = {"기록": "p-rec", "서류": "p-doc", "면접": "p-oral",
            "실기": "p-prac", "훈련": "p-train", "미정": "p-none"}


def _ledger_bar(lg) -> str:
    seg = "".join(
        f'<i class="{PATH_CLS[k]}" style="width:{lg.pct(lg.hours(k)):.2f}%" '
        f'title="{e(name)} {lg.hours(k)}시간"></i>'
        for k, name, _ in PATHS if lg.hours(k))
    leg = "".join(
        f'<span><i class="{PATH_CLS[k]}"></i>{e(name)} <b>{lg.hours(k)}</b>시간</span>'
        for k, name, _ in PATHS if lg.hours(k))
    return f'<div class="lbar">{seg}</div><div class="lleg">{leg}</div>'


def _source_link(r, ctx: ReviewContext) -> str:
    """이 줄의 판단이 나온 **원본**으로 가는 길.

    「자격 편성시간 30시간 / 요구 50시간 (60%)」이라고 말할 때, 그 말이 어디서
    나왔는지 바로 열 수 있어야 한다. 나중에 이의가 들어오면 여기서 답한다.
    """
    out = []
    if r.path == "기록":
        out.append(f'<a href="/submissions/{ctx.submission_id}/report/time">'
                   f'기록 확인 보고서</a>')
    if r.audit_id:
        out.append(f'<a href="/audit/artifact/{r.audit_id}">AI 응답 원본</a>')
    out.append(f'<a href="/audit/{e(ctx.case_number)}">감사 기록 전체</a>')
    return f'<div class="src">{" · ".join(out)}</div>'


def _ledger_block(lg, ctx: ReviewContext, key: str, name: str, hint: str) -> str:
    rows = lg.by_path(key)
    if not rows:
        return ""
    body = ""
    for r in rows:
        why = "<br>".join(e(x) for x in r.why) or "—"
        mm = (f' <span class="mm">{e(r.method_line)}</span>' if r.method_line else "")
        flag = (f'<div class="lflag">⚠ {e(r.flag)}</div>' if r.flag else "")
        go = ""
        if r.state in ("확인 예정", "미정"):
            go = (f' <a href="/assessments/{ctx.assessment_id}/review/{r.stage}">'
                  f'{r.stage}단계에서 정하기 →</a>')
        body += (f'<tr><td><b>{e(r.unit)}</b>{mm}</td>'
                 f'<td class="n">{r.hours}시간</td>'
                 f'<td><span class="tag2 {"ok" if r.recognized else ("no" if key == "훈련" else "wait")}">'
                 f'{e(r.state)}</span></td>'
                 f'<td><span class="why">{why}{go}</span>{flag}'
                 f'{_source_link(r, ctx)}</td></tr>')
    return f"""<section class="lb {PATH_CLS[key]}">
 <h3>{e(name)} <b>{lg.hours(key)}</b>시간
  <small>{e(hint)} · 능력단위 {len(rows)}개</small></h3>
 <table class="fin"><thead><tr><th>능력단위</th><th>시간</th><th>상태</th>
  <th>근거</th></tr></thead><tbody>{body}</tbody></table>
</section>"""


def _todo(lg) -> str:
    """남은 일 — 지원자에게 그대로 읽어 줄 수 있는 말로."""
    left = lg.open_paths
    if not left:
        return ('<div class="why2"><b>남은 일이 없습니다.</b> '
                '모든 능력단위가 정해졌습니다.</div>')
    parts = []
    for k, h, n in left:
        word = {"면접": "면접으로 확인할 것", "실기": "실기로 확인할 것",
                "훈련": "훈련으로 들어야 할 것", "미정": "아직 정하지 않은 것"}[k]
        units = " · ".join(x.unit for x in lg.by_path(k))
        parts.append(f'<li><b>{word} {h}시간</b> — {e(units)}</li>')
    return (f'<div class="why2"><b>남은 일</b><ul class="todo">{"".join(parts)}</ul></div>')


def _decide_box(ctx: ReviewContext, lg) -> str:
    """판정을 기록하는 자리. 「최종 결과」 화면에 있어야 한다.

    예전에는 옛 검토 화면 하단 바에만 있었고, 거기 숫자는 1단계 판단만 세는
    또 다른 계산이었다 — 이 화면이 370시간이라고 할 때 그쪽은 350시간이었다.
    """
    rb = get_rubric()
    fd = ctx.decision or {}
    got = lg.recognized_hours
    th = rb.final_decision["thresholds"]
    rate = got / lg.total_hours if lg.total_hours else 0
    suggest = ("전체인정" if rate >= th["전체인정"]
               else "불인정" if rate <= th["불인정"] else "부분인정")
    opts = "".join(
        f'<option{" selected" if (fd.get("decision") or suggest) == d else ""}>{e(d)}</option>'
        for d in rb.final_decision["decisions"])
    # 사람이 시간을 덮어쓰면 계산값과 차이가 남는다 — 그것을 화면이 말한다
    hours = fd.get("recognized_hours")
    hours = got if hours is None else hours
    return f"""<section class="decide" id="decide">
 <h3>최종 판정 기록</h3>
 <p class="sub">시스템이 정하지 않습니다. 위 원장을 보고 <b>심사위원들이 합의한
  결론</b>을 적습니다. 인정 시간은 계산값 <b>{got}시간</b>이 들어가 있고, 바꾸시면
  그 차이가 판정 기록에 함께 남습니다.</p>
 <div class="drow">
  <label>판정<select id="dec">{opts}</select></label>
  <label>인정 시간<input id="dh" type="number" min="0" max="{lg.total_hours}"
    value="{hours}"><span class="dim">/ {lg.total_hours}시간</span></label>
 </div>
 <label class="dfull">판정 사유
  <textarea id="dr" rows="4" placeholder="무엇을 무엇으로 인정했는지 현장 언어로 적으십시오."
   >{e(fd.get('reason') or '')}</textarea></label>
 <div class="drow">
  <button class="go" id="dsave" onclick="decide()">판정 기록</button>
  <span id="dmsg" class="dmsg"></span>
 </div>
 {_decision_log(ctx)}
 <div class="signrow"><div>심사위원 서명</div><div>일자</div><div>기관 확인</div></div>
</section>"""


def _decision_log(ctx: ReviewContext) -> str:
    """판정 이력. 다시 기록해도 앞선 판정이 남아야 한다.

    예전에는 감사 산출물이 덮어써져, 「370시간으로 정했다가 300시간으로
    바꿨다」는 사실은 남는데 **첫 판정의 근거는 사라졌다.**
    """
    log = ctx.decision_log
    if len(log) <= 1 and not (log and log[0].get("overridden")):
        return ""
    rows = ""
    for x in log:
        h = x["hours"]
        calc = x.get("calc")
        gap = (f' <span class="dim">(계산값 {calc}시간)</span>'
               if x["overridden"] and calc is not None and calc != h else "")
        link = (f' <a href="/audit/artifact/{x["artifact"]}">근거 보기</a>'
                if x["artifact"] else
                ' <span class="dim">근거 없음 — 예전 판정이 덮어써졌습니다</span>')
        rows += (f'<tr><td class="n">{x["n"]}회</td>'
                 f'<td>{e(x["decision"])}</td>'
                 f'<td class="n">{h if h is not None else "—"}시간{gap}</td>'
                 f'<td>{e(x["by"] or "")}</td>'
                 f'<td>{x["at"]:%Y-%m-%d %H:%M}{link}</td></tr>')
    return (f'<details class="dlog" open><summary>판정 이력 {len(log)}회</summary>'
            f'<table class="fin"><thead><tr><th>회차</th><th>판정</th><th>인정 시간</th>'
            f'<th>판정자</th><th>시각</th></tr></thead><tbody>{rows}</tbody></table>'
            f'</details>')


def _stage_final(ctx: ReviewContext) -> str:
    lg = ledger_of(ctx)
    got, tot = lg.recognized_hours, lg.total_hours
    oc = sorted(ctx.outcomes, key=lambda o: (-ctx.hours.get(o.unit_code, 0),
                                             o.unit_code, o.element_id))
    n = {k: sum(1 for o in oc if o.decision == k) for k in ("인정", "미인정", "대기")}

    head = (f'<div class="lhead"><div class="big">인정 <b>{got}</b>'
            f'<em>/ {tot}시간</em> <span>{got / tot * 100:.0f}%</span></div>'
            f'<div class="sub2">요소 인정 {n["인정"]} · 미인정 {n["미인정"]}'
            + (f' · 아직 {n["대기"]}' if n["대기"] else "") + '</div></div>')
    # 판정 뒤에 결과가 바뀌었으면 낡은 판정을 그대로 두면 안 된다
    if ctx.changed_after_decision and ctx.decision:
        was = ctx.decision.get("recognized_hours")
        head += (f'<div class="ntc wait">⚠ <b>판정 뒤에 검토 결과가 바뀌었습니다</b>'
                 f'({ctx.changed_after_decision:%m-%d %H:%M}). 기록된 판정은 '
                 f'{was}시간인데 지금 계산은 <b>{got}시간</b>입니다 — '
                 f'아래에서 다시 기록하십시오.</div>')
    if not lg.balanced:
        # 합이 안 맞으면 이 화면을 믿을 수 없다. 감추지 않는다.
        head += (f'<div class="ntc wait">⚠ 경로별 합({lg.sum_hours}시간)이 총 필수'
                 f'({tot}시간)와 다릅니다. 계산에 문제가 있으니 이 값을 쓰지 마십시오.</div>')

    blocks = "".join(_ledger_block(lg, ctx, k, name, hint) for k, name, hint in PATHS)

    # 요소별 근거는 접어서 맨 아래로 — 종합이 아니라 근거다
    rows = ""
    last = None
    for o in oc:
        if o.unit_code != last:
            last = o.unit_code
            rows += (f'<tr><td colspan="3" style="background:var(--s2);font-size:11.5px;'
                     f'color:var(--tm)">{e(o.unit)} · '
                     f'{ctx.hours.get(o.unit_code, 0)}시간</td></tr>')
        cls = {"인정": "ok", "미인정": "no"}.get(o.decision, "wait")
        go = ""
        if o.decision == "대기":
            w = _where(o, ctx)
            go = (f' <a href="/assessments/{ctx.assessment_id}/review/{w}">'
                  f'{w}단계에서 정하기 →</a>')
        rows += (f'<tr><td>{e(o.element)}</td>'
                 f'<td><span class="tag2 {cls}">{e(o.decision)}</span></td>'
                 f'<td><span class="why">{e(" · ".join(o.basis))}{go}</span></td></tr>')

    return f"""{head}
{_ledger_bar(lg)}
{_todo(lg)}
{blocks}
{_decide_box(ctx, lg)}
<details class="els"><summary>능력단위요소 {len(oc)}개 — 판단 하나하나의 근거</summary>
 <p class="sub">능력단위 시간은 그 단위의 요소가 <b>전부</b> 인정돼야 붙습니다.
  이 방식은 아직 확정되지 않았습니다(쟁점 D-7).</p>
 <table class="fin"><thead><tr><th>능력단위요소</th><th>결과</th>
  <th>무엇 때문에</th></tr></thead><tbody>{rows}</tbody></table>
</details>"""


def _notice(notice: str, analyzing: bool, stage: int) -> str:
    out = ""
    if notice:
        out += f'<div class="ntc ok">{notice}</div>'
    if analyzing:
        # 재판정이 끝나면 면접·실기 항목과 질문지가 달라진다. 그것을 모르고
        # 지금 인쇄해 가면 헛걸음이 된다.
        what = ("이 단계의 항목과 질문지가 곧 바뀝니다"
                if stage in (3, 4) else "판정이 끝나면 3·4단계가 갱신됩니다")
        out += (f'<div class="ntc wait">받은 서류를 반영해 <b>다시 판정하는 중</b>입니다 — '
                f'{what}. 끝난 뒤에 인쇄하십시오.</div>')
    return out


def render_stage(ctx: ReviewContext, stage: int, *, notice: str = "",
                 analyzing: bool = False) -> str:
    """`notice` 는 방금 한 일(서류 접수 등)을 한 줄로. `analyzing` 이면
    재판정이 도는 중이라 3·4단계 내용이 곧 바뀐다고 알린다."""
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
{_notice(notice, analyzing, stage)}
{body}

<div class="bar3"><div class="st">인정 시간 <b>{got}</b>/{tot}시간
 &nbsp;·&nbsp; 단계 {stage}/5</div>{nav}</div>

<footer style="margin-top:26px">심사 기준 v{e(ctx.rubric_version)} ·
 출력 {datetime.now():%Y-%m-%d %H:%M}<br>
이 화면은 판정이 아니라 판정의 근거입니다. 인정 여부는 보시는 분이 정하십니다.
</footer>"""

    scripts = """<script>
const AID = %d, SID = %d;
// id 로 찾는 짧은 이름. 없는 채로 쓰면 함수가 첫 줄에서 죽는데, 버튼은
// 그대로 있어 「눌러도 아무 일이 없다」로만 보인다 — 실제로 그랬다.
const $ = id => document.getElementById(id);
async function mark(btn, pick) {
  // 결과를 안 고르고 비고만 적으면 아무 일도 일어나지 않았다 — 저장이
  // 안 되는 것처럼 보인다. 무엇을 해야 하는지 말해 준다.
  if (!btn) {
    if (pick) {
      const s = pick.querySelector('.saved');
      s.textContent = '결과를 먼저 고르십시오';
      s.classList.add('warn');
      setTimeout(() => s.classList.remove('warn'), 2500);
    }
    return;
  }
  const box = btn.closest('.pick'), card = btn.closest('.item');
  const note = box.querySelector('input').value;
  box.querySelectorAll('button').forEach(b => b.classList.toggle('on', b === btn));
  const saved = box.querySelector('.saved');
  saved.textContent = '저장 중…';
  const r = await fetch(`/assessments/${AID}/remediation`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({key: card.dataset.k, method: card.dataset.m,
                          item: box.dataset.item, result: btn.dataset.r, note})});
  if (!r.ok) { saved.textContent = '저장 실패 — 다시 눌러 보십시오'; return; }
  const d = await r.json();
  saved.textContent = d.stamp || '저장됨';
  card.classList.toggle('pass', btn.dataset.r === '통과');
  card.classList.toggle('fail', btn.dataset.r === '미통과');
  refresh();
}

// 하나를 찍으면 전체가 달라진다 — 인정 시간도, 히트맵도, 다음 단계에
// 남은 항목 수도. 그것이 화면에 안 보이면 저장이 안 된 줄 안다.
// 서버가 그리는 그대로를 가져와 바꿔치기한다. 두 벌로 계산하면 어긋난다.
let pending = 0;
async function refresh() {
  const my = ++pending;
  try {
    const h = await (await fetch(location.pathname, {cache: 'no-store'})).text();
    if (my !== pending) return;                 // 그 사이 또 눌렀으면 그쪽이 이긴다
    const d = new DOMParser().parseFromString(h, 'text/html');
    for (const sel of ['section.dash', '.steps', '.bar3']) {
      const a = document.querySelector(sel), b = d.querySelector(sel);
      if (a && b) a.replaceWith(b);
    }
    flash();
  } catch (e) { /* 잠깐 끊긴 것뿐이면 다음에 다시 맞는다 */ }
}

async function decide() {
  const b = $('dsave'), m = $('dmsg');
  const h = parseInt($('dh').value, 10);
  if (!($('dr').value || '').trim()) {
    m.className = 'dmsg no'; m.textContent = '판정 사유를 적으십시오 — 나중에 이 글이 근거가 됩니다';
    $('dr').focus(); return;
  }
  b.disabled = true; m.className = 'dmsg'; m.textContent = '기록 중…';
  const r = await fetch(`/submissions/${SID}/decision`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({assessment_id: AID, decision: $('dec').value,
                          recognized_hours: isNaN(h) ? null : h,
                          reason: $('dr').value})});
  b.disabled = false;
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    m.className = 'dmsg no';
    m.textContent = '기록하지 못했습니다 — ' + (d.detail || r.status);
    return;
  }
  const d = await r.json();
  m.className = 'dmsg ok';
  m.textContent = `${d.decision} · ${d.recognized_hours}/${d.total_hours}시간 기록했습니다`;
  refresh();
}

async function closeStage(stage) {
  const b = document.getElementById('close' + stage), m = $('closemsg');
  if (!confirm(b.textContent.trim() + ' — 이미 정하신 것은 그대로 둡니다. 계속할까요?')) return;
  b.disabled = true; m.className = 'dmsg'; m.textContent = '마감 중…';
  const r = await fetch(`/assessments/${AID}/stages/${stage}/close`, {method: 'POST'});
  if (!r.ok) {
    b.disabled = false; m.className = 'dmsg no';
    m.textContent = '마감하지 못했습니다 — ' + r.status; return;
  }
  const d = await r.json();
  m.className = 'dmsg ok';
  m.textContent = `${d.settled}개를 확정했습니다 (이미 정한 것 ${d.already}개)`;
  location.reload();
}

function flash() {
  const b = document.querySelector('.bar3');
  if (!b) return;
  b.classList.add('lit');
  setTimeout(() => b.classList.remove('lit'), 700);
}
</script>""" % (ctx.assessment_id, ctx.submission_id)

    return page(f"{stage}. {title} — {ctx.case_number}", inner,
                css=CSS, here="/cases", scripts=scripts)
