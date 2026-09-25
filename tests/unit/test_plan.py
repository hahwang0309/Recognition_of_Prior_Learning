"""확인 계획 — 방법 배정 규칙과 시험 목록 (2026-09-24)."""
from __future__ import annotations

from pathlib import Path

import yaml

from services.review.plan import _check, assign, build_plan_input, exams_for, load_exams


def _items():
    return [{"ref": "지식1", "kind": "지식", "name": "도면 작성기준"},
            {"ref": "기술2", "kind": "기술", "name": "BIM 모델링"},
            {"ref": "태도1", "kind": "태도", "name": "꼼꼼함"}]


def test_assign_by_kind_and_exam_availability():
    """지식 → 시험(시험이 있을 때) 아니면 면접 · 기술 → 시연·구현 · 태도 → 면접."""
    g = assign(_items(), has_exam=True)
    assert [i["ref"] for i in g["시험"]] == ["지식1"]
    assert [i["ref"] for i in g["시연·구현"]] == ["기술2"]
    assert [i["ref"] for i in g["면접"]] == ["태도1"]
    g2 = assign(_items(), has_exam=False)
    assert g2["시험"] == [] and [i["ref"] for i in g2["면접"]] == ["지식1", "태도1"]


def test_exams_yaml_is_keyed_by_ncs_subcategory_and_marks_unverified_links(tmp_path: Path):
    ex = load_exams()
    assert "14030104" in ex and ex["14030104"]["name"] == "실내건축설계"
    for code, v in ex.items():
        assert len(code) == 8 and code.isdigit()
        for x in v.get("exams") or []:
            # 링크는 확인한 것만 — 없으면 note 에 「미확인」이 있어야 한다
            assert x.get("url") or "미확인" in (x.get("note") or ""), (code, x)
    assert exams_for("1403010408", ex) == ex["14030104"]["exams"]
    assert exams_for("9999999999", ex) == []
    # 파일이 없으면 빈 dict
    assert load_exams(tmp_path / "없음.yaml") == {}


PC = [{"element": "계획설계도면 작성하기",
       "text": "계획안의 의도를 정확하게 파악하여 기획설계도면을 작성할 수 있다."},
      {"element": "기본설계도면 작성하기",
       "text": "확정된 기획설계도면에 대한 이해를 토대로 기본설계도면을 작성할 수 있다."},
      {"element": "실시설계도서 작성하기",
       "text": "실시설계도면을 근거로 하여 공사비 내역서를 작성할 수 있다."}]

INP = {"units": [{"code": "U1", "pc": PC, "items": [{"ref": "지식1", "kind": "지식"}]}]}


def _plan(**over):
    """통과하는 최소 산출물. 시험마다 한 군데씩 무너뜨려 본다."""
    base = {
        "interview": {
            "opening": ["어떤 규모의 일을 하셨습니까"],
            "sections": [{"unit": "U1", "focus": "도면을 직접 그렸나",
                          "questions": [{"q": "어디까지 직접 그리셨습니까",
                                         "answer_points": ["담당 범위"],
                                         "follow_up": "마감재는 어떻게 표기하셨습니까"}]}],
            "closing": ["더 익혀야 할 곳은"],
        },
        "practical": [
            {"title": "기획설계도면", "units": ["U1"], "basis": PC[0]["text"],
             "task": "t", "deliverable": "d", "criteria": ["c"], "minutes": 60},
            {"title": "기본설계도면", "units": ["U1"], "basis": PC[1]["text"],
             "task": "t", "deliverable": "d", "criteria": ["c"], "minutes": 90},
            {"title": "공사비 내역서", "units": ["U1"], "basis": PC[2]["text"],
             "task": "t", "deliverable": "d", "criteria": ["c"], "minutes": 90},
        ],
    }
    base.update(over)
    return base


def test_a_well_formed_plan_passes():
    assert _check(_plan(), INP) == []


def test_the_interview_must_cover_every_hold_unit():
    p = _plan()
    p["interview"]["sections"] = []
    errs = _check(p, INP)
    assert any("면접 절 누락: U1" in x for x in errs)


def test_every_question_needs_answer_points_and_a_follow_up():
    """반구조화의 핵심은 후속 질문이다 — 대답이 얕을 때 파고들 것."""
    p = _plan()
    q = p["interview"]["sections"][0]["questions"][0]
    q["follow_up"] = ""
    q["answer_points"] = []
    errs = _check(p, INP)
    assert any("답변 요지가 없다" in x for x in errs)
    assert any("후속 질문이 없다" in x for x in errs)


def test_practical_topics_must_be_three_to_five():
    assert any("3~5개" in x for x in _check(_plan(practical=_plan()["practical"][:2]), INP))
    six = (_plan()["practical"] * 2)[:6]
    assert any("3~5개" in x for x in _check(_plan(practical=six), INP))


def test_a_practical_topic_must_quote_a_real_performance_criterion():
    """지어낸 과제와 구별되는 유일한 표시다 — 원문과 대조한다."""
    p = _plan()
    p["practical"][0]["basis"] = "실내 공간을 아름답게 꾸밀 수 있다."     # 수행준거에 없는 문장
    assert any("수행준거 원문과 다르다" in x for x in _check(p, INP))


def test_two_topics_may_not_share_one_criterion():
    p = _plan()
    p["practical"][1]["basis"] = PC[0]["text"]
    assert any("같은 수행준거" in x for x in _check(p, INP))


def test_unknown_units_are_refused():
    p = _plan()
    p["practical"][0]["units"] = ["없는단위"]
    p["interview"]["sections"].append({"unit": "없는단위", "questions": []})
    errs = _check(p, INP)
    assert any("없는 단위" in x for x in errs)


def test_build_plan_input_takes_only_hold_units():
    st = {"case_number": "R2026-0000", "official_name": "건축설계_L3", "program": "건축설계_L3",
          "units": [{"code": "1403010408", "name": "A", "hours": 80, "verdict": "보류", "n_total": 3,
                     "elements": [{"eid": "E1", "name": "도면 작성하기", "ok": False},
                                  {"eid": "E2", "name": "검토하기", "ok": True}],
                     "items": [{"eid": "E1", "ref": "지식1", "kind": "지식", "name": "n",
                                "element": "도면 작성하기", "quotes": [], "prior": []}]},
                    {"code": "1403010108", "name": "B", "hours": 80, "verdict": "불인정",
                     "n_total": 3, "elements": [], "items": []}]}
    ex = {"14030104": {"name": "실내건축설계", "exams": [{"name": "X", "scope": "s"}]}}
    inp = build_plan_input(st, ex, {"1403010408": PC})
    assert [u["code"] for u in inp["units"]] == ["1403010408"]
    u = inp["units"][0]
    assert u["pc"] == PC, "수행준거가 실기 주제의 뼈대다 — 빠지면 근거 없이 지어낸다"
    assert u["counts"]["시험"] == 1, "항목 수는 집계로 남는다"
    assert [x["name"] for x in u["open_elements"]] == ["도면 작성하기"], \
        "확인 대상 요소만 넘긴다 — 이미 인정된 요소는 확인할 것이 없다"
    assert "method" not in u["items"][0], "항목별 문안을 더 받지 않는다"
    assert yaml.safe_dump(inp, allow_unicode=True)   # 직렬화 가능
