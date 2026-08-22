"""보고서에서 무엇을 전문가 검토로 넘길 것인가 — 선별 규칙 한 자리.

## 왜 추리는가

보고서는 요소를 빠짐없이 싣는다. 그래야 근거가 된다.
그러나 **사람이 판단할 것은 그중 일부**다. 훈련이수증에 능력단위코드·시간·
평가결과가 적혀 있어 규칙으로 확정된 항목은 다시 판단할 여지가 없다.
실측으로 33개 중 15개가 그랬다. 그 15개까지 한 줄씩 누르게 하면 정작
따져야 할 18개에 쓸 힘이 흩어진다.

## 세 갈래

  look    먼저 보실 것 — 결정과 어긋나는 자료가 있다
  judge   판단이 필요한 것 — 근거를 보고 인정 여부를 정한다
  settled 기록으로 확정된 것 — 확인만 하면 된다

`look` 을 「부정 진술이 있음」으로 잡으면 절반이 걸려 선별이 되지 않는다
(33개 중 17개였다). 정작 봐야 할 것은 **결정과 어긋나는 자료가 있는데도
그렇게 정해진 것**이다. 예: 훈련 기록으로 기이수 확정됐는데 반장 확인서에는
「그 자세는 담당한 적 없다」.
"""
from __future__ import annotations

from typing import Any

LOOK, JUDGE, SETTLED = "look", "judge", "settled"

# 화면에 그대로 쓰는 말. 묶음 제목·설명·배지 색.
BUCKETS: list[tuple[str, str, str, str, bool]] = [
    (LOOK, "먼저 보실 것",
     "결정과 어긋나는 자료가 있습니다. 그대로 두실지 내리실지 정해 주세요", "no", True),
    (JUDGE, "판단이 필요한 것",
     "근거를 보시고 인정 여부를 정하십시오", "wn", True),
    (SETTLED, "기록으로 확정된 것",
     "훈련이수증에 능력단위코드·시간·평가결과가 적혀 있어 규칙대로 정해진 항목입니다. "
     "확인만 하시면 됩니다", "ok", False),
]


def bucket(payload: dict[str, Any]) -> str:
    """요소 하나가 어느 갈래인지."""
    odd = (bool(payload.get("conflicts"))
           or bool(payload.get("needs_expert_review"))
           or (payload.get("decided_by") == "rule"
               and bool(payload.get("negative_statements"))))
    if odd:
        return LOOK
    return SETTLED if payload.get("decided_by") == "rule" else JUDGE


def needs_judgment(payload: dict[str, Any]) -> bool:
    """사람이 따져야 하는가. 확정된 것은 확인만 하면 된다."""
    return bucket(payload) != SETTLED


def split(elements: list[dict]) -> dict[str, list[dict]]:
    """요소 목록을 세 갈래로. 키가 없어도 빈 목록이 오게 미리 만들어 둔다."""
    out: dict[str, list[dict]] = {k: [] for k, *_ in BUCKETS}
    for x in elements:
        out[bucket(x.get("payload") or {})].append(x)
    return out


def counts(elements: list[dict]) -> dict[str, int]:
    return {k: len(v) for k, v in split(elements).items()}
