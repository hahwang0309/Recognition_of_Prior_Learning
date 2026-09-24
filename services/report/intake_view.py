"""접수 등록 · 문서 업로드 화면 — 담당자가 일을 시작하는 자리.

접수는 두 단계다.
  ① 심사번호·목표 종목·보유 자격을 적는다
  ② 지원자가 낸 서류를 올리고, 서류마다 종류와 신뢰도 등급을 지정한다

②의 등급은 사람이 정한다. 「경력증명서는 B등급」 같은 대응은 기준서에 있지만,
실제로 받은 종이가 그 유형이 맞는지는 담당자가 봐야 안다.
"""
from __future__ import annotations

import json

from services.report.layout import e, page

CSS = """
.pick{position:relative}
.hits{position:absolute;left:0;right:0;top:100%;z-index:5;background:var(--s1);
 border:1px solid var(--bd);border-radius:7px;margin-top:2px;max-height:260px;overflow-y:auto;
 box-shadow:0 6px 18px rgba(0,0,0,.10)}
.hits div{padding:7px 11px;font-size:12.8px;cursor:pointer;border-bottom:1px solid var(--bd)}
.hits div:last-child{border-bottom:0}
.hits div:hover,.hits div.on{background:var(--s2)}
.hits small{display:block;color:var(--tm);font-size:11.3px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;min-height:26px}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:12px;padding:3px 6px 3px 11px;
 border-radius:14px;background:var(--s3);color:var(--ts)}
.chip button{border:0;background:none;color:var(--tm);padding:0 4px;font-size:15px;line-height:1}
.chip button:hover{color:var(--no)}
.drop{display:block;border:2px dashed var(--bd);border-radius:10px;padding:26px;
 text-align:center;color:var(--ts);font-size:13px;cursor:pointer;background:var(--s2)}
.drop:hover{border-color:var(--tm)}
.drop.over{border-color:var(--ac);color:var(--ac);background:rgba(43,110,166,.07)}
/* 파일 입력을 display:none 으로 감추면 탭 순서와 접근성 트리에서 사라진다.
   화면에서만 지우고 초점은 받을 수 있게 둔다 — 그래야 키보드로 서류를 올릴 수 있다. */
.drop input[type=file]{position:absolute;width:1px;height:1px;opacity:0;
 overflow:hidden;clip:rect(0 0 0 0)}
.drop:focus-within{border-color:var(--ac);outline:2px solid var(--ac);outline-offset:2px}
.files{margin-top:12px}
.f{display:grid;grid-template-columns:26px 1fr 190px 96px 30px;gap:9px;align-items:center;
 padding:8px 11px;background:var(--s2);border:1px solid var(--bd);border-radius:8px;
 margin-bottom:6px;font-size:12.5px}
.f .k{color:var(--tm);font-variant-numeric:tabular-nums;font-size:11.5px}
.f .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.f .nm small{display:block;color:var(--tm);font-size:11px}
.f select{padding:4px 8px;font-size:12px}
.f .x{border:0;background:none;color:var(--tm);font-size:16px;padding:0}
.f .x:hover{color:var(--no)}
/* 이름으로 못 맞힌 줄. 담당자가 반드시 손대야 하는 곳이라 눈에 띄어야 한다. */
.f.ask{border-color:var(--wn);background:rgba(250,178,25,.09)}
.f.ask .nm small{color:#a06f00}
.f.ask select:first-of-type{border-color:var(--wn)}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]) .f.ask .nm small{color:var(--wn)}}
@media(max-width:680px){.f{grid-template-columns:1fr;gap:5px}}
"""


def render_new(programs: list[dict], doc_types: list[dict],
               next_case: str, env: str) -> str:
    """접수 등록 — 심사번호·종목·자격."""
    body = f"""
<h1>새 접수</h1>
<p class="sub">지원자를 등록하고 서류를 올립니다. 다음 화면에서 서류를 받습니다.</p>
<div class="note">
 <b>식별정보는 받지 않습니다.</b> 성명·생년월일·연락처를 적는 칸이 없습니다.
 지원자는 심사번호로만 다룹니다. 제출 서류에 식별정보가 있으면 수집 단계에서 자동으로 가려집니다.
</div>

<div class="card">
 <div class="row two">
  <div><label for="case">심사번호</label>
   <input id="case" value="{e(next_case)}" pattern="R\\d{{4}}-\\d{{4}}"
          placeholder="R2026-0001"></div>
  <div><label for="track">구분</label>
   <select id="track">
    <option value="B" selected>Track B — 경력·훈련 등 제출 서류 기반</option>
    <option value="A">Track A — 과정평가형 자격 보유 (기록 확인만)</option>
   </select></div>
 </div>

 <div class="row">
  <div class="pick"><label for="prog">목표 종목</label>
   <input id="prog" placeholder="종목명 일부를 입력하세요 (예: 용접, 제빵)" autocomplete="off">
   <div class="hits" id="prog-hits" style="display:none"></div>
   <div class="chips" id="prog-chip"></div></div>
 </div>

 <div class="row">
  <div class="pick"><label for="qual">보유 자격 <span style="color:var(--tm)">— Track A 는 필수</span></label>
   <input id="qual" placeholder="자격명 일부를 입력하세요 (예: 용접, 정보처리)" autocomplete="off">
   <div class="hits" id="qual-hits" style="display:none"></div>
   <div class="chips" id="qual-chip"></div></div>
 </div>

 <div class="row">
  <div><label for="note">메모 <span style="color:var(--tm)">— 선택</span></label>
   <input id="note" placeholder="예: 폴리텍 용접과정 수료 + 조선소 경력"></div>
 </div>

 <div id="msg"></div>
 <button class="go" id="save">등록하고 서류 올리기 →</button>
</div>
"""
    scripts = """<script>
const $ = id => document.getElementById(id);
let prog = null, quals = [];

function chips() {
  $('prog-chip').innerHTML = prog
    ? `<span class="chip">${prog}<button onclick="prog=null;chips()">×</button></span>` : '';
  $('qual-chip').innerHTML = quals.map((q, i) =>
    `<span class="chip">${q}<button onclick="quals.splice(${i},1);chips()">×</button></span>`).join('');
}

function picker(inputId, hitsId, url, label, onPick) {
  const inp = $(inputId), box = $(hitsId);
  let timer;
  inp.oninput = () => {
    clearTimeout(timer);
    const q = inp.value.trim();
    if (q.length < 1) { box.style.display = 'none'; return; }
    timer = setTimeout(async () => {
      const r = await fetch(url + encodeURIComponent(q));
      const rows = await r.json();
      if (!rows.length) {
        box.innerHTML = '<div style="color:var(--tm)">맞는 항목이 없습니다</div>';
      } else {
        box.innerHTML = rows.slice(0, 20).map(x =>
          `<div onclick='pick_${inputId}(${JSON.stringify(JSON.stringify(x))})'>`
          + label(x) + '</div>').join('');
      }
      box.style.display = 'block';
    }, 180);
  };
  window['pick_' + inputId] = raw => {
    onPick(JSON.parse(raw));
    inp.value = ''; box.style.display = 'none'; chips();
  };
  document.addEventListener('click', ev => {
    if (!inp.parentElement.contains(ev.target)) box.style.display = 'none';
  });
}

picker('prog', 'prog-hits', '/programs?active_only=true&limit=20&q=',
  x => `${x.program_id}<small>${x.official_name || ''} · 총 ${x.total_hours || '?'}시간`
      + ` · 능력단위 ${x.n_units || '?'}개</small>`,
  x => { prog = x.program_id; });

picker('qual', 'qual-hits', '/qualifications?limit=20&q=',
  x => `${x.qual_id}<small>능력단위 ${x.n_units || '?'}개</small>`,
  x => { if (!quals.includes(x.qual_id)) quals.push(x.qual_id); });

$('save').onclick = async () => {
  const msg = $('msg');
  const track = $('track').value;
  if (!prog) return msg.innerHTML = '<div class="msg no">목표 종목을 선택하세요.</div>';
  if (track === 'A' && !quals.length)
    return msg.innerHTML = '<div class="msg no">Track A 는 보유 자격이 필요합니다.</div>';
  $('save').disabled = true;
  msg.innerHTML = '';
  const r = await fetch('/submissions', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({case_number: $('case').value.trim(), track,
      target_program_id: prog, qualifications: quals,
      note: $('note').value.trim() || null})});
  const d = await r.json();
  if (!r.ok) {
    $('save').disabled = false;
    return msg.innerHTML = `<div class="msg no">${d.detail || '등록하지 못했습니다'}</div>`;
  }
  location.href = `/submissions/${d.id}/upload`;
};
</script>"""
    return page("새 접수", body, css=CSS, here="/submissions/new", env=env, scripts=scripts)


def render_upload(sub: dict, doc_types: list[dict], grades: list[str],
                  existing: list[dict], env: str, *,
                  accept: list[str] | None = None, max_mb: int = 50) -> str:
    """문서 업로드 — 서류마다 종류와 신뢰도 등급을 지정한다."""
    # 못 맞힌 파일은 비워 둔다 — 목록의 첫 항목을 조용히 넣어 두면
    # 담당자가 그대로 두는 순간 자기소개서가 공적증빙 A등급으로 들어간다.
    opts = ('<option value="">— 고르세요 —</option>'
            + "".join(f'<option value="{e(d["name"])}">{e(d["name"])} '
                      f'({e(d["grade"])}등급)</option>' for d in doc_types))
    gopts = "".join(f'<option value="{g}">{g}</option>' for g in grades)
    rows = "".join(f"""<tr><td>{e(d['doc_key'])}</td><td>{e(d['doc_type'])}</td>
        <td>{e(d['grade'])}</td><td>{e(d['issuer'] or '')}</td>
        <td class="n">{d['n_frag']}</td></tr>""" for d in existing)
    already = f"""<h2>이미 올린 서류 <span class="st">{len(existing)}건</span></h2>
<table><thead><tr><th>번호</th><th>종류</th><th>등급</th><th>발급처</th><th>조각</th></tr></thead>
<tbody>{rows}</tbody></table>""" if existing else ""

    body = f"""
<h1>{e(sub['case_number'])} — 서류 올리기</h1>
<p class="sub">{e(sub['official_name'] or sub['target_program_id'])} ·
 Track {e(sub['track'])} · 현재 {e(sub['status'])}</p>

<div class="note">
 서류마다 <b>종류</b>와 <b>신뢰도 등급</b>을 지정해 주세요. 이 등급이 판정 근거의 무게가 됩니다.
 기본값은 종류에 따라 자동으로 잡히지만, 실제 받은 서류를 보고 조정하실 수 있습니다.
 <br>올린 파일은 <b>식별정보가 자동으로 가려진 뒤</b> 저장됩니다.
</div>

<label class="drop" id="drop" for="file">
 파일을 여기에 끌어놓거나 눌러서 고르세요<br>
 <span style="font-size:11.5px">{" · ".join(accept or [])} · 파일당 {max_mb}MB 까지</span>
 <input type="file" id="file" multiple
        accept="{",".join("." + x for x in (accept or []))}">
</label>
<div class="files" id="files"></div>
<div id="msg"></div>
<div style="display:flex;gap:8px;margin-top:14px">
 <button class="go" id="up" disabled>서류 수집하기</button>
 <button onclick="location.href='/submissions/{sub['id']}'">나중에 하기</button>
</div>
{already}
"""
    scripts = f"""<script>
const SID = {sub['id']};
const START = {len(existing)};
const $ = id => document.getElementById(id);
const OPTS = `{opts}`, GOPTS = `{gopts}`;
const DEFAULT_GRADE = {json.dumps({d["name"]: d["grade"] for d in doc_types},
                                  ensure_ascii=False)};
let files = [];

function draw() {{
  $('files').innerHTML = files.map((f, i) => `
    <div class="f${{f.type ? '' : ' ask'}}">
      <span class="k">D${{String(START + i + 1).padStart(2, '0')}}</span>
      <span class="nm">${{f.file.name}}<small>${{(f.file.size / 1024).toFixed(0)}}KB${{
        f.matched ? ` · 「${{f.matched}}」 로 봄` : (f.type ? '' : ' · 종류를 고르세요')
      }}</small></span>
      <select onchange="setType(${{i}}, this.value)">${{OPTS}}</select>
      <select onchange="files[${{i}}].grade=this.value">${{GOPTS}}</select>
      <button class="x" onclick="files.splice(${{i}},1);draw()">×</button>
    </div>`).join('');
  files.forEach((f, i) => {{
    const s = $('files').children[i].querySelectorAll('select');
    s[0].value = f.type; s[1].value = f.grade;
  }});
  // 종류를 못 정한 파일이 있으면 올리지 않는다. 잘못 들어가면 되돌리기 어렵다.
  const left = files.filter(f => !f.type).length;
  $('up').disabled = !files.length || left > 0;
  $('up').textContent = left ? `종류를 고르세요 (${{left}}건 남음)` : '서류 수집하기';
}}
function setType(i, v) {{
  files[i].type = v;
  files[i].grade = DEFAULT_GRADE[v] || 'C';
  files[i].matched = '';        // 사람이 고쳤다 — 더는 기계가 본 것이 아니다
  draw();
}}
async function add(list) {{
  const fresh = [...list].map(file => ({{file, type: '', grade: 'C', matched: ''}}));
  files.push(...fresh);
  draw();
  // 이름으로 종류를 알아맞힌다. 판별은 서버 한 곳에만 둔다 —
  // 화면에도 같은 규칙을 두면 곧 갈라진다.
  try {{
    const r = await fetch('/doc-types/guess', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{names: fresh.map(f => f.file.name)}})}});
    if (r.ok) {{
      const g = await r.json();
      fresh.forEach((f, i) => {{
        if (g[i] && g[i].doc_type) {{
          f.type = g[i].doc_type;
          f.grade = g[i].grade || DEFAULT_GRADE[g[i].doc_type] || 'C';
          f.matched = g[i].matched || '';
        }}
      }});
    }}
  }} catch (e) {{ /* 못 맞히면 사람이 고른다 */ }}
  draw();
}}

$('file').onchange = ev => add(ev.target.files);
['dragenter', 'dragover'].forEach(n => $('drop').addEventListener(n, ev => {{
  ev.preventDefault(); $('drop').classList.add('over'); }}));
['dragleave', 'drop'].forEach(n => $('drop').addEventListener(n, ev => {{
  ev.preventDefault(); $('drop').classList.remove('over'); }}));
$('drop').addEventListener('drop', ev => add(ev.dataTransfer.files));

$('up').onclick = async () => {{
  $('up').disabled = true;
  $('msg').innerHTML = '<div class="msg">올리는 중…</div>';
  const fd = new FormData();
  files.forEach((f, i) => {{
    fd.append('files', f.file);
    fd.append('doc_types', f.type);
    fd.append('grades', f.grade);
  }});
  const r = await fetch(`/submissions/${{SID}}/upload`, {{method: 'POST', body: fd}});
  const d = await r.json();
  if (!r.ok) {{
    $('up').disabled = false;
    return $('msg').innerHTML = `<div class="msg no">${{d.detail || '올리지 못했습니다'}}</div>`;
  }}
  const warn = (d.warnings || []).map(w => `<div class="msg no">${{w}}</div>`).join('');
  const masked = Object.entries(d.masked || {{}})
    .map(([k, v]) => `${{k}} ${{v}}건`).join(' · ') || '없음';
  const next = `/submissions/${{SID}}`;
  $('msg').innerHTML = warn + `<div class="msg ok">
    문서 ${{d.n_documents}}건 · 조각 ${{d.n_fragments}}개 · 가려진 개인정보 ${{masked}}
    · 기이수 ${{d.prior_learning.length}}건</div>`;
  // 다음에 할 일은 심사 개요에 있다. 홈으로 보내면 방금 올린 건을 다시 찾아야 한다.
  // 경고가 있으면 넘기지 않는다 — 1.4초에 스쳐 지나가면 못 읽는다.
  if (warn) {{
    $('msg').innerHTML += `<div style="margin-top:10px">
      <a class="go" style="display:inline-block;padding:8px 18px;border-radius:8px;
         background:var(--tp);color:var(--s1);font-weight:600" href="${{next}}">
         그래도 계속 →</a></div>`;
    return;
  }}
  setTimeout(() => location.href = next, 1400);
}};
</script>"""
    return page(f"{sub['case_number']} 서류 올리기", body, css=CSS,
                here="/submissions/new", env=env, scripts=scripts)
