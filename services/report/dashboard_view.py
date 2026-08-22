"""접수 현황 — 담당자가 아침에 여는 화면.

「지금 무엇을 해야 하는가」가 한눈에 보여야 한다.
그래서 단계별로 묶고, 각 건마다 **다음 할 일 버튼 하나**만 놓는다.
"""
from __future__ import annotations

from datetime import datetime

from services.report.layout import e, page

# 상태 → (묶음 이름, 배지). 「다음 할 일」은 여기서 정하지 않는다 —
# case_state.next_step 이 정한다. 목록과 개요가 다른 말을 하면 안 된다.
FLOW = {
    "received":    ("서류 대기",   ""),
    "ingested":    ("분석 대기",   "wn"),
    "queued":      ("분석 대기",   "ac"),
    "assessing":   ("분석 중",     "ac"),
    "assessed":    ("검토 대기",   "wn"),
    "needs_review": ("확인 필요",  "no"),
    "decided":     ("완료",       "ok"),
    "failed":      ("실패",       "no"),
}
ORDER = ["received", "ingested", "queued", "assessing", "assessed",
         "needs_review", "failed", "decided"]

CSS = """
.grp{margin-bottom:26px}
.grp h2{display:flex;align-items:baseline;gap:9px;margin:0 0 8px}
.grp h2 small{font-weight:400;font-size:12px;color:var(--tm)}
/* 표 칸 안에서 flex 를 쓰면 그 칸만 높이가 달라져 행 아래 선이 끊긴다.
   선은 td 가 긋고, 정렬은 안쪽 상자가 맡게 나눈다. */
td.act{text-align:right;white-space:nowrap}
td.act>*{display:inline-flex;align-items:center;gap:6px}
.bar{height:5px;border-radius:3px;background:var(--s3);overflow:hidden;min-width:70px}
/* 행마다 하나뿐인 「다음 할 일」이다. 21px 짜리 배지로는 누르기 어렵다. */
td.act .st{padding:6px 13px;font-size:12px;border-radius:7px}
td.act button.sm{padding:6px 13px;font-size:12px}
.bar i{display:block;height:100%;background:var(--ac)}
.mini{font-size:11.5px;color:var(--tm);white-space:nowrap}
.empty{color:var(--tm);font-size:12.8px;padding:14px 0}
/* 이 표는 6열인데 중단점이 없어 좁은 화면에서 가로로 넘쳤다.
   좁아지면 카드처럼 쌓고, 각 칸 앞에 무엇인지 붙인다. */
@media(max-width:760px){
 .grp table,.grp tbody,.grp tr,.grp td{display:block;width:100%}
 .grp tr{border:1px solid var(--bd);border-radius:9px;padding:10px 12px;
  margin-bottom:8px;background:var(--s1)}
 .grp td{border:0;padding:3px 0}
 td.act{text-align:left;padding-top:9px}
 td.act .st,td.act button.sm{display:inline-block;width:100%;text-align:center}}
"""


def render_dashboard(rows: list[dict], queue: dict, worker_ok: bool,
                     pending: int, env: str, *, stuck: list[dict] | None = None) -> str:
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r["status"], []).append(r)

    n_todo = sum(len(by.get(s, [])) for s in ("received", "ingested", "assessed",
                                              "needs_review", "failed"))
    kpis = f"""<div class="kpis">
 <div class="kpi"><span>내가 할 일</span><b>{n_todo}<i>건</i></b>
   <em>서류·판정·검토 대기</em></div>
 <div class="kpi"><span>진행 중</span><b>{len(by.get('assessing', [])) + len(by.get('queued', []))}<i>건</i></b>
   <em>판정 대기·진행</em></div>
 <div class="kpi"><span>완료</span><b>{len(by.get('decided', []))}<i>건</i></b>
   <em>최종 판정 기록됨</em></div>
 <div class="kpi"><span>전체</span><b>{len(rows)}<i>건</i></b>
   <em>미확정 기준 {pending}건</em></div>
</div>"""

    warn = ""
    if not worker_ok and (queue.get("queued") or 0):
        warn += ('<div class="note warn"><b>판정 워커가 돌고 있지 않습니다.</b> '
                 f'대기 중인 작업 {queue.get("queued")}건이 처리되지 않습니다. '
                 '터미널에서 <code>./scripts/dev.sh worker</code> 를 실행하세요.</div>')
    if stuck:
        items = " · ".join(f"{j['kind']} #{j['id']} ({int(j['분'])}분)" for j in stuck[:5])
        warn += ('<div class="note warn"><b>멈춰 있는 작업이 있습니다.</b> '
                 f'{items}. 워커가 중간에 죽으면 작업이 잡힌 채로 남습니다. '
                 '워커를 다시 띄우면 자동으로 거둬 갑니다.</div>')

    secs = ""
    for st in ORDER:
        items = by.get(st)
        if not items:
            continue
        label, badge = FLOW.get(st, (st, ""))
        body = ""
        for r in items:
            nxt = r.get("next_step")
            if not nxt:
                act = f'<a class="st" href="/submissions/{r["id"]}">개요 열기</a>'
            elif nxt[1] == "analyze":
                act = (f'<button class="sm" onclick="analyze({r["id"]},this)">'
                       f'{e(nxt[0])}</button>')
            else:
                act = f'<a class="st ac" href="{e(nxt[1])}">{e(nxt[0])}</a>'
            prog = ""
            if st in ("queued", "assessing"):
                # 값은 비워 두고 진행률만 따로 긁어 채운다 (통째 새로고침 없이)
                prog = (f'<div class="bar" data-run="{r["id"]}">'
                        f'<i style="width:0%"></i></div>'
                        f'<span class="mini" data-runtxt="{r["id"]}">시작 중…</span>')
            elif r["n_el"]:
                done = r["n_rev"] or 0
                prog = (f'<div class="bar"><i style="width:{done / r["n_el"] * 100:.0f}%"></i></div>'
                        f'<span class="mini">검토 {done}/{r["n_el"]}</span>')
            fin = (f'<span class="st ok">{e(r["decision"])} '
                   f'{r["recognized_hours"]}/{r["total_hours"]}h</span>'
                   if r["decision"] else "")
            body += f"""<tr>
 <td><a href="/submissions/{r['id']}"><b>{e(r['case_number'])}</b></a></td>
 <td>{e(r['official_name'] or r['target_program_id'])}
     <span class="mini">서류 {r['n_doc']} · {e(r.get('hours_note') or '')}</span></td>
 <td>{prog}</td>
 <td>{fin}</td>
 <td class="n mini">{r['received_at']:%m-%d %H:%M}</td>
 <td class="act"><span>{act}</span></td></tr>"""
        anchor = label.replace(" ", "-")
        secs += f"""<div class="grp" id="{anchor}"><h2><span class="st {badge}">{e(label)}</span>
 <small>{len(items)}건</small></h2>
 <table><tbody>{body}</tbody></table></div>"""

    if not rows:
        secs = ('<div class="empty">접수된 건이 없습니다. '
                '<a href="/submissions/new">새 접수</a>로 시작하세요.</div>')

    body = f"""<h1>접수 현황</h1>
<p class="sub">단계별로 묶었습니다. 접수번호를 누르면 그 건의 심사 개요가 열리고,
 오른쪽 버튼이 다음에 할 일입니다.</p>
<div style="margin-bottom:16px"><a href="/submissions/new"
 style="display:inline-block;font-weight:600;padding:8px 18px;border-radius:8px;
 background:var(--tp);color:var(--s1)">＋ 새 접수 시작</a></div>
{warn}{kpis}{secs}
<footer>갱신 {datetime.now():%H:%M:%S} ·
 <span id="poll">도는 건이 있으면 3초마다 그 줄만 갱신합니다</span> ·
 <a href="/audit">감사</a> · <a href="/stats">운영 통계</a></footer>"""

    scripts = """<script>
// 도는 건이 있으면 3초마다 그 줄만 갱신한다. 통째로 새로고침하면
// 스크롤이 튀고, 열어 둔 것이 닫힌다.
let idle = 0;
async function tick() {
  const bars = document.querySelectorAll('[data-run]');
  const note = document.getElementById('poll');
  if (!bars.length) {                       // 도는 건이 없다 — 느긋하게 본다
    if (note) note.textContent = '30초마다 갱신';
    setTimeout(() => location.reload(), 30000);
    return;
  }
  try {
    const d = await (await fetch('/cases/progress.json')).json();
    let moving = 0;
    for (const bar of bars) {
      const id = bar.dataset.run, p = d.running[id];
      const txt = document.querySelector(`[data-runtxt="${id}"]`);
      if (!p) { location.reload(); return; }      // 끝났다 — 한 번만 새로고침
      moving++;
      bar.querySelector('i').style.width = p.pct + '%';
      txt.textContent = p.total
        ? `${p.step} ${p.done}/${p.total}` +
          (p.remaining.length ? ` · ${p.remaining[0]} 외 ${p.remaining.length - 1}` : '')
        : p.step;
    }
    idle = moving ? 0 : idle + 1;
  } catch (e) { idle++; }
  setTimeout(tick, idle > 20 ? 15000 : 3000);
}
tick();

async function analyze(id, btn) {
  btn.disabled = true; btn.textContent = '시작 중…';
  const r = await fetch(`/submissions/${id}/analyze`, {method: 'POST'});
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    btn.disabled = false; btn.textContent = '근거 분석 시작';
    return alert(d.detail || '시작하지 못했습니다');
  }
  location.reload();
}
</script>"""
    return page("접수 현황", body, css=CSS, here="/cases", env=env, scripts=scripts)
