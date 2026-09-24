"""단계 마감 — 손대지 않은 것을 기본값으로 확정한다.

## 왜 마감인가

항목마다 「받음/못 받음」을 찍게 했더니 이런 말을 들었다 —

  「파일 선택해서 올리면 받은 거고 아니면 못 받은 건데
   이걸 일일이 체크해야 하는 이유를 모르겠다」

맞는 말이다. 올린 것은 받은 것이고, 안 올린 것은 못 받은 것이다. 다만
시스템은 **언제 기다리기를 그만두는지** 알 수 없다. 그래서 단계마다
「마감」 하나를 둔다. 손댄 것은 그대로 두고, 손대지 않은 것만 기본값으로
확정한다. 클릭 한 번으로 끝난다.

| 단계 | 손댄 것 | 마감하면 손대지 않은 것 |
|---|---|---|
| 1 인정 여부 | 사람이 정한 판정 | **AI 권고대로** 확정 |
| 2 추가 서류 | 파일을 올린 항목 = 받음 | 못 받음 → 면접·실기로 이월 |
| 3 면접 | 통과로 표시한 항목 | 미통과 |
| 4 실기 | 통과로 표시한 항목 | 미통과 |

## 1단계 기본값이 왜 AI 권고인가

실측 R2026-0004 에서 심사위원이 2·3·4단계를 다 돌고도 **최종 결과가
0시간**이었다. 1단계를 한 번도 누르지 않았기 때문이다 — 보완 항목 결과는
「조건부인정」인 요소에만 효력이 있는데 그 요소가 하나도 없었다.

권고를 기본값으로 두면 사람은 **다르게 볼 것만** 고르면 된다. 마감 버튼이
사람의 서명이다 — 무엇을 그대로 채택했는지 감사 기록에 남는다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from krpl_core.audit import AuditStore
from services.review.context import load
from services.review.stages import METHOD_OF_STAGE, save_result
from services.review.service import save_element_review

# AI 권고 → 1단계에서 손대지 않았을 때 그대로 채택할 판정
DEFAULT_OF = {
    "R0": "인정",          # 기이수 — 이미 평가를 마침
    "R1": "인정",          # 낸 서류로 판단 가능
    "R2": "조건부인정",     # 면접으로 확인
    "R3": "조건부인정",     # 실기로 확인
    "R4": "조건부인정",     # 추가서류 받고 재판단
    "R5": "불인정",        # 훈련 이수 필요
}
ADOPTED = "심사위원 합의 — AI 권고 채택"
NOT_RECEIVED = "마감 시점까지 받지 못함"
NOT_PASSED = "마감 시점까지 통과로 표시되지 않음"


@dataclass
class Closed:
    stage: int
    settled: int = 0                      # 기본값으로 확정한 수
    already: int = 0                      # 이미 손댄 수
    detail: list[dict] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.settled + self.already


def preview(s: Session, assessment_id: int, stage: int) -> Closed:
    """마감하면 무엇이 어떻게 되는지. 누르기 전에 보여 준다."""
    return _run(s, assessment_id, stage, apply=False)


def close(s: Session, assessment_id: int, stage: int) -> Closed:
    """마감한다. 손댄 것은 건드리지 않는다."""
    out = _run(s, assessment_id, stage, apply=True)
    ctx = load(s, assessment_id)
    if ctx is not None:
        store = AuditStore(s, ctx.case_number, ctx.submission_id, assessment_id)
        store.write("review", f"{stage}단계_마감",
                    {"단계": stage, "기본값으로_확정": out.settled,
                     "이미_정한_것": out.already, "내역": out.detail},
                    seq=10 + stage,
                    note=f"{stage}단계 마감 · 기본값 {out.settled}건 · 이미 정한 것 {out.already}건")
        s.execute(text("""INSERT INTO audit_log (entity, entity_id, action, actor, detail)
                          VALUES ('assessment', :i, :a, '심사위원 합의', CAST(:d AS jsonb))"""),
                  {"i": str(assessment_id), "a": f"{stage}단계_마감",
                   "d": json.dumps({"기본값으로_확정": out.settled,
                                    "이미_정한_것": out.already}, ensure_ascii=False)})
    return out


def _run(s: Session, assessment_id: int, stage: int, *, apply: bool) -> Closed:
    ctx = load(s, assessment_id)
    if ctx is None:
        raise LookupError(f"검토를 찾을 수 없습니다: assessment_id={assessment_id}")
    if stage not in (1, 2, 3, 4):
        raise ValueError(f"1~4 단계만 마감합니다: {stage}")
    out = Closed(stage=stage)

    if stage == 1:
        for x in ctx.judge_pool:
            eid = x["element_id"]
            if eid in ctx.reviews:
                out.already += 1
                continue
            want = DEFAULT_OF.get(x["recommendation"] or "", "조건부인정")
            out.settled += 1
            out.detail.append({"요소": x["_en"], "권고": x["recommendation"],
                               "확정": want})
            if apply:
                save_element_review(s, assessment_id, eid, want,
                                    note=ADOPTED, reviewer="심사위원 합의")
        return out

    method = METHOD_OF_STAGE[stage]
    live, _moot = ctx.split_items(method)
    for it in live:
        if it.done:
            out.already += 1
            continue
        out.settled += 1
        out.detail.append({"항목": it.item[:60], "확정": "미통과"})
        if apply:
            save_result(s, assessment_id, it.key, method, it.item, "미통과",
                        note=NOT_RECEIVED if stage == 2 else NOT_PASSED,
                        reviewer="심사위원 합의")
    return out
