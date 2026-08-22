"""접수 현황 — 담당자가 아침에 여는 화면.

「지금 무엇을 해야 하는가」가 한눈에 보여야 한다.
그래서 단계별로 묶고, 각 건마다 **다음 할 일 버튼 하나**만 놓는다.
"""
from __future__ import annotations

from datetime import datetime

from services.report.layout import e, page

# 상태 → (표시, 배지, 다음 할 일)
FLOW = {
    "received":    ("서류 대기",   "",   ("서류 올리기", "/submissions/{id}/upload")),
    "ingested":    ("수집 완료",   "ac", ("판정 시작", "assess")),
    "queued":      ("판정 대기",   "ac", None),
    "assessing":   ("판정 중",     "ac", None),
    "assessed":    ("검토 대기",   "wn", ("검토 열기", "/assessments/{aid}/review")),
    "needs_review": ("확인 필요",  "no", ("검토 열기", "/assessments/{aid}/review")),
    "decided":     ("완료",       "ok", ("결과 보기", "/assessments/{aid}/review")),
    "failed":      ("실패",       "no", ("다시 판정", "assess")),
}
ORDER = ["received", "ingested", "queued", "assessing", "assessed",
         "needs_review", "failed", "decided"]

CSS = """
.grp{margin-bottom:26px}
.grp h2{display:flex;align-items:baseline;gap:9px;margin:0 0 8px}
.grp h2 small{font-weight:400;font-size:12px;color:var(--tm)}
.act{display:flex;gap:6px;justify-content:flex-end}
.bar{height:5px;border-radius:3px;background:var(--s3);overflow:hidden;min-width:70px}
.bar i{display:block;height:100%;background:var(--ac)}
.mini{font-size:11.3px;color:var(--tm);white-space:nowrap}
.empty{color:var(--tm);font-size:12.8px;padding:14px 0}
.worker{font-size:12.5px}
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
        label, badge, nxt = FLOW.get(st, (st, "", None))
        body = ""
        for r in items:
            act = ""
            if nxt:
                txt, href = nxt
                if href == "assess":
                    act = (f'<button class="sm" onclick="assess({r["id"]},this)">'
                           f'{txt}</button>')
                elif "{aid}" in href and r["aid"]:
                    act = f'<a class="st ac" href="{href.format(aid=r["aid"])}">{txt}</a>'
                elif "{id}" in href:
                    act = f'<a class="st ac" href="{href.format(id=r["id"])}">{txt}</a>'
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
 <td><a href="/audit/{e(r['case_number'])}"><b>{e(r['case_number'])}</b></a>
     <span class="st">{e(r['track'])}</span></td>
 <td>{e(r['official_name'] or r['target_program_id'])}
     <span class="mini">서류 {r['n_doc']} · 조각 {r['n_frag']}</span></td>
 <td>{prog}</td>
 <td>{fin}</td>
 <td class="n mini">{r['received_at']:%m-%d %H:%M}</td>
 <td class="act">{act}</td></tr>"""
        anchor = label.replace(" ", "-")
        secs += f"""<div class="grp" id="{anchor}"><h2><span class="st {badge}">{e(label)}</span>
 <small>{len(items)}건</small></h2>
 <table><tbody>{body}</tbody></table></div>"""

    if not rows:
        secs = ('<div class="empty">접수된 건이 없습니다. '
                '<a href="/submissions/new">새 접수</a>로 시작하세요.</div>')

    body = f"""<h1>접수 현황</h1>
<p class="sub">단계별로 묶었습니다. 각 건의 오른쪽 버튼이 다음에 할 일입니다.</p>
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

async function assess(id, btn) {
  btn.disabled = true; btn.textContent = '시작 중…';
  const r = await fetch(`/submissions/${id}/assess`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({force: true})});
  if (!r.ok) {
    const d = await r.json();
    btn.disabled = false; btn.textContent = '판정 시작';
    return alert(d.detail || '시작하지 못했습니다');
  }
  location.reload();
}
</script>"""
    return page("접수 현황", body, css=CSS, here="/cases", env=env, scripts=scripts)
