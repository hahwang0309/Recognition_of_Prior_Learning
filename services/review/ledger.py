"""인정 원장 — 총 필수 시간이 어느 경로로 갔는지 한 자리에서 낸다.

## 왜 원장인가

5단계 「최종 결과」에 요소 서른 줄짜리 표 하나뿐이었다. 근거는 되지만
종합이 아니다. 심사위원이 서명 직전에 알고 싶은 것은 이것이다 —

  이 사람의 420시간 가운데
    기록으로 인정된 것이 얼마고, 낸 서류로 인정된 것이 얼마고,
    면접으로 확인할 것이 얼마고, 실기로 확인할 것이 얼마고,
    그래도 안 되면 훈련으로 들어야 할 것이 얼마인가.

## 규칙 하나

**총 필수 시간의 1시간도 빠짐없이 정확히 하나의 경로에 속한다.** 합이
총 필수 시간과 다르면 그것은 결함이다. 시험이 그것만 붙든다.

## 경로를 어떻게 가르나

능력단위 하나가 한 줄이다. 시간은 능력단위에 붙기 때문이다
(`unit_credit_rule: all_elements`, 쟁점 D-7 미확정).

  ① 기록  기록 확인(Track A)이 자격 편성시간·훈련이수증으로 갈음한 단위
  ② 서류  제출 자료만으로 요소가 전부 인정된 단위
  ③ 면접  면접으로 확인했거나 확인할 단위
  ④ 실기  실기로 확인했거나 확인할 단위
  ⑤ 훈련  확인으로 풀리지 않아 훈련으로 채워야 하는 단위
  ⑥ 미정  아직 1단계 판단이 안 된 단위

## 면접과 실기가 한 단위에 섞이면

등화장치처럼 요소 넷 가운데 둘은 면접, 둘은 실기인 단위가 있다. 시간은
단위에 붙으므로 한쪽에만 넣어야 합이 맞는다. **요소가 많은 쪽**에 넣고
(같으면 실기), 줄에는 「면접 2 · 실기 2」로 둘 다 적는다. 숨기지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from services.review.context import ReviewContext

# 경로 — 표시 순서대로. (열쇠, 화면 이름, 한 줄 설명)
PATHS: list[tuple[str, str, str]] = [
    ("기록", "기록으로 인정", "보유 자격 편성시간과 훈련 이수 기록으로 갈음된 시간"),
    ("서류", "제출 서류로 인정", "낸 자료만으로 요소가 모두 인정된 시간"),
    ("면접", "면접으로 확인", "화상면접으로 확인했거나 확인할 시간"),
    ("실기", "실기로 확인", "대면 실기로 확인했거나 확인할 시간"),
    ("훈련", "훈련으로 채워야 함", "확인으로는 풀리지 않는 시간"),
    ("미정", "아직 정하지 않음", "1단계 판단이 남은 시간"),
]
PATH_NAME = {k: n for k, n, _ in PATHS}
PATH_HINT = {k: h for k, _, h in PATHS}
# 인정으로 세는 경로 — 확인이 끝난 면접·실기는 줄마다 따로 본다
CREDITED = ("기록", "서류")


@dataclass
class Row:
    """능력단위 한 줄."""
    unit_code: str
    unit: str
    hours: int
    path: str                                   # 위 여섯 가운데 하나
    state: str                                  # 인정 | 확인 예정 | 훈련 필요 | 미정
    why: list[str] = field(default_factory=list)      # 근거 한 줄씩
    methods: dict[str, int] = field(default_factory=dict)  # 면접 2 · 실기 2
    stage: int = 5                              # 이 판단이 온 단계 (되돌아가는 링크)
    n_elements: int = 0
    n_denied: int = 0
    flag: str = ""                              # 짚어야 할 것
    audit_id: int | None = None                 # 이 판단이 나온 AI 응답 원본

    @property
    def recognized(self) -> bool:
        """지금 이 시간이 인정 시간에 들어가 있나."""
        return self.state == "인정"

    @property
    def method_line(self) -> str:
        if len(self.methods) <= 1:
            return ""
        return " · ".join(f"{m} {n}" for m, n in
                          sorted(self.methods.items(), key=lambda x: -x[1]))


@dataclass
class Ledger:
    rows: list[Row]
    total_hours: int
    recognized_hours: int

    def by_path(self, key: str) -> list[Row]:
        return [r for r in self.rows if r.path == key]

    def hours(self, key: str) -> int:
        return sum(r.hours for r in self.rows if r.path == key)

    @property
    def sum_hours(self) -> int:
        return sum(r.hours for r in self.rows)

    @property
    def balanced(self) -> bool:
        """모든 시간이 정확히 한 경로에 들어갔나. 아니면 결함이다."""
        return self.sum_hours == self.total_hours

    @property
    def open_paths(self) -> list[tuple[str, int, int]]:
        """아직 안 끝난 것 — (경로, 시간, 능력단위 수)."""
        return [(k, self.hours(k), len(self.by_path(k)))
                for k in ("면접", "실기", "훈련", "미정")
                if self.hours(k) or self.by_path(k)]

    def pct(self, h: int) -> float:
        return h / self.total_hours * 100 if self.total_hours else 0.0


def _track_a_why(ctx: ReviewContext, code: str) -> list[str]:
    """기록 확인이 이 단위를 무엇으로 갈음했나."""
    p = ctx.track_a_units.get(code) or {}
    got, need = p.get("completed_hours"), p.get("required_hours")
    lv = p.get("verdict") or ""
    src = p.get("source") or ""
    if got is None or not need:
        return [f"기록 확인 — {lv}" if lv else "기록 확인으로 갈음"]
    ratio = got / need
    head = f"{src or '기록'} {got}시간 / 요구 {need}시간 ({ratio:.0%}) — {lv}"
    if p.get("evaluation"):
        head += f", 내부평가 {p['evaluation']}"
    return [head]


def build(ctx: ReviewContext) -> Ledger:
    """검토 한 건을 원장으로. 계산은 여기서만 한다."""
    got = ctx.outcome_of
    per_el: dict[str, list] = {}
    for group in ctx.items.values():
        for it in group:
            if it.superseded:
                continue
            for t in it.targets:
                per_el.setdefault(t["eid"], []).append(it)

    rows: list[Row] = []
    for code, eids in ctx.by_unit().items():
        hours = ctx.hours.get(code, 0)
        unit = next((x["_un"] for x in ctx.elements
                     if x["element_id"] == eids[0]), code)
        ds = [got.get(i) for i in eids]
        n_denied = sum(1 for d in ds if d == "미인정")
        row = Row(unit_code=code, unit=unit, hours=hours, path="미정",
                  state="미정", n_elements=len(eids), n_denied=n_denied,
                  audit_id=ctx.unit_artifact.get(code))

        # ① 기록 확인이 갈음한 단위 — 검토 결과와 상관없이 시간이 붙는다
        if code in ctx.credited_units:
            row.path, row.state, row.stage = "기록", "인정", 1
            row.why = _track_a_why(ctx, code)
            if n_denied:
                row.flag = (f"시간은 갈음됐으나 요소 {n_denied}/{len(eids)}개가 "
                            f"미인정입니다 — 이 시간을 그대로 인정할지 정하십시오")
            rows.append(row)
            continue

        # ② 확인 방법 — 이 단위를 실제로 푼(또는 풀) 것
        methods: dict[str, int] = {}
        for i in eids:
            for it in per_el.get(i, ()):
                if it.method in ("면접", "실기", "추가서류", "훈련"):
                    methods[it.method] = methods.get(it.method, 0) + 1
        row.methods = {m: n for m, n in methods.items() if m in ("면접", "실기")}

        if any(d == "미인정" for d in ds):
            row.path, row.state, row.stage = "훈련", "훈련 필요", 1
            row.why = _reasons(ctx, eids, "미인정")
            rows.append(row)
            continue

        if any(d != "인정" for d in ds):                 # 대기 또는 미판단
            unjudged = [i for i in eids if i not in ctx.reviews
                        and needs(ctx, i)]
            if unjudged:
                row.path, row.state, row.stage = "미정", "미정", 1
                row.why = [f"1단계 판단이 남았습니다 — 요소 {len(unjudged)}개"]
            else:
                row.path = _pick(row.methods) or "서류"
                row.state, row.stage = "확인 예정", _stage_of(row.path)
                row.why = _reasons(ctx, eids, "대기")
            rows.append(row)
            continue

        # ③ 전부 인정 — 무엇이 풀었나
        row.state = "인정"
        row.path = _pick(row.methods) or "서류"
        row.stage = _stage_of(row.path)
        row.why = _reasons(ctx, eids, "인정")
        rows.append(row)

    rows.sort(key=lambda r: (-r.hours, r.unit_code))
    rec = sum(r.hours for r in rows if r.state == "인정")
    return Ledger(rows=rows, total_hours=ctx.total_hours, recognized_hours=rec)


def needs(ctx: ReviewContext, eid: str) -> bool:
    from services.review.triage import needs_judgment
    p = next((x["payload"] or {} for x in ctx.elements
              if x["element_id"] == eid), {})
    return needs_judgment(p)


def _pick(methods: dict[str, int]) -> str:
    """면접과 실기가 섞이면 요소가 많은 쪽. 같으면 실기 — 더 무거운 확인이다."""
    if not methods:
        return ""
    return max(methods.items(), key=lambda x: (x[1], x[0] == "실기"))[0]


def _stage_of(path: str) -> int:
    return {"면접": 3, "실기": 4, "서류": 2}.get(path, 1)


def _reasons(ctx: ReviewContext, eids: list[str], want: str) -> list[str]:
    """그 상태가 된 이유를 요소별로 모아 겹치는 것은 한 번만."""
    seen: list[str] = []
    for o in ctx.outcomes:
        if o.element_id not in eids or o.decision != want:
            continue
        for b in o.basis:
            if b not in seen:
                seen.append(b)
    return seen[:4]
