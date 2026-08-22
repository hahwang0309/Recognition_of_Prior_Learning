"""화면 공통 껍데기 — 색·간격·머리말을 한곳에서 정한다.

화면이 늘어날 때마다 CSS 를 복사해 붙이면 곧 서로 어긋난다.
여기 한 벌만 두고 각 화면은 자기 것만 얹는다.

담는 사람은 RPL·직종 전문가와 담당자다. 화면에 내부 용어를 쓰지 않는다.
"""
from __future__ import annotations

import html

e = lambda x: html.escape(str(x) if x is not None else "")   # noqa: E731

# 화면 목록 — 머리말 차림표. (경로, 이름)
NAV = [("/", "홈"), ("/cases", "접수 현황"), ("/submissions/new", "새 접수"),
       ("/audit", "감사"), ("/stats", "운영 통계")]

# 권고 코드는 기준서에 있는 말이라 남기되, **항상 뜻을 붙여 쓴다.**
# 화면마다 따로 적어 두면 같은 코드가 다른 말로 불린다. 여기 한 벌만 둔다.
#   코드: (색 class, 짧은 이름, 무엇을 하라는 뜻인가)
REC = {"R0": ("r0", "기이수 인정검토", "이미 평가를 마친 항목 — 추가 확인 없음"),
       "R1": ("r1", "서류 인정검토", "낸 서류만으로 판단"),
       "R2": ("r2", "면접 확인", "화상면접으로 확인"),
       "R3": ("r3", "실기 확인", "대면 실기·시연으로 확인"),
       "R4": ("r4", "추가서류 요청", "서류 보완 후 재판단"),
       "R5": ("r5", "미인정", "훈련 이수 필요")}


def rec_name(code: str) -> str:
    return REC.get(code, ("", code, ""))[1]

BASE = """*{box-sizing:border-box}
:root{--s1:#fcfcfb;--s2:#f4f4f1;--s3:#eceae4;--bd:#e0e0da;--tp:#0b0b0b;--ts:#4a4a46;
 /* --tm 은 라벨·캡션에 쓰인다(11~12.5px). 가장 밝은 배경(--s3)에서도 4.5:1 을 넘겨야 한다.
    이전 #84837c 는 3.16~3.71 로 미달이었다. 다크 모드는 그대로 둔다 — 거기서는 통과한다. */
 --tm:#6b6a63;
 /* 링크도 본문 크기다. #3f8ed0 은 3.18~3.41 이었다. */
 --ac:#2b6ea6;
 --ok:#0a8a0a;--wn:#fab219;--no:#d03b3b;
 /* 권고 태그 — 배경이 밝으면 흰 글씨로는 읽히지 않는다.
    R2(#fab219)+흰글씨는 1.83:1 이었다. 밝은 배경에는 어두운 글씨를 얹는다. */
 --r0:#0a8a0a;--r0-fg:#fff;
 --r1:#2b6ea6;--r1-fg:#fff;
 --r2:#fab219;--r2-fg:#3a2a00;
 --r3:#e07b39;--r3-fg:#2e1400;
 --r4:#7d55b8;--r4-fg:#fff;
 --r5:#d03b3b;--r5-fg:#fff}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--s1:#1a1a19;--s2:#232322;
 --s3:#2b2b29;--bd:#3a3a38;--tp:#fff;--ts:#c3c2b7;--tm:#8f8e86}}
body{margin:0;background:var(--s1);color:var(--tp);
 font:14px/1.65 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",Pretendard,sans-serif}
a{color:var(--ac);text-decoration:none}a:hover{text-decoration:underline}
/* 키보드로 옮겨 다닐 때 지금 어디에 있는지 보여야 한다.
   이전에는 input 에만 초점 표시가 있었고 button·a·details 에는 없었다.
   검토 화면은 버튼만 130개가 넘는다 — 키보드로 훑는 것이 자연스러운 사용법이다. */
:where(a,button,summary,[tabindex]):focus-visible{outline:2px solid var(--ac);
 outline-offset:2px;border-radius:4px}
input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid var(--ac);
 outline-offset:-1px}
.top{border-bottom:1px solid var(--bd);background:var(--s2)}
.top .in{max-width:1080px;margin:0 auto;padding:0 20px;display:flex;align-items:center;
 gap:20px;flex-wrap:wrap;min-height:48px}
.top .bx{font-weight:600;font-size:13.5px;color:var(--tp);white-space:nowrap}
.top nav{display:flex;gap:16px;flex:1;flex-wrap:wrap}
.top nav a{font-size:13px;color:var(--ts);padding:14px 0;border-bottom:2px solid transparent}
.top nav a.on{color:var(--tp);border-bottom-color:var(--ac);font-weight:600}
.top .env{font-size:11.5px;color:var(--tm);white-space:nowrap}
.wrap{max-width:1080px;margin:0 auto;padding:26px 20px 80px}
h1{font-size:23px;margin:0 0 4px}.sub{color:var(--tm);font-size:12.5px;margin:0 0 20px}
h2{font-size:15.5px;margin:26px 0 10px}
.note{background:var(--s2);border:1px solid var(--bd);border-left:3px solid var(--ac);
 border-radius:8px;padding:11px 15px;margin-bottom:18px;font-size:12.8px;color:var(--ts)}
.note.warn{border-left-color:var(--no)}
.note b{color:var(--tp)}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{padding:8px 10px;border-bottom:1px solid var(--bd);text-align:left;vertical-align:top}
th{color:var(--tm);font-weight:600;font-size:11.5px;white-space:nowrap}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tbody tr:hover td{background:var(--s2)}
.st{display:inline-block;font-size:11px;padding:1.5px 8px;border-radius:10px;
 background:var(--s3);color:var(--ts);white-space:nowrap}
.st.ok{background:var(--ok);color:#fff}.st.wn{background:var(--wn);color:#3a2a00}
.st.no{background:var(--no);color:#fff}.st.ac{background:var(--ac);color:#fff}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:9px;margin-bottom:18px}
.kpi{background:var(--s2);border:1px solid var(--bd);border-radius:9px;padding:10px 13px}
.kpi span{display:block;font-size:11.5px;color:var(--tm)}
.kpi b{font-size:22px;font-variant-numeric:tabular-nums}
.kpi b i{font-size:12px;font-style:normal;color:var(--ts);margin-left:2px}
.kpi em{display:block;font-style:normal;font-size:11px;color:var(--tm);margin-top:2px}
label{display:block;font-size:12px;color:var(--tm);margin-bottom:4px}
input,select,textarea{font:inherit;font-size:13px;padding:7px 11px;width:100%;
 border:1px solid var(--bd);border-radius:7px;background:var(--s1);color:var(--tp)}

.row{display:grid;gap:12px;margin-bottom:14px}
.row.two{grid-template-columns:1fr 1fr}.row.three{grid-template-columns:1fr 1fr 1fr}
button{font:inherit;font-size:13px;padding:7px 16px;border-radius:7px;cursor:pointer;
 border:1px solid var(--bd);background:var(--s1);color:var(--ts)}
button:hover{border-color:var(--tm)}
button.go{background:var(--tp);color:var(--s1);border-color:transparent;font-weight:600}
button.go:disabled{opacity:.4;cursor:not-allowed}
button.sm{font-size:12px;padding:3px 10px}
.card{background:var(--s2);border:1px solid var(--bd);border-radius:10px;padding:15px 17px;
 margin-bottom:12px}
.msg{font-size:12.8px;padding:9px 13px;border-radius:7px;margin:10px 0}
.msg.ok{background:rgba(12,163,12,.12);color:var(--ok)}
.msg.no{background:rgba(208,59,59,.12);color:var(--no)}
footer{color:var(--tm);font-size:11.5px;border-top:1px solid var(--bd);padding-top:14px;margin-top:28px}
@media(max-width:680px){
 .row.two,.row.three{grid-template-columns:1fr}
 /* 좁은 화면에서 차림표가 세로로 무너지고 이름표와 겹쳤다.
    가로로 넘기게 두고, 환경 표시는 접는다. */
 .top .in{gap:10px;min-height:0;padding:0 14px;flex-wrap:nowrap;align-items:stretch}
 .top .bx{font-size:12.5px;align-self:center;flex:none}
 .top nav{gap:14px;overflow-x:auto;flex-wrap:nowrap;
  scrollbar-width:none;-webkit-overflow-scrolling:touch}
 .top nav::-webkit-scrollbar{display:none}
 .top nav a{padding:12px 0;white-space:nowrap;font-size:12.5px}
 .top .env{display:none}
 .wrap{padding:20px 14px 80px}
 h1{font-size:20px}}
/* 보고서는 인쇄해서 회의에 들고 간다. 차림표·버튼은 종이에 쓸모가 없다. */
@media print{
 .top,.noprint,footer .noprint{display:none!important}
 body{background:#fff;color:#000;font-size:10.5pt}
 .wrap{max-width:none;padding:0}
 .card,.kpi,.note{break-inside:avoid;background:#fff;border-color:#bbb}
 h2{break-after:avoid}
 tr,.row{break-inside:avoid}
 a{color:#000;text-decoration:none}}"""


def page_open(title: str, *, css: str = "", here: str = "", env: str = "") -> str:
    """화면 껍데기의 여는 쪽 — `<div class="wrap">` 까지.

    화면마다 자기 `<!doctype>` 를 따로 쓰면 머리말 차림표가 빠진다.
    실제로 7개 중 4개가 그랬고, 그중 둘(`/audit`·`/stats`)은 차림표에 실려 있으면서도
    누르는 순간 차림표가 사라졌다. 검토 화면은 사람이 가장 오래 머무는 곳이었다.

    파일 고유 CSS(`css`)는 BASE **뒤에** 붙는다. 같은 이름의 규칙이 있으면
    파일 것이 이기므로 기존 모양이 바뀌지 않는다.
    """
    nav = "".join(f'<a href="{p}"{" class=on" if p == here else ""}>{e(n)}</a>'
                  for p, n in NAV)
    if not env:
        try:
            from krpl_core.config import get_rubric, get_settings
            env = env_label(get_settings(), get_rubric())
        except Exception:                                   # noqa: BLE001
            env = ""
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title><style>{BASE}
{css}</style></head><body>
<div class="top"><div class="in">
  <span class="bx">일학습병행 선행학습인정</span>
  <nav>{nav}</nav>
  <span class="env">{e(env)}</span>
</div></div>
<div class="wrap">"""


def page(title: str, body: str, *, css: str = "", here: str = "",
         env: str = "", scripts: str = "") -> str:
    """한 화면. body 는 .wrap 안에 들어간다."""
    return (page_open(title, css=css, here=here, env=env)
            + body + f"</div>\n{scripts}</body></html>")


def env_label(settings, rubric) -> str:
    """어느 환경에서 무슨 기준으로 도는지. 화면마다 보이게 둔다."""
    bits = [f"기준 v{rubric.version}"]
    if rubric.pending_decisions:
        bits.append(f"미확정 {len(rubric.pending_decisions)}건")
    if settings.env != "prod":
        bits.append(settings.env)
    return " · ".join(bits)
