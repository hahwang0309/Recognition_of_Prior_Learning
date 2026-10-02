"""위원 판정 제출 → 확인 계획 (2026-09-24).

시험 DB 의 시연 사례(R2026-0002)로 제출을 흉내 낸다. LLM 은 가짜 클라이언트 — 입력을 읽어 항목마다
방법에 맞는 문안을 돌려준다. 실제 호출은 없다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from krpl_core.db import session_scope
from services.report.track_b_plan import render_plan
from krpl_core.llm import LLMResult

CASE = "R2026-0002"


@pytest.fixture(scope="module", autouse=True)
def demo_data():
    with session_scope() as s:
        if s.execute(text("SELECT 1 FROM submission WHERE case_number=:c"), {"c": CASE}).first() is None:
            sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
            try:
                import load_demo
                load_demo.load()
            except FileNotFoundError as ex:
                pytest.skip(f"실사례 원본 없음: {ex}")


class FakeClient:
    """새 스키마로 답한다 — 면접 질문지 한 벌 + 실기 주제 3개.

    실기 주제의 `basis` 는 입력으로 받은 **수행준거 원문**을 그대로 쓴다.
    지어내면 기계 대조(`_check`)가 잡는다.
    """
    calls = 0

    def complete(self, turn, profile):
        FakeClient.calls += 1
        inp = json.loads(turn.messages[0]["content"])
        secs, practical = [], []
        for u in inp["units"]:
            secs.append({"unit": u["code"], "focus": f"{u['name']}을 직접 했나",
                         "questions": [{"q": f"{u['name']} 일을 어디까지 직접 하셨습니까",
                                        "answer_points": ["담당 범위", "결과"],
                                        "follow_up": "그때 어떤 기준을 따르셨습니까"}]})
            for pc in (u.get("pc") or []):
                if len(practical) >= 3:
                    break
                practical.append({"title": f"{pc['element'] or u['name']} 과제",
                                  "units": [u["code"]], "basis": pc["text"],
                                  "task": "주어진 조건으로 수행한다", "deliverable": "산출물 1건",
                                  "criteria": ["정확성", "기준 준수"], "minutes": 90})
        out = {"interview": {"opening": ["어떤 규모의 일을 하셨습니까"],
                             "sections": secs, "closing": ["더 익혀야 할 곳은"]},
               "practical": practical}
        body = json.dumps(out, ensure_ascii=False)
        return LLMResult(text=body, model="fake", output_tokens=len(body) // 3, cost_usd=0.01,
                         stop_reason="end_turn", max_tokens=profile.max_tokens)


def _aid():
    with session_scope() as s:
        return s.execute(text("""
            SELECT a.id FROM assessment a JOIN submission s ON s.id=a.submission_id
            WHERE s.case_number=:c AND a.kind='evidence' ORDER BY a.id DESC LIMIT 1"""), {"c": CASE}).scalar()


def test_submit_writes_snapshot_and_plan_then_page_renders():
    from services.review.plan import latest_plan, submit, unit_status
    aid = _aid()
    if aid is None:
        pytest.skip("근거 분석 결과 없음")
    with session_scope() as s:
        st = unit_status(s, aid)
        assert set(st["buckets"]) == {"인정", "보류", "불인정"} and st["units"]
        # 신형(2026-10-02): n_total 은 **수행준거 수**, n_covered 는 점수 ≥1. 확인 항목은 점수 < 2 인 수행준거,
        # 요소가 ok(전부 2점)이면 확인할 것이 없다. 구형이면 요소 수·항목 종류 규칙이 그대로다.
        for u in st["units"]:
            assert u["n_total"] >= u["n_covered"]
            open_eids = {x["eid"] for x in u["elements"] if not x.get("ok")}
            assert {it["eid"] for it in u["items"]} <= open_eids, "인정된 요소의 항목이 섞였다"
            if u.get("format") == "pc":
                assert u["n_total"] >= len(u["elements"]), "수행준거는 요소보다 적을 수 없다"
                assert all(it["kind"] == "준거" and it["score"] in (0, 1) for it in u["items"])
            else:
                assert u["n_total"] == len(u["elements"]), "구형은 요소를 센다"
                assert u["n_open_elements"] == u["n_total"] - u["n_covered"]
                assert all(it["kind"] in ("지식", "기술", "태도") for it in u["items"])
        plan = submit(s, aid, reviewer="시험위원", client=FakeClient())
        s.flush()
        n_hold = sum(1 for u in st["units"] if u["verdict"] == "보류")
        assert len(plan["input"]["units"]) == n_hold
        assert plan["ai_errors"] == [] and FakeClient.calls == (1 if n_hold else 0)
        rows = s.execute(text("SELECT stage, name, note FROM artifact WHERE assessment_id=:a AND stage IN ('panel','plan') ORDER BY stage"),
                         {"a": aid}).all()
        assert [r[0] for r in rows][-2:] == ["panel", "plan"] or {r[0] for r in rows} == {"panel", "plan"}
        assert latest_plan(s, aid)["submitted_at"] == plan["submitted_at"]
        assert s.execute(text("SELECT progress->>'panel_submitted_at' FROM assessment WHERE id=:i"), {"i": aid}).scalar()
    # 페이지
    from fastapi.testclient import TestClient
    from services.gateway.api import app
    h = TestClient(app).get(f"/assessments/{aid}/plan").text
    assert "확인 계획" in h and "판정 파라미터" in h
    body = re.sub(r"<[^>]+>", " ", h)
    assert not re.search(r"\bR[0-5]\b", body), "방법론 코드가 보인다"
    if n_hold:
        # 「시연·구현」은 「외부평가(대면 실기)」로 바뀌었다 (2026-09-24)
        assert "1. 시험" in h and "2. 면접" in h and "3. 외부평가" in h
        assert "반구조화" in h, "면접 질문지가 없다"
    else:
        assert "보류 단위가 없어 AI 문안" in h and "1. 시험" not in h, "보류 0 이면 AI 를 부르지 않았다고 말해야 한다"
    # 위원 페이지에 제출 시각이 붙는다
    p = TestClient(app).get(f"/assessments/{aid}/panel").text
    assert "마지막 제출" in p and f"/assessments/{aid}/plan" in p


def test_plan_page_before_submit_says_so():
    from services.report import render_plan
    with session_scope() as s:
        aid = s.execute(text("SELECT id FROM assessment WHERE kind='evidence' AND id NOT IN (SELECT assessment_id FROM artifact WHERE stage='plan') ORDER BY id LIMIT 1")).scalar()
        if aid is None:
            pytest.skip("미제출 판정 없음")
        assert "아직 위원 판정이 제출되지 않았습니다" in render_plan(s, aid)


PC1 = "확정된 기획설계도면에 대한 이해를 토대로 기본설계도면을 작성할 수 있다."
PC2 = "실시설계도면을 근거로 하여 공사비 내역서를 작성할 수 있다."
PC3 = "계획안의 의도를 정확하게 파악하여 기획설계도면을 작성할 수 있다."


def _made_plan():
    """보류 단위가 있는 확인 계획 하나. 화면만 보므로 손으로 만든다 —
    실사례에 보류 단위가 없으면 이 시험이 통째로 건너뛰어진다."""
    code = "1403010408"
    return {
        "submitted_at": "2026-09-24T22:00:00", "reviewer": "시험",
        "buckets": {"인정": 0, "보류": 80, "불인정": 240}, "total_hours": 320,
        "program": "건축설계_L3",
        "units": [{"code": code, "name": "건축설계 설계 도서작성", "hours": 80,
                   "verdict": "보류", "ratio": 0.35, "n_covered": 11, "n_total": 32}],
        "input": {"units": [{"code": code, "name": "건축설계 설계 도서작성", "hours": 80,
                             "n_uncovered": 21, "n_total": 32,
                             "counts": {"시험": 10, "면접": 6, "시연·구현": 5},
                             "open_elements": [{"eid": code + "_14v2.2", "name": "기본설계도면 작성하기"},
                                               {"eid": code + "_14v2.3", "name": "실시설계도서 작성하기"}],
                             # 같은 문장이 두 요소에 걸린 경우를 일부러 넣는다
                             "pc": [{"element": "기본설계도면 작성하기", "text": PC1},
                                    {"element": "실시설계도서 작성하기", "text": PC2},
                                    {"element": "계획설계도면 작성하기", "text": PC3},
                                    {"element": "기본설계도면 작성하기", "text": PC3}],
                             "items": [{"ref": "지식1", "kind": "지식", "name": "n",
                                        "element": "기본설계도면 작성하기", "quotes": []}]}]},
        "ai": {"interview": {"opening": ["어떤 규모의 일을 하셨습니까"],
                             "sections": [{"unit": code, "focus": "도면을 직접 그렸나",
                                           "questions": [{"q": "어디까지 직접 그리셨습니까",
                                                          "answer_points": ["담당 범위"],
                                                          "follow_up": "마감재는 어떻게 표기하셨습니까"}]}],
                             "closing": ["더 익혀야 할 곳은"]},
               "practical": [{"title": "기본설계도면", "units": [code], "basis": PC1,
                              "task": "t", "deliverable": "평면도 1매",
                              "criteria": ["치수 정확성"], "minutes": 120},
                             {"title": "공사비 내역서", "units": [code], "basis": PC2,
                              "task": "t", "deliverable": "내역서", "criteria": ["산출 근거"], "minutes": 90},
                             {"title": "기획설계도면", "units": [code], "basis": PC3,
                              "task": "t", "deliverable": "계획도", "criteria": ["동선"], "minutes": 60}]},
        "ai_errors": [], "usage": {"tries": 1, "cost_usd": 0.078},
    }


@pytest.fixture(autouse=True)
def _drop_made_plans():
    """손으로 만든 계획은 그 시험 안에서만 산다.

    남겨 두면 `latest_plan` 이 seq 가 큰 그것을 집어, 다른 시험이 자기 산출물을
    못 찾는다. 실제 제출이 만드는 seq 는 1부터 차례로 올라가므로 90 위는 전부
    손으로 만든 것이다 — 앞선 실행이 남긴 것까지 함께 지운다.
    """
    _purge()
    yield
    _purge()


def _purge():
    aid = _aid()
    if aid is None:
        return
    with session_scope() as s:
        s.execute(text("DELETE FROM artifact WHERE assessment_id=:a AND stage='plan' AND seq>=90"),
                  {"a": aid})


def _write_plan(aid: int, plan: dict, seq: int):
    from krpl_core.audit import AuditStore
    with session_scope() as s:
        r = s.execute(text("""SELECT sub.case_number, sub.id FROM assessment a
            JOIN submission sub ON sub.id = a.submission_id WHERE a.id=:i"""), {"i": aid}).first()
        AuditStore(s, r[0], r[1], aid).write("plan", "확인계획", plan, seq=seq)


def test_the_page_shows_three_sections_not_item_lists():
    """확인 계획은 「나열」이 아니라 위원이 들고 쓸 문서다.

    예전에는 지식 10개의 출제 범위, 기술 5개의 과제, 태도 8개의 질문을 하나씩
    늘어놓았다. 이제 시험 표 · 면접 질문지 한 벌 · 실기 주제 3~5개다.
    """
    aid = _aid()
    if aid is None:
        pytest.skip("근거 분석 결과 없음")
    _write_plan(aid, _made_plan(), seq=200)
    with session_scope() as s:
        h = render_plan(s, aid)

    order = [h.index("1. 시험"), h.index("2. 면접"), h.index("3. 외부평가")]
    assert order == sorted(order), "절 순서가 다르다 — 실기는 맨 아래다"

    # 항목이 한 줄씩 머리를 달고 나오던 옛 나열이 없어야 한다. 집계 문구
    # (「… 지식 3개」)는 남는다 — 그것이 무엇을 확인하는지 말해 주기 때문이다.
    assert not re.search(r">\s*(지식|기술|태도)\s*\d+\s*<", h), "항목별 나열이 남아 있다"
    assert "시험 범위 문안 없음" not in h

    assert "반구조화" in h and "↳" in h, "후속 질문이 화면에 없다"
    assert h.count("근거 수행준거") == 3, "실기 주제가 3개가 아니거나 근거가 없다"
    assert PC1 in h, "수행준거 원문이 그대로 보여야 한다"
    assert "RPL 단계에서 실기를 직접 보지 않습니다" in h
    assert "미확인" in h and "시험 10" in h, "보류 단위 요약(집계)은 남는다"


def test_a_plan_made_with_the_old_schema_says_so():
    """옛 저장본을 조용히 빈 화면으로 내밀지 않는다."""
    aid = _aid()
    if aid is None:
        pytest.skip("근거 분석 결과 없음")
    old = _made_plan()
    old["ai"] = {"units": [{"code": "1403010408", "items": []}]}     # 옛 스키마
    _write_plan(aid, old, seq=201)
    with session_scope() as s:
        h = render_plan(s, aid)
    assert "옛 형식" in h, "옛 저장본인데 아무 말이 없다"


def test_the_plan_says_which_unit_and_element_each_check_is_for():
    """「어느 능력단위의 어느 요소를 확인하는가」가 보여야 한다.

    셋 다 없으면 위원이 질문·과제가 어디에 쓰이는지 알 수 없다.
    """
    aid = _aid()
    if aid is None:
        pytest.skip("근거 분석 결과 없음")
    _write_plan(aid, _made_plan(), seq=202)
    with session_scope() as s:
        h = render_plan(s, aid)

    # ① 보류 단위 표 — 확인 대상 요소 이름
    assert "기본설계도면 작성하기" in h and "실시설계도서 작성하기" in h

    # ② 면접 절 머리
    assert "확인 대상 요소:" in h, "면접 절이 어느 요소를 보는지 말하지 않는다"

    # ③ 시험 — 어느 단위·요소의 지식인지
    assert "지식 1개" in h, "시험이 무엇을 확인하는지 말하지 않는다"

    # ④ 실기 — 단위 › 요소. 다만 같은 수행준거가 두 요소에 걸리면 단정하지 않는다
    assert "› 실시설계도서 작성하기" in h, "단정 가능한 요소를 안 적었다"
    amb = re.search(r"근거 수행준거 — " + re.escape(PC3), h)
    assert amb, "세 번째 주제가 없다"
    head = h[:amb.start()].rsplit("<h4>", 1)[-1]
    assert "›" not in head, "두 요소에 걸린 수행준거인데 요소를 단정했다"


def test_submitting_the_plan_takes_the_case_off_the_todo_list():
    """③ 확인 계획까지 나오면 Track B 흐름은 끝이다 — 할 일에서 내려온다.

    전에는 ①②③ 을 다 끝내도 접수가 「확인 필요」에 남아, 목록은 할 것이 있다고
    하는데 눌러 들어가면 할 것이 없었다.
    """
    aid = _aid()
    if aid is None:
        pytest.skip("근거 분석 결과 없음")
    from services.review.plan import submit
    with session_scope() as s:
        sid = s.execute(text("SELECT submission_id FROM assessment WHERE id=:a"),
                        {"a": aid}).scalar_one()
        before = s.execute(text("SELECT status FROM submission WHERE id=:i"),
                           {"i": sid}).scalar_one()
        s.execute(text("UPDATE submission SET status='needs_review' WHERE id=:i"), {"i": sid})
    try:
        with session_scope() as s:
            submit(s, aid, reviewer="시험", client=FakeClient())
        with session_scope() as s:
            after = s.execute(text("SELECT status FROM submission WHERE id=:i"),
                              {"i": sid}).scalar_one()
        assert after == "decided", f"제출했는데 「{after}」 에 남아 있다"
    finally:
        with session_scope() as s:
            s.execute(text("UPDATE submission SET status=:s WHERE id=:i"),
                      {"s": before, "i": sid})


def test_confirming_the_evidence_takes_it_off_needs_review():
    """「확인 완료」는 사람이 보고 넘어갔다는 뜻이다 — 그 상태에서 내려와야 한다."""
    from fastapi.testclient import TestClient
    from services.gateway.api import app
    aid = _aid()
    if aid is None:
        pytest.skip("근거 분석 결과 없음")
    with session_scope() as s:
        sid = s.execute(text("SELECT submission_id FROM assessment WHERE id=:a"),
                        {"a": aid}).scalar_one()
        before = s.execute(text("SELECT status FROM submission WHERE id=:i"),
                           {"i": sid}).scalar_one()
        rows = [dict(r) for r in s.execute(text("""SELECT id, status FROM assessment
            WHERE submission_id=:i AND kind='evidence'"""), {"i": sid}).mappings()]
        s.execute(text("UPDATE submission SET status='needs_review' WHERE id=:i"), {"i": sid})
        s.execute(text("""UPDATE assessment SET status='manual_review'
            WHERE submission_id=:i AND kind='evidence'"""), {"i": sid})
    try:
        r = TestClient(app).post(f"/submissions/{sid}/evidence/confirm", follow_redirects=False)
        assert r.status_code == 303
        with session_scope() as s:
            assert s.execute(text("SELECT status FROM submission WHERE id=:i"),
                             {"i": sid}).scalar_one() == "assessed"
    finally:
        with session_scope() as s:
            s.execute(text("UPDATE submission SET status=:s WHERE id=:i"), {"s": before, "i": sid})
            for x in rows:
                s.execute(text("UPDATE assessment SET status=:s WHERE id=:i"),
                          {"s": x["status"], "i": x["id"]})
            s.execute(text("""DELETE FROM audit_log WHERE action='evidence_confirmed'
                AND detail->>'submission_id' = :i"""), {"i": str(sid)})
