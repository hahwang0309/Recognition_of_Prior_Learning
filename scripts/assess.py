"""심사번호 하나를 Track B 로 판정한다.

  python scripts/assess.py R2026-0002 [--profile trackb_assess] [--force]

LLM 백엔드는 `KRPL_LLM_BACKEND` 가 정한다.
  replay     저장된 산출물 재생 (기본값 — 키가 없을 때). 비용 0
  anthropic  실제 호출. `ANTHROPIC_API_KEY` 필요
"""
from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import text

from krpl_core.db import session_scope
from krpl_core.llm import get_client
from krpl_core.config import get_model_profile
from services.assess.track_b_service import run_track_b


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("case", nargs="+", help="심사번호. 예: R2026-0002")
    ap.add_argument("--profile", default=None, help="config/models.yaml 프로필명")
    ap.add_argument("--force", action="store_true", help="이미 판정된 건도 다시 판정")
    ap.add_argument("--chunk-by", choices=("unit", "none"),
                    help="분할 방식을 이번 실행에만 바꾼다 (비교 측정용)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if a.chunk_by:
        from krpl_core.config import get_settings
        get_settings().assessment.chunk_by = a.chunk_by     # 이번 실행에만
    profile = get_model_profile(a.profile)
    client = get_client(profile)
    backend = type(client).__name__.replace("Client", "")
    from krpl_core.config import get_settings as _gs
    ac = _gs().assessment
    print(f"백엔드 {backend} · 모델 {profile.model} · effort {profile.effort} · "
          f"분할 {ac.chunk_by} · 상한 {profile.max_tokens:,}\n")

    rc = 0
    for case in a.case:
        with session_scope() as s:
            sid = s.execute(text("SELECT id FROM submission WHERE case_number=:c"),
                            {"c": case}).scalar()
            if sid is None:
                print(f"{case}: 접수 건 없음", file=sys.stderr)
                rc = 1
                continue
            if not a.force and s.execute(text("""
                    SELECT 1 FROM assessment WHERE submission_id=:i AND status='done'"""),
                    {"i": sid}).first():
                print(f"{case}: 이미 판정됨 (--force 로 재판정)", file=sys.stderr)
                continue
            aid = run_track_b(s, sid, client=client, profile_name=a.profile)
            r = s.execute(text("""SELECT status, attempts, cost_usd, overall_note
                                  FROM assessment WHERE id=:i"""), {"i": aid}).mappings().one()
            rec = dict(s.execute(text("""SELECT recommendation, count(*) FROM assessment_element
                                         WHERE assessment_id=:i GROUP BY 1 ORDER BY 1"""),
                                 {"i": aid}).all())
            ex = s.execute(text("""SELECT count(*) FROM assessment_element
                                   WHERE assessment_id=:i
                                     AND (payload->>'needs_expert_review')::bool"""),
                           {"i": aid}).scalar_one()

        import json
        note = json.loads(r["overall_note"])
        val = note["validation"]
        cost = f"${float(r['cost_usd']):.3f}" if r["cost_usd"] else "-"
        print(f"■ {case}  판정 {aid} · {r['status']} · 시도 {r['attempts']} · {cost}")
        print(f"   요소 {val['n_elements']}개 · 근거 {val['n_evidence']}건 · "
              f"검증 {'통과' if val['passed'] else '오류 %d' % val['n_errors']}")
        print(f"   권고 {rec}")
        print(f"   대면평가 {val['counts']['대면평가']['건수']}건 "
              f"(대체서류 제시 {val['counts']['대면평가']['대체서류제시']}건)")
        if ex:
            print(f"   ⚠ 전문가 확인 필요 {ex}건 — 미확정 기준(쟁점 4)에 걸림")
        if not val["passed"]:
            for k, v in val["by_code"].items():
                print(f"      {k} {v}")
            rc = 1
        print()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
