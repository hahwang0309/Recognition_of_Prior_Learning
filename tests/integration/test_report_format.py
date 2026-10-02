"""보고서가 연구팀 확정 포맷을 벗어나지 않는지 원본과 대조한다.

원본은 `docs/formats/trackA_보고서.html` · `trackB_보고서.html` 이다.
회람·확정된 포맷이므로 보기 좋게 만들려고 임의로 바꾸면 안 된다.
바꿔야 할 이유가 생기면 원본과 구현을 같이 고치고 이 시험도 함께 고친다.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from krpl_core.db import session_scope
from services.report import render_track_a

FORMATS = Path(__file__).resolve().parents[2] / "docs/formats"
CASE = "R2026-0002"


@pytest.fixture(scope="module", autouse=True)
def demo_data():
    with session_scope() as s:
        if s.execute(text("SELECT 1 FROM submission WHERE case_number=:c"),
                     {"c": CASE}).first() is None:
            sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
            try:
                import load_demo
                load_demo.load()
            except FileNotFoundError as ex:
                pytest.skip(f"실사례 원본 없음: {ex}")


def _origin(name: str) -> str:
    p = FORMATS / name
    if not p.exists():
        pytest.skip(f"확정 포맷 원본 없음: {p}")
    return p.read_text(encoding="utf-8")


def _rendered(kind: str = "time") -> str:
    """확정 포맷과 대조할 화면. 지금은 기록 확인 보고서뿐이다 —
    Track B 회람본 보고서는 2026-09-24 에 앱에서 걷어냈다."""
    with session_scope() as s:
        aid = s.execute(text("""
            SELECT a.id FROM assessment a JOIN submission s ON s.id=a.submission_id
            WHERE s.case_number=:c AND a.kind=:k AND a.status='done'
            ORDER BY a.id DESC LIMIT 1"""), {"c": CASE, "k": kind}).scalar()
        if aid is None:
            pytest.skip(f"{kind} 판정 없음")
        return render_track_a(s, aid)


# 원본과 구현 양쪽에 다 있어야 하는 구조.
# 값이 re.Pattern 이면 검색, 문자열이면 그대로 포함 여부를 본다.
# 「메타문자가 있으면 정규식」으로 추측했다가 `.` 를 문자열로 읽어 헛통과할 뻔했다.
TRACK_A = {
    "가로 막대 행": re.compile(r'<div class="row" title="[^"]+">', re.S),
    "능력단위 코드": re.compile(r'<div class="nm"><span class="code">\d+</span>', re.S),
    "막대 채움": re.compile(r'<div class="fill (good|warn|hold|crit|none)" style="width:[\d.]+%"></div>', re.S),
    "−50% 하한 점선": re.compile(r'<div class="minl" style="left:[\d.]+%"></div>', re.S),
    "요구시간 실선": re.compile(r'<div class="reql" style="left:[\d.]+%"><span class="reqv">\d+h</span></div>', re.S),
    "시간 표기": re.compile(r'<div class="hrs"><b>[^<]*</b><span>/\d+h</span>(<em[^>]*>[^<]*</em>)?</div>', re.S),  # 2026-09-23 인정시간 줄 추가
    "아이콘+상태": re.compile(r'<div class="st (good|warn|hold|crit|none)"><i>[●▲◆■○]</i>', re.S),
    "누적 막대": re.compile(r'<div class="sg (good|warn|hold|crit|none)" style="width:[\d.]+%"', re.S),
    "KPI 강조": '<div class="kpi hl">',
    # 「범례」는 2026-09-23 요청으로 뺐다 — 위원이 볼 것은 인정·보류·불인정 카드와 막대뿐이다.
    "데이터 표": '<summary>데이터 표로 보기</summary>',
    "카드": '<section class="card">',
    "카드 머리": '<header class="ch">',
}

TRACK_B = {
    "히트맵 열머리": re.compile(r'<th><div class="un">.*?</div><div class="uh">\d+h</div></th>', re.S),
    "히트맵 행머리": re.compile(r'<th class="rl">요소 \d+</th>', re.S),
    "칸 title": re.compile(r'<td class="hc r\d" title="[^"]+ — R\d [^"]*">', re.S),
    "칸 아이콘+이름": re.compile(r'<span class="hi">.</span><span class="hn">', re.S),
    "빈 칸": '<td class="hc empty"></td>',
    "보완계획 요약": '<div class="psum">',
    "서류 대체 강조": '<div class="hl"><b>',
    "대체서류 안내": '<div class="alt">↳ 대체서류 제출 시 면제:',
    "요소 카드": re.compile(r'<details class="el r\d"><summary><span class="badge r\d"><i>.</i>R\d</span>', re.S),
    "증거 인용": '<blockquote>',
    # 원본은 .kt 칸에 KSA 이름을 넣는다. 내가 판단 이유를 잘라 넣고 있었다.
    "증거 머리 KSA 이름": re.compile(
        r'<div class="evh"><b>(?:기술|지식|태도)\d+</b> <span class="kt">[^<]+</span>'),
    "소속·기간 보증": '<div class="pb"><b>소속·기간 보증</b>',
    "증명·비어있음": '<p class="dims"><b>증명됨</b>',
    "제출 문서 표": '<table class="docs">',
    "신뢰도 등급 배지": re.compile(r'<span class="g[ABCDE]">', re.S),
}


def _has(h: str, pat) -> bool:
    return bool(pat.search(h)) if isinstance(pat, re.Pattern) else pat in h


@pytest.mark.parametrize("name", sorted(TRACK_A))
def test_track_a_keeps_confirmed_markup(name):
    pat = TRACK_A[name]
    origin, mine = _origin("trackA_보고서.html"), _rendered("time")
    assert _has(origin, pat), f"원본에 「{name}」 이 없다 — 시험 쪽이 틀렸다"
    assert _has(mine, pat), f"구현이 확정 포맷의 「{name}」 을 잃었다"


PANEL = {
    "카드 3장": re.compile(r'id="k-rec".*id="k-hold".*id="k-rej"', re.S),
    "3점표": '<table class="tp">',
    # 긴 설명 문단은 2026-09-24 뺐다 — 제목이 할 일을 말한다.
    "수행준거별 점수": "<h2>수행준거별 점수(위원 판정 필요)</h2>",
    "점수 정의": "2 = 직접 근거 있음 · 1 = 간접 근거만 · 0 = 근거 없음 또는 부정 진술",
    "파라미터 표": "판정 파라미터 — 위원 논의로 수정 가능",
    "문서 열람창": 'id="dv"',
    "방법론 코드 없음": None,
}


@pytest.mark.parametrize("name", sorted(PANEL))
def test_track_b_panel_has_the_agreed_sections(name):
    """1~3차 TF 가 요구한 것: 세 묶음 카드 · 능력단위 3점표 · 위원 판정 · 파라미터, 4차 TF: 수행준거 점수. R 코드는 안 보인다."""
    from services.report import render_panel
    with session_scope() as s:
        aid = s.execute(text("SELECT id FROM assessment WHERE kind='evidence' ORDER BY id DESC LIMIT 1")).scalar()
        if aid is None:
            pytest.skip("근거 분석 결과 없음")
        h = render_panel(s, aid)
    pat = PANEL[name]
    if pat is None:
        body = re.sub(r"<script>.*</script>", "", h, flags=re.S)
        body = re.sub(r"<[^>]+>", " ", body)
        assert not re.search(r"\bR[0-5]\b", body), "위원 화면에 R 코드가 보인다"
        assert not re.search(r"\bD\d{2}-[SP]\d+\b", body), "조각 번호가 풀리지 않고 보인다"
        assert "fid" not in body.lower().replace("confidence", "")
    else:
        assert _has(h, pat), f"위원 페이지에 「{name}」 이 없다"


# Track B 회람본 보고서(Ⅰ 히트맵·Ⅱ 보완계획·Ⅲ 요소별 판정 근거)를 원본과 대조하던
# 시험 넷은 뺐다 — 그 화면을 2026-09-24 에 앱에서 걷어냈기 때문이다. 단계줄이 옛
# 화면을 가리켜 「옛날 것으로 돌아갔다」가 된 뒤의 결정이다.
#
# 원본 `docs/formats/trackB_보고서.html` 은 연구 자료로 그대로 남아 있고, 위원
# 페이지가 확정 포맷을 지키는지는 위의 test_track_b_panel_has_the_agreed_sections
# 가 계속 본다.


def test_track_a_scale_is_shared_across_rows():
    """척도는 카드 안에서 공통이다 — 행마다 따로 잡으면 막대를 견줄 수 없다.

    같은 요구시간을 가진 두 행의 빨간 실선 위치가 같아야 한다.
    """
    h = _rendered("time")
    rows = re.findall(
        r'<div class="reql" style="left:([\d.]+)%"><span class="reqv">(\d+)h</span>', h)
    by_req: dict[str, set[str]] = {}
    for left, req in rows:
        by_req.setdefault(req, set()).add(left)
    bad = {k: v for k, v in by_req.items() if len(v) > 1}
    assert not bad, f"같은 요구시간인데 실선 위치가 다르다: {bad}"


def test_track_a_colour_is_never_the_only_signal():
    """적록색약에서 초록·빨강은 ΔE 4.1 로 구분이 어렵다.
    그래서 모든 막대에 아이콘과 상태 텍스트를 함께 둔다."""
    h = _rendered("time")
    marks = re.findall(r'<div class="st (\w+)"><i>([●▲◆■○])</i>([^<]+)</div>', h)
    fills = re.findall(r'<div class="fill (?!cred)(\w+)"', h)   # cred = 인정시간 층(2026-09-23), 상태 막대가 아니다
    assert len(marks) == len(fills), "아이콘·상태 텍스트가 없는 막대가 있다"
    assert all(ico and word.strip() for _, ico, word in marks)
