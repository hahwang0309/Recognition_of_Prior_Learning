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
# ── 단계 어휘 ───────────────────────────────────────────────────────
#
# 두 트랙은 접수부터 다른 경로이고 거치는 화면도 다르다. Track B 에는 ① 기록
# 확인이 없다 — 코드가 맞는 이수 기록이 없는 것이 전제이므로 근거 분석이 곧
# 판정이다. 그래서 단계줄을 트랙별로 따로 둔다.
#
#   Track A   ① 기록 확인  ② 근거 분석  ③ 전문가 검토  ④ 최종 판정
#   Track B   ① 근거 분석  ② 위원 검토  ③ 확인 계획    ④ 최종 판정
#
# 확정 보고서 제목(「RPL Track A/B 심사 보고서」)은 트랙별로 그대로 둔다.
# 단계 이름은 그 위에 얹는다.
STEP_A = {
    "time":     ("① 기록 확인", "NCS 코드가 맞는 이수시간을 센다"),
    "evidence": ("② 근거 분석", "그 밖의 자료로 추가 인정이 가능한지 본다"),
    "review":   ("③ 전문가 검토", "근거를 보고 추가 인정 시간을 정한다"),
    "final":    ("④ 최종 판정", "인정시간 → 인정 능력단위 → 면제시간"),
}
# Track B 는 ③ 확인 계획에서 끝난다. 요소·항목에는 시간이 없어(NCS 원자료 확인)
# 면제 시간을 여기서 확정하지 않는다 — 확인 계획이 인정·보류·불인정을 보이고 마무리한다.
STEP_B = {
    "evidence": ("① 근거 분석", "제출 자료를 능력단위 항목에 배치한다"),
    "panel":    ("② 위원 검토", "근거를 보고 항목별 인정 여부를 정한다"),
    "plan":     ("③ 확인 계획", "인정·보류·불인정과 보류 단위의 확인 방법"),
}
STEP = STEP_A            # 옛 이름 — Track A 화면이 쓰던 것

ORDER = {"A": ("time", "evidence", "review", "final"),
         "B": ("evidence", "panel", "plan")}

# 못 가는 단계에 왜 못 가는지 붙인다 — 흐린 글씨만 두면 고장으로 읽힌다.
STEP_BLOCKED = {
    "time":     "기록 확인 결과가 아직 없습니다",
    "evidence": "근거 분석을 아직 돌리지 않았습니다",
    "review":   "기록 확인이 끝나야 들어갈 수 있습니다",
    "panel":    "근거 분석이 끝나야 들어갈 수 있습니다",
    "plan":     "위원 검토를 제출해야 만들어집니다",
    "final":    "판정 결과가 아직 없습니다",
}


def steps_of(track: str | None) -> dict[str, tuple[str, str]]:
    return STEP_B if (track or "A").upper() == "B" else STEP_A


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


def step_head(key: str, confirmed_title: str, *, track: str = "A",
              nav: dict[str, str | None] | None = None) -> str:
    """단계 이름(크게) + 확정 포맷 제목(작게) + 네 단계 이동줄.

    `nav` 는 `{단계키: 주소}`. 주소가 없으면(None) 그 단계는 흐리게 두고 왜 못
    가는지 말한다. `nav` 를 아예 넘기지 않으면 예전처럼 글자만 그린다.

    이동줄을 링크로 둔 이유: 이 줄이 「지금 어디인가」를 이미 말하고 있으므로,
    같은 자리에서 움직일 수 있는 것이 가장 짧은 길이다. 화면마다 다음 단계
    버튼을 따로 두면 위치도 문구도 갈라진다 — 실제로 여섯 가지로 갈라졌다.
    """
    steps = steps_of(track)
    name, what = steps[key]
    out = ""
    for k in ORDER[(track or "A").upper()]:
        label = e(steps[k][0])
        if k == key:
            out += f'<span class="on">{label}</span>'
        elif nav is None:
            out += f'<span>{label}</span>'
        elif nav.get(k):
            out += f'<a href="{e(nav[k])}" title="{e(steps[k][1])}">{label}</a>'
        else:
            out += f'<span class="off" title="{e(STEP_BLOCKED[k])}">{label}</span>'
    return (f'<div class="step-nav">{out}</div>'
            f'<h1 class="step-h">{e(name)}<small>{e(what)}</small></h1>'
            f'<p class="step-src">확정 보고서 포맷: {e(confirmed_title)}</p>')


def step_nav(submission_id: int, time_aid: int | None, has_evidence: bool,
             *, track: str = "A", ev_aid: int | None = None,
             has_plan: bool = False) -> dict[str, str | None]:
    """단계별 주소. 한 곳에서 만든다 — 화면마다 조립하면 또 갈라진다.

    Track B 는 근거 분석 판정(`ev_aid`)을 축으로 돈다. 위원 검토·확인 계획이
    모두 그 판정에 붙어 있기 때문이다.
    """
    if (track or "A").upper() == "B":
        return {
            # ① 은 근거 분석 화면 하나뿐이다. 회람본 3장 보고서는 화면에서 걷어냈다
            # (2026-09-24) — 단계줄이 그것을 가리켜 「옛날 것으로 돌아갔다」가 됐다.
            "evidence": f"/submissions/{submission_id}/report/evidence" if ev_aid else None,
            "panel": f"/assessments/{ev_aid}/panel" if ev_aid else None,
            "plan": f"/assessments/{ev_aid}/plan" if (ev_aid and has_plan) else None,
        }
    return {
        "time": f"/submissions/{submission_id}/report/time" if time_aid else None,
        "evidence": f"/submissions/{submission_id}/report/evidence" if has_evidence else None,
        "review": f"/assessments/{time_aid}/review" if time_aid else None,
        "final": f"/assessments/{time_aid}/exemption" if time_aid else None,
    }


def unit_count_text(u: dict) -> str:
    """단위 판정 dict → 「수행준거 7/9 ≥1 · 평균 1.6」(신형) / 「요소 2/3 인정」(구형).

    unit_verdicts·plan 스냅샷·계획 artifact 가 같은 dict 모양을 쓴다. 신형은 `mean` 이 있다.
    """
    if u.get("mean") is not None and u.get("format", "pc") != "ksa":
        return f"수행준거 {u.get('n_covered', 0)}/{u.get('n_total', 0)} ≥1 · 평균 {u['mean']:.2f}"
    return f"요소 {u.get('n_covered', 0)}/{u.get('n_total', 0)} 인정"

def unit_rule_text(rb, short: bool = False) -> str:
    """능력단위 판정 규칙을 rubric(track_b.unit_rule) 값 그대로 한 문장으로. 화면 문구는 전부 이것을 쓴다."""
    ur = (getattr(rb, "track_b", None) or {}).get("unit_rule") or {}
    acc, hold = float(ur.get("accept_mean", 1.5)), float(ur.get("hold_mean", 1.0))
    zero = bool(ur.get("require_all_nonzero", True))
    if short:
        return (f"0 이 하나라도 있으면 불인정, 전부 1 이상이면 평균 {acc:.1f} 이상 인정·{hold:.1f} 이상 보류" if zero
                else f"수행준거 점수 평균 {acc:.1f} 이상 인정·{hold:.1f} 이상 보류·미만 불인정")
    return (f"0 인 수행준거가 하나라도 있으면 불인정 · 전부 1 이상이고 평균 {acc:.1f} 이상이면 인정 · 평균 {hold:.1f} 이상이면 보류" if zero
            else f"수행준거 점수(0·1·2)의 평균이 {acc:.1f} 이상이면 인정 · {hold:.1f} 이상이면 보류 · 미만이면 불인정 (0 인 수행준거가 있어도 평균으로 본다)")



# 근거를 보이는 순서 — 공신력 높은 자료가 위로 (4차 TF 의견 9, 2026-10-02).
# 등급(A→E)이 먼저, 같은 등급 안에서는 이 순서, 그 다음 적합도(직접→간접→부정).
DOC_PRIORITY = [
    "국가기술자격증", "직무능력인정서", "사업주자격증_정부인정",
    "학위·성적증명서", "4대보험_가입내역",
    "NCS기반_훈련이수증", "교육과정_편성표",
    "사내·기관_교육이수내역", "강의계획서", "비NCS_교육수료증", "경력증명서", "사업주자격증",
    "포트폴리오·산출물", "작업일지·업무일지",
    "제3자_확인서",
    "경력기술서·자기소개서",
    "기타",
]
GRADE_RANK = {g: i for i, g in enumerate("ABCDE")}
FIT_RANK = {"직접": 0, "간접": 1, "부정": 2}


def evidence_sort_key(grade: str | None, doc_type: str | None, fit: str | None) -> tuple:
    """정렬 열쇠. 모르는 등급·종류·적합도는 맨 뒤."""
    return (GRADE_RANK.get((grade or "").upper()[:1], 9),
            DOC_PRIORITY.index(doc_type) if doc_type in DOC_PRIORITY else len(DOC_PRIORITY),
            FIT_RANK.get(fit or "직접", 9))
