"""Track A·B 위원 페이지가 같이 쓰는 조각 — 판정 파라미터 표.

값은 rubric 에서 읽는다. 「구분」은 현행 규칙 / TF 결정 필요 둘뿐이다(pending_decisions 에 있으면 후자).
"""
from __future__ import annotations

import html

e = lambda x: html.escape(str(x) if x is not None else "")   # noqa: E731


def param_table(rows: list[tuple[str, str, str, bool]], title: str = "판정 파라미터 — 위원 논의로 수정 가능") -> str:
    """rows: (항목, 현재값, 근거, TF결정필요?)"""
    body = "".join(
        f"<tr><td>{e(k)}</td><td>{e(v)}</td><td>{e(src)}</td>"
        f"<td>{'<b>TF 결정 필요</b>' if pend else '현행 규칙'}</td><td style='min-width:160px'></td></tr>"
        for k, v, src, pend in rows)
    return f"""<h3 style="font-size:14px;margin:0 0 8px;color:var(--tp)">{e(title)}</h3>
<div class="tw"><table class="hold-tbl"><thead><tr><th>항목</th><th>현재값</th><th>근거</th><th>구분</th><th>수정 의견</th></tr></thead>
<tbody>{body}</tbody></table></div>"""


def pending(rubric, key: str) -> bool:
    return any(p.key == key for p in rubric.pending_decisions)


# ── 접수 구분 (submission.track) ────────────────────────────────────
#
# 「Track A/B」라는 말이 이 앱에서 두 가지를 가리킨다.
#
#   접수 구분  submission.track   — 이 사람을 어떤 경로로 심사하나 (A·B)
#   판정 종류  assessment.kind    — 어떤 판정을 돌렸나 (기록 확인·근거 분석)
#
# 보고서 제목의 「RPL Track A/B 심사 보고서」는 **판정 종류**이고 연구팀 확정
# 포맷이라 고칠 수 없다. 그래서 접수 구분은 제목이 아니라 배지로 따로 적는다.
# 문구는 접수 화면(intake_view)의 선택지에서 그대로 가져왔다 — 고른 말과
# 보이는 말이 다르면 같은 것인지 알 수 없다.
TRACK = {
    "A": ("A 자격", "과정평가형 자격 보유 — 기록 확인"),
    "B": ("B 서류", "경력·훈련 등 제출 서류 기반 — 근거 분석"),
}

TRACK_CSS = """
.trk{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.02em;
 border:1px solid var(--bd);border-radius:999px;padding:1px 7px;margin-left:6px;
 white-space:nowrap;vertical-align:middle}
.trk.a{color:#1c4587;border-color:#1c4587}
.trk.b{color:#7a4706;border-color:#7a4706}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])) .trk.a{color:#9dc1f5;border-color:#9dc1f5}
 :root:where(:not([data-theme=light])) .trk.b{color:#e0b487;border-color:#e0b487}}
"""


def track_chip(track: str | None, *, full: bool = False) -> str:
    """접수 구분 배지. `full` 이면 뜻까지 적는다 — 한 건만 보는 화면용."""
    short, long = TRACK.get((track or "").upper(), ("구분 미상", "접수 구분이 기록되지 않았습니다"))
    cls = (track or "").lower() if (track or "").upper() in TRACK else ""
    text = f"{short} · {long.split(' — ')[0]}" if full else short
    return f'<span class="trk {cls}" title="{e(long)}">{e(text)}</span>'


# ── Track A 의 단계 이름 ────────────────────────────────────────────
#
# Track A·B 는 접수부터 다른 경로다. 근거 분석은 B 가 아니라 **Track A 안의
# 2단계**인데, 화면에는 확정 포맷 제목 「RPL Track B 심사 보고서」가 떠서 트랙이
# 바뀐 것처럼 보였다. 제목은 연구팀 회람본이라 못 바꾸므로(docs/formats/README.md)
# 단계 이름을 제목 **위에** 크게 붙이고 확정 제목은 아래로 내린다.
STEP = {
    "time":     ("① 기록 확인", "NCS 코드가 맞는 이수시간을 센다"),
    "evidence": ("② 근거 분석", "그 밖의 자료로 추가 인정이 가능한지 본다"),
    "review":   ("③ 전문가 검토", "근거를 보고 추가 인정 시간을 정한다"),
    "final":    ("④ 최종 판정", "인정시간 → 인정 능력단위 → 면제시간"),
}

# 못 가는 단계에 왜 못 가는지 붙인다 — 흐린 글씨만 두면 고장으로 읽힌다.
STEP_BLOCKED = {
    "time":     "기록 확인 결과가 아직 없습니다",
    "evidence": "근거 분석을 아직 돌리지 않았습니다",
    "review":   "기록 확인이 끝나야 들어갈 수 있습니다",
    "final":    "기록 확인이 끝나야 들어갈 수 있습니다",
}

STEP_CSS = """
.step-h{margin:0 0 2px;font-size:21px;letter-spacing:-.02em}
.step-h small{display:block;font-size:12.5px;font-weight:400;color:var(--tm);margin-top:2px}
.step-src{margin:0 0 14px;font-size:11.5px;color:var(--tm)}
.step-nav{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 12px;font-size:11.5px}
.step-nav a,.step-nav span{padding:3px 10px;border:1px solid var(--bd);border-radius:999px;
 color:var(--ts);text-decoration:none}
.step-nav a:hover{border-color:var(--tp);color:var(--tp)}
.step-nav .on{border-color:var(--tp);color:var(--tp);font-weight:700}
.step-nav .off{color:var(--tm);opacity:.55;cursor:not-allowed}

/* 그 화면에서 할 일 하나. 화면당 하나만 쓴다. */
.act-row{display:flex;justify-content:flex-end;align-items:center;gap:10px;margin:14px 0 0}
a.go,button.go{display:inline-block;font:inherit;font-size:13px;font-weight:600;
 padding:7px 16px;border-radius:8px;border:1px solid var(--tp);
 background:var(--tp);color:#fff;cursor:pointer;text-decoration:none}
a.go:hover,button.go:hover{opacity:.88}
"""


def step_head(key: str, confirmed_title: str, *,
              nav: dict[str, str | None] | None = None) -> str:
    """단계 이름(크게) + 확정 포맷 제목(작게) + 네 단계 이동줄.

    `nav` 는 `{단계키: 주소}`. 주소가 없으면(None) 그 단계는 흐리게 두고 왜 못
    가는지 말한다. `nav` 를 아예 넘기지 않으면 예전처럼 글자만 그린다.

    이동줄을 링크로 둔 이유: 이 줄이 「지금 어디인가」를 이미 말하고 있으므로,
    같은 자리에서 움직일 수 있는 것이 가장 짧은 길이다. 화면마다 다음 단계
    버튼을 따로 두면 위치도 문구도 갈라진다 — 실제로 여섯 가지로 갈라졌다.
    """
    name, what = STEP[key]
    out = ""
    for k in ("time", "evidence", "review", "final"):
        label = e(STEP[k][0])
        if k == key:
            out += f'<span class="on">{label}</span>'
        elif nav is None:
            out += f'<span>{label}</span>'
        elif nav.get(k):
            out += f'<a href="{e(nav[k])}" title="{e(STEP[k][1])}">{label}</a>'
        else:
            out += f'<span class="off" title="{e(STEP_BLOCKED[k])}">{label}</span>'
    return (f'<div class="step-nav">{out}</div>'
            f'<h1 class="step-h">{e(name)}<small>{e(what)}</small></h1>'
            f'<p class="step-src">확정 보고서 포맷: {e(confirmed_title)}</p>')


def step_nav(submission_id: int, time_aid: int | None,
             has_evidence: bool) -> dict[str, str | None]:
    """네 단계의 주소. 한 곳에서 만든다 — 화면마다 조립하면 또 갈라진다."""
    return {
        "time": f"/submissions/{submission_id}/report/time" if time_aid else None,
        "evidence": f"/submissions/{submission_id}/report/evidence" if has_evidence else None,
        "review": f"/assessments/{time_aid}/review" if time_aid else None,
        "final": f"/assessments/{time_aid}/exemption" if time_aid else None,
    }
