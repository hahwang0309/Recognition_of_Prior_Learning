"""Track A·B 위원 페이지가 같이 쓰는 조각 — 판정 파라미터 표.

값은 rubric 에서 읽는다. 「구분」은 현행 규칙 / TF 결정 필요 둘뿐이다(pending_decisions 에 있으면 후자).
"""
from __future__ import annotations

import html

e = lambda x: html.escape(str(x) if x is not None else "")   # noqa: E731


def param_table(rows: list[tuple[str, str, str, bool]], title: str = "판정 파라미터 — 위원 논의로 수정 가능") -> str:
    """rows: (항목, 현재값, 근거, TF결정필요?)"""
    body = "".join(
        f"<tr><td>{e(k)}</td><td>{e(v)}</td><td>{e(src)}</td>"
        f"<td>{'<b>TF 결정 필요</b>' if pend else '현행 규칙'}</td><td style='min-width:160px'></td></tr>"
        for k, v, src, pend in rows)
    return f"""<h3 style="font-size:14px;margin:0 0 8px;color:var(--tp)">{e(title)}</h3>
<div class="tw"><table class="hold-tbl"><thead><tr><th>항목</th><th>현재값</th><th>근거</th><th>구분</th><th>수정 의견</th></tr></thead>
<tbody>{body}</tbody></table></div>"""


def pending(rubric, key: str) -> bool:
    return any(p.key == key for p in rubric.pending_decisions)
