"""부족한 능력단위에 위원이 시간을 넣고 제출하기까지.

기록 확인이 50% 미만으로 떨어뜨린 단위를 근거를 보고 메우는 흐름이다.
숫자가 화면·저장·보고서에서 갈라지지 않는지를 여기서 지킨다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from krpl_core.db import session_scope
from services.gateway.api import app
from services.review.unit_hours import unit_gaps

CASE = "R2026-0002"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def time_aid():
    with session_scope() as s:
        v = s.execute(text("""SELECT a.id FROM assessment a
            JOIN submission sub ON sub.id=a.submission_id
            WHERE sub.case_number=:c AND a.kind='time' ORDER BY a.id DESC LIMIT 1"""),
            {"c": CASE}).scalar()
    if v is None:
        pytest.skip("기록 확인 판정 없음")
    return v


@pytest.fixture(autouse=True)
def _clean(time_aid):
    yield
    with session_scope() as s:
        s.execute(text("UPDATE element_review SET granted_hours=NULL WHERE assessment_id=:a"),
                  {"a": time_aid})


def test_the_review_page_shows_the_units_that_need_hours(client, time_aid):
    h = client.get(f"/assessments/{time_aid}/review").text
    with session_scope() as s:
        gaps = unit_gaps(s, time_aid)
    if not gaps:
        pytest.skip("보완 대상 단위 없음")
    assert 'id="gapsec"' in h, "추가 인정 표가 없다"
    for g in gaps:
        assert g.unit_name in h, f"보완 대상 단위가 화면에 없다: {g.unit_name}"
    assert 'id="dv"' in h, "문서 열람창이 없다 — 근거를 원문으로 볼 수 없다"


def test_submitting_hours_is_saved_and_returned(client, time_aid):
    with session_scope() as s:
        gaps = unit_gaps(s, time_aid)
    if not gaps:
        pytest.skip("보완 대상 단위 없음")
    g = gaps[0]
    want = max(1, g.gap // 2)

    r = client.post(f"/assessments/{time_aid}/units/hours",
                    json={"hours": {g.unit_code: want}})
    assert r.status_code == 200
    body = r.json()
    got = {u["unit_code"]: u for u in body["units"]}[g.unit_code]
    assert got["granted"] == want
    assert got["counted"] == g.record + want, "인정시간 = 이수 + 위원"
    assert got["credited"] == (g.required if got["passes"] else 0), \
        "면제는 합산이 아니라 게이트 — 요구시간 전체이거나 0 이다"

    with session_scope() as s:
        again = {x.unit_code: x for x in unit_gaps(s, time_aid)}
    assert again[g.unit_code].granted == want, "다시 읽어도 같은 값이어야 한다"


def test_it_refuses_more_than_the_gap(client, time_aid):
    """화면이 막아도 요청은 직접 올 수 있다. 저장 쪽에서도 자른다."""
    with session_scope() as s:
        gaps = unit_gaps(s, time_aid)
    if not gaps:
        pytest.skip("보완 대상 단위 없음")
    g = gaps[0]
    r = client.post(f"/assessments/{time_aid}/units/hours",
                    json={"hours": {g.unit_code: g.gap + 500}})
    got = {u["unit_code"]: u for u in r.json()["units"]}[g.unit_code]
    assert got["granted"] == g.gap
    assert got["counted"] == g.required, "요구시간을 넘지 않는다"
    assert got["credited"] == g.required, "부족분을 다 채웠으니 인정선을 넘는다"


def test_a_unit_that_is_not_a_gap_is_ignored(client, time_aid):
    """이미 인정된 단위에 시간을 넣어도 받지 않는다."""
    r = client.post(f"/assessments/{time_aid}/units/hours",
                    json={"hours": {"9999999999": 40}})
    assert r.status_code == 200
    assert all(u["unit_code"] != "9999999999" for u in r.json()["units"])


def test_submitting_leads_to_the_final_step(client, time_aid):
    """③ 전문가 검토의 다음은 ④ 최종 판정이다.

    근거 분석(②)은 이 화면에 오기 전에 끝나 있어야 하는 단계다 — 제출하고
    거기로 되돌아가면 흐름이 뒤로 간다. 제출은 유료 분석을 걸지 않는다.
    """
    h = client.get(f"/assessments/{time_aid}/review").text
    with session_scope() as s:
        gaps = unit_gaps(s, time_aid)
    if not gaps:
        pytest.skip("보완 대상 단위 없음")
    assert "제출 → ④ 최종 판정" in h, "버튼이 어디로 가는지 말하지 않는다"
    assert "/exemption" in h, "최종 판정으로 가는 길이 없다"
    assert "/analyze" not in h, "제출이 유료 분석을 자동으로 걸어서는 안 된다"
    assert "report/evidence" not in h.split("id=\"gapsec\"")[-1], "제출이 ② 로 되돌아간다"


def test_the_exemption_report_matches_what_was_submitted(client, time_aid):
    with session_scope() as s:
        gaps = unit_gaps(s, time_aid)
    if not gaps:
        pytest.skip("보완 대상 단위 없음")
    g = gaps[0]
    client.post(f"/assessments/{time_aid}/units/hours", json={"hours": {g.unit_code: g.gap}})

    r = client.get(f"/assessments/{time_aid}/exemption")
    assert r.status_code == 200
    assert "면제 결과" in r.text
    assert f"이수 {g.record}h + 위원 인정 {g.gap}h" in r.text, "근거 설명이 제출값과 다르다"
    assert "인정선 통과, 요구시간 전체 면제" in r.text


def test_the_exemption_report_never_exceeds_the_required_hours(client, time_aid):
    """면제 + 남은 훈련 = 총 필수 시간. 이 합이 깨지면 숫자를 믿을 수 없다."""
    import re
    with session_scope() as s:
        gaps = unit_gaps(s, time_aid)
    if gaps:
        client.post(f"/assessments/{time_aid}/units/hours",
                    json={"hours": {x.unit_code: x.gap for x in gaps}})
    h = client.get(f"/assessments/{time_aid}/exemption").text
    tot = int(re.search(r"필수 훈련 (\d+)시간", h).group(1))
    ex = int(re.search(r"<span>면제되는 시간</span><b>(\d+)h</b>", h).group(1))
    left = int(re.search(r"<span>남은 훈련</span><b>(\d+)h</b>", h).group(1))
    assert ex + left == tot, f"면제 {ex} + 남은 {left} ≠ 총 {tot}"


def test_the_same_quote_is_not_listed_twice(time_aid):
    """같은 문장이 항목마다 되풀이돼 나오면 위원이 읽기를 포기한다.

    실측 한 단위에서 같은 부정 진술이 41번 나왔다. 인용·출처·적합도가 같으면
    한 줄로 묶고 몇 곳에 걸렸는지만 적는다.
    """
    from services.review.unit_hours import unit_evidence
    with session_scope() as s:
        sid = s.execute(text("SELECT submission_id FROM assessment WHERE id=:a"),
                        {"a": time_aid}).scalar_one()
        gaps = unit_gaps(s, time_aid)
        ev = unit_evidence(s, sid, [g.unit_code for g in gaps])
    if not any(ev.values()):
        pytest.skip("근거 없음")
    for code, items in ev.items():
        keys = [(",".join(i["fids"]), i["quote"], i["fit"]) for i in items]
        assert len(keys) == len(set(keys)), f"{code} 에 같은 근거가 두 번 실렸다"
        for i in items:
            assert i["n"] >= 1
            if i["n"] > 1:
                assert len(i["elements"]) >= 1, "묶었으면 어디에 걸렸는지 남아야 한다"


def test_a_document_cannot_break_out_of_the_script(client, time_aid):
    """제출 문서에 `</script>` 가 들어 있어도 화면을 장악하지 못한다.

    조각 본문은 지원자가 낸 파일에서 파싱한 것이라 통제 밖이다. 원문을
    페이지에 실어 두는 열람창이 그것을 그대로 내보내면, 파일 하나로 임의의
    태그가 실행된다. 이스케이프는 `doc_viewer.js_literal()` 한 곳에서 한다.
    """
    attack = '</script><img src=x onerror="alert(1)">'
    with session_scope() as s:
        sid = s.execute(text("SELECT submission_id FROM assessment WHERE id=:a"),
                        {"a": time_aid}).scalar_one()
        doc = s.execute(text("SELECT doc_key FROM document WHERE submission_id=:i LIMIT 1"),
                        {"i": sid}).scalar()
        if doc is None:
            pytest.skip("문서 없음")
        s.execute(text("""INSERT INTO fragment (submission_id, fid, doc_key, doc_type,
                              grade, stype, text, freq)
                          VALUES (:i, 'D99-X99', :d, '기타', 'D', '직접수행', :t, 1)"""),
                  {"i": sid, "d": doc, "t": attack})
    try:
        h = client.get(f"/assessments/{time_aid}/review").text
        # 태그가 만들어지려면 날것의 `<` 가 있어야 한다. 그것이 없으면 안전하다 —
        # 이스케이프된 문자열 안에 onerror 라는 글자가 남는 것은 무해하다.
        assert "</script><img" not in h, "조각 본문이 스크립트를 빠져나갔다"
        assert "<img src=x" not in h, "조각 본문에서 태그가 만들어졌다"
        assert "\\u003c/script" in h, "이스케이프된 형태로 실려 있어야 한다"
    finally:
        with session_scope() as s:
            s.execute(text("DELETE FROM fragment WHERE submission_id=:i AND fid='D99-X99'"),
                      {"i": sid})


def test_the_exemption_is_all_or_nothing_per_unit(client, time_aid):
    """면제는 합산이 아니라 게이트다 — 요구시간 전체이거나 0 이다.

    45h 를 인정했다고 45h 가 면제되지 않는다. 요구 80h 짜리 단위에 45h(56%)를
    인정하면 그 단위가 「인정 능력단위」가 되어 80h 전체가 면제된다.
    """
    with session_scope() as s:
        gaps = unit_gaps(s, time_aid)
    g = next((x for x in gaps if x.to_pass and x.to_pass <= x.gap), None)
    if g is None:
        pytest.skip("인정선을 넘길 수 있는 단위가 없음")

    # 한 시간 모자라게 → 면제 0
    under = client.post(f"/assessments/{time_aid}/units/hours",
                        json={"hours": {g.unit_code: g.to_pass - 1}}).json()
    u = {x["unit_code"]: x for x in under["units"]}[g.unit_code]
    assert u["passes"] is False and u["credited"] == 0, "인정선 미달인데 면제가 생겼다"

    # 딱 맞추면 → 요구시간 전체
    over = client.post(f"/assessments/{time_aid}/units/hours",
                       json={"hours": {g.unit_code: g.to_pass}}).json()
    u = {x["unit_code"]: x for x in over["units"]}[g.unit_code]
    assert u["passes"] is True
    assert u["credited"] == g.required, "인정선을 넘었는데 요구시간 전체가 면제되지 않았다"
    assert u["credited"] > u["counted"], "면제는 인정시간보다 크다 — 조정 조항의 효과"


def test_the_evidence_page_only_shows_units_that_need_hours(client, time_aid):
    """② 근거 분석 화면은 추가 인정이 필요한 단위만 싣는다.

    이미 인정선을 넘은 단위를 같이 늘어놓으면 볼 것이 많아 정작 근거를 못 읽는다.
    """
    with session_scope() as s:
        sid = s.execute(text("SELECT submission_id FROM assessment WHERE id=:a"),
                        {"a": time_aid}).scalar_one()
        gaps = unit_gaps(s, time_aid)
        passed = [dict(r) for r in s.execute(text("""
            SELECT payload->>'unit_name' AS n FROM assessment_element
            WHERE assessment_id=:a AND evidence_level IN ('완전충족','조정범위내')"""),
            {"a": time_aid}).mappings()]
    r = client.get(f"/submissions/{sid}/report/evidence")
    if r.status_code == 404:
        pytest.skip("근거 분석 결과 없음")
    # 히트맵의 세로축(능력단위)만 본다. 인용문 안에 이름이 스쳐 나오는 것은 상관없다 —
    # 그건 제출 문서가 그렇게 적혀 있는 것이지 화면이 그 단위를 실은 것이 아니다.
    import re
    # 머리 행의 빈 칸(`<th class="unit"></th>`)도 매치되도록 `.*?` 를 쓴다.
    # `.+?` 로 두면 빈 칸을 건너뛰어 다음 칸(문서명)까지 물어 온다.
    rows = [re.sub(r"<[^>]+>", "", m.group(1)).split("요구")[0].strip()
            for m in re.finditer(r'<th class="unit">(.*?)</th>', r.text, re.S)]
    rows = [x for x in rows if x]
    assert rows, "히트맵에 능력단위 행이 없다"
    assert set(rows) == {g.unit_name for g in gaps}, "대상 단위와 히트맵 행이 다르다"
    for p in passed:
        if p["n"] and p["n"] not in {g.unit_name for g in gaps}:
            assert p["n"] not in rows, f"이미 인정된 단위가 행으로 실렸다: {p['n']}"


def test_the_evidence_page_groups_by_document(client, time_aid):
    """축은 문서다 — 능력단위별로 모으는 것은 다음 단계(전문가 검토)에서 한다."""
    with session_scope() as s:
        sid = s.execute(text("SELECT submission_id FROM assessment WHERE id=:a"),
                        {"a": time_aid}).scalar_one()
    r = client.get(f"/submissions/{sid}/report/evidence")
    if r.status_code == 404:
        pytest.skip("근거 분석 결과 없음")
    h = r.text
    assert "문서별 근거 조각" in h
    assert 'class="hm"' in h, "히트맵이 없다"
    assert 'class="doc-c"' in h, "문서별 묶음이 없다"
    # 다음 단계 것을 여기서 또 보여 주지 않는다
    for gone in ("보완계획", "Ⅲ. 능력단위요소별 판정 근거", "KSA 커버리지"):
        assert gone not in h, f"다음 단계 내용이 남아 있다: {gone}"


def test_the_read_only_report_and_the_review_screen_are_different(client, time_aid):
    """③ 을 눌러 들어왔는데 ① 이 떠 있으면 어디 있는지 알 수 없다.

    한 렌더러가 두 화면을 그리되 이름과 할 일이 갈라져야 한다.
    읽기 전용 보고서에는 입력칸도 제출 버튼도 없다 — 제출은 유료 분석으로 이어진다.
    """
    with session_scope() as s:
        sid = s.execute(text("SELECT submission_id FROM assessment WHERE id=:a"),
                        {"a": time_aid}).scalar_one()
    ro = client.get(f"/submissions/{sid}/report/time").text
    rv = client.get(f"/assessments/{time_aid}/review").text

    import re
    def title(h):
        # CSS 의 `.step-h` 가 아니라 제목 마크업만 본다
        return re.search(r'<h1 class="step-h">([^<]+)', h).group(1)
    assert title(ro) == "① 기록 확인", f"읽기 전용인데 {title(ro)} 이다"
    assert title(rv) == "③ 전문가 검토", f"검토 화면인데 {title(rv)} 이다"

    assert 'class="gh"' not in ro and 'id="g-submit"' not in ro, "읽기 전용에 입력 수단이 있다"
    # 다음 단계로 가는 길은 화면마다 따로 두지 않고 단계줄 하나로 낸다
    assert f'href="/assessments/{time_aid}/review"' in ro, "단계줄에 ③ 으로 가는 길이 없다"
    assert ro.count('class="go"') == 0, "읽기 전용에 기본 행동이 있다"
    assert rv.count('class="go"') <= 1, "한 화면의 기본 행동은 하나여야 한다"

    with session_scope() as s:
        if unit_gaps(s, time_aid):
            assert 'class="gh"' in rv and 'id="g-submit"' in rv, "검토 화면에 입력칸이 없다"


STEP_SCREENS = ("/submissions/{sid}/report/time", "/submissions/{sid}/report/evidence",
                "/assessments/{aid}/review", "/assessments/{aid}/exemption")


def test_every_step_screen_carries_the_same_step_bar(client, time_aid):
    """네 화면 어디서든 같은 줄로 단계를 옮긴다.

    화면마다 다음 단계 버튼을 따로 두면 위치도 문구도 갈라진다 — 실제로
    「③ 전문가 검토 →」·「③ 전문가 검토에서 정하기」·「위원 페이지」·
    「전문가 검토로」 넷이 같은 곳을 가리키고 있었다.
    """
    import re
    with session_scope() as s:
        sid = s.execute(text("SELECT submission_id FROM assessment WHERE id=:a"),
                        {"a": time_aid}).scalar_one()
    for tpl in STEP_SCREENS:
        r = client.get(tpl.format(sid=sid, aid=time_aid))
        if r.status_code == 404:
            continue
        bar = re.search(r'(?s)<div class="step-nav">(.*?)</div>', r.text)
        assert bar, f"{tpl} 에 단계줄이 없다"
        names = re.findall(r'>([①②③④][^<]*)<', bar.group(1))
        assert names == ["① 기록 확인", "② 근거 분석", "③ 전문가 검토", "④ 최종 판정"], \
            f"{tpl} 의 단계줄이 다르다: {names}"
        assert bar.group(1).count('class="on"') == 1, f"{tpl} 의 현재 위치가 하나가 아니다"


def test_a_screen_has_at_most_one_primary_action(client, time_aid):
    """그 화면에서 할 일은 하나다. 둘이면 무엇부터 눌러야 할지 알 수 없다."""
    with session_scope() as s:
        sid = s.execute(text("SELECT submission_id FROM assessment WHERE id=:a"),
                        {"a": time_aid}).scalar_one()
    for tpl in STEP_SCREENS:
        r = client.get(tpl.format(sid=sid, aid=time_aid))
        if r.status_code == 404:
            continue
        n = r.text.count('class="go"')
        assert n <= 1, f"{tpl} 에 기본 행동이 {n}개 있다"


def test_old_navigation_words_are_gone(client, time_aid):
    """같은 곳을 여러 이름으로 부르지 않는다."""
    with session_scope() as s:
        sid = s.execute(text("SELECT submission_id FROM assessment WHERE id=:a"),
                        {"a": time_aid}).scalar_one()
    old = ("③ 전문가 검토 →", "전문가 검토에서 정하기", "전문가 검토로", "면제 결과</a>")
    for tpl in STEP_SCREENS + ("/submissions/{sid}",):
        r = client.get(tpl.format(sid=sid, aid=time_aid))
        if r.status_code == 404:
            continue
        for w in old:
            assert w not in r.text, f"{tpl} 에 옛 이름이 남아 있다: {w}"


def test_the_overview_follows_the_review_forward(client, time_aid):
    """③ 을 마치면 개요가 따라 움직인다.

    개요의 ③·④ 가 Track B 5단계 검토만 보고 있어서, 위원이 시간을 다 정하고
    ④ 까지 가도 개요는 「대기」에 머물렀다. 무엇이 끝났는지 개요가 모르면
    다음에 무엇을 할지도 알 수 없다.
    """
    with session_scope() as s:
        sid = s.execute(text("SELECT submission_id FROM assessment WHERE id=:a"),
                        {"a": time_aid}).scalar_one()
        gaps = unit_gaps(s, time_aid)
    if not gaps:
        pytest.skip("보완 대상 단위 없음")

    before = client.get(f"/submissions/{sid}").text
    assert f"{0}/{len(gaps)}" in before or "전문가 검토" in before

    client.post(f"/assessments/{time_aid}/units/hours",
                json={"hours": {g.unit_code: g.to_pass for g in gaps}})
    after = client.get(f"/submissions/{sid}").text

    import re
    plain = re.sub(r"<[^>]+>", "", after)      # <b> 때문에 글이 끊긴다
    assert "모두 정하셨습니다" in plain, "③ 이 끝났는데 개요가 모른다"
    with session_scope() as s:
        done = unit_gaps(s, time_aid)
    credited = sum(g.credited for g in done)
    assert credited, "인정선을 넘겼는데 면제가 0 이다"
    # 판정을 이미 기록한 건은 ④ 가 그 기록을 말한다 — 둘 중 하나면 된다
    assert ("면제됩니다" in plain or "인정" in plain), "④ 가 아무 말도 하지 않는다"
    assert f"/assessments/{time_aid}/exemption" in after, "④ 로 가는 길이 없다"


def test_reading_the_evidence_moves_the_case_forward(client, time_aid):
    """② 는 읽는 자리라 눌러서 바뀌는 것이 없었다 — 그래서 상태가 멈춰 있었다.

    사람이 읽었다는 사실을 남기면 ③ 으로 넘어간다. 그 사실은 감사 기록에 남는다 —
    누가 언제 확인하고 넘어갔는지가 판정의 일부다.
    """
    with session_scope() as s:
        sid = s.execute(text("SELECT submission_id FROM assessment WHERE id=:a"),
                        {"a": time_aid}).scalar_one()
        rows = [dict(r) for r in s.execute(text("""SELECT id, status FROM assessment
            WHERE submission_id=:i AND kind='evidence'"""), {"i": sid}).mappings()]
        было = s.execute(text("""SELECT count(*) FROM audit_log
            WHERE action='evidence_confirmed'"""), {}).scalar_one()
    if not rows:
        pytest.skip("근거 분석 판정 없음")
    try:
        with session_scope() as s:
            s.execute(text("""UPDATE assessment SET status='manual_review'
                WHERE submission_id=:i AND kind='evidence'"""), {"i": sid})

        before = client.get(f"/submissions/{sid}").text
        assert "확인 완료" in before, "읽고 넘어갈 길이 없다"

        r = client.post(f"/submissions/{sid}/evidence/confirm", follow_redirects=False)
        assert r.status_code == 303, "화면에서 온 요청은 개요로 돌려보낸다"

        after = client.get(f"/submissions/{sid}").text
        assert "확인함" in after, "확인했는데 상태가 그대로다"

        with session_scope() as s:
            assert s.execute(text("SELECT count(*) FROM audit_log "
                                  "WHERE action='evidence_confirmed'")).scalar_one() > было, \
                "감사 기록에 남지 않았다"
            from services.assess.case_state import case_state
            assert case_state(s, sid).evidence_ack
    finally:
        with session_scope() as s:
            for r_ in rows:
                s.execute(text("UPDATE assessment SET status=:s WHERE id=:i"),
                          {"s": r_["status"], "i": r_["id"]})
            s.execute(text("""DELETE FROM audit_log WHERE action='evidence_confirmed'
                AND detail->>'submission_id' = :i"""), {"i": str(sid)})


def test_the_overview_has_the_same_step_bar(client, time_aid):
    """개요에서도 같은 줄로 옮긴다 — 이동하는 방법이 화면마다 다르면 안 된다."""
    import re
    with session_scope() as s:
        sid = s.execute(text("SELECT submission_id FROM assessment WHERE id=:a"),
                        {"a": time_aid}).scalar_one()
    bar = re.search(r'(?s)<div class="step-nav">(.*?)</div>',
                    client.get(f"/submissions/{sid}").text)
    assert bar, "개요에 단계줄이 없다"
    names = re.findall(r'>([①②③④][^<]*)<', bar.group(1))
    assert names == ["① 기록 확인", "② 근거 분석", "③ 전문가 검토", "④ 최종 판정"]
    assert 'class="on"' not in bar.group(1), "개요는 어느 단계도 아니다"
