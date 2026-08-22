"""API 입출력 스키마."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HeldQualification(BaseModel):
    qual_id: str = Field(description="과정평가형 자격명. 예: 정보처리산업기사")


class SubmissionCreate(BaseModel):
    case_number: str = Field(pattern=r"^R\d{4}-\d{4}$", description="심사번호. 식별정보는 받지 않는다")
    track: Literal["A", "B"] = "A"
    target_program_id: str
    qualifications: list[str] = Field(min_length=1, description="보유 자격 목록")
    note: str | None = None


class SubmissionOut(BaseModel):
    id: int
    case_number: str
    track: str
    target_program_id: str
    status: str


class DocumentIn(BaseModel):
    doc_key: str = Field(pattern=r"^D\d{2}$")
    doc_type: str
    grade: Literal["A", "B", "C", "D", "E"]
    file_path: str
    issuer: str | None = None
    issued_on: str | None = None
    doc_format: Literal["narrative", "record", "dated", "list"] | None = None


class IngestRequest(BaseModel):
    documents: list[DocumentIn] = Field(min_length=1)


class IngestOut(BaseModel):
    submission_id: int
    n_documents: int
    n_fragments: int
    masked: dict[str, int]
    prior_learning: list[dict[str, Any]]
    warnings: list[str]


class FragmentOut(BaseModel):
    fid: str
    doc_key: str
    doc_type: str
    grade: str
    text: str
    stype: str
    freq: str | None


class AssessmentStatus(BaseModel):
    """진행 상태. retry_after 로 다음 폴링 시점을 서버가 지정한다."""
    submission_id: int
    case_number: str
    status: str
    step: str | None = None
    assessment_id: int | None = None
    retry_after: int | None = Field(None, description="초. null 이면 폴링 종료")


class AssessRequest(BaseModel):
    profile: str | None = Field(None, description="config/models.yaml 의 프로필명. 생략하면 기본값")
    force: bool = Field(False, description="이미 판정된 건을 다시 판정한다")


class ElementOut(BaseModel):
    unit_code: str
    unit_name: str
    required_hours: int
    min_hours: int
    completed_hours: int | None
    ratio: float | None
    verdict: str
    recommendation: str
    verification: str
    confidence: str
    evidence: list[dict[str, Any]]
    note: str | None


class AssessmentOut(BaseModel):
    """Track A — 능력단위 단위. 시간 대조만으로 판정한다."""
    track: Literal["A"] = "A"
    assessment_id: int
    case_number: str
    program_id: str
    rubric_version: str
    model: str
    summary: dict[str, Any]
    elements: list[ElementOut]


class TrackBElementOut(BaseModel):
    """Track B — 능력단위요소 단위. 판정이 아니라 판정의 근거다."""
    element_id: str
    element_name: str | None = None
    unit_name: str | None = None
    recommendation: str
    recommendation_reason: str | None = None
    evidence_level: str | None = None
    verification_method: str | None = None
    confidence: str | None = None
    needs_expert_review: bool = False
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    period_backing: dict[str, Any] | None = None
    prior_learning: dict[str, Any] | None = None
    uncovered_ksa: list[dict[str, Any]] = Field(default_factory=list)
    remediation: list[dict[str, Any]] = Field(default_factory=list)
    negative_statements: list[dict[str, Any]] = Field(default_factory=list)
    proven_dimensions: list[str] = Field(default_factory=list)
    missing_dimensions: list[str] = Field(default_factory=list)
    source_grades: list[str] = Field(default_factory=list)
    negative_grades: list[str] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    qualitative_note: str | None = None


class TrackBAssessmentOut(BaseModel):
    track: Literal["B"] = "B"
    assessment_id: int
    case_number: str
    program_id: str
    status: str
    rubric_version: str
    prompt_version: str | None
    model: str | None
    attempts: int
    validation_passed: bool
    n_expert_review: int = Field(description="전문가 확인이 필요하다고 표시된 요소 수")
    cost_usd: float | None
    prior_learning_review: str | None
    overall_note: str | None
    summary: dict[str, Any]
    elements: list[TrackBElementOut]


class ValidationAttemptOut(BaseModel):
    attempt: int
    passed: bool
    error_count: int
    by_code: dict[str, int] = Field(default_factory=dict)
    issues: list[dict[str, Any]] = Field(default_factory=list)


class ElementReviewIn(BaseModel):
    decision: Literal["인정", "조건부인정", "불인정", "보류"]
    note: str | None = None
    reviewer: str | None = None


class ElementReviewOut(BaseModel):
    element_id: str
    decision: str
    ai_recommendation: str | None
    agrees_with_ai: bool


class BulkReviewIn(BaseModel):
    """여러 요소에 같은 의견을 한 번에. 「코드가 확정한 12개 전부 인정」 같은 경우."""
    element_ids: list[str] = Field(min_length=1, max_length=500)
    decision: Literal["인정", "조건부인정", "불인정", "보류"]
    note: str | None = None
    reviewer: str | None = None


class ReviewSummaryOut(BaseModel):
    """검토 진행 상황과 감면 시간. 화면이 이 값으로 갱신된다."""
    assessment_id: int
    case_number: str
    total_hours: int
    n_elements: int
    n_reviewed: int
    n_expert_review: int
    complete: bool
    counts: dict[str, int]
    rule: str = Field(description="감면 규칙 — all_elements | proportional")
    hours: int = Field(description="인정된 요소만으로 계산한 감면 시간")
    hours_conditional: int = Field(description="조건부인정까지 포함")
    hours_other_rule: int = Field(description="다른 규칙을 적용했을 때 — 확정")
    hours_other_conditional: int = Field(description="다른 규칙 · 조건부 포함")
    other_rule: str
    rate: float
    suggested: str = Field(description="권고안. 사람이 바꿀 수 있다")
    units: list[dict[str, Any]]


class DecisionIn(BaseModel):
    assessment_id: int
    decision: Literal["전체인정", "부분인정", "불인정"]
    reason: str | None = None
    decided_by: str | None = None
    recognized_hours: int | None = Field(None, description="비우면 검토 결과에서 계산")
    conditional: bool = Field(False, description="조건부인정을 감면 시간에 포함")
    allow_incomplete: bool = Field(False, description="검토가 끝나지 않아도 기록")


class DecisionOut(BaseModel):
    submission_id: int
    assessment_id: int
    decision: str
    recognized_hours: int
    total_hours: int
    credit_basis: dict[str, Any]


class ProgramOut(BaseModel):
    program_id: str
    official_name: str | None
    official_status: str | None
    total_hours: int | None
    n_units: int | None
    daebunryu: str | None


class RecommendOut(BaseModel):
    program_id: str
    official_name: str | None
    total_hours: int
    common_units: int
    n_units: int | None
    credit_rate_strict: float
    credit_rate_adjusted: float
