"""Track A 판정 엔진.

과정평가형 자격 등 NCS 기반 이수자를 능력단위·시간 대조로 판정한다.
LLM을 쓰지 않는다. DB에도 의존하지 않는 순수 함수 — 입력을 주면 판정만 한다.

판정 임계값과 권고 매핑은 코드가 아니라 config/rubric/*.yaml 에 있다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from krpl_core.config import Rubric


# ─────────────────────────── 입력 ───────────────────────────
@dataclass(frozen=True)
class RequiredUnit:
    """목표 종목이 요구하는 능력단위."""
    unit_code: str
    unit_name: str
    required_hours: int
    min_hours: int                      # required × 조정하한


@dataclass(frozen=True)
class HeldUnit:
    """보유 자격이 편성한 능력단위."""
    unit_code: str
    composed_hours: int
    composed_hours_min: int | None = None   # 기관 편성 하한(80%)
    source: str = ""                        # 근거 자격 ID — 추적용


# ─────────────────────────── 출력 ───────────────────────────
@dataclass
class ElementVerdict:
    unit_code: str
    unit_name: str
    required_hours: int
    min_hours: int
    completed_hours: int | None
    ratio: float | None
    verdict: str                        # 완전충족|조정범위내|시간부족|미이수
    recommendation: str                 # R0|R2|R5
    verification: str
    confidence: str                     # 확정|추정(이수증명 필요)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    note: str | None = None


@dataclass
class TrackAResult:
    program_id: str
    total_hours: int
    n_units: int
    elements: list[ElementVerdict]
    rubric_version: str

    # ── 집계 ──
    @property
    def by_verdict(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.elements:
            out[e.verdict] = out.get(e.verdict, 0) + 1
        return out

    @property
    def hours(self) -> dict[str, int]:
        out = {"완전충족": 0, "조정범위내": 0, "시간부족": 0, "미이수": 0}
        for e in self.elements:
            out[e.verdict] += e.required_hours
        return out

    @property
    def unit_coverage_rate(self) -> float:
        n = len([e for e in self.elements if e.completed_hours is not None])
        return n / self.n_units if self.n_units else 0.0

    @property
    def credit_rate_strict(self) -> float:
        """확정 인정률 — 시간까지 충족한 능력단위의 요구시간 비율."""
        return self.hours["완전충족"] / self.total_hours if self.total_hours else 0.0

    @property
    def credit_rate_adjusted(self) -> float:
        """조정 적용 시 인정률 — −50% 조항까지 적용."""
        h = self.hours
        return (h["완전충족"] + h["조정범위내"]) / self.total_hours if self.total_hours else 0.0

    @property
    def remaining_hours(self) -> int:
        h = self.hours
        return h["시간부족"] + h["미이수"]

    def summary(self) -> dict[str, Any]:
        return {
            "program_id": self.program_id,
            "total_hours": self.total_hours,
            "n_units": self.n_units,
            "unit_coverage_rate": round(self.unit_coverage_rate, 4),
            "credit_rate_strict": round(self.credit_rate_strict, 4),
            "credit_rate_adjusted": round(self.credit_rate_adjusted, 4),
            "remaining_hours": self.remaining_hours,
            "by_verdict": self.by_verdict,
            "hours": self.hours,
            "rubric_version": self.rubric_version,
        }


# ─────────────────────────── 판정 ───────────────────────────
def _match(cond: dict[str, Any], ratio: float | None) -> bool:
    if cond.get("absent"):
        return ratio is None
    if ratio is None:
        return False
    if "ratio_gte" in cond and ratio < cond["ratio_gte"]:
        return False
    if "ratio_gt" in cond and not ratio > cond["ratio_gt"]:
        return False
    return True


def _pick(rubric: Rubric, ratio: float | None) -> dict[str, Any]:
    for spec in rubric.track_a["verdicts"]:
        if _match(spec["when"], ratio):
            return spec
    raise ValueError(f"판정 규칙이 ratio={ratio} 를 처리하지 못함 — rubric.track_a 확인 필요")


def assess_track_a(
    program_id: str,
    total_hours: int,
    required: list[RequiredUnit],
    held: list[HeldUnit],
    rubric: Rubric,
) -> TrackAResult:
    """목표 종목의 요구 능력단위와 보유 자격의 편성 능력단위를 대조한다."""
    held_map = {h.unit_code: h for h in held}
    labels = rubric.track_a["confidence"]["labels"]
    elements: list[ElementVerdict] = []

    for req in required:
        h = held_map.get(req.unit_code)
        ratio = (h.composed_hours / req.required_hours) if h and req.required_hours else None
        spec = _pick(rubric, ratio)

        # 신뢰도 — 편성 하한(80%)으로 계산해도 같은 판정이면 확정
        conf = labels["stable"]
        if h is not None and h.composed_hours_min is not None and req.required_hours:
            lo = h.composed_hours_min / req.required_hours
            if _pick(rubric, lo)["id"] != spec["id"]:
                conf = labels["unstable"]

        evidence = []
        if h is not None:
            evidence.append({
                "source": h.source,
                "unit_code": h.unit_code,
                "composed_hours": h.composed_hours,
                "composed_hours_range": [h.composed_hours_min, None],
            })

        elements.append(ElementVerdict(
            unit_code=req.unit_code, unit_name=req.unit_name,
            required_hours=req.required_hours, min_hours=req.min_hours,
            completed_hours=h.composed_hours if h else None,
            ratio=round(ratio, 4) if ratio is not None else None,
            verdict=spec["id"], recommendation=spec["recommendation"],
            verification=spec["verification"], confidence=conf,
            evidence=evidence, note=spec.get("note"),
        ))

    return TrackAResult(
        program_id=program_id, total_hours=total_hours, n_units=len(required),
        elements=elements, rubric_version=rubric.version,
    )
