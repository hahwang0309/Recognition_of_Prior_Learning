"""감사 화면 — 각 단계가 실제로 무엇을 했는지 눈으로 확인한다.

「잘 됐습니다」를 믿지 않아도 되게 만드는 것이 목적이다.
단계마다 그때 만들어진 파일을 그대로 열어 볼 수 있고,
파일 해시가 저장 당시와 같은지도 함께 표시한다.
"""
from __future__ import annotations

import html
import json
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from krpl_core.audit import STAGE_KO, audit_root

e = lambda x: html.escape(str(x) if x is not None else "")   # noqa: E731

CSS = """*{box-sizing:border-box}
:root{--s1:#fcfcfb;--s2:#f4f4f1;--s3:#eceae4;--bd:#e0e0da;--tp:#0b0b0b;--ts:#4a4a46;--tm:#84837c;
 --ok:#0ca30c;--wn:#fab219;--no:#d03b3b;--ac:#3f8ed0}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--s1:#1a1a19;--s2:#232322;
 --s3:#2b2b29;--bd:#3a3a38;--tp:#fff;--ts:#c3c2b7;--tm:#8f8e86}}
body{margin:0;background:var(--s1);color:var(--tp);
 font:14px/1.65 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",Pretendard,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:28px 20px 64px}
h1{font-size:23px;margin:0 0 4px}.sub{color:var(--tm);font-size:12.5px;margin:0 0 20px}
a{color:var(--ac);text-decoration:none}a:hover{text-decoration:underline}
.nav{font-size:12.5px;margin-bottom:16px}
.note{background:var(--s2);border:1px solid var(--bd);border-left:3px solid var(--ac);
 border-radius:8px;padding:11px 15px;margin-bottom:18px;font-size:12.8px;color:var(--ts)}
table{width:100%;border-collapse:collapse;font-size:12.5px;margin-bottom:8px}
th,td{padding:7px 9px;border-bottom:1px solid var(--bd);text-align:left;vertical-align:top}
th{color:var(--tm);font-weight:600;font-size:11.5px;white-space:nowrap}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr:hover td{background:var(--s2)}
.st{display:inline-block;font-size:11px;padding:1px 7px;border-radius:10px;background:var(--s3);color:var(--ts)}
.st.ok{background:var(--ok);color:#fff}.st.wn{background:var(--wn);color:#3a2a00}
.st.no{background:var(--no);color:#fff}
.stage{background:var(--s2);border:1px solid var(--bd);border-radius:10px;
 padding:14px 17px;margin-bottom:11px}
.stage h2{font-size:15px;margin:0 0 3px;display:flex;gap:9px;align-items:baseline;flex-wrap:wrap}
.stage h2 small{font-weight:400;font-size:12px;color:var(--tm)}
.facts{font-size:12.8px;color:var(--ts);margin:5px 0 9px}
.facts b{color:var(--tp);font-variant-numeric:tabular-nums}
.arts{display:grid;gap:5px}
details.run{border:1px solid var(--bd);border-radius:11px;margin-bottom:14px;
 background:var(--s1);overflow:hidden}
details.run>summary{cursor:pointer;padding:11px 15px;background:var(--s2);
 display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;font-size:13.5px}
details.run>summary::-webkit-details-marker{display:none}
details.run>summary:before{content:'▸';color:var(--tm);margin-right:2px}
details.run[open]>summary:before{content:'▾'}
details.run .rtag{font-size:11px;padding:1.5px 8px;border-radius:10px;
 background:var(--s3);color:var(--ts)}
details.run .rn{margin-left:auto;font-size:11.5px;color:var(--tm)}
details.run>.stage{margin:0;padding:12px 15px;border-top:1px solid var(--bd)}
.note.warn2{border-left:3px solid var(--wn)}
.art{display:grid;grid-template-columns:1fr auto auto auto;gap:11px;align-items:center;
 background:var(--s1);border:1px solid var(--bd);border-radius:7px;padding:7px 11px;font-size:12.3px}
.art .nm b{font-size:12.8px}
.art .nm span{display:block;color:var(--tm);font-size:11.3px}
.art .n{color:var(--tm);font-variant-numeric:tabular-nums;font-size:11.3px;white-space:nowrap}
.hash{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:10.5px;color:var(--tm)}
pre{background:var(--s2);border:1px solid var(--bd);border-radius:9px;padding:14px;
 overflow-x:auto;font-size:12px;line-height:1.55;white-space:pre-wrap;word-break:break-word}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:9px;margin-bottom:18px}
.kpi{background:var(--s2);border:1px solid var(--bd);border-radius:9px;padding:10px 13px}
.kpi span{display:block;font-size:11.5px;color:var(--tm)}
.kpi b{font-size:21px;font-variant-numeric:tabular-nums}
.kpi b i{font-size:12px;font-style:normal;color:var(--ts);margin-left:2px}
.kpi em{display:block;font-style:normal;font-size:11px;color:var(--tm);margin-top:2px}
footer{color:var(--tm);font-size:11.5px;border-top:1px solid var(--bd);padding-top:14px;margin-top:26px}
@media(max-width:680px){.art{grid-template-columns:1fr;gap:3px}}"""


def _head(title: str, here: str = "/audit") -> str:
    """공통 껍데기를 쓴다. 예전에는 자체 <head> 라서 머리말 차림표가 없었고,
    차림표에 실려 있는 「감사」·「운영 통계」를 누르는 순간 차림표가 사라졌다."""
    from services.report.layout import page_open
    return page_open(title, css=CSS, here=here)


def _kb(n: int) -> str:
    return f"{n / 1024:.0f}KB" if n >= 1024 else f"{n}B"


# ═══════════════════════ 목록 ═══════════════════════
def render_audit_list(s: Session) -> str:
    rows = list(s.execute(text("""
        SELECT sub.id, sub.case_number, sub.track, sub.target_program_id, sub.status,
               sub.received_at,
               (SELECT count(*) FROM document d WHERE d.submission_id=sub.id) AS n_doc,
               (SELECT count(*) FROM fragment f WHERE f.submission_id=sub.id) AS n_frag,
               (SELECT count(*) FROM artifact t WHERE t.submission_id=sub.id) AS n_art,
               a.id AS aid, a.status AS astatus, a.attempts, a.cost_usd, a.model,
               (SELECT count(*) FROM assessment_element x WHERE x.assessment_id=a.id) AS n_el,
               (SELECT count(*) FROM element_review v WHERE v.assessment_id=a.id) AS n_rev,
               fd.decision, fd.recognized_hours, fd.total_hours
        FROM submission sub
        LEFT JOIN LATERAL (SELECT * FROM assessment z WHERE z.submission_id=sub.id
                           ORDER BY z.id DESC LIMIT 1) a ON true
        LEFT JOIN final_decision fd ON fd.submission_id = sub.id
        ORDER BY sub.case_number"""), {}).mappings())

    body = ""
    for r in rows:
        val = s.execute(text("""SELECT passed, error_count FROM validation_log
                                WHERE assessment_id=:i ORDER BY attempt DESC LIMIT 1"""),
                        {"i": r["aid"]}).mappings().first() if r["aid"] else None
        vs = ('<span class="st ok">통과</span>' if val and val["passed"]
              else f'<span class="st no">오류 {val["error_count"]}</span>' if val
              else '<span class="st">–</span>')
        dcls = {"전체인정": "ok", "부분인정": "wn", "불인정": "no"}.get(r["decision"], "")
        dec = (f'<span class="st {dcls}">{e(r["decision"])} {r["recognized_hours"]}/'
               f'{r["total_hours"]}h</span>' if r["decision"] else '<span class="st">–</span>')
        cost = f'${float(r["cost_usd"]):.3f}' if r["cost_usd"] else "–"
        body += f"""<tr>
 <td><a href="/audit/{e(r['case_number'])}"><b>{e(r['case_number'])}</b></a>
   <span class="st">{e(r['track'])}</span></td>
 <td>{e(r['target_program_id'])}</td>
 <td><span class="st">{e(r['status'])}</span></td>
 <td class="n">{r['n_doc']} / {r['n_frag']}</td>
 <td class="n">{r['n_el'] or '–'}</td>
 <td class="n">{r['attempts'] or '–'}</td>
 <td>{vs}</td>
 <td class="n">{r['n_rev'] or 0}/{r['n_el'] or 0}</td>
 <td>{dec}</td>
 <td class="n">{cost}</td>
 <td class="n"><a href="/audit/{e(r['case_number'])}">{r['n_art']}개</a></td></tr>"""

    tot = s.execute(text("SELECT count(*), coalesce(sum(n_bytes),0) FROM artifact")).one()
    return _head("감사 — 접수 건 목록") + f"""
<h1>감사 — 접수 건 목록</h1>
<p class="sub">단계마다 남은 산출물을 열어 결과가 어떻게 나왔는지 직접 확인할 수 있습니다 ·
 <a href="/stats">운영 통계</a></p>
<div class="note">
 각 심사번호를 누르면 <b>① 문서 수집 → ② AI 입력 조립 → ③ AI 분석 → ④ 기계 검증
 → ⑤ 전문가 검토 → ⑥ 최종 판정</b> 순서로, 그 단계에서 실제로 만들어진 파일을 볼 수 있습니다.
 파일은 <code>{e(audit_root())}</code> 아래에 그대로 있으므로 앱을 거치지 않고 열어도 됩니다.
</div>
<table><thead><tr>
 <th>심사번호</th><th>목표 종목</th><th>상태</th><th>문서/조각</th><th>요소</th>
 <th>시도</th><th>기계검증</th><th>검토</th><th>최종판정</th><th>비용</th><th>산출물</th>
</tr></thead><tbody>{body}</tbody></table>
<footer>산출물 {tot[0]}개 · {_kb(tot[1])} · 생성 {datetime.now():%Y-%m-%d %H:%M}</footer>
</div></body></html>"""


# ═══════════════════════ 한 건 ═══════════════════════
def _facts(s: Session, sub, aid: int | None) -> dict[str, str]:
    """단계마다 「무슨 일이 있었는지」 한 줄 요약."""
    f: dict[str, str] = {}
    d = s.execute(text("""SELECT count(*) n, count(DISTINCT parsed_format) fm
                          FROM document WHERE submission_id=:i"""), {"i": sub["id"]}).one()
    fr = s.execute(text("""SELECT count(*), count(DISTINCT stype) FROM fragment
                           WHERE submission_id=:i"""), {"i": sub["id"]}).one()
    mask = s.execute(text("""SELECT note FROM artifact WHERE submission_id=:i
                             AND name='마스킹기록'"""), {"i": sub["id"]}).scalar()
    f["ingest"] = (f"문서 <b>{d.n}</b>건을 파싱해 조각 <b>{fr[0]}</b>개로 나눴습니다"
                   f" (서술형식 {d.fm}종 · 조각유형 {fr[1]}종)."
                   + (f" 개인정보 {e(mask.split(' — ')[0])}." if mask else ""))
    if aid is None:
        return f

    a = s.execute(text("""SELECT rubric_version, prompt_version, model, effort, attempts,
                          input_hash, input_tokens, output_tokens, cost_usd, status,
                          overall_note FROM assessment WHERE id=:i"""),
                  {"i": aid}).mappings().one()
    note = json.loads(a["overall_note"]) if a["overall_note"] else {}
    pk = note.get("package") or {}
    f["package"] = (f"능력단위 <b>{pk.get('n_units', '?')}</b>개 · 요소 <b>{pk.get('n_elements', '?')}</b>개 ·"
                    f" KSA <b>{pk.get('n_ksa', '?')}</b>개와 조각 <b>{pk.get('n_fragments', '?')}</b>개를"
                    f" 한 덩어리로 묶어 보냈습니다."
                    # 입력 지문은 판정이 끝까지 갔을 때만 남는다. 없다고 화면이
                    # 죽으면 정작 무엇이 잘못됐는지 볼 수 없다.
                    + (f" 입력 지문 {e(a['input_hash'][:16])}…" if a["input_hash"] else ""))
    f["llm"] = (f"{e(a['model'])} · 지침 {e(a['prompt_version'])} · 기준 v{e(a['rubric_version'])}"
                f" · <b>{a['attempts']}</b>회 시도"
                + (f" · 토큰 입력 {a['input_tokens']:,} 출력 {a['output_tokens']:,}"
                   if a["output_tokens"] else "")
                + (f" · ${float(a['cost_usd']):.4f}" if a["cost_usd"] else ""))

    v = note.get("validation") or {}
    codes = ", ".join(f"{k} {n}" for k, n in (v.get("by_code") or {}).items()) or "지적 없음"
    f["validate"] = (f"근거 <b>{v.get('n_evidence', '?')}</b>건을 원문과 대조했습니다 · "
                     + ("<b>통과</b>" if v.get("passed") else f"<b>오류 {v.get('n_errors')}건</b>")
                     + f" · 경고 {v.get('n_warnings', 0)}건 · {e(codes)}")

    rv = s.execute(text("""SELECT count(*) n,
                           count(*) FILTER (WHERE decision='인정') ok,
                           count(*) FILTER (WHERE decision='조건부인정') cond,
                           count(*) FILTER (WHERE decision='불인정') no,
                           count(*) FILTER (WHERE (decision='인정')<>(ai_recommendation='R0')) diff
                           FROM element_review WHERE assessment_id=:i"""), {"i": aid}).one()
    f["review"] = (f"요소 <b>{rv.n}</b>개에 의견이 기록됐습니다 · 인정 {rv.ok} · 조건부 {rv.cond}"
                   f" · 불인정 {rv.no} · AI 권고와 다른 판단 <b>{rv.diff}</b>건") if rv.n else \
                  "아직 검토가 기록되지 않았습니다."

    fd = s.execute(text("""SELECT decision, recognized_hours, total_hours, decided_by,
                           decided_on FROM final_decision WHERE submission_id=:i"""),
                   {"i": sub["id"]}).mappings().first()
    f["decide"] = (f"<b>{e(fd['decision'])}</b> · 감면 <b>{fd['recognized_hours']}</b>/"
                   f"{fd['total_hours']}시간 · {e(fd['decided_by'] or '기재 없음')}"
                   f" · {fd['decided_on']}") if fd else "아직 최종 판정이 기록되지 않았습니다."
    return f


def render_audit_case(s: Session, case_number: str) -> str:
    sub = s.execute(text("""
        SELECT sub.id, sub.case_number, sub.track, sub.target_program_id, sub.status,
               sub.received_at, p.official_name
        FROM submission sub LEFT JOIN catalog_wsd_program p
             ON p.program_id = sub.target_program_id
        WHERE sub.case_number = :c"""), {"c": case_number}).mappings().one()
    aid = s.execute(text("""SELECT id FROM assessment WHERE submission_id=:i
                            ORDER BY id DESC LIMIT 1"""), {"i": sub["id"]}).scalar()
    arts = list(s.execute(text("""
        SELECT id, assessment_id, stage, seq, name, path, sha256, n_bytes, note, created_at
        FROM artifact WHERE submission_id=:i ORDER BY stage, seq, name"""),
        {"i": sub["id"]}).mappings())

    # 판정을 다시 돌리면 산출물이 한 벌 더 쌓인다. 실행을 갈라 보여 주지 않으면
    # 어느 파일이 어느 실행의 것인지 알 수 없다 — 실측으로 같은 이름이 세 번씩
    # 나와 「호출실패」가 한 번인지 세 번인지 구분되지 않았다.
    runs = {r["id"]: dict(r) for r in s.execute(text("""
        SELECT id, kind, status, attempts, model, started_at, finished_at
        FROM assessment WHERE submission_id=:i ORDER BY id DESC"""),
        {"i": sub["id"]}).mappings()}

    by_run: dict[int | None, dict[str, list]] = {}
    for a in arts:
        by_run.setdefault(a["assessment_id"], {}).setdefault(a["stage"], []).append(a)
    facts = _facts(s, sub, aid)

    def _rows(items) -> str:
        return "".join(f"""<div class="art">
 <div class="nm"><b>{e(a['name'])}</b><span>{e(a['note'] or '')}</span></div>
 <div class="n">{_kb(a['n_bytes'])}</div>
 <div class="n hash">{e(a['sha256'][:10])}</div>
 <div><a href="/audit/artifact/{a['id']}">열기</a></div></div>""" for a in items)

    def _stages(stages: dict[str, list], keys, with_facts: bool = True) -> str:
        """`keys` 에 든 단계만 그린다.

        모든 단계를 늘 그렸더니 실행별로 나눈 뒤 ②③④ 가 위에도 한 번,
        실행 상자 안에도 한 번 — 빈 껍데기가 겹쳐 보였다.
        """
        out = ""
        for st, ko in STAGE_KO.items():
            if st not in keys:
                continue
            items = stages.get(st, [])
            empty = "" if items else '<div class="facts" style="color:var(--tm)">남은 파일 없음</div>'
            out += f"""<div class="stage">
 <h2>{e(ko)}<small>{len(items)}개 파일</small></h2>
 {f'<div class="facts">{facts.get(st, "아직 진행되지 않았습니다.")}</div>' if with_facts else ''}
 <div class="arts">{_rows(items)}</div>{empty}</div>"""
        return out

    # 수집(assessment_id 없음)은 접수 건에 딸린 것이라 실행과 무관하다.
    run_keys = {st for rid, v in by_run.items() if rid is not None for st in v}
    sub_keys = set(by_run.get(None, {}))
    secs = _stages(by_run.get(None, {}), sub_keys)

    order = sorted((k for k in by_run if k is not None), reverse=True)
    for n, rid in enumerate(order):
        r = runs.get(rid) or {}
        n_files = sum(len(v) for v in by_run[rid].values())
        head = (f"판정 {rid} · {e(r.get('status') or '?')}"
                f" · 시도 {r.get('attempts') or 0}회"
                + (f" · {r['started_at']:%m-%d %H:%M}" if r.get("started_at") else ""))
        # 오래된 것일수록 큰 번호가 붙던 것을 바로잡는다 — 바로 앞 실행이 1이다.
        tag = "최신" if n == 0 else f"{n}번 전"
        secs += f"""<details class="run" {"open" if n == 0 else ""}>
 <summary><b>{head}</b><span class="rtag">{tag}</span>
  <span class="rn">{n_files}개 파일</span></summary>
 {_stages(by_run[rid], set(by_run[rid]), with_facts=(n == 0))}</details>"""

    # 파일이 없는 단계(검토·판정)는 어느 실행에도 없다. 설명만 한 번 붙인다.
    rest = set(STAGE_KO) - run_keys - sub_keys
    if rest:
        secs += _stages({}, rest)

    if len(order) > 1:
        secs = (f'<div class="note warn2">이 건은 <b>{len(order)}번</b> 판정했습니다. '
                f'아래는 실행별로 나눠 두었고, 맨 위가 가장 최근 것입니다. '
                f'화면·보고서는 <b>최신 판정({order[0]})</b>을 씁니다.</div>' + secs)

    val = list(s.execute(text("""SELECT attempt, passed, error_count, errors
                                 FROM validation_log WHERE assessment_id=:i
                                 ORDER BY attempt"""), {"i": aid}).mappings()) if aid else []
    vrows = "".join(f"""<tr><td class="n">{v['attempt']}차</td>
 <td>{'<span class="st ok">통과</span>' if v['passed'] else f'<span class="st no">오류 {v["error_count"]}건</span>'}</td>
 <td>{e(', '.join(f'{k} {n}' for k, n in ((v['errors'] or {}).get('by_code') or {}).items()) or '–')}</td>
 </tr>""" for v in val)
    vtab = (f'<h2 style="font-size:15px;margin:24px 0 8px">기계 검증 이력</h2>'
            f'<table><thead><tr><th>시도</th><th>결과</th><th>지적 내용</th></tr></thead>'
            f'<tbody>{vrows}</tbody></table>') if val else ""

    diff = list(s.execute(text("""
        SELECT v.element_id, v.decision, v.ai_recommendation, v.note, v.reviewer
        FROM element_review v WHERE v.assessment_id=:i
          AND (v.decision='인정') <> (v.ai_recommendation='R0')
        ORDER BY v.element_id"""), {"i": aid}).mappings()) if aid else []
    drows = "".join(f"""<tr><td>{e(d['element_id'])}</td><td>{e(d['ai_recommendation'])}</td>
 <td>{e(d['decision'])}</td><td>{e(d['note'] or '')}</td><td>{e(d['reviewer'] or '')}</td></tr>"""
                    for d in diff)
    dtab = (f'<h2 style="font-size:15px;margin:24px 0 8px">AI 권고와 다르게 판단한 요소'
            f' <small style="font-weight:400;color:var(--tm)">{len(diff)}건</small></h2>'
            f'<table><thead><tr><th>요소</th><th>AI 권고</th><th>사람 의견</th>'
            f'<th>메모</th><th>검토자</th></tr></thead><tbody>{drows}</tbody></table>') if diff else ""

    log = list(s.execute(text("""SELECT action, actor, created_at, detail FROM audit_log
                                 WHERE (entity='submission' AND entity_id=:s)
                                    OR (entity='assessment' AND entity_id=:a)
                                    OR (entity='final_decision' AND entity_id=:s)
                                 ORDER BY created_at DESC LIMIT 30"""),
        {"s": str(sub["id"]), "a": str(aid or -1)}).mappings())
    lrows = "".join(f"""<tr><td class="n">{l['created_at']:%m-%d %H:%M:%S}</td>
 <td>{e(l['action'])}</td><td>{e(l['actor'])}</td></tr>""" for l in log)

    review_link = (f' · <a href="/assessments/{aid}/review">검토 화면</a>'
                   f' · <a href="/assessments/{aid}">판정 결과(JSON)</a>') if aid else ""
    return _head(f"감사 — {case_number}") + f"""
<div class="nav"><a href="/audit">← 접수 건 목록</a>{review_link}</div>
<h1>{e(case_number)}</h1>
<p class="sub">{e(sub['official_name'] or sub['target_program_id'])} · Track {e(sub['track'])} ·
 접수 {sub['received_at']:%Y-%m-%d %H:%M} · 현재 상태 {e(sub['status'])}
 {f'· 판정 {aid}' if aid else ''}</p>
<div class="note">
 아래 파일은 각 단계가 <b>실제로 만들어 낸 것</b>입니다. 나중에 다시 쓴 설명이 아닙니다.
 해시(앞 10자리)는 저장 당시 내용의 지문이며, 파일을 열 때 다시 계산해 대조합니다.
 원본 경로: <code>{e(audit_root() / case_number)}</code>
</div>
{secs}{vtab}{dtab}
<h2 style="font-size:15px;margin:24px 0 8px">처리 기록</h2>
<table><thead><tr><th>시각</th><th>동작</th><th>주체</th></tr></thead><tbody>{lrows}</tbody></table>
<footer>생성 {datetime.now():%Y-%m-%d %H:%M}</footer></div></body></html>"""


def render_artifact(meta: dict, body: str | None) -> str:
    ok = meta.get("integrity") == "일치"
    badge = ('<span class="st ok">해시 일치</span>' if ok
             else f'<span class="st no">{e(meta.get("integrity"))}</span>')
    if body is None:
        content = "<pre>파일을 찾을 수 없습니다.</pre>"
    else:
        shown = body if len(body) <= 400_000 else body[:400_000] + "\n\n… (이하 생략)"
        content = f"<pre>{e(shown)}</pre>"
    return _head(f"산출물 — {meta['name']}") + f"""
<div class="nav"><a href="/audit/{e(meta['case_number'])}">← {e(meta['case_number'])} 감사</a></div>
<h1>{e(meta['name'])}</h1>
<p class="sub">{e(STAGE_KO.get(meta['stage'], meta['stage']))} ·
 {_kb(meta['n_bytes'])} · 저장 {meta['created_at']:%Y-%m-%d %H:%M:%S} · {badge}</p>
<div class="note">{e(meta['note'] or '')}<br>
 <span class="hash">경로 {e(meta['path'])}</span><br>
 <span class="hash">sha256 {e(meta['sha256'])}</span></div>
{content}
</div></body></html>"""


# ═══════════════════════ 통계 ═══════════════════════
def render_stats(s: Session) -> str:
    q = lambda sql, **p: s.execute(text(sql), p).mappings().first()   # noqa: E731
    g = q("""SELECT count(*) n,
             count(*) FILTER (WHERE status='decided') decided,
             count(*) FILTER (WHERE status='needs_review') needs,
             count(*) FILTER (WHERE status='failed') failed FROM submission""")
    a = q("""SELECT count(*) n, avg(attempts)::numeric(4,2) att,
             sum(cost_usd) cost, avg(cost_usd)::numeric(10,4) avgcost,
             avg(extract(epoch from (finished_at-started_at)))::numeric(8,1) secs,
             sum(input_tokens) tin, sum(output_tokens) tout, sum(cache_read_tokens) tcache
             FROM assessment WHERE status IN ('done','manual_review')""")
    v = q("""SELECT count(*) n, count(*) FILTER (WHERE passed) ok,
             count(DISTINCT assessment_id) FILTER (WHERE attempt=1 AND passed) first_pass,
             count(DISTINCT assessment_id) assessments FROM validation_log""")
    r = q("""SELECT count(*) n,
             count(*) FILTER (WHERE (decision='인정')=(ai_recommendation='R0')) agree
             FROM element_review""")
    codes = list(s.execute(text("""
        SELECT k AS code, sum((v)::int) AS n FROM validation_log,
             LATERAL jsonb_each_text(coalesce(errors->'by_code','{}'::jsonb)) AS t(k, v)
        WHERE NOT passed GROUP BY k ORDER BY n DESC LIMIT 12""")).mappings())
    recs = list(s.execute(text("""
        SELECT recommendation, count(*) n FROM assessment_element
        GROUP BY 1 ORDER BY 1""")).mappings())
    jobs = list(s.execute(text("""
        SELECT kind, status, count(*) n FROM job GROUP BY 1,2 ORDER BY 1,2""")).mappings())

    first = (v["first_pass"] / v["assessments"] * 100) if v["assessments"] else 0
    agree = (r["agree"] / r["n"] * 100) if r["n"] else 0
    crow = "".join(f'<tr><td>{e(c["code"])}</td><td class="n">{c["n"]}</td></tr>' for c in codes)
    rrow = "".join(f'<tr><td>{e(x["recommendation"])}</td><td class="n">{x["n"]}</td></tr>'
                   for x in recs)
    jrow = "".join(f'<tr><td>{e(j["kind"])}</td><td>{e(j["status"])}</td>'
                   f'<td class="n">{j["n"]}</td></tr>' for j in jobs)
    cost = float(a["cost"] or 0)
    return _head("운영 통계", "/stats") + f"""
<div class="nav"><a href="/audit">← 감사 목록</a></div>
<h1>운영 통계</h1><p class="sub">지금까지 처리된 것의 집계입니다.</p>
<div class="kpis">
 <div class="kpi"><span>접수</span><b>{g['n']}<i>건</i></b>
   <em>최종판정 {g['decided']} · 확인필요 {g['needs']} · 실패 {g['failed']}</em></div>
 <div class="kpi"><span>1차 검증 통과율</span><b>{first:.0f}<i>%</i></b>
   <em>재요청 없이 통과 {v['first_pass']}/{v['assessments']}</em></div>
 <div class="kpi"><span>평균 시도</span><b>{a['att'] or 0}<i>회</i></b>
   <em>검증 기록 {v['n']}건 중 통과 {v['ok']}</em></div>
 <div class="kpi"><span>AI 권고 · 사람 판단 일치</span><b>{agree:.0f}<i>%</i></b>
   <em>{r['agree']}/{r['n']} 요소</em></div>
 <div class="kpi"><span>누적 비용</span><b>${cost:.2f}</b>
   <em>1건 평균 ${float(a['avgcost'] or 0):.3f}</em></div>
 <div class="kpi"><span>1건 평균 소요</span><b>{a['secs'] or 0}<i>초</i></b>
   <em>판정 {a['n']}건 기준</em></div>
</div>
<div class="note">
 토큰 누적 — 입력 {a['tin'] or 0:,} · 출력 {a['tout'] or 0:,} · 캐시 재사용 {a['tcache'] or 0:,}.
 「AI 권고·사람 판단 일치」는 <b>AI 가 R0(기이수 인정검토)로 본 것</b>과
 <b>사람이 인정한 것</b>이 같은 비율입니다. 낮다고 나쁜 것이 아니라,
 사람이 실제로 다르게 판단하고 있다는 뜻입니다.
</div>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px">
<div><h2 style="font-size:15px;margin:0 0 6px">검증에 걸린 항목</h2>
 <table><thead><tr><th>지적</th><th>건수</th></tr></thead>
 <tbody>{crow or '<tr><td colspan=2>없음</td></tr>'}</tbody></table></div>
<div><h2 style="font-size:15px;margin:0 0 6px">권고 분포</h2>
 <table><thead><tr><th>권고</th><th>요소</th></tr></thead><tbody>{rrow}</tbody></table></div>
<div><h2 style="font-size:15px;margin:0 0 6px">작업 큐</h2>
 <table><thead><tr><th>종류</th><th>상태</th><th>건수</th></tr></thead>
 <tbody>{jrow or '<tr><td colspan=3>없음</td></tr>'}</tbody></table></div>
</div>
<footer>생성 {datetime.now():%Y-%m-%d %H:%M}</footer></div></body></html>"""
