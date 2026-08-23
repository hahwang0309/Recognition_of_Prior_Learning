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
from services.report import render_evidence, render_track_a

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


def _rendered(kind: str) -> str:
    with session_scope() as s:
        aid = s.execute(text("""
            SELECT a.id FROM assessment a JOIN submission s ON s.id=a.submission_id
            WHERE s.case_number=:c AND a.kind=:k AND a.status='done'
            ORDER BY a.id DESC LIMIT 1"""), {"c": CASE, "k": kind}).scalar()
        if aid is None:
            pytest.skip(f"{kind} 판정 없음")
        return render_track_a(s, aid) if kind == "time" else render_evidence(s, aid)


# 원본과 구현 양쪽에 다 있어야 하는 구조.
# 값이 re.Pattern 이면 검색, 문자열이면 그대로 포함 여부를 본다.
# 「메타문자가 있으면 정규식」으로 추측했다가 `.` 를 문자열로 읽어 헛통과할 뻔했다.
TRACK_A = {
    "가로 막대 행": re.compile(r'<div class="row" title="[^"]+">', re.S),
    "능력단위 코드": re.compile(r'<div class="nm"><span class="code">\d+</span>', re.S),
    "막대 채움": re.compile(r'<div class="fill (good|warn|crit|none)" style="width:[\d.]+%"></div>', re.S),
    "−50% 하한 점선": re.compile(r'<div class="minl" style="left:[\d.]+%"></div>', re.S),
    "요구시간 실선": re.compile(r'<div class="reql" style="left:[\d.]+%"><span class="reqv">\d+h</span></div>', re.S),
    "시간 표기": re.compile(r'<div class="hrs"><b>[^<]*</b><span>/\d+h</span></div>', re.S),
    "아이콘+상태": re.compile(r'<div class="st (good|warn|crit|none)"><i>[●▲■○]</i>', re.S),
    "누적 막대": re.compile(r'<div class="sg (good|warn|crit|none)" style="width:[\d.]+%"', re.S),
    "KPI 강조": '<div class="kpi hl">',
    "범례": '<div class="lgd">',
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


@pytest.mark.parametrize("name", sorted(TRACK_B))
def test_track_b_keeps_confirmed_markup(name):
    pat = TRACK_B[name]
    origin, mine = _origin("trackB_보고서.html"), _rendered("evidence")
    assert _has(origin, pat), f"원본에 「{name}」 이 없다 — 시험 쪽이 틀렸다"
    assert _has(mine, pat), f"구현이 확정 포맷의 「{name}」 을 잃었다"


def test_track_b_has_three_chapters():
    h = _rendered("evidence")
    for chap in ("Ⅰ. 히트맵", "Ⅱ. 보완계획", "Ⅲ. 능력단위요소별 판정 근거"):
        assert chap in h, f"확정 포맷의 「{chap}」 이 빠졌다"


def test_heatmap_rows_run_high_to_low():
    """세로축은 요소 번호가 큰 것부터다. 원본이 그렇게 읽히도록 짜여 있다."""
    h = _rendered("evidence")
    nos = [int(n) for n in re.findall(r'<th class="rl">요소 (\d+)</th>', h)]
    assert nos and nos == sorted(nos, reverse=True), f"행 순서가 어긋남: {nos}"


def test_heatmap_columns_run_by_hours():
    """가로축은 요구시간이 큰 능력단위부터. 시간이 큰 쪽 판단이 더 크게 걸린다."""
    h = _rendered("evidence")
    hrs = [int(x) for x in re.findall(r'<div class="uh">(\d+)h</div>', h)]
    assert hrs and hrs == sorted(hrs, reverse=True), f"열 순서가 어긋남: {hrs}"


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
    marks = re.findall(r'<div class="st (\w+)"><i>([●▲■○])</i>([^<]+)</div>', h)
    fills = re.findall(r'<div class="fill (\w+)"', h)
    assert len(marks) == len(fills), "아이콘·상태 텍스트가 없는 막대가 있다"
    assert all(ico and word.strip() for _, ico, word in marks)
