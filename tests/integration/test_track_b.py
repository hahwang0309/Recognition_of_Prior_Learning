"""Track B 종단 시험 — 패키지 조립 → 판정 → 기계 검증 → 재요청 → 저장.

LLM 은 부르지 않는다. `ReplayClient` 가 실제 Opus 5 산출물(고정자료)을 돌려준다.
재요청 루프는 일부러 망가뜨린 산출물을 먼저 물려서 확인한다.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from krpl_core.config import get_model_profile, get_rubric
from krpl_core.db import session_scope
from krpl_core.llm import LLMError, ReplayClient, Turn
from krpl_rules import validate_track_b
from services.assess.package import build_package, package_hash, package_stats
from services.assess.track_b_service import run_track_b
from services.gateway.api import app

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/trackb"
CASES = ["R2026-0001", "R2026-0002", "R2026-0003", "R2026-0004"]


@pytest.fixture(scope="module", autouse=True)
def demo_data():
    """실사례 4건이 없으면 채워 넣는다. 시험 순서에 기대지 않기 위한 것."""
    with session_scope() as s:
        have = {r[0] for r in s.execute(text(
            "SELECT case_number FROM submission WHERE case_number = ANY(:c)"), {"c": CASES})}
    if set(CASES) - have:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        try:
            import load_demo
            load_demo.load()
        except FileNotFoundError as e:
            pytest.skip(f"실사례 원본 없음: {e}")


def sid_of(s, case: str) -> int:
    r = s.execute(text("SELECT id FROM submission WHERE case_number=:c"), {"c": case}).scalar()
    if r is None:
        pytest.skip(f"{case} 미적재 — ./scripts/dev.sh demo 실행 필요")
    return r


@pytest.fixture(scope="module")
def rb():
    return get_rubric()


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# ── 패키지 조립 ──
def test_package_matches_catalog():
    with session_scope() as s:
        pkg = build_package(s, sid_of(s, "R2026-0002"))
    st = package_stats(pkg)
    assert (st["n_units"], st["n_elements"]) == (10, 33)
    assert st["n_prior_learning"] == 4
    u = next(u for u in pkg["ncs"]["units"] if u["unit_code"] == "1601050111")
    assert u["required_hours"] == 70
    e = u["elements"][0]
    assert e["element_id"] == "1601050111_21v3.1"
    # KSA 는 수행준거마다 반복 수록된다 — 중복이 걷혔는지
    assert [k["ref"] for k in e["ksa"]] == [
        "기술1", "기술2", "기술3", "지식1", "지식2", "지식3", "지식4", "태도1", "태도2", "태도3"]
    assert len(e["performance_criteria"]) == 4


def test_package_hash_is_stable():
    with session_scope() as s:
        i = sid_of(s, "R2026-0002")
        a, b = package_hash(build_package(s, i)), package_hash(build_package(s, i))
    assert a == b and len(a) == 64


def test_package_carries_only_masked_text():
    with session_scope() as s:
        pkg = build_package(s, sid_of(s, "R2026-0002"))
    joined = " ".join(f["text"] for f in pkg["fragments"])
    assert "2025-02-11" in joined            # 작업일지 날짜는 살아 있어야 한다
    assert "***-**-*****" not in joined      # 주민번호 마스킹 흔적도 없어야 한다


# ── 고정자료 대조 ──
@pytest.mark.parametrize("case", CASES)
def test_real_outputs_pass_validation(case, rb):
    """프로토타입에서 실제로 나온 Opus 5 산출물이 지금 검증기도 통과하는가."""
    with session_scope() as s:
        pkg = build_package(s, sid_of(s, case))
    out = json.loads((FIXTURES / f"{case}.json").read_text(encoding="utf-8"))
    r = validate_track_b(pkg, out, rb)
    assert r.passed, r.by_code("error")
    assert r.n_elements == r.n_expected


def test_pending_rubric_decision_surfaces_as_warning(rb):
    """B004 에는 R1 요소가 5개 있다. 쟁점 4 확정 전이므로 표시되어야 한다."""
    with session_scope() as s:
        pkg = build_package(s, sid_of(s, "R2026-0004"))
    out = json.loads((FIXTURES / "R2026-0004.json").read_text(encoding="utf-8"))
    r = validate_track_b(pkg, out, rb)
    assert r.by_code("warn") == {"기준미확정_R1": 5} and r.passed


# ── 판정 실행 ──
# n_chunks 는 **AI 에 보내는** 청크 수다. 기이수(R0)로 확정된 능력단위는 빠진다.
@pytest.mark.parametrize("case,n_el,n_chunks,n_r0", [("R2026-0001", 27, 7, 0),
                                                     ("R2026-0002", 33, 6, 15),
                                                     ("R2026-0003", 23, 5, 9),
                                                     ("R2026-0004", 30, 9, 0)])
def test_run_stores_result(case, n_el, n_chunks, n_r0):
    """기이수는 코드가 확정하고, 나머지 능력단위만 AI 가 본다. 요소는 빠짐없이 합쳐진다."""
    with session_scope() as s:
        aid = run_track_b(s, sid_of(s, case), client=ReplayClient(FIXTURES))
        a = s.execute(text("""SELECT status, attempts, rubric_version, prompt_version,
                              input_hash, overall_note FROM assessment WHERE id=:i"""),
                      {"i": aid}).mappings().one()
        n = s.execute(text("SELECT count(*) FROM assessment_element WHERE assessment_id=:i"),
                      {"i": aid}).scalar_one()
        sub = s.execute(text("""SELECT status FROM submission WHERE id=(
                                SELECT submission_id FROM assessment WHERE id=:i)"""),
                        {"i": aid}).scalar_one()
    note = json.loads(a["overall_note"])
    assert a["status"] == "done" and n == n_el
    assert note["실행"]["기이수_코드확정"] == n_r0
    assert note["실행"]["청크"] == n_chunks and a["attempts"] == n_chunks
    assert len(note["청크별"]) == n_chunks and all(c["통과"] for c in note["청크별"])
    assert sum(c["요소"] for c in note["청크별"]) + n_r0 == n_el
    assert a["rubric_version"] == "0.2" and a["prompt_version"] and a["input_hash"]
    assert sub == "assessed"


def test_chunking_can_be_turned_off(monkeypatch):
    """`chunk_by: none` 이면 예전처럼 한 번에 부른다. 결과는 같아야 한다."""
    from krpl_core.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setattr(get_settings().assessment, "chunk_by", "none")
    with session_scope() as s:
        aid = run_track_b(s, sid_of(s, "R2026-0002"), client=ReplayClient(FIXTURES))
        a = s.execute(text("SELECT status, attempts, overall_note FROM assessment WHERE id=:i"),
                      {"i": aid}).mappings().one()
        n = s.execute(text("SELECT count(*) FROM assessment_element WHERE assessment_id=:i"),
                      {"i": aid}).scalar_one()
    note = json.loads(a["overall_note"])
    assert a["status"] == "done" and n == 33
    assert note["실행"]["분할"] == "none" and note["실행"]["청크"] == 1
    assert a["attempts"] == 1
    assert note["실행"]["기이수_코드확정"] == 15, "분할을 꺼도 기이수는 코드가 확정한다"
    get_settings.cache_clear()


def test_shared_material_goes_in_the_cached_blocks():
    """지원자 자료는 청크마다 반복되므로 캐시되는 자리(system)에 있어야 한다.
    user 메시지에 있으면 캐시가 안 먹어 입력이 4배로 뛴다."""
    from krpl_core.config import get_model_profile
    seen = {}

    class Spy:
        def complete(self, turn, profile):
            if turn.purpose == "assess":
                seen.setdefault("system", turn.system)
                seen.setdefault("user", turn.messages[-1]["content"])
            return ReplayClient(FIXTURES).complete(turn, profile)

    with session_scope() as s:
        run_track_b(s, sid_of(s, "R2026-0002"), client=Spy())
    sysall = "\n".join(seen["system"])
    assert "D01-R04" in sysall, "조각이 캐시 블록에 없다"
    assert "D01-R04" not in seen["user"], "조각이 user 에도 들어가 캐시가 무용해진다"
    assert re.search(r"\b16010502\d\d\b|\b16010501\d\d\b", seen["user"]), \
        "그 청크의 NCS 요구사항은 user 에 있어야 한다"
    assert len(seen["system"]) == len(get_model_profile().cache["blocks"]) == 3


def test_r0_only_when_evaluation_confirmed():
    """R2026-0001 은 편성표만 냈다 — 배운 기록은 있어도 평가는 없으므로 R0 가 없어야 한다.
    R2026-0002 는 내부평가 합격이 적혀 있어 R0 가 나온다."""
    got = {}
    with session_scope() as s:
        for case in ("R2026-0001", "R2026-0002"):
            aid = run_track_b(s, sid_of(s, case), client=ReplayClient(FIXTURES))
            got[case] = dict(s.execute(text("""
                SELECT recommendation, count(*) FROM assessment_element
                WHERE assessment_id=:i GROUP BY 1"""), {"i": aid}).all())
    assert "R0" not in got["R2026-0001"]
    assert got["R2026-0002"]["R0"] == 15


def test_conflicts_normalized():
    """상충 기록은 문장으로 오기도 하고 객체로 오기도 한다. 저장 시 한 모양으로 맞춘다."""
    with session_scope() as s:
        aid = run_track_b(s, sid_of(s, "R2026-0001"), client=ReplayClient(FIXTURES))
        rows = [r[0] for r in s.execute(text("""
            SELECT payload->'conflicts' FROM assessment_element
            WHERE assessment_id=:i AND jsonb_array_length(payload->'conflicts') > 0"""),
            {"i": aid})]
    assert rows
    for cl in rows:
        for c in cl:
            assert set(c) == {"topic", "adopted", "rejected", "note"}


# ── 재요청 루프 ──
def _break(out: dict) -> dict:
    """세 가지 전형적 실패를 심는다: 없는 fid · 사라진 KSA · 등급 칸 오기."""
    bad = copy.deepcopy(out)
    bad["elements"][0]["evidence"][0]["fids"] = ["D99-S99"]
    next(e for e in bad["elements"] if e["evidence"])["source_grades"] = ["A", "C", "D"]
    # KSA 전수 배정은 R0 요소에서는 검사하지 않는다 — 보완이 필요한 요소를 골라 지운다
    victim = next(e for e in bad["elements"]
                  if e["recommendation"] != "R0" and e["uncovered_ksa"])
    victim["uncovered_ksa"], victim["remediation"] = [], []
    return bad


class BreaksOneUnit:
    """지정한 능력단위의 **첫 응답만** 망가뜨린다. 나머지는 그대로 통과시킨다.

    청크 방식에서는 「몇 번째 호출인가」가 아니라 「어느 능력단위인가」로
    조작해야 한다 — 호출 순서가 동시 실행 때문에 정해져 있지 않다.
    """

    def __init__(self, unit_code: str, forever: bool = False):
        self.unit, self.forever = unit_code, forever
        self.hit = 0
        self.seen: list[str] = []

    def complete(self, turn, profile):
        from krpl_core.llm import LLMResult
        r = ReplayClient(FIXTURES).complete(turn, profile)
        user = turn.messages[-1]["content"]
        if self.unit not in user:
            return r
        self.seen.append(self.unit)
        if self.hit and not self.forever:
            return r
        self.hit += 1
        d = json.loads(r.text)
        # 없는 조각을 인용하게 만든다 — R0 요소에도 걸리는 오류라야
        # 어느 능력단위를 고르든 재현된다 (KSA 전수 검사는 R0 에서 건너뛴다).
        for e in d.get("elements") or []:
            if e.get("evidence"):
                e["evidence"][0]["fids"] = ["D99-S99"]
                break
        else:                                        # 근거가 없는 단위면 소견을 비운다
            if d.get("elements"):
                d["elements"][0]["qualitative_note"] = ""
        return LLMResult(text=json.dumps(d, ensure_ascii=False), model="claude-opus-5",
                         output_tokens=4000, cost_usd=0.12, stop_reason="end_turn",
                         max_tokens=profile.max_tokens)


@pytest.fixture
def retry_dir(tmp_path):
    good = json.loads((FIXTURES / "R2026-0002.json").read_text(encoding="utf-8"))
    (tmp_path / "R2026-0002.json").write_text(
        json.dumps(good, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def test_retry_only_reruns_the_broken_unit():
    """이게 청크로 나눈 가장 큰 이유다 — 틀린 능력단위만 다시 받는다.
    예전에는 요소 하나가 틀려도 33개를 통째로 다시 받았다."""
    UNIT = "1601050216"                       # 플럭스코어드와이어 맞대기 용접 (비기이수)
    with session_scope() as s:
        aid = run_track_b(s, sid_of(s, "R2026-0002"), client=BreaksOneUnit(UNIT))
        a = s.execute(text("SELECT status, attempts, overall_note FROM assessment WHERE id=:i"),
                      {"i": aid}).mappings().one()
        n = s.execute(text("SELECT count(*) FROM assessment_element WHERE assessment_id=:i"),
                      {"i": aid}).scalar_one()
    note = json.loads(a["overall_note"])
    retried = [c for c in note["청크별"] if c["시도"] > 1]
    assert a["status"] == "done" and n == 33
    assert len(retried) == 1, f"망가뜨린 단위 하나만 다시 받아야 한다: {retried}"
    assert "플럭스코어드와이어" in retried[0]["청크"]
    assert all(c["통과"] for c in note["청크별"])
    # 총 호출 = 청크 수 + 재시도분. 전체 재생성이 아니다.
    assert a["attempts"] == note["실행"]["청크"] + 1


def test_merged_result_is_revalidated_against_the_whole_package():
    """청크 하나가 끝내 실패하면 그 능력단위의 요소가 통째로 빠진다.
    합친 뒤 전체 패키지로 다시 검증해야 「무엇이 빠졌는지」가 기록에 남는다."""
    UNIT = "1601050113"                       # 피복아크용접 파이프용접 · 요소 2개
    with session_scope() as s:
        aid = run_track_b(s, sid_of(s, "R2026-0002"),
                          client=BreaksOneUnit(UNIT, forever=True))
        a = s.execute(text("SELECT status, overall_note FROM assessment WHERE id=:i"),
                      {"i": aid}).mappings().one()
        merged = s.execute(text("""SELECT errors FROM validation_log
                                   WHERE assessment_id=:i ORDER BY attempt DESC LIMIT 1"""),
                           {"i": aid}).scalar()
        n = s.execute(text("SELECT count(*) FROM assessment_element WHERE assessment_id=:i"),
                      {"i": aid}).scalar_one()
    note = json.loads(a["overall_note"])
    assert a["status"] == "manual_review"
    assert note["실행"]["미완료청크"] == ["R2026-0002/피복아크용접 파이프용접"], \
        "끝내 못 끝낸 청크를 숨기지 않는다"
    assert [c["통과"] for c in note["청크별"]].count(False) == 1
    # 통과 못 한 청크도 마지막 산출물은 남긴다 — 전문가가 볼 것이 없는 상태가 가장 나쁘다
    assert n == 33
    assert merged["청크"] == "합본"
    assert merged["by_code"], "합본 검증이 남은 문제를 그대로 보고해야 한다"
    assert not merged["passed"]


def test_exhausted_retries_go_to_manual_review(tmp_path):
    """끝내 통과 못 하면 확정하지 않는다. 다만 마지막 산출물은 남긴다 —
    전문가가 볼 것이 아무것도 없는 상태가 가장 나쁘다."""
    good = json.loads((FIXTURES / "R2026-0002.json").read_text(encoding="utf-8"))
    (tmp_path / "R2026-0002.json").write_text(
        json.dumps(_break(good), ensure_ascii=False), encoding="utf-8")
    with session_scope() as s:
        aid = run_track_b(s, sid_of(s, "R2026-0002"), client=ReplayClient(tmp_path))
        a = s.execute(text("SELECT status, attempts FROM assessment WHERE id=:i"),
                      {"i": aid}).mappings().one()
        n = s.execute(text("SELECT count(*) FROM assessment_element WHERE assessment_id=:i"),
                      {"i": aid}).scalar_one()
        sub = s.execute(text("""SELECT status FROM submission WHERE id=(
                                SELECT submission_id FROM assessment WHERE id=:i)"""),
                        {"i": aid}).scalar_one()
        n_log = s.execute(text("SELECT count(*) FROM validation_log WHERE assessment_id=:i"),
                          {"i": aid}).scalar_one()
    assert a["status"] == "manual_review" and sub == "needs_review"
    assert n == 33, "통과 못 해도 마지막 산출물은 남긴다"
    assert n_log >= 2, "청크별 + 합본 검증 기록이 남는다"


def test_replay_needs_matching_fixture(tmp_path):
    """재생할 산출물이 없으면 AI 청크는 전부 실패한다.
    다만 기이수(R0)는 코드가 확정하므로 그만큼은 남는다."""
    with session_scope() as s:
        aid = run_track_b(s, sid_of(s, "R2026-0002"), client=ReplayClient(tmp_path))
        st = s.execute(text("SELECT status FROM assessment WHERE id=:i"), {"i": aid}).scalar()
        n = s.execute(text("SELECT count(*) FROM assessment_element WHERE assessment_id=:i"),
                      {"i": aid}).scalar_one()
    assert st == "manual_review" and n == 15, "코드가 확정한 기이수만 남는다"

    # 기이수가 없는 건이라면 정말 아무것도 못 만든다
    with session_scope() as s:
        with pytest.raises(LLMError, match="모든 청크가 실패했습니다"):
            run_track_b(s, sid_of(s, "R2026-0001"), client=ReplayClient(tmp_path))


def test_refuses_without_fragments():
    with session_scope() as s:
        sid = s.execute(text("""
            INSERT INTO submission (case_number, track, target_program_id)
            VALUES ('R2026-0301','B','제빵_L2') RETURNING id""")).scalar_one()
        with pytest.raises(ValueError, match="조각이 없습니다"):
            run_track_b(s, sid, client=ReplayClient(FIXTURES))
        s.execute(text("DELETE FROM submission WHERE id=:i"), {"i": sid})


# ── API ──
def test_api_returns_track_b_shape(client):
    with session_scope() as s:
        aid = run_track_b(s, sid_of(s, "R2026-0002"), client=ReplayClient(FIXTURES))
    d = client.get(f"/assessments/{aid}").json()
    assert d["track"] == "B" and d["validation_passed"] is True
    assert d["status"] == "done" and d["attempts"] == 6   # 능력단위 10개 = 호출 10회
    assert len(d["elements"]) == 33
    assert [e["recommendation"] for e in d["elements"]] == sorted(
        e["recommendation"] for e in d["elements"])          # R0 부터 순서대로
    e0 = d["elements"][0]
    assert e0["recommendation"] == "R0" and e0["qualitative_note"]
    assert d["prior_learning_review"] and d["overall_note"]


def test_api_exposes_validation_history(client):
    """청크마다 한 줄, 마지막에 합본 한 줄. 어느 능력단위가 걸렸는지 보인다."""
    with session_scope() as s:
        aid = run_track_b(s, sid_of(s, "R2026-0002"),
                          client=BreaksOneUnit("1601050113", forever=True))
    v = client.get(f"/assessments/{aid}/validation").json()
    assert len(v) == 7, "AI 청크 6 + 합본 1"
    failed = [x for x in v if not x["passed"]]
    assert len(failed) == 2, "실패한 청크 1 + 합본 1"
    assert all(x["error_count"] > 0 and x["by_code"] for x in failed)
    assert failed[0]["issues"], "어느 요소가 왜 걸렸는지 남아야 한다"


def test_api_flags_expert_review(client):
    """미확정 기준(쟁점 4)에 걸린 요소는 개수로 드러나야 한다."""
    with session_scope() as s:
        aid = run_track_b(s, sid_of(s, "R2026-0004"), client=ReplayClient(FIXTURES))
    d = client.get(f"/assessments/{aid}").json()
    assert d["n_expert_review"] == 5
    assert sum(1 for e in d["elements"] if e["needs_expert_review"]) == 5


def test_assess_requires_documents(client):
    r = client.post("/submissions", json={"case_number": "R2026-0302", "track": "B",
                                          "target_program_id": "제빵_L2",
                                          "qualifications": ["제빵기능사"]})
    sid = r.json()["id"]
    assert client.post(f"/submissions/{sid}/assess").status_code == 409   # 조각 없음
    with session_scope() as s:
        s.execute(text("DELETE FROM submission WHERE id=:i"), {"i": sid})


def test_assess_enqueues_and_blocks_duplicates(client):
    with session_scope() as s:
        sid = sid_of(s, "R2026-0003")
        s.execute(text("DELETE FROM assessment WHERE submission_id=:i"), {"i": sid})
    r = client.post(f"/submissions/{sid}/assess")
    assert r.status_code == 202 and r.json()["kind"] == "track_b"
    with session_scope() as s:
        run_track_b(s, sid, client=ReplayClient(FIXTURES))
    assert client.post(f"/submissions/{sid}/assess").status_code == 409
    assert client.post(f"/submissions/{sid}/assess", json={"force": True}).status_code == 202


def test_replay_client_is_free():
    p = get_model_profile()
    res = ReplayClient(FIXTURES).complete(
        Turn(messages=[{"role": "user", "content": "심사번호 R2026-0002"}]), p)
    assert res.cost_usd == 0.0 and res.json()["target_program"] == "수동용접(CO2용접)_L4"


# ── 큐 ──
def test_worker_picks_up_track_b(monkeypatch):
    """API 가 넣은 작업을 워커가 집어 판정까지 마치는가."""
    from krpl_core.queue import dequeue, enqueue
    from services.assess import worker as w

    monkeypatch.setattr("services.assess.worker.run_track_b",
                        lambda s, sid, profile_name=None: run_track_b(
                            s, sid, client=ReplayClient(FIXTURES)))
    handlers = {"track_b": lambda s, p: w.run_track_b(s, p["submission_id"],
                                                      profile_name=p.get("profile"))}
    with session_scope() as s:
        sid = sid_of(s, "R2026-0001")
        s.execute(text("DELETE FROM assessment WHERE submission_id=:i"), {"i": sid})
        s.execute(text("DELETE FROM job WHERE kind='track_b'"))
        enqueue(s, "track_b", {"submission_id": sid})
    with session_scope() as s:
        job = dequeue(s, ["track_b"])
        assert job and job["payload"]["submission_id"] == sid
        aid = handlers[job["kind"]](s, job["payload"])
        st = s.execute(text("SELECT status FROM assessment WHERE id=:i"), {"i": aid}).scalar_one()
    assert st == "done"


# ── 해석 실패 ──
class _BrokenJSON:
    """JSON 이 깨진 응답을 돌려주는 가짜 클라이언트. 실호출에서 실제로 일어났다.

    n_broken=None 이면 계속 깨뜨린다.
    """
    def __init__(self, n_broken: int | None, good_dir=FIXTURES):
        self.n_broken, self.calls = n_broken, 0
        self.good = ReplayClient(good_dir)

    def complete(self, turn, profile):
        if turn.purpose != "assess":              # 보조 호출은 건드리지 않는다
            return self.good.complete(turn, profile)
        self.calls += 1
        if self.n_broken is None or self.calls <= self.n_broken:
            good = self.good.complete(turn, profile)
            from krpl_core.llm import LLMResult
            return LLMResult(text=good.text[:len(good.text) // 2], model="claude-opus-5",
                             output_tokens=9000, cost_usd=1.2, stop_reason="end_turn")
        return self.good.complete(turn, profile)


def test_unparseable_response_is_still_saved():
    """해석에 실패한 응답이야말로 원인을 봐야 할 물건이다.
    파싱 성공 후에 저장하면 바로 그 응답만 사라진다 — 실제로 그랬다."""
    from krpl_core.audit import read_artifact
    with session_scope() as s:
        sid = sid_of(s, "R2026-0002")
        aid = run_track_b(s, sid, client=_BrokenJSON(1))
        arts = {r["name"]: r["id"] for r in s.execute(text("""
            SELECT name, id FROM artifact WHERE assessment_id=:i AND stage='llm'"""),
            {"i": aid}).mappings()}
        broken = [n for n in arts if n.endswith("1차_AI응답")]
        failed = [n for n in arts if n.endswith("1차_해석실패")]
        assert broken and failed, f"깨진 응답도 남아야 한다: {sorted(arts)}"
        _, body = read_artifact(s, arts[broken[0]])
        # 해석되지 않는 원본이 손대지 않은 채 남았는가 — 그것이 이 시험의 요지다.
        # (자른 자리가 우연히 '}' 로 끝날 수 있으므로 글자로 판단하지 않는다)
        assert body
        with pytest.raises(json.JSONDecodeError):
            json.loads(body)
        st = s.execute(text("SELECT status, overall_note FROM assessment WHERE id=:i"),
                       {"i": aid}).mappings().one()
    note = json.loads(st["overall_note"])
    assert st["status"] == "done"
    assert sum(c["시도"] for c in note["청크별"]) > note["실행"]["청크"], "재시도가 있었다"


def test_all_attempts_unparseable_fails_cleanly():
    """끝까지 해석 못 하면 확정하지 않되, 원본은 전부 보존한다."""
    with session_scope() as s:
        sid = sid_of(s, "R2026-0002")
        aid = run_track_b(s, sid, client=_BrokenJSON(None))
        st = s.execute(text("SELECT status, attempts FROM assessment WHERE id=:i"),
                       {"i": aid}).mappings().one()
        n = s.execute(text("""SELECT count(*) FROM artifact WHERE assessment_id=:i
                              AND name LIKE '%AI응답'"""), {"i": aid}).scalar()
        cnt = s.execute(text("SELECT count(*) FROM assessment_element WHERE assessment_id=:i"),
                        {"i": aid}).scalar_one()
    assert n == 6 * 3, "AI 청크 6개 × 시도 3회 — 모든 원본이 남아야 한다"
    # AI 는 전부 실패했지만 코드가 확정한 기이수 15요소는 남는다
    assert st["status"] == "manual_review" and cnt == 15



# ── 기이수(R0) 결정론 ──
def test_r0_is_decided_by_code_not_ai():
    """같은 서류면 항상 같은 R0 여야 한다. AI 에 맡겼더니 15·15·12 로 갈렸다."""
    class NoR0:
        """AI 가 R0 를 절대 내지 않아도 결과의 R0 는 그대로여야 한다."""
        def complete(self, turn, profile):
            from krpl_core.llm import LLMResult
            r = ReplayClient(FIXTURES).complete(turn, profile)
            if turn.purpose != "assess":
                return r
            d = json.loads(r.text)
            for e in d.get("elements") or []:
                if e.get("recommendation") == "R0":
                    e["recommendation"] = "R5"
            return LLMResult(text=json.dumps(d, ensure_ascii=False), model="claude-opus-5",
                             stop_reason="end_turn", max_tokens=profile.max_tokens)

    with session_scope() as s:
        aid = run_track_b(s, sid_of(s, "R2026-0002"), client=NoR0())
        rec = dict(s.execute(text("""SELECT recommendation, count(*) FROM assessment_element
                                     WHERE assessment_id=:i GROUP BY 1"""), {"i": aid}).all())
        by = dict(s.execute(text("""SELECT element_id, payload->>'decided_by'
                                    FROM assessment_element WHERE assessment_id=:i"""),
                            {"i": aid}).all())
    assert rec["R0"] == 15, "AI 가 R0 를 안 내도 코드가 확정한다"
    assert sum(1 for v in by.values() if v == "rule") == 15
    assert sum(1 for v in by.values() if v != "rule") == 18


def test_r0_repeats_exactly():
    """세 번 돌려도 같은 요소가 R0 여야 한다."""
    seen = []
    for _ in range(3):
        with session_scope() as s:
            aid = run_track_b(s, sid_of(s, "R2026-0002"), client=ReplayClient(FIXTURES))
            seen.append({r[0] for r in s.execute(text(
                """SELECT element_id FROM assessment_element
                   WHERE assessment_id=:i AND recommendation='R0'"""), {"i": aid})})
    assert seen[0] == seen[1] == seen[2] and len(seen[0]) == 15


def test_r0_needs_evaluation_not_just_enrolment():
    """편성표만 낸 건은 배운 기록은 있어도 평가가 없다 — R0 가 하나도 없어야 한다."""
    with session_scope() as s:
        aid = run_track_b(s, sid_of(s, "R2026-0001"), client=ReplayClient(FIXTURES))
        rec = dict(s.execute(text("""SELECT recommendation, count(*) FROM assessment_element
                                     WHERE assessment_id=:i GROUP BY 1"""), {"i": aid}).all())
        note = json.loads(s.execute(text("SELECT overall_note FROM assessment WHERE id=:i"),
                                    {"i": aid}).scalar())
    assert "R0" not in rec
    assert note["기이수"]["요건충족_단위"] == []


def test_negation_sends_the_element_back_to_ai():
    """「그 자세는 담당한 바 없다」가 걸린 요소는 코드가 확정하지 않고 AI 에 넘긴다."""
    TARGET = "1601050111_21v3.3"           # 수직 자세 용접하기

    class Maps:
        def complete(self, turn, profile):
            from krpl_core.llm import LLMResult
            if turn.purpose == "negation":
                body = json.dumps({"affected": [
                    {"element_id": TARGET, "fid": "D06-S04", "quote": "담당한 바 없습니다",
                     "why": "수직 자세를 명시적으로 부정"}]}, ensure_ascii=False)
                return LLMResult(text=body, model="claude-opus-5", stop_reason="end_turn",
                                 max_tokens=profile.max_tokens)
            return ReplayClient(FIXTURES).complete(turn, profile)

    with session_scope() as s:
        aid = run_track_b(s, sid_of(s, "R2026-0002"), client=Maps())
        note = json.loads(s.execute(text("SELECT overall_note FROM assessment WHERE id=:i"),
                                    {"i": aid}).scalar())
        by = dict(s.execute(text("""SELECT element_id, payload->>'decided_by'
                                    FROM assessment_element WHERE assessment_id=:i"""),
                            {"i": aid}).all())
        n = s.execute(text("SELECT count(*) FROM assessment_element WHERE assessment_id=:i"),
                      {"i": aid}).scalar_one()
    assert note["실행"]["부정진술로_AI판정"] == [TARGET]
    assert note["실행"]["기이수_코드확정"] == 14, "15개 중 하나가 AI 로 넘어간다"
    assert by[TARGET] != "rule", "부정 진술이 걸린 요소는 사람이 읽을 판단으로 남긴다"
    assert n == 33, "그래도 요소는 빠짐없이 채워진다"


def test_negation_mapping_failure_is_conservative():
    """매핑에 실패하면 기이수 요소를 **전부** AI 로 돌린다.
    놓치고 확정하는 것보다 한 번 더 보는 편이 낫다."""
    class BadMapper:
        def complete(self, turn, profile):
            from krpl_core.llm import LLMError
            if turn.purpose == "negation":
                raise LLMError("일부러 실패")
            return ReplayClient(FIXTURES).complete(turn, profile)

    with session_scope() as s:
        aid = run_track_b(s, sid_of(s, "R2026-0002"), client=BadMapper())
        note = json.loads(s.execute(text("SELECT overall_note FROM assessment WHERE id=:i"),
                                    {"i": aid}).scalar())
        n = s.execute(text("SELECT count(*) FROM assessment_element WHERE assessment_id=:i"),
                      {"i": aid}).scalar_one()
    assert note["실행"]["기이수_코드확정"] == 0
    assert len(note["실행"]["부정진술로_AI판정"]) == 15
    assert note["기이수"]["부정진술_매핑"]["조치"] == "전부 AI 판정으로"
    assert n == 33


# ── 큐 견고성 ──
def test_missing_submission_fails_permanently():
    """접수 건이 지워졌는데 작업만 남은 경우. 세 번 더 돌려도 결과가 같다."""
    from krpl_core.queue import enqueue
    from krpl_core.worker import Worker
    with session_scope() as s:
        s.execute(text("DELETE FROM job WHERE kind='track_b'"))
        jid = enqueue(s, "track_b", {"submission_id": 999_999})
    Worker({"track_b": lambda s, p: run_track_b(s, p["submission_id"],
                                                client=ReplayClient(FIXTURES))}).run_once()
    with session_scope() as s:
        r = s.execute(text("SELECT status, attempts, last_error FROM job WHERE id=:i"),
                      {"i": jid}).mappings().one()
        s.execute(text("DELETE FROM job WHERE id=:i"), {"i": jid})
    assert r["status"] == "failed", "재시도해도 소용없는 실패는 바로 접는다"
    assert "접수 건이 없습니다" in r["last_error"]


def test_stale_job_is_reclaimed():
    """워커가 죽으면 작업이 잡힌 채 남는다. 다시 뜰 때 거둬야 한다 —
    실제로 8시간 넘게 방치된 적이 있다."""
    from krpl_core.queue import enqueue, reclaim_stale, stuck, worker_alive
    with session_scope() as s:
        # worker_alive 는 **큐 전체**를 본다. 다른 시험이 남긴 최근 작업이 있으면
        # 살아 있다고 나오므로, 이 시험만 두고 판단한다.
        s.execute(text("DELETE FROM job"))
        jid = enqueue(s, "track_b", {"submission_id": 1})
        s.execute(text("""UPDATE job SET status='running',
                          locked_at = now() - interval '90 minutes' WHERE id=:i"""),
                  {"i": jid})
    with session_scope() as s:
        assert not worker_alive(s), "90분 전 잠금은 살아 있는 것이 아니다"
        assert [j["id"] for j in stuck(s)] == [jid]
        assert reclaim_stale(s) == [jid]
    with session_scope() as s:
        r = s.execute(text("SELECT status, locked_at, last_error FROM job WHERE id=:i"),
                      {"i": jid}).mappings().one()
        assert not stuck(s)
        s.execute(text("DELETE FROM job WHERE id=:i"), {"i": jid})
    assert r["status"] == "queued" and r["locked_at"] is None
    assert "회수함" in r["last_error"]


# ── 진행 상황 ──
def test_progress_is_visible_while_running():
    """판정은 한 트랜잭션 안에서 돈다. 같은 세션으로 진행률을 적으면
    끝날 때까지 밖에서 아무것도 못 본다 — 화면이 12~28분을 「시작 중」으로 버텼다.
    판정 행을 먼저 커밋하고 진행률은 별도 세션에서 적어야 보인다."""
    import threading
    import time as _t

    class Slow:
        def complete(self, turn, profile):
            if turn.purpose == "assess":
                _t.sleep(0.4)
            return ReplayClient(FIXTURES).complete(turn, profile)

    with session_scope() as s:
        sid = sid_of(s, "R2026-0002")
    seen = []

    def watch():
        for _ in range(40):
            _t.sleep(0.15)
            with session_scope() as s:
                r = s.execute(text("""SELECT id, status, progress FROM assessment
                    WHERE submission_id=:i ORDER BY id DESC LIMIT 1"""),
                    {"i": sid}).mappings().first()
            if r and r["status"] == "running" and r["progress"]:
                seen.append(r["progress"])

    th = threading.Thread(target=watch, daemon=True)
    th.start()
    with session_scope() as s:
        aid = run_track_b(s, sid, client=Slow())
    th.join(timeout=3)

    assert seen, "판정이 도는 동안 진행 상황이 밖에서 보여야 한다"
    assert {p["단계"] for p in seen} <= {"분석", "종합", "대조"}
    done = [p["완료"] for p in seen]
    assert done == sorted(done) and max(done) >= 1, "완료 수가 늘어나야 한다"
    assert seen[0]["전체"] >= 1 and seen[0]["확정"] == 15
    with session_scope() as s:
        after = s.execute(text("SELECT progress, status FROM assessment WHERE id=:i"),
                          {"i": aid}).mappings().one()
    assert after["progress"] is None, "끝나면 진행률 칸을 비운다"
    assert after["status"] == "done"


def test_assessment_row_is_committed_before_the_run():
    """도중에 죽어도 흔적이 남아야 한다. 본 트랜잭션 안에서 만들면 아무것도 안 남는다."""
    class Boom:
        def complete(self, turn, profile):
            raise RuntimeError("일부러 터뜨림")

    with session_scope() as s:
        sid = sid_of(s, "R2026-0002")
        before = s.execute(text("SELECT count(*) FROM assessment WHERE submission_id=:i"),
                           {"i": sid}).scalar_one()
    try:
        with session_scope() as s:
            run_track_b(s, sid, client=Boom())
    except Exception:                     # noqa: BLE001
        pass
    with session_scope() as s:
        after = s.execute(text("SELECT count(*) FROM assessment WHERE submission_id=:i"),
                          {"i": sid}).scalar_one()
    assert after == before + 1, "판정 행이 남아 있어야 무슨 일이 있었는지 알 수 있다"
