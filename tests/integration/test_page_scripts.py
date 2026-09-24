"""화면에 실린 자바스크립트가 실제로 파싱되는가.

`mark(btn, box)` 로 매개변수를 하나 늘리면서 함수 안의 `const box` 와 이름이
겹쳤다. 그 한 줄 때문에 **스크립트 전체가 파싱에 실패**했고, 3·4단계의
결과 저장과 판정 기록이 통째로 죽었다. 화면은 200 을 돌려주고 버튼도
그대로 있어 아무도 몰랐다.

파이썬 시험으로는 문자열 안의 문법 오류를 잡을 수 없다. node 가 있으면
그것으로 검사하고, 없으면 건너뛴다.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from krpl_core.db import session_scope
from services.gateway.api import app

NODE = shutil.which("node")
SCRIPT = re.compile(r"<script>(.*?)</script>", re.S)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def aid():
    with session_scope() as s:
        v = s.execute(text("""SELECT id FROM assessment WHERE kind='evidence'
            AND status='done' ORDER BY id DESC LIMIT 1""")).scalar()
    if v is None:
        pytest.skip("근거 분석 결과 없음")
    return v


@pytest.fixture(scope="module")
def sid():
    with session_scope() as s:
        v = s.execute(text("SELECT id FROM submission ORDER BY id DESC LIMIT 1")).scalar()
    if v is None:
        pytest.skip("접수 건 없음")
    return v


def check(js: str, where: str) -> None:
    """node 로 문법만 본다. 돌리지는 않는다."""
    if not NODE:
        pytest.skip("node 가 없어 문법 검사를 건너뜁니다")
    r = subprocess.run([NODE, "--check", "-"], input=js, text=True,
                       capture_output=True)
    assert r.returncode == 0, f"{where} 스크립트 문법 오류:\n{r.stderr[:800]}"


def scripts_of(html: str) -> list[str]:
    return [m for m in SCRIPT.findall(html) if m.strip()]


@pytest.mark.parametrize("stage", [1, 2, 3, 4, 5])
def test_every_stage_script_parses(client, aid, stage):
    html = client.get(f"/assessments/{aid}/review/{stage}").text
    got = scripts_of(html)
    assert got, f"{stage}단계에 스크립트가 없다"
    for i, js in enumerate(got):
        check(js, f"{stage}단계 #{i}")


def test_the_review_screen_script_parses(client, aid):
    for i, js in enumerate(scripts_of(client.get(f"/assessments/{aid}/review").text)):
        check(js, f"요소별 검토 화면 #{i}")


@pytest.mark.parametrize("path", ["/", "/cases", "/submissions/new"])
def test_the_common_screens_parse(client, path):
    for i, js in enumerate(scripts_of(client.get(path).text)):
        check(js, f"{path} #{i}")


def test_the_case_screen_script_parses(client, sid):
    for i, js in enumerate(scripts_of(client.get(f"/submissions/{sid}").text)):
        check(js, f"심사 개요 #{i}")


def test_the_final_stage_defines_what_its_buttons_call(client, aid):
    """버튼이 부르는 이름이 스크립트에 없으면 눌러도 아무 일이 없다."""
    html = client.get(f"/assessments/{aid}/review/5").text
    js = "\n".join(scripts_of(html))
    builtin = {"print", "alert", "confirm", "reload"}   # 브라우저가 주는 것
    for name in re.findall(r'onclick="(\w+)\(', html):
        if name in builtin:
            continue
        assert re.search(rf"function {name}\b", js), f"{name}() 이 정의돼 있지 않다"


# ── 눌렀을 때 실제로 도는가 ──────────────────────────────────────
#
# `node --check` 는 문법만 본다. `$` 가 정의돼 있지 않은 것 같은 실수는
# 잡지 못한다 — 함수가 첫 줄에서 죽는데 버튼은 그대로 있어 「눌러도 아무
# 일이 없다」로만 보인다. 껍데기 DOM 을 씌워 실제로 불러 본다.

STUB = r"""
const calls = [];
const FILL = globalThis.__FILL === undefined ? '10' : globalThis.__FILL;
const el = () => new Proxy({value:FILL, textContent:'', className:'', disabled:false,
                            classList:{add(){}, remove(){}, toggle(){}},
                            dataset:{}, style:{}},
  {get(t,k){ if (k in t) return t[k];
             if (k === 'querySelector' || k === 'closest') return () => el();
             if (k === 'querySelectorAll') return () => [];
             if (k === 'replaceWith' || k === 'scrollIntoView' || k === 'focus'
                 || k === 'addEventListener') return () => {};
             return undefined; },
   set(t,k,v){ t[k]=v; return true; }});
globalThis.document = {getElementById: () => el(), querySelector: () => el(),
                       querySelectorAll: () => [], documentElement:{style:{setProperty(){}}}};
globalThis.location = {pathname: '/x', reload(){ calls.push(['reload']); }};
globalThis.setTimeout = (f) => 0;
globalThis.addEventListener = () => {};
globalThis.ResizeObserver = class { observe(){} };
globalThis.DOMParser = class { parseFromString(){ return document; } };
globalThis.fetch = async (url, opt) => {
  calls.push([String(url), (opt||{}).method || 'GET']);
  return {ok: true, status: 200, text: async () => '<html></html>',
          json: async () => ({stamp:'x', recognized_hours:1, total_hours:2,
                              decision:'부분인정', done:false, pct:0, text:''})};
};
"""


def run_js(js: str, after: str) -> str:
    if not NODE:
        pytest.skip("node 가 없어 실행 검사를 건너뜁니다")
    # 이어 붙이는 조각 가운데 f-string 은 첫 줄뿐이다. 나머지에 중괄호를
    # 두 개 쓰면 그대로 두 개가 나가 문법이 깨진다 — 실제로 그랬다.
    pre, body = ("", js)
    if js.startswith("globalThis.__FILL"):
        pre, body = js.split("\n", 1)
    src = (pre + "\n" + STUB + "\n" + body + "\n(async () => {\n" + after + "\n"
           "  await new Promise(r => process.nextTick(r));\n"
           "  console.log(JSON.stringify(calls));\n"
           "})().catch(e => { console.error('BOOM ' + e); process.exit(3); });")
    r = subprocess.run([NODE, "-e", src], text=True, capture_output=True)
    assert r.returncode == 0, f"스크립트가 죽었다:\n{r.stderr[:800]}"
    return r.stdout.strip()


def test_an_empty_reason_stops_the_record(client, aid):
    """사유 없이 눌러도 조용히 통과시키면 안 된다."""
    js = "\n".join(scripts_of(client.get(f"/assessments/{aid}/review/5").text))
    out = run_js("globalThis.__FILL = '';\n" + js, "await decide();")
    assert "/decision" not in out, "사유가 비었는데 판정을 보냈다"


def test_pressing_record_actually_posts_the_decision(client, aid):
    """「판정 기록」이 정말 판정을 보내는가. `$` 가 없어 첫 줄에서 죽은 적이 있다."""
    js = "\n".join(scripts_of(client.get(f"/assessments/{aid}/review/5").text))
    out = run_js(js, "await decide();")
    assert "/decision" in out, f"판정을 보내지 않았다: {out}"
    assert '"POST"' in out


def test_pressing_a_result_button_actually_posts_it(client, aid):
    """2·3·4단계의 통과/미통과도 마찬가지다. `box` 이름이 겹쳐 죽은 적이 있다."""
    js = "\n".join(scripts_of(client.get(f"/assessments/{aid}/review/2").text))
    out = run_js(js, "await mark({closest: () => document.getElementById('x'),"
                     " dataset:{r:'통과'}, classList:{toggle(){}}});")
    assert "/remediation" in out, f"결과를 보내지 않았다: {out}"
