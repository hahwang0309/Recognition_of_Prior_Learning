"""구형(KSA 항목) 재생 픽스처 → 신형(수행준거) 형식으로 기계 변환. 2026-10-02

왜: 판정 단위가 수행준거로 바뀌어(4차 TF) 프롬프트 v6 가 `pc_ref` 로 근거를 낸다. 재생
테스트(ReplayClient)는 저장된 AI 산출물을 그대로 돌려주므로 픽스처도 신형이어야 한다.
실호출로 다시 만들면 $1~2 × 4건이고, 이 변환은 **뜻이 아니라 기계적 모양**만 맞춘다 —
근거를 그 요소의 수행준거에 **순환 배정**한다. 검증기·집계·화면 경로를 시험하는 데 쓴다.

비틀기(의도적): R3 요소의 근거는 전부 `간접` 으로 바꿔 보류 단위가 생기게 한다(보류 경로 시험).
R0 요소는 uncovered_pc·remediation 을 비운다(검증기 R0 규칙). 모든 근거를 보존한다
(수행준거보다 많으면 한 준거에 여러 건) — 줄이면 source_grades 가 어긋난다.

사용: cd App && .venv/bin/python scripts/convert_fixtures_pc.py   (tests/fixtures/trackb_ksa → tests/fixtures/trackb)
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, "."); sys.path.insert(0, "packages")
from sqlalchemy import text  # noqa: E402

from krpl_core.config import get_rubric  # noqa: E402
from krpl_core.db import session_scope  # noqa: E402
from krpl_rules import validate_track_b  # noqa: E402
from services.assess.package import build_package  # noqa: E402

SRC = Path("tests/fixtures/trackb_ksa")
DST = Path("tests/fixtures/trackb")


def convert(out: dict, pkg: dict) -> dict:
    pcs = {e["element_id"]: [p["ref"] for p in e.get("performance_criteria") or []]
           for u in pkg["ncs"]["units"] for e in u["elements"]}
    new = copy.deepcopy(out)
    for el in new["elements"]:
        refs = pcs.get(el["element_id"]) or ["준거1"]
        el["schema"] = "pc"
        rec = el.get("recommendation")
        evs = el.get("evidence") or []
        covered: list[str] = []
        for i, ev in enumerate(evs):
            ev.pop("ksa_ref", None)
            ev["pc_ref"] = refs[i % len(refs)]
            if rec == "R3":
                ev["fit"] = "간접"
            if ev["pc_ref"] not in covered:
                covered.append(ev["pc_ref"])
        old_unc = el.pop("uncovered_ksa", None) or []
        notes = [u.get("note") for u in old_unc if isinstance(u, dict) and u.get("note")]
        status = next((u.get("status") for u in old_unc if isinstance(u, dict) and u.get("status") in ("교육이수(미평가)", "미확보")), "미확보")
        missing = [r for r in refs if r not in covered]
        if rec == "R0":
            el["uncovered_pc"], el["remediation"] = [], []
        else:
            # 원본에 미확보 항목이 있었으면 신형에서도 미확보 수행준거를 **남긴다** — 그래야 보완 항목이
            # 살아 있고(5단계 검토 화면·인정 시간 계산), 근거가 수행준거보다 많아 전부 덮여 버린 요소가
            # 「확인할 것 없음」으로 바뀌는 뜻 변화를 막는다. 마지막 준거의 근거를 첫 준거로 옮긴다.
            if old_unc and not missing and len(refs) > 1:
                for ev in evs:
                    if ev["pc_ref"] == refs[-1]:
                        ev["pc_ref"] = refs[0]
                missing = [refs[-1]]
            el["uncovered_pc"] = [{"ref": r, "status": status, **({"note": notes[k % len(notes)]} if notes else {})}
                                  for k, r in enumerate(missing)]
            rem = el.get("remediation") or []
            for r in rem:
                r.pop("ksa_refs", None)
                r["pc_refs"] = []
            if missing and not rem:
                rem = [{"method": "면접", "item": "변환 픽스처 — 미확보 수행준거 확인", "oral_check": [], "reason": "변환"}]
            if missing:
                # 보완 항목마다 대상 수행준거가 있어야 5단계 화면에 「확인할 것」이 뜬다. 돌아가며 나누고,
                # 미확보가 항목보다 적으면 겹쳐 준다(합집합만 같으면 검증기는 통과한다).
                for k, r in enumerate(rem):
                    r["pc_refs"] = [m for i, m in enumerate(missing) if i % len(rem) == k] or [missing[k % len(missing)]]
            el["remediation"] = rem if missing else []
        el.pop("proven_dimensions", None); el.pop("missing_dimensions", None)
        el["pc_summary"] = [{"ref": r, "summary": "변환 픽스처 — 요약 없음"} for r in refs]
    return new


def main() -> None:
    rb = get_rubric()
    DST.mkdir(parents=True, exist_ok=True)
    with session_scope() as s:
        for f in sorted(SRC.glob("R2026-*.json")):
            case = f.stem
            sid = s.execute(text("SELECT id FROM submission WHERE case_number=:c"), {"c": case}).scalar()
            if sid is None:
                print(f"{case}: 접수 없음 — 건너뜀 (scripts/load_demo.py 먼저)"); continue
            pkg = build_package(s, sid)
            out = json.loads(f.read_text(encoding="utf-8"))
            new = convert(out, pkg)
            rep = validate_track_b(pkg, new, rb)
            errs = rep.by_code("error")
            print(f"{case}: 요소 {len(new['elements'])} · 오류 {sum(errs.values())} {dict(errs) if errs else ''} · 경고 {sum(rep.by_code('warn').values())}")
            if errs:
                raise SystemExit(f"{case} 변환본이 검증을 통과하지 못했다")
            (DST / f.name).write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
            for extra in sorted(SRC.glob(f"{case}-*.json")):      # 재요청용 -2/-3 파일
                n2 = convert(json.loads(extra.read_text(encoding="utf-8")), pkg)
                (DST / extra.name).write_text(json.dumps(n2, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"  {extra.name} 변환")


if __name__ == "__main__":
    main()
