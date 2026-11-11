"""프로토타입 AI 산출물을 시험 고정자료(fixture)로 옮긴다. 1회성 변환.

프로토타입은 목록형 문서 조각에도 `R` 접두를 썼고, App 은 `P`(산출물)로 구분한다.
조각의 개수·순서·본문이 문서별로 완전히 일치할 때만 fid 를 갈아끼운다.
하나라도 어긋나면 변환을 중단한다 — 조용히 틀린 고정자료를 만드는 것이 가장 나쁘다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from sqlalchemy import text

from krpl_core.db import session_scope
from services.assess.package import build_package

SRC = Path(__file__).resolve().parents[2] / "Data(20260812)" / "derived" / "trackB"   # 연구 폴더의 시연 자료
DST = Path(__file__).resolve().parents[1] / "tests/fixtures/trackb"
CASES = {"R2026-0001": "B001", "R2026-0002": "B002", "R2026-0003": "B003", "R2026-0004": "B004"}
FID = re.compile(r"\bD\d{2}-[A-Z]\d{2}\b")


def main() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    for case, aid in CASES.items():
        with session_scope() as s:
            sid = s.execute(text("SELECT id FROM submission WHERE case_number=:c"),
                            {"c": case}).scalar()
            if sid is None:
                print(f"{case}: 접수 건 없음 — scripts/dev.sh demo 를 먼저 실행", file=sys.stderr)
                return 1
            pkg = build_package(s, sid)

        proto = json.loads((SRC / "package" / f"{aid}.json").read_text(encoding="utf-8"))
        mine: dict[str, list] = {}
        theirs: dict[str, list] = {}
        for f in pkg["fragments"]:
            mine.setdefault(f["doc_id"], []).append(f)
        for f in proto["fragments"]:
            theirs.setdefault(f["doc_id"], []).append(f)

        remap: dict[str, str] = {}
        for doc in sorted(set(mine) | set(theirs)):
            a, b = mine.get(doc, []), theirs.get(doc, [])
            if len(a) != len(b):
                print(f"{aid} {doc}: 조각 수 불일치 {len(b)}→{len(a)}. 중단", file=sys.stderr)
                return 1
            for x, y in zip(a, b):
                if x["text"] != y["text"]:
                    print(f"{aid} {doc}: 본문 불일치\n  프로토 {y['fid']} {y['text'][:50]}\n"
                          f"  App   {x['fid']} {x['text'][:50]}\n중단", file=sys.stderr)
                    return 1
                remap[y["fid"]] = x["fid"]

        raw = (SRC / "ai_out" / f"{aid}.json").read_text(encoding="utf-8")
        unknown = {f for f in FID.findall(raw) if f not in remap}
        converted = FID.sub(lambda m: remap.get(m.group(), m.group()), raw)
        out = json.loads(converted)
        out["applicant_id"] = case
        (DST / f"{case}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

        changed = sum(1 for k, v in remap.items() if k != v)
        print(f"{aid} → {case}.json  조각 {len(remap)}개 대조 · fid 교체 {changed}개"
              + (f"  ⚠ 미상 fid {sorted(unknown)}" if unknown else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
