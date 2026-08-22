"""첫 화면 — 처음 온 사람은 흐름을 알고, 매일 쓰는 사람은 바로 일한다.

두 요구가 부딪힌다.
  처음 온 사람: 이게 뭘 하는 도구인지, 어디서 시작하는지 모른다
  매일 쓰는 사람: 설명은 필요 없고 지금 할 일로 바로 가고 싶다

그래서 **할 일이 있으면 할 일을 먼저**, 없으면 흐름 안내를 앞세운다.
어느 쪽이든 「새 접수 시작」 버튼은 항상 눈에 띄는 자리에 둔다.
"""
from __future__ import annotations

from services.report.layout import e, page

# 화면 흐름과 같은 순서·같은 말을 쓴다. 여기만 옛 이름으로 남으면
# 「분석·대조」가 무엇인지 화면 어디서도 찾을 수 없다.
STEPS = [
    ("1", "접수", "심사번호·목표 종목·보유 자격을 적습니다", "/submissions/new"),
    ("2", "서류", "지원자가 낸 서류를 올립니다. 식별정보는 자동으로 가려집니다", None),
    ("3", "시간 대조", "이수 기록으로 확인되는 시간을 자동으로 맞대 봅니다", None),
    ("4", "근거 분석", "남은 시간을 제출 자료로 따져 보고 보고서를 만듭니다", None),
    ("5", "검토", "보고서를 읽으신 뒤 항목마다 인정 여부를 정하십니다", None),
    ("6", "판정", "감면 시간과 함께 최종 판정을 기록합니다", None),
]

CSS = """
.hero{display:grid;grid-template-columns:1.35fr 1fr;gap:22px;align-items:start;
 margin-bottom:26px}
.hero h1{font-size:27px;margin:0 0 8px;line-height:1.3}
.hero p{font-size:14px;color:var(--ts);margin:0 0 18px;line-height:1.7}
.cta{display:flex;gap:9px;flex-wrap:wrap}
.cta a{display:inline-flex;align-items:center;gap:7px;font-size:14px;font-weight:600;
 padding:11px 22px;border-radius:9px;background:var(--tp);color:var(--s1)}
.cta a:hover{text-decoration:none;opacity:.88}
.cta a.alt{background:var(--s2);color:var(--tp);border:1px solid var(--bd);font-weight:500}
.todo{background:var(--s2);border:1px solid var(--bd);border-radius:11px;padding:16px 18px}
.todo h3{font-size:13px;margin:0 0 11px;color:var(--tm);font-weight:600}
.todo ul{list-style:none;margin:0;padding:0}
.todo li{display:flex;align-items:center;gap:9px;padding:7px 0;font-size:13px;
 border-bottom:1px solid var(--bd)}
.todo li:last-child{border-bottom:0}
.todo li b{font-size:18px;font-variant-numeric:tabular-nums;min-width:26px;text-align:right}
.todo li span{flex:1;color:var(--ts)}
.todo li a{font-size:12px;white-space:nowrap}
.todo .none{color:var(--tm);font-size:12.8px;padding:8px 0}
.flow{display:grid;grid-template-columns:repeat(6,1fr);gap:0;margin:0 0 8px}
.step{position:relative;padding:14px 12px 14px 0}
.step:not(:last-child)::after{content:"";position:absolute;right:9px;top:24px;
 width:10px;height:10px;border-top:1.5px solid var(--bd);border-right:1.5px solid var(--bd);
 transform:rotate(45deg)}
.step .n{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;
 border-radius:50%;background:var(--s3);color:var(--ts);font-size:11.5px;font-weight:600;
 margin-bottom:7px}
.step .t{font-size:13.5px;font-weight:600;margin-bottom:3px}
.step .d{font-size:11.5px;color:var(--tm);line-height:1.5}
.step.link .n{background:var(--ac);color:#fff}
.recent td{padding:9px 10px}
@media(max-width:860px){.hero{grid-template-columns:1fr}
 .flow{grid-template-columns:1fr 1fr 1fr}.step::after{display:none}}
"""


def render_home(todo: dict, recent: list[dict], total: int,
                pending: int, env: str) -> str:
    n_todo = sum(todo.values())

    items = ""
    for label, n, href in (
        ("서류를 올려야 하는 건", todo.get("서류", 0), "/cases#서류-대기"),
        ("근거 분석을 시작할 건", todo.get("분석", 0), "/cases#분석-대기"),
        ("검토를 기다리는 건", todo.get("검토", 0), "/cases#검토-대기"),
        ("확인이 필요한 건", todo.get("확인", 0), "/cases#확인-필요"),
    ):
        if n:
            items += (f'<li><b>{n}</b><span>{e(label)}</span>'
                      f'<a href="{href}">보기 →</a></li>')
    todo_box = f"""<div class="todo"><h3>지금 할 일</h3>
 {'<ul>' + items + '</ul>' if items
  else '<div class="none">기다리는 일이 없습니다. 새 접수를 시작하시면 됩니다.</div>'}</div>"""

    flow = "".join(f"""<div class="step{' link' if href else ''}">
 <div class="n">{n}</div><div class="t">{e(t)}</div><div class="d">{e(d)}</div></div>"""
                   for n, t, d, href in STEPS)

    rows = "".join(f"""<tr>
 <td><a href="/submissions/{r['id']}"><b>{e(r['case_number'])}</b></a></td>
 <td>{e(r['official_name'] or r['target_program_id'])}</td>
 <td><span class="st">{e(r['step'])}</span></td>
 <td class="n" style="color:var(--tm);font-size:11.5px">{r['received_at']:%m-%d %H:%M}</td>
</tr>""" for r in recent)
    recent_box = f"""<h2>최근 접수 <a href="/cases" style="font-size:12px;font-weight:400">
 전체 {total}건 →</a></h2>
<table class="recent"><tbody>{rows}</tbody></table>""" if recent else ""

    body = f"""
<div class="hero">
 <div>
  <h1>지원자가 낸 서류를<br>능력단위별 판정 근거로 정리합니다</h1>
  <p>이 도구는 <b>인정 여부를 정하지 않습니다.</b> 서류의 어느 문장이
   어느 능력단위요소의 근거인지, 무엇이 비었는지를 정리해 드립니다.
   전체인정·부분인정·불인정은 검토하시는 분이 정하십니다.</p>
  <div class="cta">
   <a href="/submissions/new">＋ 새 접수 시작</a>
   <a class="alt" href="/cases">접수 현황{f' · 할 일 {n_todo}건' if n_todo else ''}</a>
  </div>
 </div>
 {todo_box}
</div>

<h2>심사는 이렇게 진행됩니다</h2>
<div class="flow">{flow}</div>
<div class="note">
 <b>2~4단계는 자동입니다.</b> 서류를 올리면 시스템이 읽고 배치하고 스스로 대조합니다.
 사람이 손대는 곳은 <b>1단계 접수</b>와 <b>5·6단계 검토·판정</b>입니다.
 각 단계가 무엇을 했는지는 <a href="/audit">감사</a> 화면에서 파일로 확인하실 수 있습니다.
 {f'<br>지금 심사 기준 가운데 <b>{pending}건</b>이 확정 대기 중입니다 — '
  f'그에 걸린 항목은 검토 화면에 표시됩니다.' if pending else ''}
</div>

{recent_box}
"""
    return page("일학습병행 선행학습인정", body, css=CSS, here="/", env=env)
