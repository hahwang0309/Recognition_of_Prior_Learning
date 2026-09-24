"""감사 추적 시험 — 각 단계가 실제로 산출물을 남기는가, 그 산출물이 믿을 만한가.

이 단계의 목적은 「잘 됐습니다」를 믿지 않아도 되게 하는 것이다.
그러니 여기서 확인할 것도 「기록이 남았다」가 아니라
**기록이 실제 결과와 일치하는가**여야 한다.
"""
from __future__ import annotations

import hashlib
import json
from krpl_core.config import get_model_profile
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from krpl_core.audit import AuditStore, audit_root, read_artifact
from krpl_core.db import session_scope
from krpl_core.llm import ReplayClient
from krpl_parsers import Masker
from services.assess.track_b_service import run_track_b
from services.gateway.api import app
from services.review import record_decision, save_element_review

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/trackb"
CASE = "R2026-0002"


@pytest.fixture(scope="module", autouse=True)
def demo_data():
    """산출물 자체를 검사하므로 수집을 **항상 다시** 돌린다.
    DB 의 색인만 있고 파일이 없는 상태에서는 아무것도 확인할 수 없다."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    try:
        import load_demo
        load_demo.load()
    except FileNotFoundError as e:
        pytest.skip(f"실사례 원본 없음: {e}")


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def aid():
    with session_scope() as s:
        sid = s.execute(text("SELECT id FROM submission WHERE case_number=:c"),
                        {"c": CASE}).scalar()
        s.execute(text("DELETE FROM final_decision WHERE submission_id=:i"), {"i": sid})
        i = run_track_b(s, sid, client=ReplayClient(FIXTURES))
        for eid, rec in s.execute(text("""SELECT element_id, recommendation
                                          FROM assessment_element WHERE assessment_id=:i"""),
                                  {"i": i}):
            save_element_review(s, i, eid, "인정" if rec == "R0" else "불인정",
                                reviewer="시험")
        record_decision(s, i, "부분인정", reason="시험", decided_by="시험")
    return i


def arts(aid) -> dict[tuple[str, str], dict]:
    with session_scope() as s:
        return {(r["stage"], r["name"]): dict(r) for r in s.execute(text("""
            SELECT a.* FROM artifact a JOIN submission sub ON sub.id=a.submission_id
            WHERE sub.case_number=:c AND (a.assessment_id IS NULL OR a.assessment_id=:i)"""),
            {"c": CASE, "i": aid}).mappings()}


def body(aid, stage, name):
    """이름이 정확히 같거나 접미가 맞는 산출물을 찾는다.
    청크 방식에서는 이름 앞에 순번·능력단위코드가 붙는다 (01_1601050111_1차_AI응답)."""
    a = arts(aid)
    if (stage, name) in a:
        art = a[(stage, name)]
    else:
        hit = sorted(k for k in a if k[0] == stage and k[1].endswith(name))
        assert hit, f"{stage}/{name} 없음: {sorted(k[1] for k in a if k[0] == stage)}"
        art = a[hit[0]]
    with session_scope() as s:
        _, txt = read_artifact(s, art["id"])
    return txt


# ── 무엇이 남는가 ──
def test_every_stage_leaves_something(aid):
    have = {st for st, _ in arts(aid)}
    assert have == {"ingest", "package", "llm", "validate", "review", "decide"}


def test_artifacts_exist_on_disk_with_matching_hash(aid):
    for (stage, name), a in arts(aid).items():
        p = audit_root() / a["path"]
        assert p.exists(), f"{stage}/{name} 파일 없음: {p}"
        raw = p.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == a["sha256"], f"{stage}/{name} 해시 불일치"
        assert len(raw) == a["n_bytes"]


def test_tampering_is_detected(aid):
    """파일을 고치면 알아챌 수 있어야 한다. 못 알아채면 감사 기록이 아니다."""
    a = arts(aid)[("ingest", "조각")]
    p = audit_root() / a["path"]
    orig = p.read_bytes()
    try:
        p.write_bytes(orig + "\n(나중에 덧붙인 줄)".encode())
        with session_scope() as s:
            meta, _ = read_artifact(s, a["id"])
        assert meta["integrity"].startswith("⚠")
    finally:
        p.write_bytes(orig)
    with session_scope() as s:
        assert read_artifact(s, a["id"])[0]["integrity"] == "일치"


# ── 기록이 실제 결과와 맞는가 ──
def test_fragment_record_matches_database(aid):
    """조각 파일이 DB 의 조각과 같아야 한다. 다르면 AI 가 본 것을 알 수 없다."""
    saved = json.loads(body(aid, "ingest", "조각"))
    with session_scope() as s:
        rows = [dict(r) for r in s.execute(text("""
            SELECT fid, doc_key, doc_type, grade, stype, text FROM fragment
            WHERE submission_id=(SELECT id FROM submission WHERE case_number=:c)
            ORDER BY fid"""), {"c": CASE}).mappings()]
    assert saved == rows and len(rows) == 30


def test_package_record_is_what_was_sent(aid):
    """저장된 패키지의 해시가 판정 기록의 input_hash 와 같아야 한다."""
    from services.assess.package import package_hash
    pkg = json.loads(body(aid, "package", "AI입력패키지"))
    with session_scope() as s:
        recorded = s.execute(text("SELECT input_hash FROM assessment WHERE id=:i"),
                             {"i": aid}).scalar_one()
    assert package_hash(pkg) == recorded


def test_ai_response_is_raw(aid):
    """AI 응답은 손대지 않은 원본이어야 한다 — 정규화 전 것."""
    raw = json.loads(body(aid, "llm", "1차_AI응답"))
    with session_scope() as s:
        stored = {r[0]: r[1] for r in s.execute(text("""
            SELECT element_id, payload FROM assessment_element WHERE assessment_id=:i"""),
            {"i": aid})}
    assert len(stored) == 33
    assert raw["elements"], "청크 응답에도 요소가 있어야 한다"
    # 저장본에는 시스템이 덧붙인 항목이 있고, 원본에는 없어야 한다
    one = raw["elements"][0]
    assert "needs_expert_review" not in one
    assert "needs_expert_review" in stored[one["element_id"]]


def test_every_chunk_leaves_its_own_response(aid):
    """AI 가 본 능력단위마다 응답이 따로 남아야 한다.
    기이수로 코드가 확정한 단위는 AI 를 거치지 않으므로 응답도 없다."""
    names = sorted(k[1] for k in arts(aid) if k[0] == "llm" and k[1].endswith("AI응답"))
    assert len(names) == 6, f"AI 청크 6개인데 응답 {len(names)}개: {names}"
    codes = {n.split("_")[1] for n in names}
    with session_scope() as s:
        rows = list(s.execute(text("""
            SELECT split_part(element_id, '_', 1) AS unit, payload->>'decided_by' AS by
            FROM assessment_element WHERE assessment_id=:i"""), {"i": aid}).mappings())
    ai_units = {r["unit"] for r in rows if r["by"] != "rule"}
    rule_units = {r["unit"] for r in rows if r["by"] == "rule"}
    assert codes == ai_units, "AI 가 본 단위마다 응답이 하나씩"
    assert not (codes & rule_units), "코드가 확정한 단위는 AI 를 거치지 않는다"


def test_masking_record_never_keeps_the_value(tmp_path):
    """마스킹 기록에 가려진 값이 들어가면 마스킹한 의미가 없다."""
    m = Masker(True, ["전화번호", "주민등록번호", "이메일"])
    r = m("담당자 010-1234-5678\n주민등록번호 900101-1234567\nhong@corp.co.kr",
          trace=True)
    dumped = json.dumps([h.as_dict() for h in r.hits], ensure_ascii=False)
    for secret in ("010-1234-5678", "1234-5678", "900101-1234567", "1234567",
                   "hong@corp.co.kr", "hong"):
        assert secret not in dumped, f"가려진 값이 기록에 남았다: {secret}"
    assert {h.pattern for h in r.hits} == {"전화번호", "주민등록번호", "이메일"}
    assert [h.line_no for h in r.hits] == [1, 2, 3]
    assert r.counts == {"전화번호": 1, "주민등록번호": 1, "이메일": 1}


def test_masking_record_is_written(client):
    """실제 수집에서도 마스킹 기록이 남는가."""
    d = Path(__file__).resolve().parent / "_tmp_mask"
    d.mkdir(exist_ok=True)
    (d / "c.txt").write_text("근무기간: 2020.03.10 ~ 2026.05.31\n담당자 010-1111-2222\n",
                             encoding="utf-8")
    try:
        r = client.post("/submissions", json={"case_number": "R2026-0401", "track": "B",
                                              "target_program_id": "제빵_L2",
                                              "qualifications": ["제빵기능사"]})
        sid = r.json()["id"]
        client.post(f"/submissions/{sid}/documents", json={"documents": [
            {"doc_key": "D01", "doc_type": "경력증명서", "grade": "B",
             "file_path": str(d / "c.txt")}]})
        with session_scope() as s:
            a = s.execute(text("""SELECT id FROM artifact WHERE submission_id=:i
                                  AND name='마스킹기록'"""), {"i": sid}).scalar_one()
            _, txt = read_artifact(s, a)
        rec = json.loads(txt)
        assert rec["총계"] == {"전화번호": 1} and rec["건수"] == 1
        assert rec["내역"][0]["유형"] == "전화번호"
        assert "1111" not in txt and "2222" not in txt      # 값은 남지 않는다
        assert "2020.03.10" in body_of(sid, "조각")          # 날짜는 살아 있다
    finally:
        with session_scope() as s:
            s.execute(text("DELETE FROM submission WHERE case_number='R2026-0401'"))
        for f in d.iterdir():
            f.unlink()
        d.rmdir()


def body_of(sid: int, name: str) -> str:
    with session_scope() as s:
        a = s.execute(text("SELECT id FROM artifact WHERE submission_id=:i AND name=:n"),
                      {"i": sid, "n": name}).scalar_one()
        return read_artifact(s, a)[1]


def test_review_record_pairs_human_with_ai(aid):
    rows = json.loads(body(aid, "review", "요소별검토"))
    assert len(rows) == 33
    assert all({"element_id", "decision", "ai_recommendation", "reviewer"} <= set(r)
               for r in rows)
    assert sum(1 for r in rows if r["decision"] == "인정") == 15   # R0 만 인정했다


def test_decision_record_carries_the_arithmetic(aid):
    # 판정마다 따로 남는다 — 「최종판정_1회」·「최종판정_2회」…
    d = json.loads(body(aid, "decide", "최종판정_1회"))
    assert d["판정"] == "부분인정" and d["감면시간"] == 190 and d["총시간"] == 410
    b = d["산출근거"]
    assert sum(u["감면"] for u in b["units"]) == d["감면시간"]
    assert "다른_규칙_적용시" in b and "pending_rubric_decisions" in b


def test_execution_record_names_the_real_model(aid):  # noqa: D401
    """설정된 모델이 아니라 실제로 응답한 것이 남아야 한다.
    재생으로 돌린 것을 Opus 5 가 돌린 것처럼 적으면 감사 기록이 거짓이 된다."""
    from krpl_core.config import get_model_profile
    model = get_model_profile().model            # 2026-09-23부터 claude-haiku-4-5
    d = json.loads(body(aid, "llm", "실행요약"))["실행"]
    assert d["설정모델"] == model
    assert d["실제모델"] == f"replay:{model}"
    with session_scope() as s:
        assert s.execute(text("SELECT model FROM assessment WHERE id=:i"),
                         {"i": aid}).scalar_one() == f"replay:{model}"


def test_retry_leaves_the_repair_message():
    """재요청했다면 무엇을 지적해 되돌려 보냈는지도 남아야 한다."""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_track_b import BreaksOneUnit

    with session_scope() as s:
        sid = s.execute(text("SELECT id FROM submission WHERE case_number=:c"),
                        {"c": CASE}).scalar()
        i = run_track_b(s, sid, client=BreaksOneUnit("1601050216"))
    a = arts(i)
    repair = [k for k in a if k[0] == "validate" and k[1].endswith("1차_재요청")]
    assert repair, "재요청 문구가 남지 않았다"
    assert [k for k in a if k[1].endswith("2차_AI응답")], "재시도 응답이 남지 않았다"
    with session_scope() as s:
        _, txt = read_artifact(s, a[repair[0]]["id"])
        s.execute(text("DELETE FROM assessment WHERE id=:i"), {"i": i})
    assert "fid_존재하지않음" in txt and "D99-S99" in txt
    # 망가뜨리지 않은 단위는 재요청이 없어야 한다 — 그게 나눈 이유다
    assert len(repair) == 1, f"틀린 단위만 다시 받아야 한다: {repair}"


# ── 화면 ──
def test_audit_list_page(client, aid):
    h = client.get("/audit").text
    assert "감사 — 접수 건 목록" in h and CASE in h
    assert str(audit_root()) in h                 # 파일 경로를 숨기지 않는다


def test_audit_case_page_walks_all_stages(client, aid):
    h = client.get(f"/audit/{CASE}").text
    for stage in ("① 문서 수집", "② AI 입력 조립", "③ AI 분석",
                  "④ 기계 검증", "⑤ 전문가 검토", "⑥ 최종 판정"):
        assert stage in h, f"{stage} 없음"
    assert f"replay:{get_model_profile().model}" in h            # 실제 모델을 그대로 보여준다
    assert "AI입력패키지" in h and "1차_AI응답" in h


def test_audit_artifact_page_shows_integrity(client, aid):
    key = next(k for k in sorted(arts(aid)) if k[1].endswith("1차_검증결과"))
    a = arts(aid)[key]
    h = client.get(f"/audit/artifact/{a['id']}").text
    assert "해시 일치" in h and a["sha256"] in h
    assert "n_evidence" in h                      # 내용이 그대로 보인다


def test_audit_404s(client):
    assert client.get("/audit/R9999-9999").status_code == 404
    assert client.get("/audit/artifact/999999").status_code == 404


def test_manifest_lists_everything_with_hashes(client, aid):
    with session_scope() as s:
        sid = s.execute(text("SELECT id FROM submission WHERE case_number=:c"),
                        {"c": CASE}).scalar()
    m = client.get(f"/submissions/{sid}/manifest").json()
    assert m["case_number"] == CASE and m["artifacts"]
    assert all(len(a["sha256"]) == 64 for a in m["artifacts"])
    assert {a["stage"] for a in m["artifacts"]} >= {"ingest", "package", "llm", "validate"}


def test_stats(client, aid):
    d = client.get("/stats.json").json()
    assert d["접수"]["전체"] > 0 and d["판정"]["건수"] > 0
    assert d["검증"]["대상"] > 0 and d["산출물"]["개수"] > 0
    h = client.get("/stats").text
    assert "운영 통계" in h and "1차 검증 통과율" in h


# ── 색인 무결성 ──
def test_reingest_updates_the_index_instead_of_duplicating():
    """수집 단계는 assessment_id 가 NULL 이다. PostgreSQL 의 UNIQUE 는 NULL 을
    서로 다른 값으로 보므로 ON CONFLICT 가 잡지 못한다 — 실제로 다시 수집할 때마다
    색인 행이 쌓이고 옛 행이 낡은 해시를 물고 남았다."""
    with session_scope() as s:
        sid = s.execute(text("SELECT id FROM submission WHERE case_number=:c"),
                        {"c": CASE}).scalar()
        st = AuditStore(s, CASE, sid)
        first = st.write("ingest", "색인시험", {"v": 1}, seq=90)
        second = st.write("ingest", "색인시험", {"v": 2}, seq=90)
        rows = s.execute(text("""SELECT id FROM artifact WHERE submission_id=:i
                                 AND name='색인시험'"""), {"i": sid}).scalars().all()
        assert rows == [second] and first != second, "행이 하나만 남아야 한다"
        meta, body = read_artifact(s, second)
        assert json.loads(body) == {"v": 2} and meta["integrity"] == "일치"
        s.execute(text("DELETE FROM artifact WHERE name='색인시험'"))


def test_index_and_disk_agree_for_this_case(aid):
    """색인이 가리키는 파일이 전부 있고 해시가 맞는가 — 감사의 최소 조건."""
    with session_scope() as s:
        rows = list(s.execute(text("""
            SELECT a.id, a.path, a.sha256, a.name FROM artifact a
            JOIN submission sub ON sub.id=a.submission_id
            WHERE sub.case_number=:c"""), {"c": CASE}).mappings())
    assert rows
    missing = [r["name"] for r in rows if not (audit_root() / r["path"]).exists()]
    bad = [r["name"] for r in rows
           if (audit_root() / r["path"]).exists()
           and hashlib.sha256((audit_root() / r["path"]).read_bytes()).hexdigest() != r["sha256"]]
    assert not missing, f"색인은 있는데 파일이 없다: {missing}"
    assert not bad, f"해시가 어긋난다: {bad}"


def test_tests_never_touch_the_operational_store():
    """시험이 운영 감사 보관함·DB 를 건드리면 감사 기록 자체를 믿을 수 없다."""
    from krpl_core.config import get_settings
    s = get_settings()
    assert s.env == "test"
    assert "_test" in s.storage.local_path
    assert s.database_url.rsplit("/", 1)[-1].endswith("_test")
    assert "_test" in str(audit_root())
