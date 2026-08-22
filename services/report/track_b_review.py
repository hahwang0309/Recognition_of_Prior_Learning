"""전문가 검토 화면 (HTML).

읽는 사람은 RPL·직종 전문가다. 컴퓨터 전문가가 아니다.
그래서 화면에는 **판정 근거만** 놓고, 방법론 용어는 쓰지 않는다.
권고 코드(R0~R5)는 기준서에 있는 말이라 남기되 항상 뜻을 붙여 쓴다.

한 요소를 볼 때 필요한 것이 한 화면에 다 있어야 한다.
근거 인용 → 그 인용이 나온 원문 조각 → 무엇이 비었는지 → 어떻게 채울지 → 소견.
"""
from __future__ import annotations

import html
import json
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from krpl_core.config import get_rubric
from services.review import review_summary

e = lambda x: html.escape(str(x) if x is not None else "")   # noqa: E731

REC = {"R0": ("r0", "기이수 인정검토", "이미 평가를 마친 항목 — 추가 확인 없음"),
       "R1": ("r1", "서류 인정검토", "낸 서류만으로 판단 가능"),
       "R2": ("r2", "면접 확인", "화상면접으로 확인"),
       "R3": ("r3", "실기 확인", "대면 실기·시연으로 확인"),
       "R4": ("r4", "추가서류 요청", "서류 보완 후 재판단"),
       "R5": ("r5", "미인정", "훈련 이수 필요")}
CONF = {"high": "높음", "medium": "보통", "low": "낮음"}
DEC = {"인정": "ok", "조건부인정": "cond", "불인정": "no", "보류": "hold"}

CSS = """*{box-sizing:border-box}
:root{--s1:#fcfcfb;--s2:#f4f4f1;--s3:#eceae4;--bd:#e0e0da;--tp:#0b0b0b;--ts:#4a4a46;--tm:#84837c;
 --r0:#0a8a0a;--r0-fg:#fff;--r1:#2b6ea6;--r1-fg:#fff;--r2:#fab219;--r2-fg:#3a2a00;
 --r3:#e07b39;--r3-fg:#2e1400;--r4:#7d55b8;--r4-fg:#fff;--r5:#d03b3b;--r5-fg:#fff;
 --ok:#0ca30c;--cond:#fab219;--no:#d03b3b;--hold:#84837c;--warn:#d03b3b}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--s1:#1a1a19;--s2:#232322;
 --s3:#2b2b29;--bd:#3a3a38;--tp:#fff;--ts:#c3c2b7;--tm:#8f8e86}}
body{margin:0;background:var(--s1);color:var(--tp);
 font:14px/1.65 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",Pretendard,sans-serif}
/* 아래 고정 바가 마지막 요소를 덮었다. 바 높이는 화면 폭에 따라 달라지므로
   (넓으면 한 줄, 좁으면 세 줄) 고정값으로는 맞출 수 없다. 실제 높이를 재서 넣는다. */
.wrap{max-width:1080px;margin:0 auto;padding:28px 20px calc(var(--barh, 120px) + 28px)}
h1{font-size:23px;margin:0 0 4px}.sub{color:var(--tm);font-size:12.5px;margin:0 0 18px}
.banner{background:var(--s2);border:1px solid var(--bd);border-left:3px solid var(--warn);
 border-radius:8px;padding:11px 15px;margin-bottom:16px;font-size:12.8px;color:var(--ts)}
.banner b{color:var(--warn)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:9px;margin-bottom:18px}
.kpi{background:var(--s2);border:1px solid var(--bd);border-radius:9px;padding:10px 13px}
.kpi span{display:block;font-size:11.5px;color:var(--tm)}
.kpi b{font-size:22px;font-variant-numeric:tabular-nums}
.kpi b i{font-size:12px;font-style:normal;color:var(--ts);margin-left:2px}
.kpi em{display:block;font-style:normal;font-size:11px;color:var(--tm);margin-top:2px}
.lgd{display:flex;flex-wrap:wrap;gap:13px;padding:10px 14px;background:var(--s2);
 border:1px solid var(--bd);border-radius:9px;margin-bottom:20px;font-size:12.3px;color:var(--ts)}
.lg{display:flex;align-items:center;gap:6px}
.dot{width:9px;height:9px;border-radius:50%;flex:none}
h2{font-size:15.5px;margin:26px 0 3px;display:flex;align-items:baseline;gap:9px}
h2 small{font-weight:400;font-size:12px;color:var(--tm)}
details.grp{border:1px solid var(--bd);border-radius:11px;background:var(--s1);
 margin-bottom:12px;overflow:hidden}
details.grp>summary{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
 padding:12px 15px;cursor:pointer;background:var(--s2);list-style:none;font-size:13px}
details.grp>summary::-webkit-details-marker{display:none}
details.grp>summary::before{content:"▸";color:var(--tm);font-size:11px;
 transition:transform .12s}
details.grp[open]>summary::before{transform:rotate(90deg)}
details.grp>summary b{font-variant-numeric:tabular-nums}
/* 묶음 머리의 상태 배지·버튼. 이 파일에는 .st 와 .sm 이 없어서
   「먼저 보실 것」 같은 분류 표시가 스타일 없는 맨 글자로 나오고,
   일괄 처리 버튼은 브라우저 기본 회색 버튼으로 떨어졌다.
   분류 표시는 이 화면에서 어디부터 볼지 알려 주는 유일한 신호다. */
details.grp>summary .st{display:inline-block;font-size:11.5px;font-weight:600;
 padding:2px 10px;border-radius:11px;background:var(--s3);color:var(--ts)}
details.grp>summary .st.no{background:var(--no);color:#fff}
details.grp>summary .st.wn{background:var(--wn);color:#3a2a00}
details.grp>summary .st.ok{background:var(--ok);color:#fff}
.gb button.sm{font:inherit;font-size:12px;padding:4px 12px;border-radius:7px;cursor:pointer;
 border:1px solid var(--bd);background:var(--s1);color:var(--ts)}
.gb button.sm:hover{border-color:var(--tm);background:var(--s3)}
.pg{font-size:11.5px;color:var(--tm);font-variant-numeric:tabular-nums}
.gh{flex:1 1 100%;font-size:11.8px;color:var(--tm);padding-left:18px}
.gb{display:flex;gap:5px;margin-left:auto}
.el{border-top:1px solid var(--bd);background:var(--s1)}
.el.done{background:var(--s2)}
.el .hd{display:flex;align-items:center;gap:9px;flex-wrap:wrap;
 padding:9px 15px 9px 33px;cursor:pointer;font-size:13px}
.el .hd:hover{background:var(--s2)}
.el .hd .tw{color:var(--tm);font-size:10px;transition:transform .12s;
 position:absolute;margin-left:-16px}
.el.open .hd .tw{transform:rotate(90deg)}
.el .en{font-weight:600;min-width:120px}
.el .un{flex:1;min-width:110px;font-size:11.5px;color:var(--tm)}
.el .cnt{font-size:11.3px;color:var(--tm);white-space:nowrap}
.el .mks{display:flex;gap:4px;flex-wrap:wrap}
.mk{font-size:10.8px;padding:1px 7px;border-radius:9px;background:var(--s3);color:var(--ts)}
.mk.neg{background:rgba(208,59,59,.14);color:var(--no)}
.mk.cf{background:rgba(250,178,25,.18);color:#8a6100}
.mk.rule{background:rgba(12,163,12,.13);color:var(--ok)}
.el .dt{display:none;padding:2px 15px 14px 33px;border-top:1px dashed var(--bd)}
.el.open .dt{display:block}
.ec{font-size:10.5px;color:var(--tm);font-variant-numeric:tabular-nums}
.tag{font-size:11.3px;padding:1.5px 8px;border-radius:11px;white-space:nowrap;font-weight:600}
.flag{font-size:11.3px;padding:1.5px 8px;border-radius:11px;border:1px solid var(--warn);
 color:var(--warn);white-space:nowrap}
.why{font-size:12.8px;color:var(--ts);margin:0 0 9px}
.blk{margin:9px 0}
.blk>.t{font-size:11.3px;color:var(--tm);margin-bottom:4px}
.ev{border-left:2px solid var(--bd);padding:2px 0 2px 11px;margin-bottom:7px}
.ev .k{font-size:11.3px;color:var(--tm)}
.ev .k b{color:var(--ts)}
.ev q{display:block;font-size:12.8px;margin:2px 0;quotes:'"' '"'}
.ev .r{font-size:11.8px;color:var(--ts)}
.src{font-size:11.3px;color:var(--tm);cursor:pointer;text-decoration:underline dotted;
 background:none;border:0;padding:0;font-family:inherit}
.src:hover{color:var(--tp)}
.orig{display:none;background:var(--s3);border-radius:6px;padding:8px 11px;
 margin:5px 0;font-size:12.3px;color:var(--ts);white-space:pre-wrap}
.orig.on{display:block}
.chips{display:flex;flex-wrap:wrap;gap:5px}
.chip{font-size:11.3px;padding:1.5px 8px;border-radius:5px;background:var(--s3);color:var(--ts)}
.chip.neg{color:var(--warn)}
.rem{font-size:12.5px;color:var(--ts);margin-bottom:4px}
.rem b{color:var(--tp)}
.rem .alt{color:var(--tm);font-size:11.5px}
.neg{border-left:2px solid var(--warn);padding:2px 0 2px 11px;margin-bottom:6px;font-size:12.8px}
.note{font-size:12.8px;color:var(--ts);background:var(--s3);border-radius:7px;
 padding:9px 12px;margin:9px 0}
.act{display:flex;gap:6px;flex-wrap:wrap;align-items:center;
 padding:0 15px 11px 33px}
/* 33개 줄에 버튼 4개 + 입력칸이 늘 펼쳐져 있으면 컨트롤이 130개가 넘는다.
   아직 정하지 않은 줄에서만 보이고, 정한 줄은 결과만 남긴다.
   펼쳤거나 마우스를 올렸거나 초점이 들어오면 언제든 다시 나온다. */
.el.done .act{padding-bottom:9px}
.el.done .act .d:not(.on){display:none}
.el.done:hover .act .d,.el.done:focus-within .act .d,
.el.done.open .act .d{display:inline-block}
.el.done .act .m{opacity:.55}
.el.done:hover .act .m,.el.done:focus-within .act .m{opacity:1}
button.d{font:inherit;font-size:12.3px;padding:4px 13px;border-radius:16px;cursor:pointer;
 border:1px solid var(--bd);background:var(--s1);color:var(--ts)}
button.d:hover{border-color:var(--tm)}
button.d.on{color:#fff;border-color:transparent}
button.d.on[data-d="인정"]{background:var(--ok)}
button.d.on[data-d="조건부인정"]{background:var(--cond);color:#3a2a00}
button.d.on[data-d="불인정"]{background:var(--no)}
button.d.on[data-d="보류"]{background:var(--hold)}
input.m{flex:1;min-width:150px;font:inherit;font-size:12.3px;padding:4px 10px;
 border:1px solid var(--bd);border-radius:7px;background:var(--s1);color:var(--tp)}
.saved{font-size:11.3px;color:var(--ok);white-space:nowrap}
.crumbs{display:flex;gap:14px;flex-wrap:wrap;font-size:12.5px;margin-bottom:12px}
.means{margin:8px 0;display:grid;gap:4px}
.means div{font-size:12.5px;line-height:1.55}
.means b{display:inline-block;min-width:74px;color:var(--tp)}
.bar{position:fixed;left:0;right:0;bottom:0;background:var(--s2);border-top:1px solid var(--bd);
 padding:11px 20px;z-index:9}
.bar .in{max-width:1080px;margin:0 auto;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
.bar .st{font-size:12.8px;color:var(--ts);flex:1;min-width:220px}
.bar .st b{font-size:16px;font-variant-numeric:tabular-nums;color:var(--tp)}
select,input.rs{font:inherit;font-size:12.8px;padding:5px 10px;border:1px solid var(--bd);
 border-radius:7px;background:var(--s1);color:var(--tp)}
button.go{font:inherit;font-size:12.8px;padding:6px 18px;border-radius:7px;border:0;
 background:var(--tp);color:var(--s1);cursor:pointer}
button.go:disabled{opacity:.4;cursor:not-allowed}
footer{color:var(--tm);font-size:11.5px;border-top:1px solid var(--bd);padding-top:14px;margin-top:28px}
@media(max-width:680px){
 .el .hd{padding-left:15px}
 .el .dt{padding-left:15px}
 .act{padding-left:15px;gap:4px}
 .act .d{flex:1 1 auto;min-width:0;font-size:12px;padding:6px 8px}
 .act .m{flex:1 1 100%;min-width:0;order:9}
 details.grp>summary{gap:6px}
 .gb{margin-left:0;flex:1 1 100%}}"""


def _evidence(ev: list[dict], frags: dict[str, str]) -> str:
    out = ""
    for x in ev:
        srcs = "".join(
            f'<button class="src" onclick="og(this)" data-f="{e(f)}">{e(f)} 원문</button> '
            for f in x.get("fids") or [])
        origs = "".join(f'<div class="orig" data-f="{e(f)}">{e(frags.get(f, "(원문 없음)"))}</div>'
                        for f in x.get("fids") or [])
        out += f"""<div class="ev">
 <div class="k"><b>{e(x.get('ksa_ref'))}</b> · 신뢰도 {e(x.get('grade'))}등급 · {srcs}</div>
 <q>{e(x.get('quote'))}</q>
 <div class="r">{e(x.get('why'))}</div>{origs}</div>"""
    return out


def _element(x: dict, frags: dict[str, str], rv: dict, names: dict[str, str],
             units: dict[str, str] | None = None) -> str:
    units = units or {}
    p = x["payload"]
    cls, label, hint = REC.get(x["recommendation"], ("r5", x["recommendation"], ""))
    flag = ('<span class="flag">전문가 확인 필요</span>'
            if p.get("needs_expert_review") else "")
    conf = CONF.get(p.get("confidence"), p.get("confidence") or "")

    body = ""
    if ev := p.get("evidence"):
        body += f'<div class="blk"><div class="t">근거 {len(ev)}건</div>{_evidence(ev, frags)}</div>'

    pb = p.get("period_backing") or {}
    if pb.get("note"):
        g = "·".join(pb.get("grades") or []) or "없음"
        body += (f'<div class="blk"><div class="t">소속·기간 뒷받침 ({e(g)}등급)</div>'
                 f'<div class="rem">{e(pb["note"])}</div></div>')

    pl = p.get("prior_learning") or {}
    if pl.get("applies"):
        body += (f'<div class="blk"><div class="t">기이수 교육과정</div><div class="rem">'
                 f'<b>{e(pl.get("unit_code"))}</b> {pl.get("completed_hours") or "?"}시간 이수 '
                 f'(요구 {pl.get("required_hours") or "?"}시간) · {e(pl.get("evaluation"))}</div></div>')

    if neg := p.get("negative_statements"):
        items = "".join(f'<div class="neg">“{e(n.get("quote"))}”'
                        + (f'<br><span class="rem alt">{e(n.get("note"))}</span>' if n.get("note") else "")
                        + "</div>" for n in neg)
        body += f'<div class="blk"><div class="t">본인이 「하지 않았다」고 밝힌 부분</div>{items}</div>'

    if unc := p.get("uncovered_ksa"):
        chips = "".join(
            f'<span class="chip{" neg" if u.get("status") == "부정진술" else ""}">'
            f'{e(u.get("ref"))} · {e(u.get("status"))}</span>' for u in unc)
        body += f'<div class="blk"><div class="t">확인 안 된 항목 {len(unc)}개</div><div class="chips">{chips}</div></div>'

    if rem := p.get("remediation"):
        items = ""
        for r in rem:
            oral = ""
            if r.get("oral_check"):
                oral = ('<br><span class="alt">구술 확인: '
                        + e(" / ".join(r["oral_check"])) + "</span>")
            alt = (f'<br><span class="alt">이 서류를 내면 갈음: {e(r["alt_document"])}</span>'
                   if r.get("alt_document") else "")
            items += (f'<div class="rem"><b>{e(r.get("method"))}</b> — {e(r.get("item"))}'
                      f'<br><span class="alt">{e(r.get("reason"))}</span>{oral}{alt}</div>')
        body += f'<div class="blk"><div class="t">채우는 방법</div>{items}</div>'

    if cf := p.get("conflicts"):
        items = "".join(
            f'<div class="rem">{e(c.get("topic") or "자료 간 차이")} — 채택: {e(c.get("adopted"))}'
            + (f'<br><span class="alt">기각: {e(c["rejected"])}</span>' if c.get("rejected") else "")
            + (f'<br><span class="alt">{e(c["note"])}</span>' if c.get("note") else "")
            + "</div>" for c in cf)
        body += f'<div class="blk"><div class="t">자료 간 어긋난 부분 (버리지 않고 남긴다)</div>{items}</div>'

    if qn := p.get("qualitative_note"):
        body += f'<div class="note">{e(qn)}</div>'

    eid = x["element_id"]
    cur = rv.get(eid) or {}
    btns = "".join(
        f'<button class="d{" on" if cur.get("decision") == d else ""}" data-d="{d}" '
        f'onclick="mark(this,\'{e(eid)}\')">{d}</button>'
        for d in ("인정", "조건부인정", "불인정", "보류"))
    name = names.get(eid) or p.get("element_name") or eid
    # 요소 이름만으로는 구분이 안 된다 — 「용접 전 검사하기」가 세 능력단위에 있다.
    # 접힌 줄에서 어느 능력단위인지 보이지 않으면 접어 둔 의미가 없다.
    unit = p.get("unit_name") or units.get(eid.split("_", 1)[0]) or ""

    # 눈여겨볼 것 — 이 표시가 있으면 펼쳐 보시라는 뜻이다
    marks = ""
    if p.get("negative_statements"):
        marks += '<span class="mk neg">「안 했다」 진술</span>'
    if p.get("conflicts"):
        marks += '<span class="mk cf">자료 상충</span>'
    if p.get("decided_by") == "rule":
        marks += '<span class="mk rule">기록으로 확정</span>'
    n_ev = len(p.get("evidence") or [])
    n_un = len(p.get("uncovered_ksa") or [])

    return f"""<div class="el{' done' if cur else ''}" id="el-{e(eid)}"
     data-rec="{e(x['recommendation'])}" data-by="{e(p.get('decided_by') or 'ai')}">
<div class="hd" onclick="fold(this)">
 <span class="tw">▸</span>
 <span class="tag" style="background:var(--{cls});color:var(--{cls}-fg)">{e(x['recommendation'])}</span>
 <span class="en">{e(name)}</span>
 <span class="un">{e(unit)}</span>
 <span class="mks">{marks}</span>
 <span class="cnt">근거 {n_ev}{f' · 빈 항목 {n_un}' if n_un else ''}</span>
 {flag}
</div>
<div class="act">{btns}
 <input class="m" placeholder="검토 의견 (선택)" value="{e(cur.get('note') or '')}"
        onclick="event.stopPropagation()"
        onchange="mark(document.querySelector('#el-{e(eid)} .d.on'),'{e(eid)}')">
 <span class="saved"></span></div>
<div class="dt">
 <p class="why">{e(p.get('recommendation_reason'))}
  <span class="ec">{hint}{' · 근거 확신 ' + conf if conf else ''}</span></p>
 {body}
</div></div>"""


def render_review(s: Session, assessment_id: int) -> str:
    rb = get_rubric()
    a = s.execute(text("""
        SELECT a.id, a.status, a.rubric_version, a.model, a.overall_note, a.finished_at,
               s.id AS sid, s.case_number, s.target_program_id,
               p.official_name, p.total_hours
        FROM assessment a JOIN submission s ON s.id = a.submission_id
        LEFT JOIN catalog_wsd_program p ON p.program_id = s.target_program_id
        WHERE a.id = :i"""), {"i": assessment_id}).mappings().one()

    els = [dict(r) for r in s.execute(text("""
        SELECT element_id, recommendation, payload FROM assessment_element
        WHERE assessment_id=:i ORDER BY element_id"""), {"i": assessment_id}).mappings()]
    frags = {r[0]: r[1] for r in s.execute(text(
        "SELECT fid, text FROM fragment WHERE submission_id=:i"), {"i": a["sid"]})}
    # 요소 이름은 고시 원문에서 가져온다 — AI 가 적어 준 값보다 이쪽이 옳다
    names = {r[0]: r[1] for r in s.execute(text("""
        SELECT element_id, element_name FROM catalog_ncs_element
        WHERE element_id = ANY(:e)"""), {"e": [x["element_id"] for x in els]})}
    rv = {r["element_id"]: dict(r) for r in s.execute(text("""
        SELECT element_id, decision, note FROM element_review
        WHERE assessment_id=:i"""), {"i": assessment_id}).mappings()}
    fd = s.execute(text("""SELECT decision, reason, decided_by, recognized_hours
                           FROM final_decision WHERE submission_id=:i"""),
                   {"i": a["sid"]}).mappings().first()

    sm = review_summary(s, assessment_id)
    unit_names = {u.unit_code: u.unit_name for u in sm.units}
    note = json.loads(a["overall_note"]) if a["overall_note"] else {}

    # 능력단위 순서가 아니라 **손이 가는 정도**로 묶는다.
    # 33개를 통째로 늘어놓으면 어디부터 볼지 알 수 없다.
    def bucket(x):
        """어디부터 보실지 가른다.

        「부정 진술이 있음」만으로는 절반이 걸려 선별이 안 된다 (33개 중 17개).
        정작 봐야 할 것은 **결정과 어긋나는 자료가 있는데도 그렇게 정해진 것**이다.
        예: 훈련 기록으로 기이수 확정됐는데 반장 확인서에는 「그 자세는 담당한 적 없다」.
        """
        pl = x["payload"]
        odd = bool(pl.get("conflicts")) or bool(pl.get("needs_expert_review")) or (
            pl.get("decided_by") == "rule" and pl.get("negative_statements"))
        if odd:
            return "look"
        return "rule" if pl.get("decided_by") == "rule" else "rest"

    BUCKETS = [
        ("look", "먼저 보실 것",
         "결정과 어긋나는 자료가 있습니다. 그대로 두실지 내리실지 정해 주세요", "no", True),
        ("rest", "판단이 필요한 것",
         "근거를 보시고 인정 여부를 정하십시오", "wn", True),
        ("rule", "기록으로 확정된 것",
         "훈련이수증에 능력단위코드·시간·평가결과가 적혀 있어 규칙대로 정해진 항목입니다. "
         "확인만 하시면 됩니다", "ok", False),
    ]
    buckets: dict[str, list[dict]] = {}
    for x in els:
        buckets.setdefault(bucket(x), []).append(x)

    secs = ""
    for key, title, hint, badge, open_ in BUCKETS:
        items = buckets.get(key) or []
        if not items:
            continue
        done = sum(1 for x in items if x["element_id"] in rv)
        # onclick 속성 안에 JSON 을 넣으면 큰따옴표가 속성을 끊는다.
        # 목록은 data-* 에 두고 버튼은 자기 묶음만 가리키게 한다.
        bulk = "".join(
            f'<button class="sm" data-d="{d}" onclick="bulk(this)">'
            f'{d} {len(items)}개</button>'
            for d in (("인정",) if key == "rule" else ("인정", "조건부인정")))
        cards = "".join(_element(x, frags, rv, names, unit_names) for x in
                        sorted(items, key=lambda y: (y["recommendation"], y["element_id"])))
        secs += f'''<details class="grp" {"open" if open_ else ""} data-k="{key}">
 <summary><span class="st {badge}">{e(title)}</span>
  <b>{len(items)}개</b>
  <span class="pg" data-k="{key}">결정 {done}/{len(items)}</span>
  <span class="gh">{e(hint)}</span>
  <span class="gb" onclick="event.preventDefault();event.stopPropagation()">{bulk}</span>
 </summary>{cards}</details>'''

    pend = len(rb.pending_decisions)
    crit = ", ".join(p.issue for p in rb.critical_pending)
    banner = ""
    if sm.n_expert_review or pend:
        bits = []
        if sm.n_expert_review:
            bits.append(f"<b>{sm.n_expert_review}개 요소</b>가 아직 정해지지 않은 기준에 걸려 있습니다"
                        f" (서류만으로 인정할 때 필요한 최소 확인 범위 — {e(crit)}).")
        bits.append(f"확정 대기 중인 기준 항목이 {pend}건 있습니다. "
                    f"간담회에서 정해지면 이 화면의 계산도 함께 바뀝니다.")
        banner = f'<div class="banner">{" ".join(bits)}</div>'

    rule_ko = ("능력단위의 요소가 <b>전부</b> 인정되어야 그 능력단위 시간을 감면"
               if sm.rule == "all_elements" else "인정된 요소 <b>비율만큼</b> 감면")
    other = "proportional" if sm.rule == "all_elements" else "all_elements"
    legend = "".join(
        f'<div class="lg"><span class="dot" style="background:var(--{REC[k][0]})"></span>'
        f'{k} {REC[k][1]}</div>' for k in ["R0", "R1", "R2", "R3", "R4", "R5"])

    means = "".join(
        f'<div><b>{e(k)}</b> {e(v)}</div>'
        for k, v in (rb.final_decision.get("element_decision_meanings") or {}).items())

    dec_opts = "".join(f'<option{" selected" if fd and fd["decision"] == d else ""}>{d}</option>'
                       for d in rb.final_decision["decisions"])
    fd_line = (f'기록됨 — {e(fd["decision"])} · {fd["recognized_hours"]}시간 '
               f'· {e(fd["decided_by"])}' if fd else "아직 기록 전")

    from services.report.layout import page_open
    return page_open(f"선행학습인정 검토 — {a['case_number']}", css=CSS, here="/cases") + f"""
<div class="crumbs">
 <a href="/submissions/{a['sid']}">← 심사 개요</a>
 <a href="/submissions/{a['sid']}/report/time">시간 대조 보고서</a>
 <a href="/submissions/{a['sid']}/report/evidence">근거 분석 보고서</a>
 <a href="/audit/{e(a['case_number'])}">감사 기록</a>
</div>
<h1>전문가 검토</h1>
<p class="sub">심사번호 {e(a['case_number'])} ·
 {e(a['official_name'] or a['target_program_id'])} · 총 필수 {sm.total_hours}시간 ·
 능력단위 {len(sm.units)}개 / 요소 {sm.n_elements}개 ·
 최종판정 <span id="fd">{fd_line}</span></p>
{banner}
<div class="note" id="guide">
 <b>무엇을 정하시는가</b> — 요소 하나하나에 대해 아래 넷 중 하나를 고르십시오.
 <div class="means">{means}</div>
 근거 분석 보고서를 먼저 읽고 오시면 어디가 쟁점인지 아신 채로 판단하실 수 있습니다.
 <b>다 읽으실 필요는 없습니다</b> — 손이 가는 정도로 묶어 두었습니다.
 요소 줄을 누르면 근거가, 인용문 옆 「원문」을 누르면 제출 자료의 해당 대목이 펼쳐집니다.
 <br><b>이 화면은 판정이 아니라 판정의 근거입니다.</b> 인정 여부는 보시는 분이 정하십니다.
</div>
<div class="kpis">
 <div class="kpi"><span>검토 진행</span><b id="k-prog">{sm.n_reviewed}<i>/{sm.n_elements}</i></b>
   <em id="k-cnt">인정 {sm.counts.get('인정', 0)} · 조건부 {sm.counts.get('조건부인정', 0)}
    · 불인정 {sm.counts.get('불인정', 0)} · 보류 {sm.counts.get('보류', 0)}</em></div>
 <div class="kpi"><span>감면 시간 — 확정</span><b id="k-h">{sm.hours()}<i>시간</i></b>
   <em id="k-r">{sm.rate() * 100:.0f}% · 인정된 것만</em></div>
 <div class="kpi"><span>감면 시간 — 조건부 포함</span><b id="k-hc">{sm.hours(conditional=True)}<i>시간</i></b>
   <em>면접·실기 통과를 전제</em></div>
 <div class="kpi"><span>{'비율 감면' if other == 'proportional' else '전부 인정' } 방식이라면</span>
   <b id="k-ho">{sm.hours(other)}<i>시간</i></b>
   <em id="k-hoc">조건부 포함 {sm.hours(other, True)}시간</em></div>
</div>
<details style="margin-bottom:14px"><summary style="cursor:pointer;font-size:12.5px;
 color:var(--tm)">감면 시간은 어떻게 계산됐나</summary>
 <div class="banner" style="margin-top:8px;border-left-color:var(--bd)">
  {rule_ko}. 이 방식은 아직 확정되지 않았습니다(D-7).
  두 방식의 결과를 모두 보여드리므로 간담회에서 고르시면 됩니다.</div></details>
<details style="margin-bottom:14px"><summary style="cursor:pointer;font-size:12.5px;
 color:var(--tm)">권고 구분 뜻 보기</summary>
 <div class="lgd" style="margin-top:8px">{legend}</div></details>

{secs}

<footer>
기준 v{e(a['rubric_version'])} · 분석 {e(a['model'])} ·
 검증 {'통과' if (note.get('validation') or {}).get('passed') else '미통과'}
 (시도 {(note.get('validation') or {}).get('n_elements') and note.get('attempts') or '-'}회) ·
 화면 생성 {datetime.now():%Y-%m-%d %H:%M}<br>
{e(note.get('overall_note') or '')}
</footer></div>

<div class="bar"><div class="in">
 <div class="st">검토 <b id="b-prog">{sm.n_reviewed}</b>/{sm.n_elements} ·
  감면 <b id="b-h">{sm.hours()}</b>/{sm.total_hours}시간
  <span id="b-sug">(권고안 {sm.suggest_decision()})</span></div>
 <select id="dec">{dec_opts}</select>
 <input class="rs" id="who" placeholder="검토자" value="{e(fd['decided_by'] if fd else '')}">
 <input class="rs" id="why" placeholder="판정 사유" style="flex:1;min-width:180px"
        value="{e(fd['reason'] if fd else '')}">
 <button class="go" id="save">최종 판정 기록</button>
</div></div>

<script>
const AID = {assessment_id}, SID = {a['sid']};

// 고정 바가 마지막 요소를 덮지 않게 한다. 창 크기가 바뀌면 바도 높이가 바뀐다.
const fitBar = () => document.documentElement.style.setProperty(
  '--barh', document.querySelector('.bar').offsetHeight + 'px');
fitBar();
addEventListener('resize', fitBar);
new ResizeObserver(fitBar).observe(document.querySelector('.bar'));
const $ = id => document.getElementById(id);      // id 에 하이픈이 있으면 전역 변수가 생기지 않는다

function og(b){{
 event.stopPropagation();
 const t = b.closest('.ev').querySelector('.orig[data-f="' + b.dataset.f + '"]');
 if(t) t.classList.toggle('on');
}}

function fold(hd){{ hd.parentElement.classList.toggle('open'); }}

function groupCounts(){{
 document.querySelectorAll('details.grp').forEach(g => {{
  const els = g.querySelectorAll('.el');
  const done = g.querySelectorAll('.el.done').length;
  const pg = g.querySelector('.pg');
  if(pg) pg.textContent = `결정 ${{done}}/${{els.length}}`;
 }});
}}

async function bulk(btn){{
 const grp = btn.closest('details.grp');
 const ids = [...grp.querySelectorAll('.el')].map(el => el.id.slice(3));
 const decision = btn.dataset.d;
 if(!ids.length) return;
 if(!confirm(`${{ids.length}}개 요소를 "${{decision}}"으로 한 번에 기록합니다. 계속할까요?`)) return;
 const old = btn.textContent; btn.disabled = true; btn.textContent = '기록 중…';
 try {{
  const r = await fetch(`/assessments/${{AID}}/reviews`, {{
   method: 'POST', headers: {{'Content-Type': 'application/json'}},
   body: JSON.stringify({{element_ids: ids, decision,
                        reviewer: $('who').value || null}})}});
  if(!r.ok) throw new Error((await r.json()).detail || r.status);
  ids.forEach(id => {{
   const el = document.getElementById('el-' + id);
   if(!el) return;
   el.classList.add('done');
   el.querySelectorAll('button.d').forEach(b =>
     b.classList.toggle('on', b.dataset.d === decision));
  }});
  groupCounts(); refresh();
 }} catch(err) {{ alert('기록하지 못했습니다: ' + err.message); }}
 finally {{ btn.disabled = false; btn.textContent = old; }}
}}

async function refresh(){{
 let d;
 try {{
  const r = await fetch(`/assessments/${{AID}}/review/summary`);
  if(!r.ok) throw new Error(r.status);
  d = await r.json();
 }} catch(err) {{
  $('b-sug').textContent = '(진행 상황을 불러오지 못했습니다)';
  return;
 }}
 $('k-prog').innerHTML = d.n_reviewed + '<i>/' + d.n_elements + '</i>';
 $('k-cnt').textContent = `인정 ${{d.counts.인정}} · 조건부 ${{d.counts.조건부인정}}`
   + ` · 불인정 ${{d.counts.불인정}} · 보류 ${{d.counts.보류}}`;
 $('k-h').innerHTML = d.hours + '<i>시간</i>';
 $('k-r').textContent = Math.round(d.rate * 100) + '% · 인정된 것만';
 $('k-hc').innerHTML = d.hours_conditional + '<i>시간</i>';
 $('k-ho').innerHTML = d.hours_other_rule + '<i>시간</i>';
 $('k-hoc').textContent = '조건부 포함 ' + d.hours_other_conditional + '시간';
 $('b-prog').textContent = d.n_reviewed;
 $('b-h').textContent = d.hours;
 $('b-sug').textContent = d.complete ? `(권고안 ${{d.suggested}})`
   : `(남은 요소 ${{d.n_elements - d.n_reviewed}}개)`;
 $('dec').value = d.suggested;
 $('save').disabled = !d.complete;
 $('save').title = d.complete ? '' : '요소 검토를 모두 마쳐야 기록할 수 있습니다';
}}

async function mark(btn, eid){{
 if(!btn) return;
 const el = document.getElementById('el-' + eid);
 el.querySelectorAll('button.d').forEach(b => b.classList.toggle('on', b === btn));
 const tag = el.querySelector('.saved');
 tag.textContent = '저장 중…'; tag.style.color = 'var(--tm)';
 try {{
  const r = await fetch(`/assessments/${{AID}}/elements/${{encodeURIComponent(eid)}}/review`, {{
   method: 'POST', headers: {{'Content-Type': 'application/json'}},
   body: JSON.stringify({{decision: btn.dataset.d,
                        note: el.querySelector('input.m').value || null,
                        reviewer: $('who').value || null}})}});
  if(!r.ok) throw new Error((await r.json()).detail || r.status);
  tag.textContent = '저장됨'; tag.style.color = 'var(--ok)';
  el.classList.add('done');
  groupCounts();
 }} catch(err) {{
  tag.textContent = '저장 실패 — ' + err.message; tag.style.color = 'var(--no)';
  return;
 }}
 refresh();
}}

$('save').onclick = async () => {{
 const b = $('save'); b.disabled = true;
 try {{
  const r = await fetch(`/submissions/${{SID}}/decision`, {{
   method: 'POST', headers: {{'Content-Type': 'application/json'}},
   body: JSON.stringify({{assessment_id: AID, decision: $('dec').value,
                        reason: $('why').value || null,
                        decided_by: $('who').value || null}})}});
  const d = await r.json();
  if(r.ok) $('fd').textContent =
    `기록됨 — ${{d.decision}} · ${{d.recognized_hours}}시간 · ${{$('who').value || '검토자 미기재'}}`;
  alert(r.ok ? `기록했습니다 — ${{d.decision}} · 감면 ${{d.recognized_hours}}시간`
             : `기록하지 못했습니다: ${{d.detail}}`);
 }} finally {{
  refresh();
 }}
}};

refresh();
</script></body></html>"""
