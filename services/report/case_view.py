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

from sqlalchemy.orm import Session

from services.assess.case_state import CaseState, case_state
from services.report.layout import e, page

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
.bar2 .maybe{background:var(--ac)}
.leg{display:flex;gap:16px;font-size:11.5px;color:var(--tm);margin-top:7px;flex-wrap:wrap}
.leg i{display:inline-block;width:11px;height:11px;border-radius:3px;
 margin-right:5px;vertical-align:-1px;font-style:normal}
.leg .yes{background:var(--ok)}.leg .maybe{background:var(--ac)}.leg .no{background:var(--s3)}

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
.miss table{margin-top:8px}
"""


def _bar(st: CaseState) -> str:
    tot = st.total_hours or 1
    yes = st.credited_hours / tot * 100
    maybe = 0.0
    if st.evidence_done:
        # 근거 분석이 「인정 검토」로 본 시간까지 파랗게 — 아직 확정은 아니다.
        maybe = min(100 - yes, st.open_hours / tot * 100)
    return (f'<div class="bar2"><div class="yes" style="width:{yes:.2f}%"></div>'
            f'<div class="maybe" style="width:{maybe:.2f}%"></div></div>')


def _step(no: str, title: str, badge: str, why: str, act: str = "",
          *, now: bool = False, off: bool = False, extra: str = "") -> str:
    cls = " now" if now else (" off" if off else "")
    return f"""<div class="step{cls}">
  <div class="no">{no}</div>
  <div class="ttl">{e(title)}{badge}</div>
  <div class="act">{act}</div>
  <div class="why">{why}</div>{extra}
</div>"""


def _st(text: str, kind: str = "") -> str:
    return f'<span class="st {kind}">{e(text)}</span>'


def render_case(s: Session, submission_id: int) -> str | None:
    st = case_state(s, submission_id)
    if st is None:
        return None
    sid = st.submission_id
    steps = ""

    # ── ① 시간 대조 ────────────────────────────────────────────────
    if st.time and st.time.done:
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
        steps += _step("①", "시간 대조", _st("완료", "ok"), why,
                       f'<a href="/submissions/{sid}/report/time">보고서 보기</a>')
    elif st.n_documents == 0:
        steps += _step("①", "시간 대조", _st("대기"),
                       "제출 자료가 없습니다. 서류를 올리면 자동으로 대조합니다.",
                       f'<a class="go" href="/submissions/{sid}/upload">서류 올리기</a>',
                       now=True)
    else:
        steps += _step("①", "시간 대조", _st("안 돌았음", "no"),
                       "자동 실행이 실패했습니다. 서류를 다시 올리면 재시도합니다.",
                       f'<a href="/submissions/{sid}/upload">서류 다시 올리기</a>', now=True)

    # ── ② 근거 분석 ────────────────────────────────────────────────
    # 「도는 중」과 「이미 나온 보고서」는 따로 본다. 재실행 한 번에 완성된
    # 보고서가 화면에서 사라지면 안 된다.
    ev, done = st.evidence, st.evidence_done
    report_link = (f'<a href="/submissions/{sid}/report/evidence">보고서 보기</a>'
                   if done else "")
    if st.analyzing:
        pr = (ev.progress if ev else None) or {}
        n_done, n_all = pr.get("done", 0), pr.get("total", 0) or 1
        bar = (f'<div class="prog"><div class="t"><div class="f" '
               f'style="width:{n_done / n_all * 100:.0f}%"></div></div>'
               f'<small>{n_done}/{n_all} 능력단위 · '
               f'{e(pr.get("phase") or "분석 중")}</small></div>')
        why = "제출 자료를 능력단위별로 읽고 있습니다. 6~30분 걸립니다."
        if done:
            why += " <em>지난 보고서는 그대로 보실 수 있습니다.</em>"
        steps += _step("②", "근거 분석", _st("진행 중", "ac"), why,
                       report_link or '<a href="">새로 고침</a>', now=True, extra=bar)
    elif done:
        cost = f" · 비용 ${done.cost:.2f}" if done.cost else ""
        # 두 Run 은 서로 다른 조회에서 왔으므로 같은 판정이라도 객체가 다르다.
        # `is not` 로 비교했다가 실패한 적이 없는데도 실패했다고 적었다. id 로 본다.
        warn = ('<em> 다시 돌린 분석이 끝나지 못했습니다 — 아래는 지난 결과입니다.</em>'
                if ev and ev.id != done.id and not ev.running else "")
        steps += _step("②", "근거 분석", _st("완료", "ok"),
                       f"추가 자료 {len(st.extra_docs)}종에서 "
                       f"<b>{done.n_elements}개 항목</b>을 판단했습니다."
                       f"<em> 호출 {done.attempts}회{cost}</em>{warn}",
                       report_link)
    elif st.can_analyze:
        kinds = "·".join(sorted({d["doc_type"] for d in st.extra_docs})[:3])
        failed = ('<em> 지난 분석이 끝나지 못했습니다. 다시 시작하실 수 있습니다.</em>'
                  if ev else "")
        steps += _step("②", "근거 분석", _st("할 수 있음", "wn"),
                       f"경력·수행을 보여 주는 자료가 <b>{len(st.extra_docs)}건</b> 있습니다"
                       f"({e(kinds)} 등). 시간 대조로 덮이지 않은 "
                       f"<b>{st.open_hours}시간</b>을 이 자료로 따져 볼 수 있습니다.{failed}",
                       f'<form method="post" action="/submissions/{sid}/analyze">'
                       f'<button class="go" type="submit">근거 분석 시작</button></form>',
                       now=True)
    else:
        steps += _step("②", "근거 분석", _st("해당 없음"),
                       "경력·수행을 보여 주는 자료가 없어 분석할 것이 없습니다.",
                       off=True)

    # ── ③ 전문가 검토 ──────────────────────────────────────────────
    if done:
        left = done.n_elements - st.n_reviewed
        if st.review_done:
            steps += _step("③", "전문가 검토", _st("완료", "ok"),
                           f"{done.n_elements}개 항목을 모두 판단하셨습니다.",
                           f'<a href="/assessments/{done.id}/review">다시 보기</a>')
        else:
            steps += _step("③", "전문가 검토",
                           _st(f"{st.n_reviewed}/{done.n_elements}", "wn"),
                           f"보고서를 읽으신 뒤 <b>{left}개 항목</b>에 가·부를 정해 주십시오.",
                           f'<a class="go" href="/assessments/{done.id}/review">검토하기</a>',
                           now=True)
    else:
        steps += _step("③", "전문가 검토", _st("대기"),
                       "근거 분석이 끝나면 판단할 항목이 나옵니다.", off=True)

    # ── ④ 최종 판정 ────────────────────────────────────────────────
    if st.decision:
        d = st.decision
        h = (f" · 인정 {d['recognized_hours']}시간"
             if d.get("recognized_hours") is not None else "")
        steps += _step("④", "최종 판정", _st(str(d["decision"]), "ok"),
                       f"{e(d.get('decided_by') or '심사자')}{h}"
                       f"<em> {e(d.get('reason') or '')}</em>",
                       f'<a href="/audit/{e(st.case_number)}">기록 보기</a>')
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
 {_st(e(st.program_name))}</div>
<p class="sub">총 필수 {tot}시간 · 접수 {st.received_at:%Y-%m-%d} · 제출 자료 {st.n_documents}건</p>

<div class="gauge">
 <div class="line">기록으로 확인된 시간 <b>{st.credited_hours}</b>시간
  <span class="dim">/ {tot}시간 ({st.credited_ratio:.0%})</span>
  &nbsp;·&nbsp; 아직 확인되지 않은 시간 <b>{st.open_hours}</b>시간</div>
 {_bar(st)}
 <div class="leg"><span><i class="yes"></i>이수 기록으로 확인</span>
  <span><i class="maybe"></i>제출 자료로 따져 볼 수 있음</span>
  <span><i class="no"></i>훈련으로 채워야 함</span></div>
</div>

{steps}

<h2>제출 자료</h2>
<div class="docs">{doc_line or '아직 없습니다.'}
 <div class="sub" style="margin:6px 0 0">인용 가능한 조각 {st.n_fragments}개 ·
  <a href="/audit/{e(st.case_number)}">감사 기록 보기</a></div>
 {miss}
</div>"""
    return page(f"{st.case_number} 심사 개요", body, css=CSS, here="/cases")
