"""검증기 단위시험 — 각 검사가 실제로 무엇을 잡는지 한 건씩 확인한다.

검증기는 AI 산출물을 믿지 않기 위해 있다. 그 검증기 자체가 헐거우면 의미가 없다.
"""
from __future__ import annotations

import copy

import pytest

from krpl_core.config import get_rubric
from krpl_rules import validate_track_b


@pytest.fixture(scope="module")
def rb():
    return get_rubric()


@pytest.fixture
def pkg():
    return {
        "applicant_id": "R2026-0001", "target_program": "제빵_L2",
        "documents": [{"doc_id": "D01", "grade": "B"}, {"doc_id": "D02", "grade": "E"}],
        "fragments": [
            {"fid": "D01-R01", "doc_id": "D01", "grade": "B",
             "text": "1301010101_20v1 반죽하기 60시간 · 내부평가 합격(90점)"},
            {"fid": "D02-S01", "doc_id": "D02", "grade": "E",
             "text": "밀가루 배합비를 계산해 반죽을 만들었습니다."},
            {"fid": "D02-S02", "doc_id": "D02", "grade": "E",
             "text": "발효실 온습도 관리는 담당한 바 없습니다."},
        ],
        "prior_learning": [],
        "ncs": {"program": "제빵_L2", "units": [{
            "unit_code": "1301010101", "unit_name": "반죽하기", "required_hours": 40,
            "elements": [{"element_id": "1301010101_20v1.1", "element_name": "배합하기",
                          "performance_criteria": [],
                          "ksa": [{"ref": "기술1", "text": "계량"},
                                  {"ref": "지식1", "text": "배합비"}]}]}]},
    }


@pytest.fixture
def good():
    """모든 검사를 통과하는 최소 산출물."""
    return {"applicant_id": "R2026-0001", "target_program": "제빵_L2",
            "prior_learning_review": "", "overall_note": "",
            "elements": [{
                "element_id": "1301010101_20v1.1",
                "evidence": [{"ksa_ref": "기술1", "fids": ["D02-S01"], "grade": "E",
                              "quote": "밀가루 배합비를 계산해", "why": "직접 수행 진술"}],
                "period_backing": {"fids": ["D01-R01"], "grades": ["B"], "note": "훈련기관 이수증"},
                "prior_learning": {"applies": False},
                "uncovered_ksa": [{"ref": "지식1", "status": "미확보"}],
                "remediation": [{"ksa_refs": ["지식1"], "method": "면접",
                                 "item": "배합비 산출 근거 확인", "reason": "진술만 있음"}],
                "negative_statements": [], "evidence_level": "부분",
                "proven_dimensions": ["수행내용"], "missing_dimensions": ["역량수준"],
                "source_grades": ["B", "E"], "negative_grades": [],
                "recommendation": "R2", "recommendation_reason": "면접 확인 필요",
                "verification_method": "화상면접",
                "qualitative_note": "배합 계산은 본인 진술로만 확인된다. 면접에서 한 번 물어보면 된다.",
                "conflicts": [], "confidence": "medium"}]}


def codes(pkg, out, rb, severity="error"):
    return validate_track_b(pkg, out, rb).by_code(severity)


def test_good_passes(pkg, good, rb):
    r = validate_track_b(pkg, good, rb)
    assert r.passed and r.n_elements == 1 == r.n_expected and r.n_evidence == 1
    assert r.counts["권고"] == {"R2": 1}


def test_missing_element(pkg, good, rb):
    good["elements"] = []
    assert codes(pkg, good, rb) == {"element_누락": 1}


def test_unknown_element(pkg, good, rb):
    good["elements"].append(copy.deepcopy(good["elements"][0]))
    good["elements"][1]["element_id"] = "9999999999_99v9.1"
    assert codes(pkg, good, rb)["element_없음"] == 1


def test_hallucinated_fid(pkg, good, rb):
    good["elements"][0]["evidence"][0]["fids"] = ["D09-S99"]
    c = codes(pkg, good, rb)
    assert c["fid_존재하지않음"] == 1 and "인용문_불일치" in c


def test_paraphrased_quote_caught(pkg, good, rb):
    """요약·의역은 잡아야 한다 — 원문에 그대로 없는 문장이다."""
    good["elements"][0]["evidence"][0]["quote"] = "밀가루 배합을 계산함"
    assert codes(pkg, good, rb) == {"인용문_불일치": 1}


def test_unknown_ksa_ref(pkg, good, rb):
    good["elements"][0]["evidence"][0]["ksa_ref"] = "기술9"
    c = codes(pkg, good, rb)
    assert c["ksa_ref_없음"] == 1 and c["KSA_합_불일치"] == 1


def test_ksa_must_be_fully_assigned(pkg, good, rb):
    """어느 쪽에도 없는 KSA 는 조용히 사라진 것이다."""
    good["elements"][0]["uncovered_ksa"] = []
    good["elements"][0]["remediation"] = []
    assert codes(pkg, good, rb) == {"KSA_합_불일치": 1}


def test_source_grades_must_match_actual(pkg, good, rb):
    good["elements"][0]["source_grades"] = ["A", "B", "E"]
    assert codes(pkg, good, rb) == {"source_grades_불일치": 1}


def test_source_grades_without_any_backing(pkg, good, rb):
    """뒷받침 자료가 하나도 없는데 등급을 선언하면 안 된다."""
    el = good["elements"][0]
    el["evidence"] = []
    el["period_backing"] = {"fids": [], "grades": [], "note": "없음"}
    el["uncovered_ksa"] = [{"ref": "기술1", "status": "미확보"},
                           {"ref": "지식1", "status": "미확보"}]
    el["remediation"][0]["ksa_refs"] = ["기술1", "지식1"]
    assert codes(pkg, good, rb) == {"source_grades_근거없음": 1}


def test_period_backing_grade_must_match_fid(pkg, good, rb):
    good["elements"][0]["period_backing"]["grades"] = ["A"]
    good["elements"][0]["source_grades"] = ["A", "E"]
    assert codes(pkg, good, rb) == {"pb_등급불일치": 1}


def test_negative_grades_split_from_source(pkg, good, rb):
    """반박 자료 등급을 뒷받침 칸에 넣으면 안 된다 (v4 오류 49건의 원인)."""
    el = good["elements"][0]
    el["negative_statements"] = [{"fid": "D02-S02", "quote": "담당한 바 없습니다"}]
    assert codes(pkg, good, rb) == {"negative_grades_불일치": 1}     # [] 로 선언
    del el["negative_grades"]
    assert codes(pkg, good, rb) == {"negative_grades_누락": 1}       # 칸 자체가 없음
    el["negative_grades"] = ["E"]
    assert codes(pkg, good, rb) == {}
    el["source_grades"] = ["B", "E", "E"]                           # 뒷받침 칸에 중복
    assert codes(pkg, good, rb) == {"source_grades_중복": 1}


def test_remediation_must_cover_uncovered(pkg, good, rb):
    good["elements"][0]["remediation"][0]["ksa_refs"] = ["기술1"]
    c = codes(pkg, good, rb)
    assert c["보완계획_불일치"] == 1


def test_face_to_face_at_most_one(pkg, good, rb):
    el = good["elements"][0]
    el["remediation"] = [
        {"ksa_refs": ["지식1"], "method": "면접", "item": "구술", "reason": "x"},
        {"ksa_refs": ["지식1"], "method": "실기", "item": "시연", "reason": "y"},
    ]
    assert codes(pkg, good, rb) == {"대면평가_중복": 1}


def test_r1_requires_ab_period_backing(pkg, good, rb):
    """본인진술(E) 단독으로는 R1 이 될 수 없다 — 기준서 철칙."""
    el = good["elements"][0]
    el["period_backing"] = {"fids": ["D02-S01"], "grades": ["E"], "note": "본인 진술"}
    el["source_grades"] = ["E"]
    el["recommendation"] = "R1"
    el["verification_method"] = "불필요"
    assert codes(pkg, good, rb)["R1철칙_위반"] == 1


def test_r1_flags_pending_rubric_decision(pkg, good, rb):
    """쟁점 4(KSA 커버리지 하한) 미확정 — 막지 않고 표시만 한다."""
    el = good["elements"][0]
    el["recommendation"] = "R1"
    el["verification_method"] = "불필요"
    r = validate_track_b(pkg, good, rb)
    assert r.by_code("warn") == {"기준미확정_R1": 1}
    assert r.passed, "경고는 판정을 막지 않는다"


def test_negative_statement_forces_r5(pkg, good, rb):
    good["elements"][0]["evidence_level"] = "부정진술"
    assert codes(pkg, good, rb)["R8_불일치"] == 1


def test_r0_requires_prior_learning(pkg, good, rb):
    el = good["elements"][0]
    el["recommendation"], el["verification_method"] = "R0", "불필요"
    c = codes(pkg, good, rb)
    assert c["R0_기이수없음"] == 1 and c["R0_보완계획존재"] == 1


def test_r0_downgrades_when_hours_short(pkg, good, rb):
    """이수시간이 요구시간의 50% 미만이면 R0 가 아니다."""
    el = good["elements"][0]
    el["recommendation"], el["verification_method"] = "R0", "불필요"
    el["uncovered_ksa"], el["remediation"] = [], []
    el["prior_learning"] = {"applies": True, "unit_code": "1301010101",
                            "completed_hours": 15, "required_hours": 40,
                            "evaluation": "내부평가 합격(90점)", "fid": "D01-R01"}
    assert codes(pkg, good, rb) == {"R0_시간미달": 1}


def test_r0_requires_evaluation_passed(pkg, good, rb):
    """편성표만 낸 경우 — 배웠다는 증거는 있어도 평가는 없다."""
    el = good["elements"][0]
    el["recommendation"], el["verification_method"] = "R0", "불필요"
    el["uncovered_ksa"], el["remediation"] = [], []
    el["prior_learning"] = {"applies": True, "unit_code": "1301010101",
                            "completed_hours": 60, "required_hours": 40,
                            "evaluation": "내부평가 미실시", "fid": "D01-R01"}
    assert codes(pkg, good, rb) == {"R0_평가미확인": 1}


def test_qualitative_note_required(pkg, good, rb):
    good["elements"][0]["qualitative_note"] = ""
    assert codes(pkg, good, rb) == {"정성소견_누락": 1}
    good["elements"][0]["qualitative_note"] = "확인 필요"
    assert codes(pkg, good, rb) == {"정성소견_부실": 1}


def test_enum_values_come_from_rubric(pkg, good, rb):
    good["elements"][0]["confidence"] = "아주높음"
    good["elements"][0]["verification_method"] = "전화"
    c = codes(pkg, good, rb)
    assert c == {"confidence_오류": 1, "verification_method_오류": 1}


def test_feedback_is_actionable(pkg, good, rb):
    good["elements"][0]["evidence"][0]["fids"] = ["D09-S99"]
    fb = validate_track_b(pkg, good, rb).feedback()
    assert "fid_존재하지않음" in fb and "D09-S99" in fb and "전체를 다시" in fb


def test_feedback_empty_when_passed(pkg, good, rb):
    assert validate_track_b(pkg, good, rb).feedback() == ""


# ── 출력 상한 ──
def test_truncation_is_detected():
    """상한에 걸려 끊긴 응답은 JSON 이 깨져 그 시도가 통째로 버려진다.
    실측에서 실제로 일어났다 — 조용히 실패하면 안 된다."""
    from krpl_core.llm import LLMResult
    ok = LLMResult(text="{}", model="m", output_tokens=38_000,
                   max_tokens=120_000, stop_reason="end_turn")
    cut = LLMResult(text="{", model="m", output_tokens=64_000,
                    max_tokens=64_000, stop_reason="max_tokens")
    assert not ok.truncated and ok.headroom == pytest.approx(0.683, abs=0.01)
    assert cut.truncated and cut.headroom == 0.0


def test_max_tokens_leaves_room_for_thinking():
    """설정된 상한이 실측 소요를 충분히 덮는가.
    실측(R2026-0002): 본문 약 38,000 + 사고 최대 20,000 토큰."""
    from krpl_core.config import get_model_profile
    p = get_model_profile()
    측정_최대 = 58_604
    assert p.max_tokens >= 측정_최대 * 1.5, (
        f"상한 {p.max_tokens:,} 이 실측 최대 {측정_최대:,} 의 1.5배에 못 미친다")
    assert p.max_tokens <= 128_000, "claude-opus-5 의 출력 한도는 128,000"
