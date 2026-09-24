"""진행률을 적는 말과 읽는 말이 같은가.

판정은 한글 열쇠로 적는다 — `{"단계": "분석", "전체": 7, "완료": 3, "남은": [...]}`.
화면은 영어 열쇠(`total`·`done`·`phase`)로 읽고 있었다. 그래서 능력단위
일곱 개를 도는 내내 **「0/7」이 아니라 「0/1 능력단위」**라고 말했다.
멈춘 것처럼 보인다.

읽는 자리를 `Run.steps` 하나로 모았다. 여기서 두 쪽을 함께 붙든다.
"""
from __future__ import annotations

import inspect

from services.assess.case_state import Run
from services.assess import track_b_service as tb


def _run(progress: dict | None) -> Run:
    return Run(id=1, status="running", model=None, attempts=1, cost=None,
               started_at=None, finished_at=None, progress=progress)


def test_it_reads_what_the_judge_writes():
    got = _run({"단계": "분석", "전체": 7, "완료": 3,
                "남은": ["엔진본체 정비", "제동장치 정비"]}).steps
    assert got == (3, 7, "분석", ["엔진본체 정비", "제동장치 정비"])


def test_no_progress_yet_is_zero_of_zero():
    """아직 아무것도 안 적혔으면 0/0 이다. 1 로 채우면 「0/1」이 되어
    일곱 개짜리 판정이 한 개짜리로 보인다."""
    assert _run(None).steps == (0, 0, "분석 중", [])
    assert _run({}).steps[:2] == (0, 0)


def test_the_words_the_judge_writes_are_the_words_we_read():
    """`set_progress` 를 부르는 자리가 쓰는 열쇠말이 `steps` 가 읽는 것과
    같아야 한다. 어느 한쪽만 고치면 다시 갈라진다."""
    src = inspect.getsource(tb.run_track_b)
    for key in ("단계=", "전체=", "완료=", "남은="):
        assert key in src, f"판정이 {key} 를 안 적는다 — 화면이 읽을 것이 없다"


def test_the_screen_does_not_read_english_keys():
    """실측으로 이 두 자리가 영어 열쇠를 읽고 있었다."""
    from services.report import case_view
    from services.gateway import api
    for mod in (case_view, api):
        src = inspect.getsource(mod)
        for bad in ('get("done"', 'get("total"', 'get("phase"'):
            assert bad not in src, f"{mod.__name__} 이 아직 {bad} 를 읽는다"
