"""부족한 능력단위를 위원이 메운다 — 인정선을 넘었나가 전부다.

## 셈

    인정시간 = min(이수, 요구) + 위원 추가 인정      ← 비율의 분자
    비율     = 인정시간 ÷ 요구시간
    면제시간 = 비율 ≥ 50% 이면 **요구시간 전체**, 미만이면 0

**합산이 아니라 게이트다.** 45h 를 인정했다고 45h 가 면제되는 것이 아니다.
요구 80h 짜리 단위에 45h(56%)를 인정하면 그 단위는 「인정 능력단위」가 되고
요구시간 **80h 전체**가 면제된다. 44h(55%)여도 마찬가지, 39h(49%)면 0h 다.

## 왜 이 규칙인가

기준서가 이미 그렇게 적고 있다 — `track_a.verdicts` 의

    조정범위내  ratio_gte: 0.5
    "훈련기준 「−50%까지 조정 가능」 조항 적용 — 요구시간 전체 인정"

지금까지 그 비율을 **이수시간만**으로 쟀다. 여기서는 분자에 **위원이 추가로
인정한 시간**을 더해 같은 게이트를 통과시킨다. 기준 수치는 고치지 않는다.

## 이것이 Track A 의 두 번째 단계다

Track A 와 B 는 접수부터 다른 경로다. 근거 분석은 B 가 아니라 **Track A 안의
2단계** — ① 기록 확인(NCS 코드 비교)으로 안 덮인 부분을, 그 밖의 자료로 메울 수
있는지 보는 자리다. 최종 판정은 사람이 한다.

## 숫자를 말하는 자리는 하나다

화면·보고서·최종 판정이 모두 `compute_gaps()` 만 읽는다. 각자 세면 반드시
갈라진다 — 실제로 그런 일이 네 군데 있었다(README 참고).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

# 위원이 채워야 하는 판정들. 50% 이상(완전충족·조정범위내)은 규칙이 이미
# 요구시간 전체를 인정했으므로 판단할 것이 없다.
NEEDS_REVIEW = ("보류", "시간부족", "미이수")


def credit_floor() -> float:
    """인정선. 기준서에서 읽는다 — 코드에 0.5 를 박으면 기준을 고쳐도 안 따라온다."""
    from krpl_core.config import get_rubric
    for v in get_rubric().track_a["verdicts"]:
        if v["id"] == "조정범위내":
            return float(v["when"]["ratio_gte"])
    raise KeyError("기준서에 조정범위내 구간이 없다")


@dataclass(frozen=True)
class UnitGap:
    """능력단위 하나의 시간 셈. 면제는 합산이 아니라 게이트다."""
    unit_code: str
    unit_name: str
    verdict: str
    required: int
    completed: int
    ratio: float | None               # 기록만으로 잰 비율 (기록 확인이 낸 값)
    granted: int                      # 위원이 인정한 시간 (부족분 안으로 잘린 값)
    floor: float                      # 인정선 — 기준서에서 온 값

    @property
    def record(self) -> int:
        """이수 기록이 비율에 보태는 몫. **면제시간이 아니다.**"""
        return min(self.completed, self.required)

    @property
    def gap(self) -> int:
        """위원이 채울 수 있는 최대."""
        return self.required - self.record

    @property
    def counted(self) -> int:
        """인정시간 = 기록 + 위원. 비율의 분자."""
        return self.record + self.granted

    @property
    def ratio_final(self) -> float:
        return self.counted / self.required if self.required else 0.0

    @property
    def passes(self) -> bool:
        return bool(self.required) and self.ratio_final >= self.floor

    @property
    def credited(self) -> int:
        """면제시간. 인정선을 넘으면 요구시간 전체, 아니면 0."""
        return self.required if self.passes else 0

    @property
    def to_pass(self) -> int:
        """인정선까지 위원이 더 넣어야 하는 시간. 올림한다 — 요구 45h 의 절반은 23h."""
        if not self.required:
            return 0
        need = math.ceil(self.floor * self.required) - self.record
        return max(0, min(need, self.gap))


def compute_gaps(rows: Iterable[tuple[str, str, dict[str, Any]]],
                 granted: dict[str, int | None],
                 floor: float | None = None) -> list[UnitGap]:
    """기록 확인 판정의 요소 행에서 보완 대상 단위를 골라 셈한다.

    `rows` 는 `(element_id, evidence_level, payload)`. 기록 확인 판정에서
    element_id 는 **능력단위 코드**다.
    `granted` 는 `{능력단위코드: 위원이 적은 시간}` — 없거나 음수면 0 으로 본다.
    """
    line = credit_floor() if floor is None else floor
    out: list[UnitGap] = []
    for code, verdict, payload in rows:
        if verdict not in NEEDS_REVIEW:
            continue
        p = payload or {}
        required = int(p.get("required_hours") or 0)
        completed = int(p.get("completed_hours") or 0)
        gap = required - min(completed, required)
        want = granted.get(code)
        want = 0 if want is None or want < 0 else int(want)
        out.append(UnitGap(
            unit_code=code, unit_name=p.get("unit_name") or code, verdict=verdict,
            required=required, completed=completed, ratio=p.get("ratio"),
            granted=min(want, gap), floor=line))
    return out


def granted_hours(s: Session, time_aid: int) -> dict[str, int | None]:
    """저장된 위원 인정 시간. 기록 확인 판정에 요소별 검토로 쌓인다."""
    return {r[0]: r[1] for r in s.execute(text(
        "SELECT element_id, granted_hours FROM element_review WHERE assessment_id=:a"),
        {"a": time_aid})}


def unit_gaps(s: Session, time_aid: int) -> list[UnitGap]:
    """기록 확인 판정 하나의 보완 대상 단위 전부."""
    rows = [(r[0], r[1], r[2]) for r in s.execute(text(
        """SELECT element_id, evidence_level, payload FROM assessment_element
           WHERE assessment_id=:a ORDER BY element_id"""), {"a": time_aid})]
    return compute_gaps(rows, granted_hours(s, time_aid))


def evidence_aid(s: Session, submission_id: int) -> int | None:
    """근거를 가져올 판정. 검증을 통과 못 했어도(manual_review) 산출물은 쓴다."""
    return s.execute(text(
        """SELECT a.id FROM assessment a
           WHERE a.submission_id=:i AND a.kind='evidence'
             AND a.status IN ('done', 'manual_review')
             AND EXISTS (SELECT 1 FROM assessment_element e WHERE e.assessment_id=a.id)
           ORDER BY a.id DESC LIMIT 1"""), {"i": submission_id}).scalar()


def unit_evidence(s: Session, submission_id: int,
                  unit_codes: Iterable[str]) -> dict[str, list[dict[str, Any]]]:
    """능력단위별로 근거 분석이 뽑아 둔 조각을 모은다.

    근거 분석은 **능력단위요소** 단위로 판정하므로 카탈로그로 단위에 잇는다
    (`1403010108_14v2.1` → `1403010108`). 요소 이름도 함께 실어 위원이
    「어느 요소를 뒷받침하는 근거인지」 알 수 있게 한다.
    """
    codes = list(dict.fromkeys(unit_codes))
    out: dict[str, list[dict[str, Any]]] = {c: [] for c in codes}
    aid = evidence_aid(s, submission_id)
    if aid is None or not codes:
        return out

    unit_of = {r[0]: r[1] for r in s.execute(text(
        """SELECT e.element_id, e.unit_code FROM catalog_ncs_element e
           WHERE e.unit_code = ANY(:c)"""), {"c": codes})}

    # 같은 문장이 항목마다 되풀이된다. 실측 한 단위에서 같은 부정 진술이 41번
    # 나왔다 — 위원에게 41건으로 보이면 읽기를 포기한다. 인용·출처가 같으면
    # 한 줄로 묶고 어느 항목에 걸렸는지만 늘어놓는다.
    seen: dict[str, dict[str, dict[str, Any]]] = {c: {} for c in codes}
    for eid, payload in s.execute(text(
            """SELECT element_id, payload FROM assessment_element
               WHERE assessment_id=:a ORDER BY element_id"""), {"a": aid}):
        code = unit_of.get(eid)
        if code is None or code not in out:
            continue
        p = payload or {}
        for ev in (p.get("evidence") or []):
            fids = [f for f in (ev.get("fids") or []) if f]
            quote = ev.get("quote") or ""
            ref = ev.get("pc_ref") or ev.get("ksa_ref") or ""      # 신형(수행준거) / 구형(항목)
            key = f"{','.join(fids)}|{quote}|{ev.get('fit') or ''}"
            got = seen[code].get(key)
            if got is None:
                seen[code][key] = {
                    "element_id": eid,
                    "element_name": p.get("element_name") or "",
                    "quote": quote,
                    "why": ev.get("why") or "",
                    "fit": ev.get("fit") or "직접",   # 옛 결과에는 없다 — 직접으로 본다
                    "grade": ev.get("grade") or "",
                    "ksa_ref": ref,
                    "fids": fids,
                    "refs": [x for x in [ref] if x],
                    "elements": [p.get("element_name") or eid],
                    "n": 1,
                }
            else:
                got["n"] += 1
                r, el = ref, p.get("element_name") or eid
                if r and r not in got["refs"]:
                    got["refs"].append(r)
                if el not in got["elements"]:
                    got["elements"].append(el)
    for code in codes:
        out[code] = list(seen[code].values())
    return out


def save_unit_hours(s: Session, time_aid: int, hours: dict[str, int],
                    reviewer: str | None = None) -> list[UnitGap]:
    """위원이 적은 시간을 저장한다. 저장 뒤의 셈을 돌려준다.

    값은 **부족분 안으로 자른다.** 화면에서 막고 있지만, 저장 경로에서도 막지
    않으면 직접 부른 요청 하나로 요구시간을 넘는 인정이 들어간다.

    요소별 검토 표를 그대로 쓴다 — 기록 확인 판정의 element_id 가 능력단위
    코드이므로 행이 겹치지 않는다. `decision` 은 시간에서 유도한다(칸이
    NOT NULL 이고, 「몇 시간을 인정했나」가 곧 「인정했나」이기 때문이다).
    """
    gaps = {g.unit_code: g for g in unit_gaps(s, time_aid)}
    saved: list[str] = []
    for code, want in (hours or {}).items():
        g = gaps.get(code)
        if g is None:                      # 보완 대상이 아닌 단위는 받지 않는다
            continue
        want = 0 if want is None or int(want) < 0 else int(want)
        want = min(want, g.gap)
        rec = s.execute(text("""SELECT recommendation FROM assessment_element
                                WHERE assessment_id=:a AND element_id=:e"""),
                        {"a": time_aid, "e": code}).scalar()
        s.execute(text("""
            INSERT INTO element_review (assessment_id, element_id, decision,
                                        ai_recommendation, reviewer, granted_hours)
            VALUES (:a, :e, :d, :r, :w, :h)
            ON CONFLICT (assessment_id, element_id) DO UPDATE
            SET decision=EXCLUDED.decision, reviewer=EXCLUDED.reviewer,
                granted_hours=EXCLUDED.granted_hours, reviewed_at=now()"""),
            {"a": time_aid, "e": code, "d": "인정" if want else "불인정",
             "r": rec, "w": reviewer, "h": want})
        saved.append(code)

    if saved:
        s.execute(text("""INSERT INTO audit_log (entity, entity_id, action, actor, detail)
                          VALUES ('element_review', :i, 'unit_hours', :w, CAST(:d AS jsonb))"""),
                  {"i": str(time_aid), "w": reviewer or "unknown",
                   "d": json.dumps({c: int(hours.get(c) or 0) for c in saved},
                                   ensure_ascii=False)})
    return unit_gaps(s, time_aid)
