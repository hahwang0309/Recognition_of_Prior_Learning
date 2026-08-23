"""전문가 검토 5단계 — 보완 항목을 모으고, 결과를 요소 인정으로 계산한다.

## 왜 단계로 나누는가

요소 서른세 개에 한꺼번에 가·부를 찍으라고 하면 무엇부터 볼지 알 수 없다.
심사는 실제로 순서가 있는 일이다 — 먼저 서류만으로 판단할 것을 정하고,
남은 것 중 서류를 더 받으면 풀리는 것을 추리고, 그래도 남으면 면접,
그래도 남으면 실기를 본다. 화면이 그 순서를 따라간다.

  1 인정검토   판단이 필요한 요소에 인정 여부를 정한다
  2 추가서류   인정 안 된 것 중 서류를 받으면 풀리는 것
  3 면접       화상면접으로 확인할 것 + 질문지
  4 실기       대면 실기로 확인할 것 + 과제 목록
  5 최종       무엇이 얼마나 인정됐는지, 무엇 때문에 그렇게 됐는지

## 보완 항목은 요소가 아니라 항목 단위로 다룬다

「안전보건교육 이수확인서」 한 건이 5개 능력단위 15개 요소를 한꺼번에 푼다.
요소마다 따로 물으면 같은 서류를 열다섯 번 확인하는 꼴이 된다.

## 결과는 계산이다

항목을 통과했으면 그 항목이 채우기로 한 KSA 가 채워진 것이므로 요소 인정은
따로 누를 것이 없다. 한 요소에 면접·실기가 둘 다 걸렸으면 둘 다 통과해야 한다.
「무엇을 보고 그렇게 됐는지」는 5단계와 감사 기록에 남긴다.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.review.triage import needs_judgment

# 단계 — (번호, 열쇠말, 화면 제목, 한 줄 설명)
STAGES: list[tuple[int, str, str, str]] = [
    (1, "judge", "인정 여부 검토", "제출 자료만으로 판단할 수 있는 것을 먼저 정합니다"),
    (2, "docs", "추가 서류", "서류를 더 받으면 풀리는 것을 추립니다"),
    (3, "oral", "면접", "화상면접으로 확인할 것과 질문지"),
    (4, "practical", "실기", "대면 실기로 확인할 것과 과제"),
    (5, "final", "최종 결과", "무엇이 얼마나 인정됐는지"),
]
STAGE_OF = {k: n for n, k, *_ in STAGES}
KEY_OF = {n: k for n, k, *_ in STAGES}
TITLE_OF = {n: t for n, _, t, _ in STAGES}
# 단계 ↔ 보완 방법
METHOD_OF_STAGE = {2: "추가서류", 3: "면접", 4: "실기"}

RESULTS = ("통과", "미통과", "미실시")
# 1단계에서 이 판정이 나면 더 볼 것이 없다.
SETTLED_DECISIONS = {"인정", "불인정"}


def item_key(method: str, item: str) -> str:
    """항목 글 자체로 이름을 만든다 — 판정을 다시 돌려도 같은 항목은 같은 이름."""
    raw = f"{method} {(item or '').strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class Item:
    """보완 항목 하나. 여러 요소에 걸쳐 병합된 것."""
    key: str
    method: str
    item: str
    reason: str = ""
    alt_document: str | None = None
    oral_check: list[str] = field(default_factory=list)
    targets: list[dict] = field(default_factory=list)   # {eid, unit_code, unit, element, ksa}
    result: str | None = None
    note: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None

    @property
    def n_elements(self) -> int:
        return len({t["eid"] for t in self.targets})

    @property
    def n_units(self) -> int:
        return len({t["unit_code"] for t in self.targets})

    @property
    def n_ksa(self) -> int:
        return sum(len(t["ksa"]) for t in self.targets)

    @property
    def units(self) -> list[str]:
        seen: dict[str, None] = {}
        for t in self.targets:
            seen.setdefault(t["unit"], None)
        return list(seen)

    @property
    def done(self) -> bool:
        return self.result in RESULTS

    @property
    def passed(self) -> bool:
        return self.result == "통과"


def collect_items(els: list[dict], names: dict[str, tuple[str, str]] | None = None
                  ) -> dict[str, list[Item]]:
    """요소들의 remediation 을 방법별·항목별로 병합한다.

    같은 글의 항목은 하나로 묶고 대상 요소를 모은다. 대체서류·구술 질문은
    먼저 나온 것을 쓰되, 비어 있으면 뒤에 나온 것으로 채운다.
    """
    names = names or {}
    by_method: dict[str, dict[str, Item]] = {}
    for x in els:
        eid = x["element_id"]
        p = x.get("payload") or {}
        un, en = names.get(eid, (None, None))
        un = un or p.get("unit_name") or eid.split("_")[0]
        en = en or p.get("element_name") or eid
        for r in p.get("remediation") or []:
            if not isinstance(r, dict):
                continue
            m, txt = r.get("method") or "", (r.get("item") or "").strip()
            if not m or not txt:
                continue
            k = item_key(m, txt)
            it = by_method.setdefault(m, {}).get(k)
            if it is None:
                it = Item(key=k, method=m, item=txt, reason=r.get("reason") or "",
                          alt_document=r.get("alt_document"),
                          oral_check=list(r.get("oral_check") or []))
                by_method[m][k] = it
            else:
                if not it.alt_document and r.get("alt_document"):
                    it.alt_document = r["alt_document"]
                for q in r.get("oral_check") or []:
                    if q not in it.oral_check:
                        it.oral_check.append(q)
            it.targets.append({"eid": eid, "unit_code": eid.split("_")[0],
                               "unit": un, "element": en,
                               "ksa": list(r.get("ksa_refs") or [])})
    return {m: sorted(v.values(), key=lambda i: (-i.n_elements, i.item))
            for m, v in by_method.items()}


def load_results(s: Session, assessment_id: int) -> dict[str, dict[str, Any]]:
    return {r["item_key"]: dict(r) for r in s.execute(text("""
        SELECT item_key, method, item, result, note, decided_by, decided_at
        FROM remediation_result WHERE assessment_id=:a"""),
        {"a": assessment_id}).mappings()}


def apply_results(items: dict[str, list[Item]], results: dict[str, dict]) -> None:
    for group in items.values():
        for it in group:
            if (r := results.get(it.key)) is not None:
                it.result, it.note = r["result"], r["note"]
                it.decided_by, it.decided_at = r["decided_by"], r["decided_at"]


def save_result(s: Session, assessment_id: int, key: str, method: str, item: str,
                result: str, *, note: str | None = None,
                reviewer: str | None = None) -> None:
    """항목 결과를 기록한다. 같은 항목을 다시 찍으면 덮어쓴다."""
    if result not in RESULTS:
        raise ValueError(f"모르는 결과입니다: {result} (가능: {', '.join(RESULTS)})")
    s.execute(text("""
        INSERT INTO remediation_result
            (assessment_id, item_key, method, item, result, note, decided_by, decided_at)
        VALUES (:a, :k, :m, :i, :r, :n, :w, now())
        ON CONFLICT (assessment_id, item_key) DO UPDATE
        SET result=EXCLUDED.result, note=EXCLUDED.note,
            decided_by=EXCLUDED.decided_by, decided_at=now()"""),
        {"a": assessment_id, "k": key, "m": method, "i": item,
         "r": result, "n": note, "w": reviewer})


# ── 요소 인정 계산 ────────────────────────────────────────────────

@dataclass
class Outcome:
    """요소 하나의 최종 상태와 그렇게 된 이유."""
    element_id: str
    unit_code: str
    unit: str
    element: str
    decision: str                                    # 인정 | 미인정 | 대기
    basis: list[str] = field(default_factory=list)   # 왜 그렇게 됐는지 한 줄씩
    reviewer_decision: str | None = None             # 1단계에서 사람이 정한 것

    @property
    def recognized(self) -> bool:
        return self.decision == "인정"


def _short(t: str, n: int = 34) -> str:
    t = (t or "").strip()
    return t if len(t) <= n else t[:n] + "…"


def outcomes(els: list[dict], reviews: dict[str, dict],
             items: dict[str, list[Item]],
             names: dict[str, tuple[str, str]] | None = None) -> list[Outcome]:
    """요소마다 지금 어떤 상태이고 무엇 때문에 그런지.

    ① 1단계에서 인정·불인정으로 정해졌으면 그대로다.
    ② 조건부인정이면 그 요소에 걸린 보완 항목이 **전부** 통과해야 인정이다.
       하나라도 미통과면 미인정, 아직 안 찍힌 것이 있으면 대기.
    ③ 훈련 항목이 걸려 있으면 확인으로 풀리지 않는다 — 미인정.
    """
    names = names or {}
    per_el: dict[str, list[Item]] = {}
    for group in items.values():
        for it in group:
            for t in it.targets:
                per_el.setdefault(t["eid"], []).append(it)

    out: list[Outcome] = []
    for x in els:
        eid = x["element_id"]
        p = x.get("payload") or {}
        un, en = names.get(eid, (None, None))
        o = Outcome(element_id=eid, unit_code=eid.split("_")[0],
                    unit=un or p.get("unit_name") or eid.split("_")[0],
                    element=en or p.get("element_name") or eid,
                    decision="대기")
        rv = reviews.get(eid) or {}
        o.reviewer_decision = rv.get("decision")

        # 1단계에서 묻지 않은 것 — 훈련이수증에 능력단위코드·시간·평가결과가
        # 적혀 있어 규칙으로 확정된 항목이다. 판단할 여지가 없으므로 인정이다.
        # 이것을 「대기」로 두면 사람이 찍지도 않은 것 때문에 능력단위 시간이
        # 영영 붙지 않는다 (실측: 33개 중 15개가 그래서 0시간이 됐다).
        if o.reviewer_decision is None and not needs_judgment(p):
            o.decision = "인정"
            pl = p.get("prior_learning") or {}
            if pl.get("completed_hours") and pl.get("required_hours"):
                o.basis.append(
                    f"이수 기록으로 확정 — 요구 {pl['required_hours']}시간 대비 "
                    f"{pl['completed_hours']}시간 이수"
                    f"({pl['completed_hours'] / pl['required_hours']:.0%})"
                    + (f", 내부평가 {pl['evaluation']}" if pl.get("evaluation") else ""))
            else:
                o.basis.append("이수 기록으로 확정 — 판단할 여지가 없는 항목")
            out.append(o)
            continue

        if o.reviewer_decision in SETTLED_DECISIONS:
            o.decision = "인정" if o.reviewer_decision == "인정" else "미인정"
            o.basis.append(f"전문가 판단 — {o.reviewer_decision}")
            out.append(o)
            continue
        if o.reviewer_decision == "보류":
            o.basis.append("전문가 판단 — 보류. 자료를 더 받은 뒤 다시 봅니다")
            out.append(o)
            continue
        if o.reviewer_decision is None:
            o.basis.append("아직 판단하지 않았습니다")
            out.append(o)
            continue

        # 조건부인정 — 걸린 보완 항목이 전부 통과해야 한다
        mine = per_el.get(eid) or []
        if not mine:
            o.decision = "인정"
            o.basis.append("전문가 판단 — 조건부인정, 남은 확인 항목 없음")
            out.append(o)
            continue
        failed = [i for i in mine if i.result == "미통과"]
        train = [i for i in mine if i.method == "훈련"]
        waiting = [i for i in mine if not i.done and i.method != "훈련"]
        if train:
            o.decision = "미인정"
            o.basis += [f"훈련 이수 필요 — {_short(i.item, 44)}" for i in train]
        elif failed:
            o.decision = "미인정"
            o.basis += [f"{i.method} 「{_short(i.item)}」 미통과"
                        + (f" ({i.decided_at:%Y-%m-%d})" if i.decided_at else "")
                        for i in failed]
        elif waiting:
            o.decision = "대기"
            o.basis += [f"{i.method} 「{_short(i.item)}」 결과 대기" for i in waiting]
        else:
            o.decision = "인정"
            o.basis += [f"{i.method} 「{_short(i.item)}」 통과"
                        + (f" ({i.decided_at:%Y-%m-%d})" if i.decided_at else "")
                        for i in mine if i.passed]
            if not o.basis:
                o.basis.append("남은 확인 항목이 모두 정리됨")
        out.append(o)
    return out


# ── 단계 진척 ────────────────────────────────────────────────────

@dataclass
class StageState:
    n: int
    key: str
    title: str
    hint: str
    total: int = 0          # 이 단계에서 다룰 것의 수
    done: int = 0           # 그중 처리된 수
    skipped: bool = False   # 다룰 것이 없어 건너뛰는 단계

    @property
    def complete(self) -> bool:
        return self.skipped or (self.total > 0 and self.done >= self.total)


def stage_states(judge_total: int, judge_done: int,
                 items: dict[str, list[Item]]) -> list[StageState]:
    out: list[StageState] = []
    for n, key, title, hint in STAGES:
        st = StageState(n=n, key=key, title=title, hint=hint)
        if n == 1:
            st.total, st.done = judge_total, judge_done
            st.skipped = judge_total == 0
        elif n in METHOD_OF_STAGE:
            group = items.get(METHOD_OF_STAGE[n]) or []
            st.total = len(group)
            st.done = sum(1 for i in group if i.done)
            st.skipped = st.total == 0
        out.append(st)
    return out


def next_open_stage(states: list[StageState]) -> int:
    """다음에 손댈 단계. 다 끝났으면 5(최종)."""
    for st in states:
        if st.n < 5 and not st.complete:
            return st.n
    return 5
