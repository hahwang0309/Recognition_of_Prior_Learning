"""Track B 경로 — 근거 분석 → 위원 검토 → 확인 계획 → 최종 판정.

Track A 와 B 는 접수부터 다른 경로다. Track B 에는 ① 기록 확인이 없다 — 코드가
맞는 이수 기록이 없는 것이 전제이므로 근거 분석이 곧 판정이다.

판정 엔진은 진작 있었는데 **거기까지 가는 길이 없었다.** 위원 페이지는 개요
어디에서도 연결되지 않아 주소를 직접 쳐야 들어갈 수 있었다.
"""
from __future__ import annotations

import json
import re

import pytest
from krpl_core.config import get_rubric
from fastapi.testclient import TestClient
from sqlalchemy import text

from krpl_core.db import session_scope
from services.gateway.api import app
from services.review.coverage import unit_verdicts
from services.review.unit_hours import evidence_aid

CASE = "R2026-0002"
B_STEPS = ["① 근거 분석", "② 위원 검토", "③ 확인 계획"]   # Track B 는 확인 계획에서 끝난다


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def case():
    with session_scope() as s:
        sid = s.execute(text("SELECT id FROM submission WHERE case_number=:c"),
                        {"c": CASE}).scalar()
        if sid is None:
            pytest.skip("실사례 없음")
        before = s.execute(text("SELECT track FROM submission WHERE id=:i"),
                           {"i": sid}).scalar_one()
        s.execute(text("UPDATE submission SET track='B' WHERE id=:i"), {"i": sid})
        ev = evidence_aid(s, sid)
        time_aid = s.execute(text("""SELECT id FROM assessment WHERE submission_id=:i
            AND kind='time' ORDER BY id DESC LIMIT 1"""), {"i": sid}).scalar()
    if ev is None:
        pytest.skip("근거 분석 결과 없음")
    yield {"sid": sid, "ev": ev, "time": time_aid}
    with session_scope() as s:
        s.execute(text("UPDATE submission SET track=:t WHERE id=:i"),
                  {"t": before, "i": sid})


def _bar_html(html: str) -> str:
    m = re.search(r'(?s)<div class="step-nav">(.*?)</div>', html)
    return m.group(1) if m else ""


def _bar(html: str) -> list[str]:
    m = re.search(r'(?s)<div class="step-nav">(.*?)</div>', html)
    return re.findall(r'>([①②③④][^<]*)<', m.group(1)) if m else []


def test_the_overview_leads_to_the_panel(client, case):
    """위원 페이지로 가는 길이 개요에 있어야 한다.

    없어서 위원이 주소를 직접 쳐야 했다. 판정 엔진이 다 있어도 닿지 못하면 없는
    것과 같다.
    """
    h = client.get(f"/submissions/{case['sid']}").text
    assert f'/assessments/{case["ev"]}/panel' in h, "개요에서 위원 페이지로 갈 길이 없다"
    assert "위원 검토" in h


def test_the_overview_uses_the_track_b_steps(client, case):
    h = client.get(f"/submissions/{case['sid']}").text
    assert _bar(h) == B_STEPS, "개요가 Track A 단계줄을 그린다"
    assert "기록 확인 보기" in h, "기록 확인 결과는 참고로 남는다"


@pytest.mark.parametrize("path", ["/submissions/{sid}/report/evidence",
                                  "/assessments/{ev}/panel", "/assessments/{ev}/plan"])
def test_every_track_b_screen_carries_the_same_bar(client, case, path):
    url = path.format(sid=case["sid"], ev=case["ev"], time=case["time"])
    r = client.get(url)
    assert r.status_code == 200, f"{url} 이 열리지 않는다"
    assert _bar(r.text) == B_STEPS, f"{url} 의 단계줄이 다르다"


def test_the_plan_page_is_the_last_word(client, case):
    """Track B 는 ③ 확인 계획에서 끝난다.

    요소·항목에는 시간이 없어(NCS 원자료 확인) 면제 시간을 여기서 확정하지 않는다.
    확인 계획이 인정·보류·불인정을 보이고 마무리한다.
    """
    h = client.get(f"/submissions/{case['sid']}").text
    assert "최종 판정" not in _bar_html(h), "Track B 단계줄에 최종 판정이 남아 있다"
    assert "/exemption" not in h, "개요가 아직 면제 결과로 보낸다"

    plan = client.get(f"/assessments/{case['ev']}/plan")
    assert plan.status_code == 200
    for word in ("인정", "보류", "불인정"):
        assert word in plan.text, f"확인 계획이 「{word}」을 말하지 않는다"


def test_the_unit_verdict_counts_performance_criteria(client, case):
    """신형(2026-10-02) — 세는 것은 수행준거다. n_total = 그 단위 요소들의 수행준거 수, n_covered = 점수 ≥1."""
    with session_scope() as s:
        units = unit_verdicts(s, case["ev"])
        pcs = {u["code"]: s.execute(text("""SELECT count(*) FROM catalog_ncs_pc p
            WHERE p.unit_code=:c AND EXISTS (SELECT 1 FROM assessment_element x
                WHERE x.assessment_id=:a AND x.element_id LIKE :p
                  AND split_part(x.element_id, '.', 2)::int = p.element_no)"""),
            {"a": case["ev"], "c": u["code"], "p": u["code"] + "%"}).scalar_one() for u in units}
    assert units
    for u in units:
        assert u["format"] == "pc"
        assert u["n_total"] == pcs[u["code"]], f"{u['name']}: n_total 이 수행준거 수가 아니다"
        assert 0 <= u["n_covered"] <= u["n_total"] and 0 <= u["mean"] <= 2
        assert u["ratio"] == pytest.approx(u["mean"] / 2)
        assert u["verdict"] in ("인정", "보류", "불인정")
        ur = get_rubric().track_b["unit_rule"]
        if ur["require_all_nonzero"] and u["n_zero"]:
            assert u["verdict"] == "불인정", "0 조건이 켜져 있으면 0 인 수행준거가 있을 때 불인정"
        else:
            want = "인정" if u["mean"] >= ur["accept_mean"] else "보류" if u["mean"] >= ur["hold_mean"] else "불인정"
            assert u["verdict"] == want, "판정은 rubric unit_rule 의 평균 문턱 그대로"


def test_track_a_screens_keep_their_own_bar(client, case):
    """트랙이 서로 새지 않는다."""
    with session_scope() as s:
        s.execute(text("UPDATE submission SET track='A' WHERE id=:i"), {"i": case["sid"]})
    try:
        h = client.get(f"/submissions/{case['sid']}").text
        assert _bar(h) == ["① 기록 확인", "② 근거 분석", "③ 전문가 검토", "④ 최종 판정"]
    finally:
        with session_scope() as s:
            s.execute(text("UPDATE submission SET track='B' WHERE id=:i"), {"i": case["sid"]})


def test_document_names_are_composed(case):
    """macOS 파일명은 NFD 다 — 그대로 실으면 「수료증」이 자모로 풀려 보인다.

    화면에서만 이상해 보이는 것이 아니라 낱말 찾기도 걸리지 않는다.
    """
    import unicodedata
    from services.report.doc_viewer import viewer_data
    with session_scope() as s:
        fr, dn = viewer_data(s, case["sid"])
    assert dn, "문서가 없다"
    for d in dn:
        assert d["name"] == unicodedata.normalize("NFC", d["name"]), \
            f"문서 이름이 NFD 다: {d['name']!r}"
    for f in fr[:50]:
        assert f["name"] == unicodedata.normalize("NFC", f["name"])


def test_the_heatmap_shows_its_totals(client, case):
    """합계 칸이 빈칸용 클래스를 쓰면 글자가 투명해져 숫자가 사라진다."""
    h = client.get(f"/submissions/{case['sid']}/report/evidence")
    if h.status_code == 404:
        pytest.skip("근거 분석 결과 없음")
    m = re.search(r'(?s)<table class="hm">.*?</table>', h.text)
    assert m, "히트맵이 없다"
    totals = re.findall(r'<td class="sum">(\d+)</td>', m.group(0))
    assert totals, "합계 칸이 없다"
    assert any(int(x) for x in totals), "합계가 모두 0 이다"
    assert '<td class="z">' in m.group(0), "빈칸은 그대로 비워 둔다"


def test_step_one_opens_the_new_screen_not_the_old_report(client, case):
    """① 근거 분석은 새 화면이다.

    단계줄이 회람본 3장 보고서를 가리키고 있었다 — 눌러 보면 「옛날 것으로
    돌아갔다」로 읽힌다. 회람본은 그 화면 안의 각주로만 연다.
    """
    h = client.get(f"/submissions/{case['sid']}").text
    bar = re.search(r'(?s)<div class="step-nav">(.*?)</div>', h).group(1)
    one = re.search(r'<a href="([^"]+)"[^>]*>① 근거 분석', bar)
    assert one, "① 이 링크가 아니다"
    assert one.group(1) == f"/submissions/{case['sid']}/report/evidence", \
        f"① 이 옛 보고서를 가리킨다: {one.group(1)}"

    page = client.get(one.group(1)).text
    assert re.search(r'<h1 class="step-h">① 근거 분석', page), "화면이 자기를 ① 이라 하지 않는다"
    assert 'class="hm"' in page, "새 화면(히트맵)이 아니다"
    assert f'/assessments/{case["ev"]}/report' not in page, "걷어낸 화면으로 가는 길이 남아 있다"


def test_a_strange_fit_value_does_not_kill_the_panel(client, case):
    """AI 가 어휘 밖의 적합도를 내도 위원 페이지는 떠야 한다.

    실제 사고(판정 820): AI 가 「간직」을 냈고 기계 검증이 `fit_어휘` 로 잡았지만
    3회 안에 못 고쳐 그대로 저장됐다. 화면이 KeyError 로 죽어 위원이 아무것도
    볼 수 없었다. 자료가 이상해도 화면은 뜨고, 이상하다는 것을 보여야 한다.
    """
    with session_scope() as s:
        row = s.execute(text("""SELECT element_id, payload FROM assessment_element
            WHERE assessment_id=:a AND jsonb_array_length(COALESCE(payload->'evidence','[]'::jsonb)) > 0
            LIMIT 1"""), {"a": case["ev"]}).mappings().first()
    if row is None:
        pytest.skip("근거가 붙은 요소가 없다")
    import copy
    bad = copy.deepcopy(dict(row["payload"]))
    bad["evidence"][0]["fit"] = "간직"
    try:
        with session_scope() as s:
            s.execute(text("""UPDATE assessment_element SET payload=CAST(:p AS jsonb)
                WHERE assessment_id=:a AND element_id=:e"""),
                {"p": json.dumps(bad, ensure_ascii=False), "a": case["ev"], "e": row["element_id"]})
        r = client.get(f"/assessments/{case['ev']}/panel")
        assert r.status_code == 200, "어휘 밖 값 하나에 화면이 죽는다"
        assert "알 수 없는 값" in r.text, "이상하다는 것을 말하지 않는다"
    finally:
        with session_scope() as s:
            s.execute(text("""UPDATE assessment_element SET payload=CAST(:p AS jsonb)
                WHERE assessment_id=:a AND element_id=:e"""),
                {"p": json.dumps(dict(row["payload"]), ensure_ascii=False),
                 "a": case["ev"], "e": row["element_id"]})


def test_the_exemption_page_is_not_part_of_track_b(client, case):
    """면제 결과는 Track A 의 ④ 다 — Track B 에서 열면 500 이 아니라 안내가 나와야 한다."""
    r = client.get(f"/assessments/{case['ev']}/exemption")
    assert r.status_code == 404
    assert "확인 계획에서 끝납니다" in r.json()["detail"]


def test_the_submit_button_shows_that_it_is_working(client, case):
    """제출은 AI 1회(10~30초)를 부른다 — 아무 표시가 없으면 「멈췄다」로 읽힌다.

    폼은 그대로 보내되 버튼을 잠그고 진행 막대를 켠다. 두 번 눌러 두 번
    부르는 일도 함께 막힌다.
    """
    h = client.get(f"/assessments/{case['ev']}/panel").text
    assert 'id="subbusy"' in h and 'class="pbar"' in h, "진행 표시가 없다"
    assert "b.disabled=true" in h, "두 번 눌러도 막히지 않는다"
    assert "10~30초" in h, "얼마나 걸리는지 말하지 않는다"
    # 표시는 눌러야 나온다 — 처음에는 숨어 있다
    assert re.search(r'<div id="subbusy" hidden>', h), "처음부터 보인다"
