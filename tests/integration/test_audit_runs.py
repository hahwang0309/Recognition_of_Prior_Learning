"""판정을 여러 번 돌렸을 때 감사 화면이 실행을 갈라 보여 주는가.

판정을 다시 돌리면 산출물이 한 벌 더 쌓인다. 실행을 갈라 보여 주지 않으면
어느 파일이 어느 실행의 것인지 알 수 없다 — 실측으로 같은 이름이 세 번씩
나와 「호출실패」가 한 번인지 세 번인지 구분되지 않았다.

감사 가능성이 이 앱의 요구사항이므로 여기서 잡는다.
"""
from __future__ import annotations

import re

import pytest
from sqlalchemy import text

from krpl_core.db import session_scope
from services.report import render_audit_case

CASE = "R2026-9070"


@pytest.fixture
def three_runs():
    """한 접수 건에 판정 세 벌과 그 산출물을 만든다."""
    with session_scope() as s:
        s.execute(text("DELETE FROM submission WHERE case_number=:c"), {"c": CASE})
        sid = s.execute(text("""
            INSERT INTO submission (case_number, track, target_program_id, status)
            VALUES (:c, 'B', '양식조리_L4', 'needs_review') RETURNING id"""),
            {"c": CASE}).scalar_one()
        # 수집 산출물 — 실행과 무관하다
        s.execute(text("""
            INSERT INTO artifact (submission_id, assessment_id, stage, seq, name,
                                  path, sha256, n_bytes, note)
            VALUES (:i, NULL, 'ingest', 1, '조각', '/x', :h, 100, '수집')"""),
            {"i": sid, "h": "a" * 64})
        aids = []
        for n in range(3):
            aid = s.execute(text("""
                INSERT INTO assessment (submission_id, kind, status, rubric_version,
                                        model, attempts, started_at, finished_at)
                VALUES (:i, 'evidence', 'manual_review', 'v0.2', 'test', 18,
                        now(), now()) RETURNING id"""), {"i": sid}).scalar_one()
            aids.append(aid)
            for stage, name in (("package", "AI입력패키지"), ("llm", "01_호출실패"),
                                ("validate", "검증결과")):
                s.execute(text("""
                    INSERT INTO artifact (submission_id, assessment_id, stage, seq,
                                          name, path, sha256, n_bytes, note)
                    VALUES (:i, :a, :st, 1, :n, '/x', :h, 100, '')"""),
                    {"i": sid, "a": aid, "st": stage, "n": name, "h": "b" * 64})
    yield sid, aids
    with session_scope() as s:
        s.execute(text("DELETE FROM submission WHERE case_number=:c"), {"c": CASE})


def _page() -> str:
    with session_scope() as s:
        return render_audit_case(s, CASE)


def test_runs_are_separated(three_runs):
    h = _page()
    assert h.count('<details class="run"') == 3, "실행이 갈리지 않았다"


def test_the_newest_run_is_open_and_the_rest_are_folded(three_runs):
    h = _page()
    assert h.count('<details class="run" open>') == 1
    tags = re.findall(r'<span class="rtag">([^<]*)</span>', h)
    assert tags == ["최신", "1번 전", "2번 전"], tags


def test_each_run_is_labelled_with_what_it_was(three_runs):
    _, aids = three_runs
    h = _page()
    for aid in aids:
        assert f"판정 {aid}" in h, f"판정 {aid} 이 어디에도 없다"
    assert h.count("manual_review") >= 3, "실행마다 상태가 붙어야 한다"


def test_a_repeated_file_name_appears_once_per_run(three_runs):
    """같은 이름이 세 번 나오되, 각각 다른 실행 상자 안에 있어야 한다."""
    h = _page()
    assert h.count("01_호출실패") == 3
    for block in re.findall(r'<details class="run".*?</details>', h, re.S):
        assert block.count("01_호출실패") == 1


def test_collection_artifacts_are_not_repeated(three_runs):
    """수집은 접수 건에 딸린 것이라 실행마다 되풀이하지 않는다."""
    h = _page()
    assert h.count("① 문서 수집") == 1
    assert h.count(">조각<") == 1


def test_empty_stages_are_not_drawn_twice(three_runs):
    """②③④ 가 위에도 한 번, 실행 상자 안에도 한 번 — 빈 껍데기가 겹쳤다."""
    h = _page()
    for ko in ("② AI 입력 조립", "③ AI 분석", "④ 기계 검증"):
        assert h.count(ko) == 3, f"{ko} 가 {h.count(ko)}번 나온다 (실행 수만큼이어야)"
    # 파일이 없는 단계는 설명만 한 번
    for ko in ("⑤ 전문가 검토", "⑥ 최종 판정"):
        assert h.count(ko) == 1


def test_it_warns_that_the_case_was_judged_more_than_once(three_runs):
    _, aids = three_runs
    h = _page()
    assert "3번</b> 판정했습니다" in h
    assert f"최신 판정({max(aids)})" in h, "어느 것이 쓰이는지 말해야 한다"


def test_a_single_run_gets_no_warning():
    """한 번만 돌린 건에는 군더더기를 붙이지 않는다."""
    with session_scope() as s:
        cn = s.execute(text("""
            SELECT s.case_number FROM submission s
            JOIN assessment a ON a.submission_id = s.id AND a.kind='evidence'
            GROUP BY s.case_number HAVING count(*) = 1 LIMIT 1""")).scalar()
        if cn is None:
            pytest.skip("판정이 한 벌인 건이 없다")
        h = render_audit_case(s, cn)
    assert "판정했습니다" not in h
    assert h.count('<details class="run"') == 1
