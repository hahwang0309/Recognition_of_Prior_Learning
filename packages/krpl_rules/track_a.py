"""Track A 판정 엔진.

과정평가형 자격 등 NCS 기반 이수자를 능력단위·기록 확인으로 판정한다.
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
    verdict: str                        # 완전충족|조정범위내|보류|시간부족|미이수 (rubric.track_a.verdicts)
    recommendation: str                 # R0|R4|R5
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
    verdict_order: list[str] = field(default_factory=lambda: ["완전충족", "조정범위내", "보류", "시간부족", "미이수"])
    # 인정 / 보류 / 불인정 — rubric.track_a.buckets
    buckets: dict[str, list[str]] = field(default_factory=lambda: {
        "인정": ["완전충족", "조정범위내"], "보류": ["보류"], "불인정": ["시간부족", "미이수"]})

    # ── 집계 ──
    @property
    def by_verdict(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.elements:
            out[e.verdict] = out.get(e.verdict, 0) + 1
        return out

    @property
    def hours(self) -> dict[str, int]:
        """판정별 요구시간 합. 인정된 단위는 이수시간이 아니라 **요구시간 전체**가 감면된다."""
        out = {k: 0 for k in self.verdict_order}
        for e in self.elements:
            out[e.verdict] = out.get(e.verdict, 0) + e.required_hours
        return out

    @property
    def bucket_hours(self) -> dict[str, int]:
        """인정 / 보류 / 불인정 시간 — 2차 TF 가 요구한 세 묶음."""
        h = self.hours
        return {b: sum(h.get(v, 0) for v in vs) for b, vs in self.buckets.items()}

    @property
    def unit_coverage_rate(self) -> float:
        n = len([e for e in self.elements if e.completed_hours is not None])
        return n / self.n_units if self.n_units else 0.0

    @property
    def credit_rate_strict(self) -> float:
        """참고값 — 이수시간이 요구시간을 100% 채운 단위만. 현행 규칙(50% 이상 전체 인정)보다 엄격하다."""
        return self.hours.get("완전충족", 0) / self.total_hours if self.total_hours else 0.0

    @property
    def credit_rate_adjusted(self) -> float:
        """인정률 — 현행 선이수인정 규칙(코드 일치 + 요구시간의 50% 이상 → 요구시간 전체 인정)."""
        return self.bucket_hours["인정"] / self.total_hours if self.total_hours else 0.0

    @property
    def hold_rate(self) -> float:
        return self.bucket_hours["보류"] / self.total_hours if self.total_hours else 0.0

    @property
    def remaining_hours(self) -> int:
        """불인정 시간 — 훈련으로 이수해야 하는 시간. 보류는 포함하지 않는다."""
        return self.bucket_hours["불인정"]

    def summary(self) -> dict[str, Any]:
        return {
            "program_id": self.program_id,
            "total_hours": self.total_hours,
            "n_units": self.n_units,
            "unit_coverage_rate": round(self.unit_coverage_rate, 4),
            "credit_rate_strict": round(self.credit_rate_strict, 4),
            "credit_rate_adjusted": round(self.credit_rate_adjusted, 4),
            "hold_rate": round(self.hold_rate, 4),
            "remaining_hours": self.remaining_hours,
            "by_verdict": self.by_verdict,
            "hours": self.hours,
            "bucket_hours": self.bucket_hours,
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

    ta = rubric.track_a
    return TrackAResult(
        program_id=program_id, total_hours=total_hours, n_units=len(required),
        verdict_order=[v["id"] for v in ta["verdicts"]],
        buckets={k: list(v) for k, v in (ta.get("buckets") or {}).items()} or
                {"인정": ["완전충족", "조정범위내"], "보류": ["보류"], "불인정": ["시간부족", "미이수"]},
        elements=elements, rubric_version=rubric.version,
    )
