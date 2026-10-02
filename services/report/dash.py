"""종합 현황 대시보드 — Track B 보고서의 「히트맵까지」 부분.

## 왜 따로 뽑는가

전문가 검토 다섯 단계 내내 이 그림이 위에 붙어 있어야 한다. 단계를 넘길 때마다
「지금 어디까지 왔나」가 갱신되지 않으면, 항목에 통과를 찍어도 그것이 전체에서
무슨 뜻인지 알 수 없다.

Track B 보고서와 **같은 마크업**을 쓴다. 연구팀이 회람·확정한 포맷이므로
두 벌로 갈라 두면 곧 어긋난다. 보고서는 판정 시점의 그림을 그대로 보여 주고,
검토 화면은 사람이 정한 것을 얹어 그린다.

## 색이 바뀌는 규칙

판정 시점에는 권고(R0~R5)로 칠한다. 검토가 시작되면 **사람이 정한 것**으로
덮어쓴다 — 인정은 초록, 미인정은 빨강, 아직 안 정한 것은 원래 권고 색을 흐리게.
"""
from __future__ import annotations

import html

e = lambda x: html.escape(str(x) if x is not None else "")   # noqa: E731

# 권고 → (class, 아이콘, 이름, 부연). Track B 보고서와 같은 값.
REC = {"R0": ("r0", "★", "기이수 인정", "이미 평가를 마침"),
       "R1": ("r1", "●", "서류 인정", "낸 서류로 판단"),
       "R2": ("r2", "▲", "면접확인", "화상면접"),
       "R3": ("r3", "■", "실기확인", "대면실기·시연"),
       "R4": ("r4", "◆", "추가서류", "서류 보완 후 재판단"),
       "R5": ("r5", "○", "미인정", "훈련 이수 필요")}
RORDER = ["R0", "R1", "R2", "R3", "R4", "R5"]

# 검토 결과 → (class, 아이콘, 이름)
OUT = {"인정": ("ok", "●", "인정"),
       "미인정": ("no", "○", "미인정"),
       "대기": ("wait", "·", "아직")}

CSS = """
.dash{border:1px solid var(--bd);border-radius:12px;background:var(--s1);
 padding:16px 18px;margin-bottom:20px}
.dash>h3{font-size:14px;margin:0 0 3px;display:flex;align-items:baseline;gap:9px}
.dash>h3 small{font-weight:400;font-size:11.5px;color:var(--tm)}
.dash .sub{color:var(--tm);font-size:12px;margin:0 0 12px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin-bottom:9px}
.kpi{background:var(--s2);border:1px solid var(--bd);border-left-width:4px;border-radius:8px;padding:8px 11px}
.kpi span{display:block;font-size:11px;color:var(--tm)}
.kpi b{font-size:20px;font-variant-numeric:tabular-nums}
.kpi em{display:block;font-style:normal;font-size:10.5px;color:var(--tm)}
.kpi.r0{border-left-color:var(--dr0)}.kpi.r1{border-left-color:var(--dr1)}
.kpi.r2{border-left-color:var(--dr2)}.kpi.r3{border-left-color:var(--dr3)}
.kpi.r4{border-left-color:var(--dr4)}.kpi.r5{border-left-color:var(--dr5)}
.kpi.ok{border-left-color:var(--dok)}.kpi.no{border-left-color:var(--dno)}
.kpi.wait{border-left-color:var(--dwait)}
.dstack{display:flex;height:10px;border-radius:5px;overflow:hidden;gap:2px;
 background:var(--s2);margin-bottom:5px}
.dstack i{display:block}
.sg.r0{background:var(--dr0)}.sg.r1{background:var(--dr1)}.sg.r2{background:var(--dr2)}
.sg.r3{background:var(--dr3)}.sg.r4{background:var(--dr4)}.sg.r5{background:var(--dr5)}
.sg.ok{background:var(--dok)}.sg.no{background:var(--dno)}.sg.wait{background:var(--dwait)}
.dlab{font-size:11.5px;color:var(--tm);margin-bottom:13px}
.hmw{overflow-x:auto;border:1px solid var(--bd);border-radius:9px;padding:10px}
.hm{border-collapse:separate;border-spacing:3px;width:auto;min-width:100%}
.hm th{padding:4px 6px;font-size:11px;color:var(--tm);font-weight:600;text-align:center;vertical-align:bottom}
.hm th.rl{text-align:right;white-space:nowrap;font-size:10.5px;padding-right:8px}
.un{font-size:11.5px;color:var(--tp);font-weight:600;max-width:110px;line-height:1.25}
.uh{font-size:10px;color:var(--tm);font-variant-numeric:tabular-nums}
.hc{width:112px;height:46px;border-radius:6px;padding:4px 6px;vertical-align:middle;
 font-size:10.5px;line-height:1.25;color:#fff;overflow:hidden}
.hc.empty{background:transparent}
.hc.r0{background:var(--dr0)}.hc.r1{background:var(--dr1)}.hc.r2{background:#a06f00}
.hc.r3{background:var(--dr3)}.hc.r4{background:var(--dr4)}.hc.r5{background:var(--dr5)}
.hc.ok{background:var(--dok)}.hc.no{background:var(--dno)}
.hc.wait{background:var(--s3);color:var(--ts)}
.hi{font-size:9px;opacity:.85;margin-right:3px}
.hn{display:inline}
.dlgd{display:flex;flex-wrap:wrap;gap:12px;font-size:11.5px;color:var(--ts);margin-top:9px}
.dlgd span{display:flex;align-items:center;gap:5px}
.dlgd i{width:16px;height:9px;border-radius:3px;font-style:normal}
.dlgd i.ok{background:var(--dok)}.dlgd i.no{background:var(--dno)}
.dlgd i.wait{background:var(--s3);border:1px solid var(--bd)}
:root{--dr0:#1a5fb4;--dr1:#0ca30c;--dr2:#fab219;--dr3:#d03b3b;--dr4:#2a78d6;--dr5:#a9a9a2;
 --dok:#0a8a0a;--dno:#d03b3b;--dwait:#a9a9a2}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--dr5:#6b6b66;--dwait:#6b6b66}}
@media print{.dash{break-inside:avoid}}
"""


def heatmap(units: list[dict], cells: dict[tuple[str, int], dict], max_no: int,
            outcome_of: dict[str, str] | None = None) -> str:
    """가로축 능력단위 · 세로축 요소 번호(큰 번호가 위) · 칸 색은 판정.

    `outcome_of` 를 주면 사람이 정한 것으로 칠한다. 없으면 AI 권고 색.
    """
    outcome_of = outcome_of or {}
    head = "".join(f'<th><div class="un">{e(u["name"])}</div>'
                   f'<div class="uh">{u["hours"]}h</div></th>' for u in units)
    body = ""
    for no in range(max_no, 0, -1):
        tds = ""
        for u in units:
            x = cells.get((u["code"], no))
            if x is None:
                tds += '<td class="hc empty"></td>'
                continue
            rec = x["recommendation"]
            rcls, rico, rname, _ = REC[rec]
            name = x.get("_en") or x["element_id"]
            got = outcome_of.get(x["element_id"])
            if got:
                cls, ico, label = OUT.get(got, (rcls, rico, rname))
                tip = f'{name} — {label} (권고 {rec} {rname})'
            else:
                cls, ico = rcls, rico
                pl = x["payload"]
                n_gap = len(pl.get("uncovered_pc") or pl.get("uncovered_ksa") or [])
                what = "수행준거" if pl.get("schema") == "pc" else "KSA"
                tip = (f'{name} — {rec} {rname}'
                       + (f' / 미확보 {what} {n_gap}개' if n_gap else ''))
            tds += (f'<td class="hc {cls}" title="{e(tip)}">'
                    f'<span class="hi">{ico}</span><span class="hn">{e(name)}</span></td>')
        body += f'<tr><th class="rl">요소 {no}</th>{tds}</tr>'
    return (f'<div class="hmw"><table class="hm"><thead><tr><th class="rl"></th>{head}</tr>'
            f'</thead><tbody>{body}</tbody></table></div>')


def _bar(counts: dict[str, int], order: list[str], total: int,
         look: dict[str, tuple[str, str, str]]) -> tuple[str, str]:
    seg = "".join(
        f'<i class="sg {look[k][0]}" style="width:{counts[k] / total * 100:.2f}%" '
        f'title="{e(look[k][2])} {counts[k]}"></i>'
        for k in order if counts.get(k))
    lab = " · ".join(f"{look[k][2]} {counts[k]}" for k in order if counts.get(k))
    return seg, lab


def render(*, title: str, sub: str, units: list[dict],
           cells: dict[tuple[str, int], dict], max_no: int,
           n_elements: int, rec_counts: dict[str, int],
           outcome_of: dict[str, str] | None = None,
           note: str = "") -> str:
    """대시보드 한 벌. 검토가 시작되면 사람이 정한 것으로 갈아입는다."""
    if outcome_of:
        counts: dict[str, int] = {}
        for v in outcome_of.values():
            counts[v] = counts.get(v, 0) + 1
        order = ["인정", "대기", "미인정"]
        look = {k: OUT[k] for k in order}
        kpis = "".join(
            f'<div class="kpi {OUT[k][0]}"><span>{k}</span><b>{counts[k]}</b>'
            f'<em>요소 {n_elements}개 중</em></div>' for k in order if counts.get(k))
        seg, lab = _bar(counts, order, n_elements or 1, look)
        legend = ('<div class="dlgd"><span><i class="ok"></i>인정</span>'
                  '<span><i class="no"></i>미인정</span>'
                  '<span><i class="wait"></i>아직 정하지 않음</span></div>')
    else:
        look = {k: (REC[k][0], REC[k][1], REC[k][2]) for k in RORDER}
        kpis = "".join(
            f'<div class="kpi {REC[k][0]}"><span>{REC[k][2]}</span><b>{rec_counts[k]}</b>'
            f'<em>{REC[k][3]}</em></div>' for k in RORDER if rec_counts.get(k))
        seg, lab = _bar(rec_counts, RORDER, n_elements or 1, look)
        legend = ""

    return f"""<section class="dash">
 <h3>{e(title)}<small>{e(sub)}</small></h3>
 {f'<p class="sub">{note}</p>' if note else ''}
 <div class="kpis">{kpis}</div>
 <div class="dstack">{seg}</div>
 <div class="dlab">{e(lab)}</div>
 {heatmap(units, cells, max_no, outcome_of)}
 {legend}
</section>"""
