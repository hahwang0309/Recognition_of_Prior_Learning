"""심사 개요 — 접수번호를 누르면 열리는 화면.

## 이 화면이 답하는 것

심사위원이 한 건을 열었을 때 알고 싶은 것은 셋이다.

  ① 이 사람은 지금 어디까지 인정됐나
  ② 다음에 무엇을 해야 하나
  ③ 그 근거는 어디서 보나

그래서 화면도 셋이다 — 한 줄 요약, 네 단계 카드, 제출 자료.
판단을 입력하는 자리는 여기에 없다. 그것은 검토 화면이 맡는다.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.assess.case_state import CaseState, case_state
from services.report.layout import e, page
from services.report._shared import (ORDER, STEP_BLOCKED, STEP_CSS, step_nav,
                                     steps_of, track_chip)
from services.review.coverage import unit_verdicts
from services.review.unit_hours import evidence_aid, unit_gaps

CSS = """
.hdr{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:2px}
.hdr h1{margin:0}
.gauge{background:var(--s2);border:1px solid var(--bd);border-radius:10px;
 padding:14px 17px;margin-bottom:22px}
.gauge .line{font-size:14.5px;line-height:1.6;margin-bottom:10px}
.gauge .line b{font-size:19px;font-variant-numeric:tabular-nums}
.gauge .line .dim{color:var(--tm)}
.bar2{display:flex;height:14px;border-radius:7px;overflow:hidden;background:var(--s3)}
.bar2 .yes{background:var(--ok)}
.bar2 .exp{background:var(--ok);opacity:.5}
.bar2 .maybe{background:var(--ac)}
.bar2 .todo{background:var(--ac);opacity:.35}
.leg{display:flex;gap:16px;font-size:11.5px;color:var(--tm);margin-top:7px;flex-wrap:wrap}
.leg i{display:inline-block;width:11px;height:11px;border-radius:3px;
 margin-right:5px;vertical-align:-1px;font-style:normal}
.leg .yes{background:var(--ok)}.leg .maybe{background:var(--ac)}.leg .no{background:var(--s3)}
.leg .exp{background:var(--ok);opacity:.5}
.leg .todo{background:var(--ac);opacity:.35}
.gauge .line.dim{color:var(--tm)}

/* 네 단계. 번호·제목·상태가 한 줄, 설명과 버튼이 그 아래. */
.step{display:grid;grid-template-columns:30px 1fr auto;gap:0 12px;
 background:var(--s2);border:1px solid var(--bd);border-radius:10px;
 padding:13px 16px;margin-bottom:9px;align-items:start}
.step.now{border-color:var(--ac);box-shadow:0 0 0 1px var(--ac)}
.step.off{opacity:.55}
.step .no{grid-row:1/3;font-size:15px;font-weight:600;color:var(--tm);
 font-variant-numeric:tabular-nums;line-height:1.5}
.step .ttl{font-size:14.5px;font-weight:600;display:flex;align-items:center;
 gap:8px;flex-wrap:wrap}
.step .why{grid-column:2;font-size:12.8px;color:var(--ts);margin-top:3px;line-height:1.55}
.step .why em{font-style:normal;color:var(--tm)}
.step .act{grid-row:1/3;grid-column:3;align-self:center;white-space:nowrap}
.step .act a{display:inline-block;font-size:13px;padding:7px 15px;border-radius:7px;
 border:1px solid var(--bd);background:var(--s1);color:var(--ts)}
.step .act a:hover{border-color:var(--tm);text-decoration:none}
details.danger{margin:22px 0 0;border:1px solid var(--crit,#d03b3b);border-radius:10px;padding:10px 14px}
details.danger summary{cursor:pointer;color:var(--crit,#d03b3b);font-weight:600;font-size:13px}
details.danger p{font-size:12.5px;margin:8px 0 4px}
details.danger .drow{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:8px}
details.danger input[type=text],details.danger input#rmc{font:inherit;font-size:13px;padding:5px 8px;border:1px solid var(--bd);border-radius:6px}
details.danger label{font-size:12.5px}
button.danger-go{font:inherit;font-size:13px;font-weight:600;padding:6px 14px;border-radius:8px;
 border:1px solid var(--crit,#d03b3b);background:var(--crit,#d03b3b);color:#fff;cursor:pointer}
#rmnote{font-size:12px;color:var(--tm)}
.step .act a.go{background:var(--tp);color:var(--s1);border-color:transparent;font-weight:600}
.step .act form{display:inline}

/* 진행 중 막대 */
.prog{margin-top:8px;grid-column:2}
.prog .t{height:6px;border-radius:3px;background:var(--s3);overflow:hidden;max-width:280px}
.prog .f{height:100%;background:var(--ac);transition:width .4s}
.prog small{display:block;font-size:11.5px;color:var(--tm);margin-top:4px}

.docs{font-size:12.5px}
.docs .g{display:inline-block;font-size:10.5px;padding:1px 6px;border-radius:9px;
 background:var(--s3);color:var(--ts);margin-left:6px;vertical-align:1px}
.miss{margin-top:10px}
.miss summary{cursor:pointer;font-size:12.8px;color:var(--ac)}
/* 다섯 단계로 바로 가는 줄 — 면접 질문지·실기 과제가 여기 있다 */
.slinks{grid-column:2;display:flex;flex-wrap:wrap;gap:6px;margin-top:9px}
.slinks a{font-size:12.2px;padding:4px 10px;border-radius:14px;
 border:1px solid var(--bd);background:var(--s1);color:var(--ts);white-space:nowrap}
.slinks a:hover{border-color:var(--tm);text-decoration:none}
.slinks a em{font-style:normal;color:var(--tm);margin-left:4px;font-size:11.3px}
.slinks a.done{color:var(--tm)}
.slinks a.now{border-color:var(--ac);color:var(--tp);font-weight:600}
.miss table{margin-top:8px}
"""


def _gauge(st: CaseState, b_units: list | None = None) -> str:
    """시간이 지금 어디에 놓여 있는지 한 눈에.

    예전에는 기록 확인 결과만 읽었다. 그래서 전문가가 100시간을 더 인정한
    뒤에도 「아직 확인되지 않은 시간」이 그대로 300시간이라고 적혀 있었다
    (실측 R2026-9002: 450시간 중 기록 150 + 전문가 100, 남은 것은 200시간).
    검토가 시작됐으면 그 결과까지 읽는다.
    """
    tot = st.total_hours or 1
    # 최종 판정이 기록됐으면 그것이 답이다 — 트랙보다 앞선다(아래 분기가 처리한다).
    if b_units is not None and (st.decision or {}).get("recognized_hours") is None:
        # Track B 에는 기록 확인이 없다 — 「기록으로 확인된 시간」을 말할 수 없다.
        yes = sum(u["hours"] for u in b_units if u["verdict"] == "인정")
        hold = sum(u["hours"] for u in b_units if u["verdict"] == "보류")
        return (f'<div class="line">근거로 인정된 시간 <b>{yes}</b>시간'
                f' <span class="dim">/ {st.total_hours}시간 ({yes / tot:.0%})</span>'
                f'{f" · 보류 <b>{hold}</b>시간" if hold else ""}'
                f' · 남은 훈련 <b>{st.total_hours - yes}</b>시간</div>')
    sp = st.split
    if sp is None:
        # 아직 검토 전 — 기록 확인이 남긴 것만 말할 수 있다.
        yes = st.credited_hours / tot * 100
        maybe = min(100 - yes, st.open_hours / tot * 100) if st.evidence_done else 0.0
        return (
            f'<div class="line">기록으로 확인된 시간 <b>{st.credited_hours}</b>시간'
            f' <span class="dim">/ {st.total_hours}시간 ({st.credited_ratio:.0%})</span>'
            f'&nbsp;·&nbsp; 아직 확인되지 않은 시간 <b>{st.open_hours}</b>시간</div>\n'
            f' <div class="bar2"><div class="yes" style="width:{yes:.2f}%"></div>'
            f'<div class="maybe" style="width:{maybe:.2f}%"></div></div>\n'
            f' <div class="leg"><span><i class="yes"></i>이수 기록으로 확인</span>'
            + (f'<span><i class="maybe"></i>제출 자료로 따져 볼 수 있음</span>'
               if maybe else "")
            + f'<span><i class="no"></i>{"훈련으로 채워야 함" if st.evidence_done else "아직 확인 안 됨"}</span></div>')

    # 최종 판정이 났으면 그것이 답이다. 계산값과 다르면 그 차이도 적는다 —
    # 실측 R2026-9010 에서 막대는 370시간, ④ 칸은 300시간이라 말했다.
    dec = st.decision or {}
    fixed = dec.get("recognized_hours")
    if fixed is not None:
        pct = fixed / sp.total * 100 if sp.total else 0
        gap = sp.credited - int(fixed)
        note = (f' <span class="dim">검토 계산은 {sp.credited}시간이었고, '
                f'심사위원이 {abs(gap)}시간을 '
                f'{"빼고" if gap > 0 else "더해"} 정했습니다.</span>' if gap else "")
        return (
            f'<div class="line">최종 판정 <b>{e(str(dec.get("decision") or ""))}</b>'
            f' · 인정 <b>{fixed}</b>시간'
            f' <span class="dim">/ {sp.total}시간 ({pct:.0f}%)</span>{note}</div>\n'
            f' <div class="line">훈련으로 채워야 할 시간 <b>{sp.total - int(fixed)}</b>시간'
            f' <span class="dim">· 기록 확인 {sp.record}시간 + 전문가 판단 {sp.expert}시간'
            f' 으로 확인된 것 가운데 정한 것입니다</span></div>\n'
            f' <div class="bar2"><div class="yes" style="width:{pct:.2f}%"></div></div>\n'
            f' <div class="leg"><span><i class="yes"></i>인정</span>'
            f'<span><i class="no"></i>훈련으로 채워야 함</span></div>')

    # 검토가 시작된 뒤 — 다섯 칸으로 가른다. 합은 언제나 총 필수 시간이다.
    # 0시간짜리 칸은 범례에서 뺀다 — 색이 없는데 이름만 있으면 헷갈린다.
    leg = "".join(
        f'<span><i class="{c}"></i>{n}</span>'
        for h, c, n in ((sp.record, "yes", "이수 기록으로 확인"),
                        (sp.expert, "exp", "전문가 판단으로 인정"),
                        (sp.pending, "maybe", "면접·실기·추가서류로 확인"),
                        (sp.unjudged, "todo", "아직 판단 전"),
                        (sp.training, "no", "훈련으로 채워야 함")) if h)
    parts = []
    if sp.unjudged:
        parts.append(f"검토가 남은 {sp.unjudged}시간")
    if sp.pending:
        parts.append(f"면접·실기·추가서류로 확인할 {sp.pending}시간")
    if sp.training:
        parts.append(f"훈련으로 채워야 할 {sp.training}시간")
    if len(parts) > 1:
        rest = "= " + " + ".join(parts)
    elif sp.training:
        rest = "— 확인으로 풀리는 것은 없습니다. 훈련으로 채워야 합니다"
    elif sp.pending:
        rest = "— 모두 면접·실기·추가서류로 확인할 수 있습니다"
    elif sp.unjudged:
        rest = ("— 아직 1단계 판단이 남았습니다. 여기서 무엇을 면접·실기로 "
                "볼지 갈립니다")
    else:
        rest = ""
    how = ""
    if sp.methods:
        # 한 단위에 면접·실기가 둘 다 걸릴 수 있어 겹쳐 센다. 그렇다고 적는다.
        ms = " · ".join(f"{e(m)} {h}시간" for m, h in
                        sorted(sp.methods.items(), key=lambda x: -x[1]))
        dup = " — 한 단위에 둘이 걸린 곳이 있어 겹쳐 셌습니다" if len(sp.methods) > 1 else ""
        how = (f'<div class="line dim" style="font-size:12.5px">'
               f'기계가 제안한 확인 방법 — {ms}{dup}</div>')
    return (
        f'<div class="line">지금까지 인정 <b>{sp.credited}</b>시간'
        f' <span class="dim">/ {sp.total}시간 ({sp.pct(sp.credited):.0f}%)'
        f' &nbsp;= 기록 확인 {sp.record}시간 + 전문가 판단 {sp.expert}시간</span></div>\n'
        f' <div class="line">아직 확인되지 않은 시간 <b>{sp.open}</b>시간'
        f' <span class="dim">{rest}</span></div>\n'
        f' {how}\n'
        f' <div class="bar2"><div class="yes" style="width:{sp.pct(sp.record):.2f}%"></div>'
        f'<div class="exp" style="width:{sp.pct(sp.expert):.2f}%"></div>'
        f'<div class="maybe" style="width:{sp.pct(sp.pending):.2f}%"></div>'
        f'<div class="todo" style="width:{sp.pct(sp.unjudged):.2f}%"></div></div>\n'
        f' <div class="leg">{leg}</div>')


def _step_bar(st: CaseState, sid: int, has_ev: bool,
              ev_aid: int | None, has_plan: bool) -> str:
    """개요에도 같은 단계줄을 둔다 — 이동하는 방법이 화면마다 다르면 안 된다.

    트랙에 따라 줄이 다르다. Track B 에는 ① 기록 확인이 없고 근거 분석 판정을
    축으로 돈다. 개요는 어느 단계도 아니므로 「현재」 표시는 없다.
    """
    track = (st.track or "A").upper()
    steps = steps_of(track)
    nav = step_nav(sid, st.time.id if st.time else None, has_ev,
                   track=track, ev_aid=ev_aid, has_plan=has_plan)
    out = ""
    for k in ORDER[track]:
        label = e(steps[k][0])
        if nav.get(k):
            out += f'<a href="{e(nav[k])}" title="{e(steps[k][1])}">{label}</a>'
        else:
            out += f'<span class="off" title="{e(STEP_BLOCKED[k])}">{label}</span>'
    return f'<div class="step-nav">{out}</div>'


def _step(no: str, title: str, badge: str, why: str, act: str = "",
          *, now: bool = False, off: bool = False, extra: str = "") -> str:
    cls = " now" if now else (" off" if off else "")
    return f"""<div class="step{cls}">
  <div class="no">{no}</div>
  <div class="ttl">{e(title)}{badge}</div>
  <div class="act">{act}</div>
  <div class="why">{why}</div>{extra}
</div>"""


# 다섯 단계로 바로 들어가는 줄. 「검토하기」 한 개만 있으면 면접 질문지와
# 실기 과제 목록이 어디 있는지 알 수 없다 — 실제로 그런 질문을 받았다.
WHAT = {2: "요청할 서류", 3: "면접 질문지", 4: "실기 과제"}


def _stage_links(st: CaseState, aid: int) -> str:
    if not st.stages:
        return ""
    out = ""
    for x in st.stages:
        n = x["n"]
        if x["skipped"]:
            note = (f"{x['moot']}건 · 결과 안 바뀜" if x.get("moot")
                    else "해당 없음")
        elif n == 5:
            note = "보기"
        elif x["complete"]:
            note = f"{x['done']}/{x['total']} 완료"
        else:
            note = f"{x['done']}/{x['total']}"
        cls = "sl done" if x["complete"] else ("sl now" if n == st.next_stage else "sl")
        what = WHAT.get(n)
        # 무엇이 들어 있는 단계인지 이름을 붙여 준다
        # 건너뛴 단계라도 볼 것이 남아 있으면 이름을 붙인다 — 면접 질문지가
        # 어디 있는지 묻는 사람에게 「3 면접」만으로는 답이 되지 않는다.
        has = (not x["skipped"]) or x.get("moot")
        title = f"{x['title']} · {what}" if what and has else x["title"]
        out += (f'<a class="{cls}" href="/assessments/{aid}/review/{n}">'
                f'{n} {e(title)} <em>{e(note)}</em></a>')
    return f'<div class="slinks">{out}</div>'


def _st(text: str, kind: str = "") -> str:
    return f'<span class="st {kind}">{e(text)}</span>'


DELETE_JS = """
(function(){
 var g=document.getElementById('rmgo'); if(!g) return;
 g.addEventListener('click', function(){
   var c=document.getElementById('rmc').value.trim();
   var n=document.getElementById('rmnote');
   if(!c){ n.textContent='심사번호를 적으십시오'; return; }
   if(!confirm('정말 지웁니까? 되돌릴 수 없습니다.')) return;
   n.textContent='지우는 중…';
   fetch('/submissions/%d/remove', {method:'POST',
     headers:{'Content-Type':'application/json'},
     body:JSON.stringify({confirm:c, purge_audit:document.getElementById('rmp').checked})})
    .then(function(r){ if(!r.ok) return r.json().then(function(j){throw new Error(j.detail||r.status)});
                       return r.json(); })
    .then(function(){ location.href='/cases'; })
    .catch(function(e){ n.textContent='지우지 못했습니다 — '+e.message; });
 });
})();
"""


def render_case(s: Session, submission_id: int) -> str | None:
    st = case_state(s, submission_id)
    if st is None:
        return None
    sid = st.submission_id
    is_b = (st.track or "A").upper() == "B"
    # Track B 에는 ① 기록 확인이 없다. 번호가 겹치면 어느 것이 먼저인지 알 수 없다.
    NO_REC, NO_EV = ("참고", "①") if is_b else ("①", "②")
    steps = ""

    # ── ① 기록 확인 ────────────────────────────────────────────────
    # Track B 는 NCS 이수 기록이 없는 것이 전제라 기록 확인을 돌리지 않는다.
    # 대신 서류가 없으면 올리라고 말해야 한다 — 그 안내까지 사라지면 안 된다.
    if is_b:
        if st.n_documents == 0:
            steps += _step("", "서류 접수", _st("대기"),
                           "제출 자료가 없습니다. 서류를 올리면 근거 분석을 할 수 있습니다.",
                           f'<a class="go" href="/submissions/{sid}/upload">서류 올리기</a>',
                           now=True)
        elif st.time and st.time.done and st.credited_hours:
            # 돌린 적이 있고 무언가 나왔다면 참고로 남긴다(옛 접수 건).
            steps += _step("참고", "기록 확인", _st("있음"),
                           f"이수 기록에서 <b>{st.credited_hours}시간</b>이 확인됐습니다. "
                           "Track B 판정에는 쓰지 않습니다.",
                           f'<a href="/submissions/{sid}/report/time">기록 확인 보기</a>')
    elif st.time and st.time.done:
        n = st.time.note.get("근거", {})
        src = []
        if n.get("자격"):
            src.append(f"과정평가형 자격 {n['자격']}개 단위")
        if n.get("기이수"):
            src.append(f"훈련 이수 기록 {n['기이수']}개 단위")
        why = (f"{' · '.join(src)}에서 <b>{st.credited_hours}시간</b>이 확인됐습니다."
               if src else
               "요구 시간을 갈음할 이수 기록이 확인되지 않았습니다.")
        if st.skipped:
            why += (f' <em>이수 기록을 낸 {len(st.skipped)}개 단위는 갈음되지 '
                    f'않았습니다 — 아래에 이유를 적었습니다.</em>')
        steps += _step(NO_REC, "기록 확인", _st("완료", "ok"), why,
                       f'<a href="/submissions/{sid}/report/time">기록 확인 보기</a>')
    elif st.n_documents == 0:
        steps += _step(NO_REC, "기록 확인", _st("대기"),
                       "제출 자료가 없습니다. 서류를 올리면 자동으로 대조합니다.",
                       f'<a class="go" href="/submissions/{sid}/upload">서류 올리기</a>',
                       now=True)
    else:
        steps += _step(NO_REC, "기록 확인", _st("안 돌았음", "no"),
                       "자동 실행이 실패했습니다. 서류를 다시 올리면 재시도합니다.",
                       f'<a href="/submissions/{sid}/upload">서류 다시 올리기</a>', now=True)

    # ── ② 근거 분석 ────────────────────────────────────────────────
    # 「도는 중」과 「이미 나온 보고서」는 따로 본다. 재실행 한 번에 완성된
    # 보고서가 화면에서 사라지면 안 된다.
    ev, done = st.evidence, st.evidence_done
    # 검증을 통과 못 한 실행(manual_review)도 산출물은 있다. 그것을 볼 길을 막아 두면
    # 위원이 결과를 보려고 「다시 시도」를 누르게 된다 — 누를 때마다 AI 실호출이다.
    # 실제로 그렇게 한 건에서 $0.81 이 더 나갔다.
    # 「볼 수 있는 결과가 있나」는 보고서 라우트와 **같은 함수**로 판단한다.
    # 각자 세면 갈라진다 — 개요는 최신 실행만 보고 라우트는 요소가 있는 실행을 골라서,
    # 뒤에 빈 실행이 한 번 돌면 개요에서 링크가 사라지고 URL 로는 열리는 상태가 됐다.
    report_link = (f'<a href="/submissions/{sid}/report/evidence">{NO_EV} 근거 분석 보기</a>'
                   if evidence_aid(s, sid) else "")
    if st.analyzing:
        n_done, n_all, phase, _left = ev.steps if ev else (0, 0, "", [])
        pct = n_done / n_all * 100 if ev and ev.running and n_all else 0
        step = e(phase) if ev and ev.running else "차례를 기다리는 중"
        bar = (f'<div class="prog"><div class="t"><div class="f" '
               f'style="width:{pct:.0f}%"></div></div>'
               f'<small id="prog-txt">'
               + (f'{n_done}/{n_all or "?"} 능력단위 · {step}' if ev and ev.running
                  else f'{step} — 시작 {st.queued_at:%H:%M:%S}')
               + '</small></div>')
        if st.stalled:
            # 큐에 넣기만 하고 아무도 집지 않는다. 그대로 두면 영영 안 된다.
            why = ("<b>판정 워커가 돌고 있지 않습니다.</b> 시작은 기록됐지만 "
                   "아무도 집어 가지 않습니다.<br>터미널에서 아래를 실행하십시오 — "
                   "그러면 이 건이 바로 시작됩니다."
                   "<br><code style='font-size:12px'>./scripts/dev.sh worker</code>")
            steps += _step(NO_EV, "근거 분석", _st("워커 없음", "no"), why,
                           '<a href="">새로 고침</a>', now=True, extra=bar)
        else:
            why = ("차례를 기다리는 중입니다. 몇 초 안에 시작됩니다."
                   if st.waiting_in_queue else
                   "제출 자료를 능력단위별로 읽고 있습니다. 6~30분 걸립니다.")
            if done:
                why += " <em>지난 보고서는 그대로 보실 수 있습니다.</em>"
            steps += _step(NO_EV, "근거 분석",
                           _st("대기 중" if st.waiting_in_queue else "진행 중", "ac"),
                           why, report_link or '<a href="">새로 고침</a>',
                           now=True, extra=bar)
    elif ev is not None and ev.broke and not done:
        # 끝났는데 기계 검증을 다 통과하지 못했다. 그래도 판단한 항목은 남아 있으므로
        # 사람이 읽고 「확인」하면 넘어간다 — ② 는 읽는 자리라 눌러서 바뀌는 것이
        # 없었고, 그래서 이 칸이 영영 「확인 필요」에 머물렀다.
        confirm = (f'<form method="post" action="/submissions/{sid}/evidence/confirm" '
                   f'style="display:inline;margin-left:10px">'
                   f'<button class="go" type="submit">확인 완료</button></form>')
        again = (f'<form method="post" action="/submissions/{sid}/analyze" '
                 f'style="display:inline;margin-left:10px">'
                 f'<button type="submit">다시 시도 (AI 재호출 · 약 $1)</button></form>')
        if st.evidence_ack:
            steps += _step(NO_EV, "근거 분석", _st("확인함", "ok"),
                           f"{e(ev.trouble)}<em> 호출 {ev.attempts}회"
                           f"{f' · {ev.finished_at:%m-%d %H:%M}' if ev.finished_at else ''}</em>"
                           "<br>기계 검증은 다 통과하지 못했지만 <b>읽고 넘어가신 결과</b>입니다.",
                           (report_link or '') + again)
        else:
            steps += _step(NO_EV, "근거 분석",
                           _st("확인 필요" if ev.status == "manual_review" else "실패", "no"),
                           f"{e(ev.trouble)}<em> 호출 {ev.attempts}회"
                           f"{f' · {ev.finished_at:%m-%d %H:%M}' if ev.finished_at else ''}</em>"
                           "<br><b>결과는 그대로 보실 수 있습니다.</b> 기계 검증을 다 통과하지 "
                           "못했을 뿐이며, 판단한 항목은 남아 있습니다. 읽어 보신 뒤 "
                           "<b>확인 완료</b>를 누르면 ③ 으로 넘어갑니다.",
                           (report_link or '') + confirm + again,
                           now=True)
    elif done:
        # 재판정한 건은 마지막 실행분만 보이면 실제보다 싸 보인다.
        cost = f" · 비용 ${st.runs_cost:.2f}" if st.runs_cost else ""
        again = (f" · 판정 {st.n_runs}회(추가 서류 반영)" if st.n_runs > 1 else "")
        # 두 Run 은 서로 다른 조회에서 왔으므로 같은 판정이라도 객체가 다르다.
        # `is not` 로 비교했다가 실패한 적이 없는데도 실패했다고 적었다. id 로 본다.
        warn = ('<em> 다시 돌린 분석이 끝나지 못했습니다 — 아래는 지난 결과입니다.</em>'
                if ev and ev.id != done.id and not ev.running else "")
        steps += _step(NO_EV, "근거 분석", _st("완료", "ok"),
                       f"추가 자료 {len(st.extra_docs)}종에서 "
                       f"<b>{done.n_elements}개 항목</b>을 판단했습니다."
                       f"<em> 호출 {st.runs_attempts}회{cost}{again}</em>{warn}",
                       report_link)
    elif st.can_analyze:
        kinds = "·".join(sorted({d["doc_type"] for d in st.extra_docs})[:3])
        failed = ('<em> 지난 분석이 끝나지 못했습니다. 다시 시작하실 수 있습니다.</em>'
                  if ev else "")
        steps += _step(NO_EV, "근거 분석", _st("할 수 있음", "wn"),
                       f"경력·수행을 보여 주는 자료가 <b>{len(st.extra_docs)}건</b> 있습니다"
                       f"({e(kinds)} 등). 기록 확인으로 덮이지 않은 "
                       f"<b>{st.open_hours}시간</b>을 이 자료로 따져 볼 수 있습니다.{failed}",
                       f'<form method="post" action="/submissions/{sid}/analyze">'
                       f'<button class="go" type="submit">{NO_EV} 근거 분석 시작</button></form>',
                       now=True)
    else:
        steps += _step(NO_EV, "근거 분석", _st("해당 없음"),
                       "경력·수행을 보여 주는 자료가 없어 분석할 것이 없습니다.",
                       off=True)

    # ── ③ 전문가 검토 ──────────────────────────────────────────────
    # 시간이 모자란 단위를 위원이 메우는 자리다. 진행 상태는 저장된 인정 시간으로
    # 센다 — 예전에는 Track B 5단계 검토만 보고 있어서, 위원이 ③ 을 다 마쳐도
    # 개요는 「대기」에 머물렀다.
    gaps = [] if is_b else (unit_gaps(s, st.time.id) if st.time else [])
    ev_aid = evidence_aid(s, sid)
    b_units = unit_verdicts(s, ev_aid) if (is_b and ev_aid) else []
    has_plan = bool(ev_aid) and bool(s.execute(text(
        "SELECT 1 FROM artifact WHERE assessment_id=:a AND stage='plan' LIMIT 1"),
        {"a": ev_aid}).first())
    # Track B 로 접수한 건은 다섯 단계 검토가 따로 있다. 그 줄을 없애면 면접 질문지와
    # 실기 과제 목록으로 가는 길이 사라진다 — 실제로 그 질문을 받았던 자리다.
    stg = _stage_links(st, done.id) if done else ""
    # 근거 분석 결과가 있으면 그쪽 검토 수치도 함께 말한다 — 개요와 검토 화면이
    # 다른 수를 말하면 어느 쪽을 믿어야 할지 알 수 없다.
    if done and st.n_settled:
        stg = (f'<em> 근거 분석 항목 가운데 <b>{st.n_settled}개</b>는 '
               f'이수 기록으로 확정된 것입니다.</em>') + stg
    if is_b:
        # Track B 의 검토는 항목별 근거 인정이다 — 위원 페이지가 그 자리다.
        # 여기까지 가는 길이 없어 위원이 주소를 직접 쳐야 했다.
        if ev_aid is None:
            steps += _step("②", "위원 검토", _st("대기"),
                           "근거 분석이 끝나면 판단할 항목이 나옵니다.", off=True)
        else:
            steps += _step("②", "위원 검토",
                           _st("제출함" if has_plan else "할 수 있음",
                               "ok" if has_plan else "wn"),
                           ("항목별로 인정 여부를 정하고 제출하셨습니다. "
                            "확인 계획이 만들어져 있습니다."
                            if has_plan else
                            "근거마다 적합도(직접·간접·부정)가 매겨져 있습니다. "
                            "간접 근거를 인정할지 정하고 제출하십시오.") + stg,
                           (f'<a href="/assessments/{ev_aid}/panel">② 위원 검토 보기</a>'
                            if has_plan else
                            f'<a class="go" href="/assessments/{ev_aid}/panel">② 위원 검토</a>'),
                           now=not has_plan)
            if has_plan:
                steps += _step("③", "확인 계획", _st("있음", "ok"),
                               "보류 단위의 미확인 항목을 시험·시연·면접으로 배정했습니다.",
                               f'<a href="/assessments/{ev_aid}/plan">③ 확인 계획 보기</a>')
            else:
                steps += _step("③", "확인 계획", _st("대기"),
                               "위원 검토를 제출하면 만들어집니다.", off=True)
    elif st.time is None:
        steps += _step("③", "전문가 검토", _st("대기"),
                       "기록 확인이 끝나면 정할 것이 나옵니다." + stg, off=True)
    elif not gaps:
        steps += _step("③", "전문가 검토", _st("해당 없음", "ok"),
                       "모든 능력단위가 이수 기록만으로 인정선을 넘었습니다. "
                       "위원이 더 정할 것이 없습니다." + stg,
                       f'<a href="/assessments/{st.time.id}/review">③ 전문가 검토 보기</a>')
    else:
        decided = {r[0] for r in s.execute(text(
            """SELECT element_id FROM element_review
               WHERE assessment_id=:a AND granted_hours IS NOT NULL"""),
            {"a": st.time.id})}
        n_done = sum(1 for g in gaps if g.unit_code in decided)
        passed = [g for g in gaps if g.passes]
        note = (f" 그 가운데 <b>{len(passed)}개</b>가 인정선을 넘었습니다."
                if passed else "")
        act = (f'<a href="/assessments/{st.time.id}/review">③ 전문가 검토 보기</a>'
               if n_done >= len(gaps) else
               f'<a class="go" href="/assessments/{st.time.id}/review">③ 전문가 검토</a>')
        if n_done >= len(gaps):
            steps += _step("③", "전문가 검토", _st("완료", "ok"),
                           f"추가 인정이 필요한 <b>{len(gaps)}개</b> 단위를 모두 정하셨습니다."
                           + note + stg, act)
        else:
            ev_note = ("" if evidence_aid(s, sid) else
                       " <em>근거 분석을 먼저 돌리면 판단할 자료가 함께 보입니다.</em>")
            steps += _step("③", "전문가 검토",
                           _st(f"{n_done}/{len(gaps)}", "wn" if n_done else "ac"),
                           f"이수 기록만으로는 인정선에 못 미친 단위가 "
                           f"<b>{len(gaps)}개</b> 있습니다. 근거를 보고 추가 인정 시간을 "
                           f"정하십시오.{note}{ev_note}{stg}", act,
                           now=bool(done or st.evidence_ack or not st.can_analyze))

    # ── ④ 최종 판정 ────────────────────────────────────────────────
    # 면제 시간은 위원이 정한 값까지 반영한 결과다. 판정 기록 전에도 보여 준다 —
    # 「지금까지 얼마가 면제되나」가 ③ 을 계속할지 정하는 근거이기 때문이다.
    if is_b:
        # Track B 는 ③ 확인 계획에서 끝난다. 요소·항목에 시간이 없어 여기서 면제
        # 시간을 확정하지 않는다 — 인정·보류·불인정은 확인 계획이 보인다.
        credited, look = 0, ""
    elif st.time:
        credited = st.credited_hours + sum(g.credited for g in gaps)
        look = f'<a href="/assessments/{st.time.id}/exemption">④ 최종 판정 보기</a>'
    else:
        credited, look = 0, ""
    pct = credited / st.total_hours * 100 if st.total_hours else 0

    if is_b:
        pass                       # ③ 확인 계획이 마지막이다
    elif st.decision:
        d = st.decision
        h = (f" · 인정 {d['recognized_hours']}시간"
             if d.get("recognized_hours") is not None else "")
        steps += _step("④", "최종 판정", _st(str(d["decision"]), "ok"),
                       f"{e(d.get('decided_by') or '심사자')}{h}"
                       f"<em> {e(d.get('reason') or '')}</em>", look)
    elif st.time:
        steps += _step("④", "최종 판정", _st("기록 전", "wn" if credited else ""),
                       f"지금까지 <b>{credited}시간</b>이 면제됩니다 "
                       f"({pct:.0f}% · 남은 훈련 {st.total_hours - credited}시간). "
                       "확정하면 여기에 기록합니다.", look)
    else:
        steps += _step("④", "최종 판정", _st("아직"),
                       "검토를 마치면 전체·부분·불인정을 기록합니다.", off=True)

    # ── 제출 자료 ──────────────────────────────────────────────────
    by_type: dict[str, int] = {}
    for d in st.extra_docs:
        by_type[d["doc_type"]] = by_type.get(d["doc_type"], 0) + 1
    time_docs = st.n_documents - len(st.extra_docs)
    doc_line = " · ".join(f"{e(k)} {v}건" for k, v in sorted(by_type.items()))
    if time_docs:
        doc_line = f"<b>이수 증빙 {time_docs}건</b> · " + doc_line

    miss = ""
    if st.skipped:
        rows = "".join(
            f"<tr><td>{e(x['unit_name'])}</td><td class=n>{x['required_hours']}시간</td>"
            f"<td>{e(x['doc_type'])}</td><td>{e(x['reason'])}</td></tr>"
            for x in st.skipped)
        miss = f"""<details class="miss" open>
<summary>이수 기록을 냈으나 시간으로 갈음되지 않은 {len(st.skipped)}개 단위</summary>
<table><thead><tr><th>능력단위</th><th>요구</th><th>낸 자료</th><th>이유</th></tr></thead>
<tbody>{rows}</tbody></table></details>"""

    tot = st.total_hours
    body = f"""<div class="hdr"><h1>{e(st.case_number)}</h1>
 {_st(e(st.program_name))}{track_chip(st.track, full=True)}</div>
<p class="sub">총 필수 {tot}시간 · 접수 {st.received_at:%Y-%m-%d} · 제출 자료 {st.n_documents}건</p>
{_step_bar(st, sid, ev_aid is not None, ev_aid, has_plan)}

<div class="gauge">
 {_gauge(st, b_units if is_b else None)}
</div>

{steps}

<h2>제출 자료</h2>
<div class="docs">{doc_line or '아직 없습니다.'}
 <div class="sub" style="margin:6px 0 0">인용 가능한 조각 {st.n_fragments}개</div>
 {miss}
</div>

<details class="danger"><summary>이 접수 지우기</summary>
 <p>되돌릴 수 없습니다. 제출 자료·조각·판정·검토·최종 판정이 함께 사라지고,
  지원자가 낸 <b>원본 파일도 지워집니다</b>. 감사 산출물은 기본적으로 남겨 둡니다 —
  무엇을 보고 판정했는지가 마지막으로 남는 자리입니다.</p>
 <p class="sub">지우려면 심사번호 <b>{e(st.case_number)}</b> 를 그대로 적으십시오.</p>
 <div class="drow">
  <input id="rmc" placeholder="{e(st.case_number)}" autocomplete="off">
  <label><input type="checkbox" id="rmp"> 감사 산출물까지 지우기</label>
  <button id="rmgo" class="danger-go">지우기</button><span id="rmnote"></span>
 </div>
</details>"""
    scripts = ""
    if st.analyzing:
        # 3초마다 진행률만 긁어 막대를 움직이고, 끝나면 한 번 새로고침한다.
        # 통째로 새로고침하면 스크롤이 튄다.
        scripts = """<script>
const SID = %d;
async function tick() {
  try {
    const d = await (await fetch(`/submissions/${SID}/progress.json`)).json();
    if (d.done) { location.reload(); return; }
    const f = document.querySelector('.prog .f'), t = document.getElementById('prog-txt');
    if (f) f.style.width = d.pct + '%%';
    if (t) t.textContent = d.text;
  } catch (e) { /* 잠깐 끊긴 것뿐이면 다음 차례에 다시 본다 */ }
  setTimeout(tick, 3000);
}
setTimeout(tick, 3000);

</script>""" % st.submission_id
    # 삭제 단추는 접혀 있어도 늘 있다 — 진행률 스크립트에 끼워 두면 분석 중이
    # 아닌 화면에서 통째로 빠진다(실제로 그랬다).
    scripts += "<script>" + (DELETE_JS % st.submission_id) + "</script>"
    return page(f"{st.case_number} 심사 개요", body, css=CSS, here="/cases",
                scripts=scripts)
