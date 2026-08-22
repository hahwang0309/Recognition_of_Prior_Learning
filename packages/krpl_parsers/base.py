"""파일 → 텍스트. 형식별 파서를 한 곳에서 고른다."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ParsedDoc:
    path: str
    ext: str
    text: str
    tables: list[list[list[str]]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def n_chars(self) -> int:
        return len(self.text)


def supported_extensions() -> list[str]:
    return ["hwp", "hwpx", "pdf", "txt", "md"]


def _from_tables(tables: list[list[list[str]]]) -> str:
    """표를 줄 단위 텍스트로. 빈 셀은 버리고 셀 사이는 ' | ' 로 잇는다."""
    out = []
    for g in tables:
        for row in g:
            cells = [c.strip() for c in row if c and c.strip()]
            if cells:
                out.append(" | ".join(cells))
    return "\n".join(out)


def parse_file(path: str | Path) -> ParsedDoc:
    p = Path(path)
    ext = p.suffix.lower().lstrip(".")
    if not p.exists():
        raise FileNotFoundError(p)

    if ext in ("txt", "md"):
        return ParsedDoc(str(p), ext, p.read_text(encoding="utf-8"))

    if ext == "hwp":
        from krpl_parsers.hwp import tables as hwp_tables
        t = hwp_tables(str(p))
        return ParsedDoc(str(p), ext, _from_tables(t), t, {"n_tables": len(t)})

    if ext == "hwpx":
        from krpl_parsers.hwpx import tables as hwpx_tables
        t = hwpx_tables(str(p))
        return ParsedDoc(str(p), ext, _from_tables(t), t, {"n_tables": len(t)})

    if ext == "pdf":
        from pypdf import PdfReader
        r = PdfReader(str(p))
        pages = [(pg.extract_text() or "") for pg in r.pages]
        text = "\n".join(pages)
        return ParsedDoc(str(p), ext, text, [], {"n_pages": len(r.pages),
                                                 "empty_pages": sum(1 for x in pages if not x.strip())})

    raise ValueError(f"지원하지 않는 형식: .{ext} (지원: {', '.join(supported_extensions())})")
