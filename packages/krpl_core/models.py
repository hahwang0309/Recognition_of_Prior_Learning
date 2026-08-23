"""도메인 모델.

catalog_*  : NCS 참조 데이터 (읽기 전용, 고시 기준)
그 외      : 운영 데이터
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Index,
    Integer, Numeric, SmallInteger, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}


# ═══════════════════ 참조 데이터 (NCS 고시) ═══════════════════
class NcsUnit(Base):
    __tablename__ = "catalog_ncs_unit"
    unit_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    unit_name: Mapped[str] = mapped_column(String(200))
    level: Mapped[int | None]
    std_hours: Mapped[int | None]
    sebunryu_code: Mapped[str | None] = mapped_column(String(8), index=True)
    sebunryu_name: Mapped[str | None] = mapped_column(String(200))
    daebunryu_name: Mapped[str | None] = mapped_column(String(100))
    latest_version: Mapped[str | None] = mapped_column(String(10))


class NcsUnitElement(Base):
    __tablename__ = "catalog_ncs_element"
    element_id: Mapped[str] = mapped_column(String(24), primary_key=True)
    unit_code: Mapped[str] = mapped_column(String(10), index=True)
    unit_version: Mapped[str | None] = mapped_column(String(10))
    unit_name: Mapped[str | None] = mapped_column(String(200))
    element_no: Mapped[int | None]
    element_name: Mapped[str] = mapped_column(String(300))
    sebunryu_code: Mapped[str | None] = mapped_column(String(8))


class NcsPerformanceCriteria(Base):
    __tablename__ = "catalog_ncs_pc"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    unit_code: Mapped[str] = mapped_column(String(10))
    element_no: Mapped[int]
    pc_no: Mapped[int]
    pc_text: Mapped[str] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("unit_code", "element_no", "pc_no"),
                      Index("ix_pc_unit_elem", "unit_code", "element_no"))


class NcsKsa(Base):
    __tablename__ = "catalog_ncs_ksa"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    unit_code: Mapped[str] = mapped_column(String(10))
    element_no: Mapped[int]
    pc_no: Mapped[int]
    ksa_type: Mapped[str] = mapped_column(String(4))       # 지식|기술|태도
    ksa_no: Mapped[int]
    ksa_text: Mapped[str] = mapped_column(Text)
    __table_args__ = (Index("ix_ksa_unit_elem", "unit_code", "element_no"),)


class WsdProgram(Base):
    """일학습병행 종목"""
    __tablename__ = "catalog_wsd_program"
    program_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    jikjong: Mapped[str | None] = mapped_column(String(80))
    level: Mapped[str | None] = mapped_column(String(4))
    total_hours: Mapped[int | None]
    n_units: Mapped[int | None]
    official_name: Mapped[str | None] = mapped_column(String(80))
    official_status: Mapped[str | None] = mapped_column(String(10))   # 유효|폐지
    daebunryu: Mapped[str | None] = mapped_column(String(60))
    jungbunryu: Mapped[str | None] = mapped_column(String(60))
    qc_status: Mapped[str | None] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text)


class WsdRequired(Base):
    """종목별 요구 능력단위·시간"""
    __tablename__ = "catalog_wsd_required"
    program_id: Mapped[str] = mapped_column(String(80), ForeignKey("catalog_wsd_program.program_id"), primary_key=True)
    unit_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    unit_version: Mapped[str | None] = mapped_column(String(10))
    unit_name: Mapped[str | None] = mapped_column(String(200))
    unit_level: Mapped[int | None]
    required_hours: Mapped[int]
    min_hours: Mapped[int]                                  # required × 조정하한
    __table_args__ = (Index("ix_wsd_req_unit", "unit_code"),)


class CbqQualification(Base):
    """과정평가형 자격"""
    __tablename__ = "catalog_cbq_qual"
    qual_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    grade: Mapped[str | None] = mapped_column(String(20))
    version: Mapped[str | None] = mapped_column(String(20))
    total_a: Mapped[int | None]
    essential_b: Mapped[int | None]
    b_min: Mapped[int | None]
    b_max: Mapped[int | None]
    n_units: Mapped[int | None]
    qc_status: Mapped[str | None] = mapped_column(String(20))


class CbqComposed(Base):
    __tablename__ = "catalog_cbq_composed"
    qual_id: Mapped[str] = mapped_column(String(80), ForeignKey("catalog_cbq_qual.qual_id"), primary_key=True)
    unit_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    unit_version: Mapped[str | None] = mapped_column(String(10))
    unit_name: Mapped[str | None] = mapped_column(String(200))
    unit_level: Mapped[int | None]
    sebunryu_name: Mapped[str | None] = mapped_column(String(200))
    composed_hours: Mapped[int]
    composed_hours_min: Mapped[int | None]
    composed_hours_max: Mapped[int | None]
    __table_args__ = (Index("ix_cbq_unit", "unit_code"),)


class UnitVersionMap(Base):
    __tablename__ = "catalog_unit_version"
    unit_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    wsd_versions: Mapped[str | None] = mapped_column(String(120))
    cbq_versions: Mapped[str | None] = mapped_column(String(120))
    ncs_version: Mapped[str | None] = mapped_column(String(10))
    version_match: Mapped[str | None] = mapped_column(String(12))
    needs_review: Mapped[bool] = mapped_column(Boolean, server_default="false")
    resolution: Mapped[str | None] = mapped_column(String(60))


# ═══════════════════════ 운영 데이터 ═══════════════════════
class Submission(Base):
    """접수 건. 심사번호만 사용하며 식별정보는 저장하지 않는다."""
    __tablename__ = "submission"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    case_number: Mapped[str] = mapped_column(String(24), unique=True)   # R2026-0001
    track: Mapped[str] = mapped_column(String(1))                       # A | B
    target_program_id: Mapped[str] = mapped_column(String(80), ForeignKey("catalog_wsd_program.program_id"))
    status: Mapped[str] = mapped_column(String(20), server_default="received", index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    note: Mapped[str | None] = mapped_column(Text)
    documents: Mapped[list["Document"]] = relationship(back_populates="submission", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "document"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submission.id", ondelete="CASCADE"), index=True)
    doc_key: Mapped[str] = mapped_column(String(8))                     # D01
    doc_type: Mapped[str] = mapped_column(String(60))
    grade: Mapped[str] = mapped_column(String(1))                       # A~E
    issuer: Mapped[str | None] = mapped_column(String(120))
    issued_on: Mapped[str | None] = mapped_column(String(20))
    file_path: Mapped[str | None] = mapped_column(Text)
    parsed_format: Mapped[str | None] = mapped_column(String(20))       # record|narrative|dated|list
    submission: Mapped[Submission] = relationship(back_populates="documents")
    __table_args__ = (UniqueConstraint("submission_id", "doc_key"),)


class Fragment(Base):
    """문서 조각. AI 인용의 기준 단위."""
    __tablename__ = "fragment"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submission.id", ondelete="CASCADE"), index=True)
    fid: Mapped[str] = mapped_column(String(16))                        # D04-S03
    doc_key: Mapped[str] = mapped_column(String(8))
    doc_type: Mapped[str] = mapped_column(String(60))
    grade: Mapped[str] = mapped_column(String(1))
    text: Mapped[str] = mapped_column(Text)
    stype: Mapped[str] = mapped_column(String(12))                      # 직접수행|부정|불확실|기재사항…
    freq: Mapped[str | None] = mapped_column(String(20))
    __table_args__ = (UniqueConstraint("submission_id", "fid"),)


class Assessment(Base):
    """판정 실행. 재현성을 위해 기준·프롬프트·모델 버전을 반드시 기록한다."""
    __tablename__ = "assessment"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submission.id", ondelete="CASCADE"), index=True)
    # 어떤 판정인가 — time(시간 대조·결정론) / evidence(근거 분석·AI).
    # 한 접수에 둘 다 있을 수 있고, 화면은 이 값으로 갈라진다.
    kind: Mapped[str] = mapped_column(String(10), server_default="evidence", index=True)
    status: Mapped[str] = mapped_column(String(20), server_default="queued", index=True)
    rubric_version: Mapped[str] = mapped_column(String(10))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(60))
    effort: Mapped[str | None] = mapped_column(String(10))
    input_hash: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    cache_read_tokens: Mapped[int | None]
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 4))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    overall_note: Mapped[str | None] = mapped_column(Text)
    # 전문가 검토가 어느 단계까지 왔나.
    #   1 인정검토 · 2 추가서류 · 3 면접 · 4 실기 · 5 최종
    review_stage: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    # 진행 상황. 판정이 도는 동안 **별도 세션에서 즉시 커밋**한다 —
    # 본 트랜잭션은 끝날 때까지 커밋되지 않아 밖에서는 아무것도 안 보이기 때문이다.
    progress: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    elements: Mapped[list["AssessmentElement"]] = relationship(back_populates="assessment", cascade="all, delete-orphan")


class AssessmentElement(Base):
    __tablename__ = "assessment_element"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessment.id", ondelete="CASCADE"), index=True)
    element_id: Mapped[str] = mapped_column(String(24))
    recommendation: Mapped[str] = mapped_column(String(4))              # R0~R5
    evidence_level: Mapped[str | None] = mapped_column(String(20))
    verification_method: Mapped[str | None] = mapped_column(String(20))
    confidence: Mapped[str | None] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)              # evidence·remediation 원본
    assessment: Mapped[Assessment] = relationship(back_populates="elements")
    __table_args__ = (UniqueConstraint("assessment_id", "element_id"),)


class ValidationLog(Base):
    __tablename__ = "validation_log"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessment.id", ondelete="CASCADE"), index=True)
    attempt: Mapped[int]
    passed: Mapped[bool]
    error_count: Mapped[int] = mapped_column(server_default="0")
    errors: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RemediationResult(Base):
    """보완 항목 하나의 결과 — 서류를 받았나, 면접·실기를 통과했나.

    ## 왜 요소가 아니라 항목 단위인가

    보완 항목은 여러 요소에 걸쳐 병합된다. 「안전보건교육 이수확인서」 한 건이
    5개 능력단위 15개 요소를 한꺼번에 푼다. 요소마다 따로 물으면 같은 서류를
    열다섯 번 확인하는 꼴이 된다.

    통과하면 그 항목이 채우기로 한 KSA 가 채워진 것이므로 요소 인정은 계산이다.
    다만 「무엇을 보고 그렇게 됐는지」는 최종 화면과 감사 기록에 남긴다.
    """
    __tablename__ = "remediation_result"
    __table_args__ = (UniqueConstraint("assessment_id", "item_key",
                                       name="uq_remediation_item"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessment.id", ondelete="CASCADE"), index=True)
    # 항목 글 자체의 sha256 앞 16자. 같은 판정 안에서 항목을 가리키는 이름이다.
    item_key: Mapped[str] = mapped_column(String(16))
    method: Mapped[str] = mapped_column(String(8))        # 추가서류|면접|실기|훈련
    item: Mapped[str] = mapped_column(Text)               # 무엇을 물었는지 그대로 남긴다
    result: Mapped[str] = mapped_column(String(8))        # 통과|미통과|미실시
    note: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(String(60))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ElementReview(Base):
    """능력단위요소 하나에 대한 전문가 의견.

    AI 산출물을 덮어쓰지 않는다. 옆에 나란히 쌓는다 —
    나중에 「기계는 뭐라 했고 사람은 뭐라 했나」를 대조할 수 있어야 한다.
    """
    __tablename__ = "element_review"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessment.id", ondelete="CASCADE"), index=True)
    element_id: Mapped[str] = mapped_column(String(24))
    decision: Mapped[str] = mapped_column(String(12))                   # 인정|조건부인정|불인정|보류
    ai_recommendation: Mapped[str | None] = mapped_column(String(4))    # 검토 시점의 AI 권고 (대조용)
    note: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str | None] = mapped_column(String(60))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("assessment_id", "element_id"),)


class FinalDecision(Base):
    """전문가 TF 최종 판정. 시스템은 여기에 값을 쓰지 않는다."""
    __tablename__ = "final_decision"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submission.id", ondelete="CASCADE"), unique=True)
    assessment_id: Mapped[int | None] = mapped_column(ForeignKey("assessment.id", ondelete="SET NULL"))
    decision: Mapped[str] = mapped_column(String(20))                   # 전체인정|부분인정|불인정
    reason: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(String(60))
    decided_on: Mapped[Date | None] = mapped_column(Date)
    recognized_hours: Mapped[int | None]
    total_hours: Mapped[int | None]
    credit_basis: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # 산출 근거 — 계산식을 남긴다
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Artifact(Base):
    """단계별 중간 산출물 색인.

    실제 내용은 storage/audit/ 아래 파일로 있다. 여기는 「무엇이 언제 어떤 해시로」만.
    해시를 남기는 이유는 나중에 파일이 바뀌었는지 확인할 수 있어야 하기 때문이다.
    """
    __tablename__ = "artifact"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submission.id", ondelete="CASCADE"), index=True)
    assessment_id: Mapped[int | None] = mapped_column(ForeignKey("assessment.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(12))                      # ingest|package|llm|…
    seq: Mapped[int] = mapped_column(server_default="0")
    name: Mapped[str] = mapped_column(String(60))
    path: Mapped[str] = mapped_column(Text)                             # audit/ 기준 상대경로
    sha256: Mapped[str] = mapped_column(String(64))
    n_bytes: Mapped[int]
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("submission_id", "assessment_id", "stage", "seq", "name"),)


class Job(Base):
    """PostgreSQL 작업 큐. SELECT … FOR UPDATE SKIP LOCKED 로 집는다."""
    __tablename__ = "job"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(12), server_default="queued", index=True)
    attempts: Mapped[int] = mapped_column(server_default="0")
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("ix_job_pick", "status", "next_run_at"),)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str | None] = mapped_column(String(60))
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
