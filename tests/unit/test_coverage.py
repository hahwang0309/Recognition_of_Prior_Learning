"""위원 화면의 커버리지·묶음·3점표 — 규칙만으로 계산되는가 (LLM 없음)."""
import pytest

from krpl_core.config import get_rubric
from services.review.coverage import element_bucket, element_coverage, three_point, unit_verdict
from services.review.time_axis import band, extract


@pytest.fixture
def rb():
    return get_rubric()


def _p(rec, ev, unc=(), neg=False):
    return {"recommendation": rec,
            "evidence": [{"ksa_ref": r, "fids": list(f), "grade": g} for r, f, g in ev],
            "uncovered_ksa": [{"ref": r} for r in unc],
            "negative_statements": [{"fid": "D10-S01"}] if neg else []}


def test_coverage_counts_each_ksa_once_and_excluded_drops_it():
    p = _p("R1", [("기술1", ["D01-P01"], "B"), ("기술1", ["D05-P02"], "B"), ("지식1", ["D07-P03"], "C")], unc=["지식2"])
    assert element_coverage(p) == (2, 3, pytest.approx(2 / 3))
    assert element_coverage(p, excluded=["D07-P03"]) == (1, 3, pytest.approx(1 / 3))
    # 같은 KSA 의 근거 둘 중 하나만 빼면 아직 덮여 있다
    assert element_coverage(p, excluded=["D01-P01"])[0] == 2


def test_bucket_folds_recommendations_and_demotes_r1_below_floor(rb):
    assert element_bucket(_p("R0", []), rb) == "인정후보"
    assert element_bucket(_p("R5", []), rb) == "미인정"
    assert element_bucket(_p("R3", []), rb) == "추가확인"
    p = _p("R1", [("기술1", ["D01-P01"], "B"), ("기술2", ["D01-P02"], "B")], unc=["지식1", "지식2"])
    assert element_bucket(p, rb) == "인정후보"                                 # 50% = 하한
    assert element_bucket(p, rb, excluded=["D01-P02"]) == "추가확인"           # 25% < 50%


def test_unit_verdict_all_elements_rule():
    assert unit_verdict(["인정후보", "인정후보"]) == "인정"
    assert unit_verdict(["인정후보", "추가확인"]) == "보류"
    assert unit_verdict(["인정후보", "미인정"]) == "불인정"
    assert unit_verdict([]) == "불인정"


def test_three_point_bands(rb):
    els = [_p("R1", [("기술1", ["D01-P01"], "A")], unc=["지식1"]),          # 50%
           _p("R2", [("기술1", ["D08-S01"], "D")], unc=["지식1", "지식2"], neg=True)]  # 33%
    r = three_point(els, rb)
    assert r["match"] == "중" and r["coverage"] == pytest.approx((0.5 + 1 / 3) / 2)
    assert r["verify"] == "상" and r["best_grade"] == "A" and r["negative"] is False   # 부정 진술 기준 삭제
    assert r["verdict"] == "보류"


def test_time_axis_reads_hours_and_months():
    frags = [{"fid": "D01-P04", "doc_type": "비NCS_교육수료증", "text": "과정명 | Revit 기반 BIM 실무 과정 (120시간)"},
             {"fid": "D05-P04", "doc_type": "경력증명서", "text": "근무기간 | 2023.03.02 ~ 현재 (3년 6개월)"}]
    from datetime import date
    ax = extract(frags, today=date(2026, 9, 23))
    assert ax["hours"] == 120 and ax["months"] == 42
    rb = get_rubric()
    assert band(320, ax, rb) == ("하", "120/320h")   # 37.5% < 50%
    assert band(200, ax, rb)[0] == "중"                                       # 60%
    assert band(100, ax, rb)[0] == "상"                                       # 120%
    assert band(320, {"months": 42}, rb) == ("상", "경력 3년 6개월 (교육시간 없음)")
    assert band(320, {}, rb) == ("하", "확인 불가")


def test_an_element_is_all_or_nothing_at_half(rb):
    """요소는 이분법이다 — 항목이 50% 이상이면 그 요소 **전체**를 인정한다.

    요소·항목에는 시간이 없다(NCS 원자료 확인). 시간으로 환산할 근거가 없으니
    충족 여부로 간다 — Data(20260812)/derived/README.md 의 설계안 그대로다.
    """
    from services.review.coverage import element_verdict
    half = _p("R2", [("기술1", ["D05-P01"], "B"), ("기술2", ["D07-P02"], "C")], unc=["지식1", "지식2"])
    ok, cov, tot, ratio = element_verdict(half, [], ["기술1", "기술2", "지식1", "지식2"], rb)
    assert (cov, tot) == (2, 4) and ratio == 0.5
    assert ok, "50% 는 포함이다"

    under = _p("R2", [("기술1", ["D05-P01"], "B")], unc=["지식1", "지식2"])
    ok2, cov2, tot2, _ = element_verdict(under, [], ["기술1", "지식1", "지식2"], rb)
    assert (cov2, tot2) == (1, 3) and not ok2, "33% 는 미인정"


def test_unit_counts_recognized_elements_not_an_average(rb):
    """단위는 **인정된 요소의 비율**로 본다. 예전에는 요소 비율의 평균이었다 —
    항목이 적은 요소가 과대 반영됐다(4차 자료 표 9 #3)."""
    from services.review.coverage import unit_by_coverage
    full = _p("R2", [("기술1", ["D05-P01"], "B"), ("기술2", ["D07-P02"], "C")], unc=[])       # 2/2 → 인정
    half = _p("R2", [("기술1", ["D05-P01"], "B")], unc=["지식1"])                              # 1/2 → 인정
    none = _p("R5", [], unc=["기술1", "지식1"])                                                # 0/2 → 미인정
    refs = {"U_1.1": ["기술1", "기술2"], "U_1.2": ["기술1", "지식1"],
            "U_1.3": ["기술1", "지식1"], "U_1.4": ["기술1", "지식1"]}

    r = unit_by_coverage([("U_1.1", full), ("U_1.2", half), ("U_1.3", none), ("U_1.4", none)], rb, refs_of=refs)
    assert (r["n_covered"], r["n_total"]) == (2, 4), "세는 것은 요소다"
    assert r["ratio"] == 0.5 and r["verdict"] == "인정", "인정 요소 50% 면 단위 인정"

    r2 = unit_by_coverage([("U_1.1", full), ("U_1.3", none), ("U_1.4", none)], rb, refs_of=refs)
    assert r2["ratio"] == pytest.approx(1 / 3) and r2["verdict"] == "보류", "33% 는 보류"

    r3 = unit_by_coverage([("U_1.3", none), ("U_1.4", none)], rb, refs_of=refs)
    assert r3["verdict"] == "불인정"


def test_unit_verdict_follows_recognized_items(rb):
    """항목 인정 → 커버리지 → 단위 판정. 근거를 빼면 내려가고, 위원이 항목을 직접 인정하면 올라간다.
    위원의 척도·질문 표시("s:", "q:")는 기록만 — 판정을 바꾸지 않는다."""
    from services.review.coverage import unit_by_coverage
    e1 = ("U_1.1", _p("R2", [("기술1", ["D05-P01"], "B"), ("기술2", ["D07-P02"], "C")], unc=["지식1"]))   # 2/3
    e2 = ("U_1.2", _p("R5", [], unc=["기술1", "지식1"]))                                                  # 0/2
    refs = {"U_1.1": ["기술1", "기술2", "지식1"], "U_1.2": ["기술1", "지식1"]}
    # 세는 것은 **요소**다 (2026-09-24 두 단계 게이트). e1 은 2/3(67%) → 요소 인정,
    # e2 는 0/2 → 미인정. 인정 요소 1/2 = 50% → 단위 인정.
    r = unit_by_coverage([e1, e2], rb, refs_of=refs)
    assert (r["n_covered"], r["n_total"]) == (1, 2) and r["ratio"] == 0.5 and r["verdict"] == "인정"
    # 위원이 근거 없는 항목 둘을 직접 인정 → e2 도 2/2 → 요소 2/2 → 인정
    r2 = unit_by_coverage([e1, e2], rb, excluded={"U_1.2": ["add:기술1", "add:지식1"]}, refs_of=refs)
    assert r2["n_covered"] == 2 and r2["verdict"] == "인정"
    # 근거를 빼면 내려간다 — 두 요소 다 0% → 인정 요소 0개
    r3 = unit_by_coverage([e1, e2], rb, excluded=["D05-P01", "D07-P02"], refs_of=refs)
    assert r3["n_covered"] == 0 and r3["verdict"] == "불인정"
    # 간접·부정 근거는 인정으로 세지 않는다 (2026-09-24). 위원이 「위원 인정」하면 올라간다
    ind = ("U_1.3", {"evidence": [{"ksa_ref": "기술1", "fids": ["D02-P01"], "grade": "B", "fit": "간접"},
                                  {"ksa_ref": "지식1", "fids": ["D10-S02"], "grade": "E", "fit": "부정"}], "uncovered_ksa": []})
    assert element_coverage(ind[1], [], ["기술1", "지식1"])[0] == 0
    assert element_coverage(ind[1], ["add:기술1"], ["기술1", "지식1"])[0] == 1
    # 척도·질문 표시는 기록용 — 판정 불변
    adds = {"U_1.2": ["add:기술1", "add:지식1", "s:match:하", "q:1:부"]}
    assert unit_by_coverage([e1, e2], rb, adds, refs)["verdict"] == "인정"
