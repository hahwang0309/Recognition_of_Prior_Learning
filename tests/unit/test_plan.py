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


def test_check_requires_every_item_with_the_right_field():
    inp = {"units": [{"code": "U1", "items": [{"eid": "E1", "ref": "지식1", "method": "면접"}, {"eid": "E1", "ref": "기술2", "method": "시연·구현"},
                                              {"eid": "E2", "ref": "지식1", "method": "시험"}]}]}   # 같은 번호가 요소마다 있다
    good = {"units": [{"code": "U1", "items": [
        {"eid": "E1", "ref": "지식1", "questions": [{"q": "어떻게 했나", "answer_points": ["a"]}]},
        {"eid": "E1", "ref": "기술2", "task": {"title": "모델 만들기", "criteria": ["c"]}},
        {"eid": "E2", "ref": "지식1", "topics": ["도면 기호"]}]}]}
    assert _check(good, inp) == []
    bad = {"units": [{"code": "U1", "items": [{"eid": "E1", "ref": "지식1", "questions": []}, {"eid": "E1", "ref": "기술9", "task": {"title": "x"}}]}]}
    errs = _check(bad, inp)
    assert any("면접 질문 없음" in x for x in errs) and any("없는 항목" in x for x in errs)
    assert any("항목 누락 E1/기술2" in x for x in errs) and any("항목 누락 E2/지식1" in x for x in errs)


def test_build_plan_input_takes_only_hold_units():
    st = {"case_number": "R2026-0000", "official_name": "건축설계_L3", "program": "건축설계_L3",
          "units": [{"code": "1403010408", "name": "A", "hours": 80, "verdict": "보류", "n_total": 3,
                     "items": [{"eid": "E1", "ref": "지식1", "kind": "지식", "name": "n", "element": "e", "quotes": [], "prior": []}]},
                    {"code": "1403010108", "name": "B", "hours": 80, "verdict": "불인정", "n_total": 3, "items": []}]}
    ex = {"14030104": {"name": "실내건축설계", "exams": [{"name": "X", "scope": "s"}]}}
    inp = build_plan_input(st, ex)
    assert [u["code"] for u in inp["units"]] == ["1403010408"]
    assert inp["units"][0]["items"][0]["method"] == "시험" and inp["units"][0]["exams"] == [{"name": "X", "scope": "s"}]
    assert yaml.safe_dump(inp, allow_unicode=True)   # 직렬화 가능
