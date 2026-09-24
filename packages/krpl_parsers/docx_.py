"""DOCX(Word) 읽기 — 문단과 표를 문서 순서대로.

검토용 docx(`워크숍/*/검토용_문서/`)를 별도 입력 세트로 바꾸지 않고 그대로 접수하기 위한 것이다.
표는 hwpx 파서와 같은 형식(list[list[list[str]]])으로 돌려주고, 본문 텍스트에는 표 행을
' | ' 로 이어 넣는다 — 이수증의 「코드 | 시간 | 평가」 한 행 추출이 hwpx 와 같게 동작한다.
"""
from __future__ import annotations

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph


def _iter_blocks(doc):
    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield Paragraph(child, doc)
        elif tag == "tbl":
            yield Table(child, doc)


def _grid(tbl: Table) -> list[list[str]]:
    g: list[list[str]] = []
    for row in tbl.rows:
        cells, prev = [], None
        for c in row.cells:
            # 병합 셀은 같은 객체가 반복된다 — 한 번만 쓴다
            txt = c.text.strip() if c._tc is not prev else ""
            prev = c._tc
            cells.append(txt)
        g.append(cells)
    return g


def read(path: str) -> tuple[str, list[list[list[str]]]]:
    doc = Document(path)
    lines: list[str] = []
    tables: list[list[list[str]]] = []
    for b in _iter_blocks(doc):
        if isinstance(b, Paragraph):
            s = b.text.strip()
            if s:
                lines.append(s)
        else:
            g = _grid(b)
            tables.append(g)
            for row in g:
                cells = [c for c in row if c]
                if cells:
                    lines.append(" | ".join(cells))
    return "\n".join(lines), tables
