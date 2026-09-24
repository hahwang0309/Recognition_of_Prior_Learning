"""중앙 설정 로더.

계층:  config/settings.yaml  ←  config/environments/{env}.yaml  ←  .env  ←  실제 환경변수
       (기본값)                  (환경별 덮어쓰기)                 (비밀값)  (가장 셈)

타입 검증을 통과하지 못하면 기동하지 않는다.

`.env` 는 여기서 **os.environ 에 실어 준다.** pydantic-settings 의 env_file 만으로는
`Settings` 필드에만 닿고, `os.getenv` 로 읽는 값들(ANTHROPIC_API_KEY·KRPL_LLM_BACKEND 등)에는
닿지 않는다. 그러면 키를 .env 에 넣어도 조용히 무시된다 — 가장 나쁜 실패 방식이다.

이미 설정된 실제 환경변수는 덮어쓰지 않는다.
`KRPL_LLM_BACKEND=replay ./scripts/dev.sh assess …` 처럼 그때그때 지정한 값이 이겨야 한다.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import dotenv_values, load_dotenv
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = APP_DIR / "config"
ENV_FILE = APP_DIR / ".env"

def _load_env_file() -> None:
    """App/.env 를 읽어 os.environ 에 싣는다. 어느 디렉터리에서 실행하든 같다.

    - override=False — 실행할 때 직접 준 환경변수가 .env 를 이긴다.
    - `KEY=` 처럼 **빈 값은 「설정하지 않음」으로 본다.** 빈 문자열을 그대로 두면
      `KRPL_LLM_BACKEND=` 하나에 기동이 죽는다. 견본 파일이 비워 두라고 안내하는 항목들이라
      더 그렇다.
    """
    if not ENV_FILE.exists():
        return
    load_dotenv(ENV_FILE, override=False)
    for k, v in dotenv_values(ENV_FILE).items():
        if not (v or "").strip() and os.environ.get(k, "").strip() == "":
            os.environ.pop(k, None)


_load_env_file()


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _deep_merge(out[k], v) if isinstance(out.get(k), dict) and isinstance(v, dict) else v
    return out


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"설정 파일 없음: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


# ─────────────────────────── settings ───────────────────────────
class AppCfg(BaseModel):
    name: str
    case_number_prefix: str = "R"
    timezone: str = "Asia/Seoul"


class RubricCfg(BaseModel):
    active_version: str
    fail_on_pending: bool = False


class StorageCfg(BaseModel):
    backend: Literal["local", "s3"] = "local"
    local_path: str = "./storage"
    max_upload_mb: int = 50
    allowed_extensions: list[str]

    @model_validator(mode="after")
    def _parseable(self):
        """받기로 한 형식을 파서가 정말 읽는가.

        한때 8개 중 5개(docx·xlsx·jpg·jpeg·png)를 받도록 해 두었는데
        파서는 못 읽었다. 올린 담당자는 「조각 0개」를 보고서야 알았다.
        여기서 막아 두면 설정과 코드가 다시 어긋나지 않는다.
        """
        from krpl_parsers import supported_extensions
        can = set(supported_extensions())
        bad = sorted(set(self.allowed_extensions) - can)
        if bad:
            raise ValueError(
                f"받기로 한 형식을 파서가 읽지 못합니다: {bad} "
                f"(읽을 수 있는 것: {sorted(can)})")
        return self


class MaskingCfg(BaseModel):
    enabled: bool = True
    patterns: list[str] = Field(default_factory=list)


class IngestCfg(BaseModel):
    ocr_enabled: bool = False
    masking: MaskingCfg = Field(default_factory=MaskingCfg)


class QueueCfg(BaseModel):
    backend: Literal["postgres", "celery"] = "postgres"
    poll_interval_sec: int = 5
    max_attempts: int = 3
    backoff_base_sec: int = 30


class AssessmentCfg(BaseModel):
    validation_max_retries: int = 3
    on_validation_exhausted: str = "manual_review"
    chunk_by: Literal["unit", "none"] = "unit"
    chunk_concurrency: int = Field(4, ge=1, le=16)
    synthesize_overall: bool = True


class Settings(BaseSettings):
    """환경변수는 KRPL_ 접두어. 예: KRPL_DATABASE_URL"""

    model_config = SettingsConfigDict(env_prefix="KRPL_", env_file=ENV_FILE, extra="ignore")

    env: str = "local"
    database_url: str = "postgresql+psycopg://krpl:krpl@localhost:5432/krpl"

    app: AppCfg
    rubric: RubricCfg
    prompt: dict[str, Any]
    storage: StorageCfg
    ingest: IngestCfg
    queue: QueueCfg
    assessment: AssessmentCfg
    retention: dict[str, Any]
    logging: dict[str, Any]


@lru_cache
def get_settings() -> Settings:
    env = os.getenv("KRPL_ENV", "local")
    data = _load_yaml(CONFIG_DIR / "settings.yaml")
    env_path = CONFIG_DIR / "environments" / f"{env}.yaml"
    if env_path.exists():
        data = _deep_merge(data, _load_yaml(env_path))

    # YAML 값은 init 인자로 들어가는데, pydantic-settings 는 init 인자를 환경변수보다
    # 우선한다. 그러면 `KRPL_DATABASE_URL=... ` 로 덮어쓸 수 없다.
    # 환경변수가 있는 항목은 YAML 에서 빼서 환경변수가 이기게 한다.
    for field in Settings.model_fields:
        if f"KRPL_{field.upper()}" in os.environ:
            data.pop(field, None)
    return Settings(env=env, **data)


# ─────────────────────────── rubric ─────────────────────────────
class PendingDecision(BaseModel):
    key: str
    issue: str
    urgency: Literal["critical", "high", "medium", "low"]


class Rubric(BaseModel):
    """심사 기준. 값 하나가 바뀌면 판정이 달라지므로 버전을 기록에 남긴다."""

    version: str
    effective_from: str
    source_document: str
    grades: dict[str, dict[str, Any]]
    grade_order: list[str]
    dimensions: list[str]
    document_types: dict[str, dict[str, Any]]
    recommendations: dict[str, dict[str, Any]]
    rules: dict[str, dict[str, Any]]
    training_hours: dict[str, Any]
    track_b: dict[str, Any] = Field(default_factory=dict)   # 위원 화면 묶음·표시 규칙 (2026-09-23)
    track_a: dict[str, Any]
    output_vocabulary: dict[str, list[str]]
    final_decision: dict[str, Any]
    remediation: dict[str, Any]
    uncovered_status: dict[str, Any]
    third_party_statement: dict[str, Any]
    pending_decisions: list[PendingDecision] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_consistency(self):
        for name, spec in self.document_types.items():
            if spec["grade"] not in self.grades:
                raise ValueError(f"자료유형 '{name}' 의 등급 '{spec['grade']}' 이 grades 에 없음")
            for dim in (spec.get("proves") or {}):
                if dim not in self.dimensions:
                    raise ValueError(f"자료유형 '{name}' 의 차원 '{dim}' 이 dimensions 에 없음")
        for name in ("evidence_level", "verification_method", "confidence"):
            if not self.output_vocabulary.get(name):
                raise ValueError(f"output_vocabulary.{name} 이 비어 있음")
        for m in self.remediation["face_to_face"]:
            if m not in self.remediation["methods"]:
                raise ValueError(f"대면평가 '{m}' 이 remediation.methods 에 없음")
        fd = self.final_decision
        if fd["unit_credit_rule"] not in ("all_elements", "proportional"):
            raise ValueError(f"unit_credit_rule 값이 잘못됨: {fd['unit_credit_rule']}")
        for code, spec in self.recommendations.items():
            for g in (spec.get("requires") or {}).get("period_backing_grades", []):
                if g not in self.grades:
                    raise ValueError(f"{code} 의 등급 '{g}' 이 grades 에 없음")
        return self

    @property
    def critical_pending(self) -> list[PendingDecision]:
        return [p for p in self.pending_decisions if p.urgency == "critical"]

    def is_decided(self, key: str) -> bool:
        """해당 설정이 확정되었는지. 미확정이면 판정을 보류해야 한다."""
        return not any(p.key == key for p in self.pending_decisions)


@lru_cache
def get_rubric(version: str | None = None) -> Rubric:
    s = get_settings()
    v = version or s.rubric.active_version
    rb = Rubric(**_load_yaml(CONFIG_DIR / "rubric" / f"v{v}.yaml"))
    if s.rubric.fail_on_pending and rb.pending_decisions:
        keys = ", ".join(p.key for p in rb.pending_decisions)
        raise RuntimeError(f"미확정 기준 항목이 있어 기동할 수 없습니다 ({s.env}): {keys}")
    return rb


# ─────────────────────────── models ─────────────────────────────
class ModelProfile(BaseModel):
    provider: str
    model: str
    max_tokens: int
    streaming: bool = True
    thinking: dict[str, Any] | None = None
    effort: str | None = "high"      # None 이면 output_config.effort 를 보내지 않는다 (Haiku 4.5)
    structured_output: str | None = None
    cache: dict[str, Any] = Field(default_factory=dict)
    timeout_sec: int = 900
    max_retries: int = 2
    use_batch_api: bool = False


@lru_cache
def get_model_profile(name: str | None = None) -> ModelProfile:
    data = _load_yaml(CONFIG_DIR / "models.yaml")
    key = name or data["default"]
    spec = dict(data["profiles"][key])
    if parent := spec.pop("inherits", None):
        spec = _deep_merge(dict(data["profiles"][parent]), spec)
    return ModelProfile(**spec)
