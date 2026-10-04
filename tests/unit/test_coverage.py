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


# ───────────────────────── 수행준거 점수 (신형, 2026-10-02) ─────────────────────────

def _pc(evs, decided_by=None, schema="pc"):
    """evs: [(pc_ref, fit)] → 신형 요소 payload."""
    p = {"schema": schema,
         "evidence": [{"pc_ref": r, "fids": [f"D01-P0{i % 9 + 1}"], "grade": "B", "fit": fit}
                      for i, (r, fit) in enumerate(evs)]}
    if decided_by:
        p["decided_by"] = decided_by
    return p


PCS3 = [{"ref": "준거1", "text": "a"}, {"ref": "준거2", "text": "b"}, {"ref": "준거3", "text": "c"}]


def test_pc_score_is_existence_based(rb):
    """직접 1건↑ → 2 · 간접만 → 1 · 없음 → 0 · 부정 → 0. 근거가 많아져도 내려가지 않는다."""
    from services.review.coverage import pc_score, is_pc_format
    p = _pc([("준거1", "직접"), ("준거1", "간접"), ("준거1", "간접"), ("준거1", "간접"),   # 직접 1 · 간접 3 → 2
             ("준거2", "간접"), ("준거2", "간접"),                                          # 간접만 → 1
             ("준거3", "직접"), ("준거3", "부정")])                                          # 부정 → 0
    assert is_pc_format(p)
    assert pc_score(p, "준거1", (), rb) == (2, "ai"), "간접이 과반이어도 직접이 있으면 2"
    assert pc_score(p, "준거2", (), rb) == (1, "ai")
    assert pc_score(p, "준거3", (), rb) == (0, "ai"), "부정 진술이 붙으면 0"
    assert pc_score(p, "준거9", (), rb) == (0, "ai"), "근거 없음"
    # 알 수 없는 fit 은 간접으로
    assert pc_score(_pc([("준거1", "간직")]), "준거1", (), rb) == (1, "ai")
    # 기이수(규칙) 요소는 전부 2
    assert pc_score(_pc([], decided_by="rule"), "준거1", (), rb) == (2, "rule")


def test_pc_override_by_reviewer(rb):
    from services.review.coverage import pc_score, pc_overrides
    p = _pc([("준거1", "직접")])
    assert pc_overrides(["pc:준거1=0", "pc:준거2=2", "pc:준거3=7", "add:기술1", "D01-P01"]) == {"준거1": 0, "준거2": 2}
    assert pc_score(p, "준거1", ["pc:준거1=0"], rb) == (0, "reviewer")
    assert pc_score(p, "준거2", ["pc:준거2=2"], rb) == (2, "reviewer")
    assert pc_score(p, "준거3", ["pc:준거3=7"], rb) == (0, "ai"), "어휘 밖 값은 무시"


def _rule(rb, **unit_rule):
    """판정 규칙만 바꾼 rubric 대역 — 규칙의 두 방식(0 조건 있음/없음)을 rubric 현재값과 무관하게 검증한다."""
    from types import SimpleNamespace
    tb = dict(rb.track_b); tb["unit_rule"] = unit_rule
    return SimpleNamespace(track_b=tb)


def test_unit_by_scores_rule_and_boundaries(rb):
    """0 조건 있는 방식(4차 TF 합의안): 모든 수행준거 ≥1 이고 평균 ≥1.5 인정 · ≥1.0 보류 · 0 이 하나라도 있으면 불인정."""
    from services.review.coverage import unit_by_scores
    rb = _rule(rb, require_all_nonzero=True, accept_mean=1.5, hold_mean=1.0)
    pcs = {"U_1.1": PCS3, "U_1.2": [{"ref": "준거1", "text": "d"}]}
    # [2,2,1,1] 평균 1.5 → 인정 (경계 포함)
    e1 = _pc([("준거1", "직접"), ("준거2", "직접"), ("준거3", "간접")]); e2 = _pc([("준거1", "간접")])
    r = unit_by_scores([("U_1.1", e1), ("U_1.2", e2)], rb, {}, pcs)
    assert (r["n_pc"], r["n_zero"], r["mean"], r["verdict"]) == (4, 0, 1.5, "인정")
    assert (r["n_covered"], r["n_total"], r["ratio"]) == (4, 4, 0.75), "구형 키 호환"
    # [2,1,1,1] 평균 1.25 → 보류
    e1b = _pc([("준거1", "직접"), ("준거2", "간접"), ("준거3", "간접")])
    assert unit_by_scores([("U_1.1", e1b), ("U_1.2", e2)], rb, {}, pcs)["verdict"] == "보류"
    # [2,2,2,0] 평균 1.5 지만 0 이 있어 불인정
    e1c = _pc([("준거1", "직접"), ("준거2", "직접"), ("준거3", "직접")]); e2c = _pc([])
    r3 = unit_by_scores([("U_1.1", e1c), ("U_1.2", e2c)], rb, {}, pcs)
    assert r3["verdict"] == "불인정" and r3["n_zero"] == 1
    # 위원이 그 0 을 1 로 올리면 [2,2,2,1] 평균 1.75 → 인정. 표시는 요소별 dict 로만 받는다
    r4 = unit_by_scores([("U_1.1", e1c), ("U_1.2", e2c)], rb, {"U_1.2": ["pc:준거1=1"]}, pcs)
    assert r4["verdict"] == "인정" and r4["scores"][-1]["src"] == "reviewer"
    with pytest.raises(TypeError):
        unit_by_scores([("U_1.1", e1c)], rb, ["pc:준거1=1"], pcs)
    # 수행준거가 없으면 불인정
    assert unit_by_scores([("U_1.1", e1c)], rb, {}, {})["verdict"] == "불인정"
    # [1,1,1,1] 평균 1.0 → 보류 (경계) · [1,1,1,0]… 는 위에서. 평균 1.0 미만은 0 없이는 불가능
    e_all1 = _pc([("준거1", "간접"), ("준거2", "간접"), ("준거3", "간접")])
    assert unit_by_scores([("U_1.1", e_all1), ("U_1.2", e2)], rb, {}, pcs)["verdict"] == "보류"


def test_unit_by_scores_mean_only_rule(rb):
    """0 조건 없는 방식(2026-10-04): 평균만 본다 — 0 이 있어도 평균 ≥ 문턱이면 인정."""
    from services.review.coverage import unit_by_scores
    rb = _rule(rb, require_all_nonzero=False, accept_mean=1.3, hold_mean=1.0)
    pcs = {"U_1.1": PCS3, "U_1.2": [{"ref": "준거1", "text": "d"}]}
    d3 = _pc([("준거1", "직접"), ("준거2", "직접"), ("준거3", "직접")]); none = _pc([]); ind = _pc([("준거1", "간접")])
    r = unit_by_scores([("U_1.1", d3), ("U_1.2", none)], rb, {}, pcs)          # [2,2,2,0] 1.5
    assert (r["verdict"], r["n_zero"], r["mean"]) == ("인정", 1, 1.5)
    d1 = _pc([("준거1", "직접"), ("준거2", "간접"), ("준거3", "간접")])
    assert unit_by_scores([("U_1.1", d1), ("U_1.2", ind)], rb, {}, pcs)["verdict"] == "보류"      # [2,1,1,1] 1.25 < 1.3
    d2 = _pc([("준거1", "직접"), ("준거2", "직접"), ("준거3", "간접")])
    assert unit_by_scores([("U_1.1", d2), ("U_1.2", ind)], rb, {}, pcs)["verdict"] == "인정"      # [2,2,1,1] 1.5
    assert unit_by_scores([("U_1.1", d2), ("U_1.2", none)], rb, {}, pcs)["verdict"] == "보류"     # [2,2,1,0] 1.25
    i3 = _pc([("준거1", "간접"), ("준거2", "간접"), ("준거3", "간접")])
    assert unit_by_scores([("U_1.1", i3), ("U_1.2", none)], rb, {}, pcs)["verdict"] == "불인정"   # [1,1,1,0] 0.75
    assert unit_by_scores([("U_1.1", d3)], rb, {}, {})["verdict"] == "불인정", "수행준거가 없으면 불인정"


def test_rubric_unit_rule_values(rb):
    """rubric 의 현재 출발값(2026-10-04): 0 조건 없음 · 평균 1.3 인정 · 1.0 보류. 바꾸면 문서(README·CLAUDE.md §3)도 함께."""
    ur = rb.track_b["unit_rule"]
    assert (ur["require_all_nonzero"], ur["accept_mean"], ur["hold_mean"]) == (False, 1.3, 1.0)


def test_old_format_is_not_pc(rb):
    from services.review.coverage import is_pc_format
    assert not is_pc_format(_p("R2", [("기술1", ["D05-P01"], "B")]))
    assert not is_pc_format({"evidence": []})
    assert is_pc_format({"schema": "pc", "evidence": []}), "근거 없는 신형 R5 는 schema 표시로 안다"
