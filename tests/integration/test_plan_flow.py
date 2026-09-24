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
    """입력 JSON 의 항목마다 방법에 맞는 문안을 만든다."""
    calls = 0

    def complete(self, turn, profile):
        FakeClient.calls += 1
        inp = json.loads(turn.messages[0]["content"])
        out = {"units": []}
        for u in inp["units"]:
            items = []
            for it in u["items"]:
                m = it["method"]
                if m == "면접":
                    items.append({"eid": it["eid"], "ref": it["ref"], "questions": [{"q": f"{it['name']}을 어떻게 했습니까", "answer_points": ["절차", "결과"]}]})
                elif m == "시연·구현":
                    items.append({"eid": it["eid"], "ref": it["ref"], "task": {"title": f"{it['name']} 시연", "deliverable": "화면 공유", "criteria": ["순서"], "minutes": 20}})
                else:
                    items.append({"eid": it["eid"], "ref": it["ref"], "topics": [f"{it['name']} 관련 문항"]})
            out["units"].append({"code": u["code"], "items": items})
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
        # 항목 목록: 미확인 항목만, 종류가 셋 중 하나
        for u in st["units"]:
            assert u["n_total"] >= u["n_covered"] and len(u["items"]) == u["n_total"] - u["n_covered"]
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
        assert "시험" in h and "시연·구현" in h and "면접" in h
        assert "어떻게 했습니까" in h or "시연" in h
    else:
        assert "보류 단위가 없습니다" in h
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
