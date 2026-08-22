"""판정 결과를 HTML 보고서로 저장.  python scripts/make_report.py [assessment_id ...]"""

import sys
from pathlib import Path

from sqlalchemy import text

from krpl_core.config import get_settings
from krpl_core.db import session_scope
from services.report import render_track_a

if __name__ == "__main__":
    out = Path(get_settings().storage.local_path) / "reports"
    out.mkdir(parents=True, exist_ok=True)
    ids = [int(x) for x in sys.argv[1:]]
    with session_scope() as s:
        q = "SELECT a.id, s.case_number FROM assessment a JOIN submission s ON s.id=a.submission_id"
        if ids:
            q += " WHERE a.id = ANY(:ids)"
        rows = s.execute(text(q + " ORDER BY a.id"), {"ids": ids} if ids else {}).all()
        for r in rows:
            p = out / f"{r.case_number}.html"
            p.write_text(render_track_a(s, r.id), encoding="utf-8")
            print(f"  {p}")
    print(f"{len(rows)}건 생성")
