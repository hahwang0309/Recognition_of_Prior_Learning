"""제출 문서 열람창 — 인용을 누르면 원문이 열리고 그 문장이 강조된다.

## 왜 공용인가

위원이 판단하려면 AI 가 요약한 인용문이 아니라 **원문**을 봐야 한다. 그 창을
화면마다 복사해 붙이면 곧 서로 어긋난다(CLAUDE.md — 화면 공통은 한 벌).
여기 한 벌만 둔다.

## 쓰는 법

    css   → <style> 안에 VIEWER_CSS
    html  → </div> 뒤(본문 바깥)에 VIEWER_HTML
    js    → 페이지 스크립트 안에서 `FR`·`DN`·`$` 를 정의한 뒤 VIEWER_JS
    자료  → viewer_data(s, submission_id) 가 (FR, DN) 을 준다

`a.fx[data-fid]` 인 링크는 자동으로 걸린다. `data-fid` 가 없으면 `data-doc`
으로 문서 전체를 연다.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

_FNO = re.compile(r"(\d+)$")


def js_literal(o) -> str:
    """<script> 안에 넣는 JSON.

    조각 본문은 **제출 문서에서 파싱한 내용**이라 통제 밖이다. `</script>` 가
    든 파일 하나면 스크립트를 빠져나와 임의의 태그를 심을 수 있다.
    `<`·`>`·`&` 와 줄바꿈으로 읽히는 U+2028/2029 를 모두 이스케이프한다.
    """
    return (json.dumps(o, ensure_ascii=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


_PREFIX = re.compile(r"^(?:[A-Z]\d{2}|\d{1,2})[_-]")


def doc_name(path: str | None, key: str) -> str:
    """파일 이름에서 사람이 읽을 이름을 만든다.

    앞머리 번호를 뗀다 — 접수 때 붙는 문서키와 순번이 겹쳐 붙어
    `D08_07_개발팀장_확인서` 처럼 되는데, 화면에서 「D08 07」은 읽을 것이 없고
    히트맵 같은 좁은 칸에서는 정작 이름을 밀어낸다. 다 떼면 빈 이름이 되는
    경우(파일명이 번호뿐)에는 문서키를 쓴다.
    """
    if not path:
        return key
    n = Path(path).name.rsplit(".", 1)[0]
    while _PREFIX.match(n):
        n = _PREFIX.sub("", n, count=1)
    n = n.replace("_", " ").strip()
    # macOS 파일명은 NFD 다 — 그대로 두면 「수료증」이 「수료증」처럼 자모가 풀려
    # 보이고 낱말 찾기도 걸리지 않는다. 이름을 만드는 이 자리에서 되돌린다.
    return unicodedata.normalize("NFC", n) or key


def _fno(fid: str) -> int:
    m = _FNO.search(fid or "")
    return int(m.group(1)) if m else 0


def viewer_data(s: Session, submission_id: int) -> tuple[list[dict[str, Any]],
                                                         list[dict[str, Any]]]:
    """(조각, 문서). 조각은 문서별·번호순 — 원문을 읽는 차례 그대로다."""
    docs = [dict(r) for r in s.execute(text(
        """SELECT doc_key, doc_type, grade, file_path FROM document
           WHERE submission_id=:i ORDER BY doc_key"""), {"i": submission_id}).mappings()]
    by_key = {d["doc_key"]: d for d in docs}
    frags = [dict(r) for r in s.execute(text(
        """SELECT fid, doc_key, grade, text FROM fragment
           WHERE submission_id=:i"""), {"i": submission_id}).mappings()]
    fr = [{"fid": f["fid"], "doc": f["doc_key"],
           "name": doc_name(by_key.get(f["doc_key"], {}).get("file_path"), f["doc_key"]),
           "grade": f["grade"], "text": f["text"]}
          for f in sorted(frags, key=lambda f: (f["doc_key"], _fno(f["fid"])))]
    dn = [{"doc": d["doc_key"], "name": doc_name(d["file_path"], d["doc_key"]),
           "grade": d["grade"], "type": d["doc_type"]} for d in docs]
    return fr, dn


VIEWER_CSS = """
#dv{position:fixed;top:0;right:0;width:440px;max-width:92vw;height:100vh;background:var(--sf,#fff);border-left:1px solid var(--bd);box-shadow:-6px 0 18px rgba(0,0,0,.08);z-index:50;display:none;flex-direction:column;font-size:12.5px}
#dv.open{display:flex}
#dv .hd{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid var(--bd)}
#dv .hd b{flex:1;font-size:13px}
#dv .hd button{border:1px solid var(--bd);background:none;border-radius:6px;padding:2px 8px;cursor:pointer;font-size:14px}
#dv .tabs{display:flex;flex-wrap:wrap;gap:4px;padding:8px 12px;border-bottom:1px solid var(--bd)}
#dv .tabs button{border:1px solid var(--bd);background:none;border-radius:6px;padding:2px 7px;cursor:pointer;font-size:11.5px;color:var(--ts)}
#dv .tabs button.on{background:var(--tp);color:#fff;border-color:var(--tp)}
#dv input{margin:8px 12px 0;padding:5px 8px;border:1px solid var(--bd);border-radius:6px;font-size:12.5px}
#dv .body{flex:1;overflow:auto;padding:8px 12px 20px}
#dv .body p{margin:0;padding:5px 6px;border-bottom:1px solid var(--bd);white-space:normal;line-height:1.45}
#dv .body p.hit{background:#fff3b0;border-radius:4px}
#dv .body .dn{font-weight:700;margin:8px 0 2px;color:var(--ts)}
a.fx{cursor:pointer;color:var(--tp);text-decoration:underline dotted}
@media print{#dv{display:none!important}}
"""

VIEWER_HTML = """<aside id="dv"><div class="hd"><b id="dv-t">제출 문서</b>
<button id="dv-x" title="닫기 (Esc)">×</button></div>
<div class="tabs" id="dv-tabs"></div>
<input id="dv-q" placeholder="낱말로 찾기 (모든 문서)"><div class="body" id="dv-b"></div></aside>"""

# `FR`·`DN`·`$` 가 이미 정의돼 있어야 한다. f-string 안에 넣지 않으므로
# 중괄호를 두 번 쓰지 않는다 — 그 이스케이프가 실제로 스크립트를 깨뜨린 적이 있다.
VIEWER_JS = """
var dv=$('dv'), dvB=$('dv-b'), dvQ=$('dv-q'), dvTabs=$('dv-tabs'), curDoc=null, dvSrc=null;
function esc(s){return String(s).replace(/[&<>"]/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function dvRender(doc, hit){
  curDoc=doc; dvQ.value='';
  dvTabs.querySelectorAll('button').forEach(function(b){b.className=b.dataset.doc===doc?'on':''});
  var d=DN.filter(function(x){return x.doc===doc})[0];
  $('dv-t').textContent=d?d.name+' ('+d.grade+')':'제출 문서';
  dvB.innerHTML=FR.filter(function(f){return f.doc===doc}).map(function(f){
    return '<p data-fid="'+f.fid+'"'+(f.fid===hit?' class="hit"':'')+'>'+esc(f.text)+'</p>'}).join('');
  var h=dvB.querySelector('p.hit'); if(h) h.scrollIntoView({block:'center'}); else dvB.scrollTop=0;
}
function dvSearch(q){
  q=q.trim().toLowerCase(); if(!q){ if(curDoc) dvRender(curDoc); return; }
  dvTabs.querySelectorAll('button').forEach(function(b){b.className=''});
  $('dv-t').textContent='찾기: '+q;
  var last=null, out='';
  FR.forEach(function(f){ if(f.text.toLowerCase().indexOf(q)<0) return;
    if(f.doc!==last){ out+='<div class="dn">'+esc(f.name)+' ('+f.grade+')</div>'; last=f.doc; }
    out+='<p data-fid="'+f.fid+'">'+esc(f.text)+'</p>'; });
  dvB.innerHTML=out||'<p>없음</p>'; dvB.scrollTop=0;
}
function dvOpen(doc, fid, src){
  if(dv.className==='open' && dvSrc===src){ dv.className=''; dvSrc=null; return; }
  dvSrc=src; dv.className='open'; dvRender(doc, fid);
}
dvTabs.innerHTML=DN.map(function(d){
  return '<button data-doc="'+d.doc+'">'+esc(d.name)+' ('+d.grade+')</button>'}).join('');
dvTabs.addEventListener('click', function(ev){ var b=ev.target.closest('button'); if(b) dvRender(b.dataset.doc); });
dvQ.addEventListener('input', function(){ dvSearch(dvQ.value); });
$('dv-x').addEventListener('click', function(){ dv.className=''; dvSrc=null; });
document.addEventListener('keydown', function(ev){ if(ev.key==='Escape'){ dv.className=''; dvSrc=null; } });
document.querySelectorAll('a.fx').forEach(function(a){ a.addEventListener('click', function(ev){
  ev.preventDefault(); var fid=a.dataset.fid; dvOpen(fid?fid.slice(0,3):a.dataset.doc, fid||null, a); }); });
"""
