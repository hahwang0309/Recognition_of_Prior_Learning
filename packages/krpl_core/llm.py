"""LLM 호출 계층.

두 가지 구현을 같은 자리에 끼운다.

  anthropic  실제 호출. 모델·effort·캐시·타임아웃은 config/models.yaml 이 정한다.
  replay     저장된 산출물을 그대로 돌려준다. 시험·시연에 쓴다. 비용 0.

전환은 환경변수 `KRPL_LLM_BACKEND` 하나다. 코드는 어느 쪽인지 모른다.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from krpl_core.config import CONFIG_DIR, ModelProfile, get_model_profile

log = logging.getLogger(__name__)
JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


class LLMError(RuntimeError):
    pass


def _is_schema_rejection(e: Exception) -> bool:
    if getattr(e, "status_code", None) != 400:
        return False
    m = str(e).lower()
    return "schema" in m or "output_config" in m or "output format" in m


class CostGuardExceeded(LLMError):
    """한 건 비용이 상한을 넘었다. 관리자 승인 없이는 진행하지 않는다."""


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0        # output_tokens 에 포함된 내부 추론분
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    stop_reason: str | None = None
    max_tokens: int = 0             # 그때 걸어 둔 상한 — 잘렸는지 판단하는 데 쓴다

    @property
    def truncated(self) -> bool:
        """상한에 걸려 끊겼는가. 이러면 JSON 이 깨져 그 시도가 통째로 버려진다."""
        return self.stop_reason == "max_tokens"

    @property
    def headroom(self) -> float:
        """상한 대비 남은 여유. 0.1 미만이면 다음 건이 잘릴 수 있다."""
        return 1 - self.output_tokens / self.max_tokens if self.max_tokens else 1.0

    def json(self) -> dict[str, Any]:
        """산출물에서 JSON 하나를 꺼낸다. 코드펜스·앞뒤 군더더기를 견딘다."""
        raw = self.text.strip()
        if m := JSON_BLOCK.search(raw):
            raw = m.group(1).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            i, j = raw.find("{"), raw.rfind("}")
            if i < 0 or j <= i:
                raise LLMError(f"JSON 을 찾을 수 없음 (길이 {len(self.text)}): {raw[:200]}") from None
            try:
                return json.loads(raw[i:j + 1])
            except json.JSONDecodeError as e:
                raise LLMError(f"JSON 해석 실패: {e}") from None


@dataclass
class Turn:
    """대화 한 판. system 은 캐시 대상이므로 messages 와 분리해 둔다."""
    system: list[str] = field(default_factory=list)      # 앞쪽부터 캐시된다
    messages: list[dict[str, str]] = field(default_factory=list)
    purpose: str = "assess"   # assess | negation | synthesize — 재생이 무엇을 흉내 낼지


class LLMClient(Protocol):
    def complete(self, turn: Turn, profile: ModelProfile) -> LLMResult: ...


# ─────────────────────────── 요금 ───────────────────────────
def _pricing() -> dict:
    return yaml.safe_load((CONFIG_DIR / "models.yaml").read_text(encoding="utf-8"))


def estimate_cost(model: str, input_tokens: int, output_tokens: int,
                  cache_read: int = 0, cache_write: int = 0) -> float:
    cfg = _pricing()
    p = (cfg.get("pricing") or {}).get(model)
    if not p:
        log.warning("요금표에 없는 모델 %s — 비용 0 으로 기록", model)
        return 0.0
    mul = cfg.get("cache_multiplier") or {"read": 0.10, "write": 1.25}
    return round((input_tokens * p["input"]
                  + cache_read * p["input"] * mul["read"]
                  + cache_write * p["input"] * mul["write"]
                  + output_tokens * p["output"]) / 1_000_000, 6)


def cost_guard() -> dict:
    return _pricing().get("cost_guard") or {}


# ─────────────────────────── anthropic ───────────────────────────
class AnthropicClient:
    """실제 호출. 긴 출력이 잦으므로 스트리밍을 기본으로 둔다."""

    def __init__(self, api_key: str | None = None):
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise LLMError("anthropic 패키지가 없습니다: uv pip install anthropic") from e
        key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("ANTHROPIC_API_KEY 가 설정되지 않았습니다")
        self._c = Anthropic(api_key=key)

    def _system(self, turn: Turn, profile: ModelProfile) -> list[dict]:
        """고정 블록(기준·프롬프트)에만 캐시를 건다. 지원자 자료는 매번 다르다."""
        n_cache = len(profile.cache.get("blocks") or []) if profile.cache.get("enabled") else 0
        out = []
        for i, s in enumerate(turn.system):
            b: dict[str, Any] = {"type": "text", "text": s}
            if i < n_cache:
                b["cache_control"] = {"type": "ephemeral"}
            out.append(b)
        return out

    def _kwargs(self, turn: Turn, profile: ModelProfile) -> dict:
        oc: dict[str, Any] = {}
        if profile.effort:               # Haiku 4.5 는 effort 를 거부하므로 설정이 없으면 보내지 않는다
            oc["effort"] = profile.effort
        if profile.structured_output:
            path = CONFIG_DIR / "schemas" / f"{profile.structured_output}.json"
            oc["format"] = {"type": "json_schema",
                            "schema": json.loads(path.read_text(encoding="utf-8"))}
        kw: dict[str, Any] = {
            "model": profile.model,
            "max_tokens": profile.max_tokens,
            "system": self._system(turn, profile),
            "messages": turn.messages,
            "timeout": float(profile.timeout_sec),
        }
        if oc:
            kw["output_config"] = oc
        if profile.thinking:
            kw["thinking"] = profile.thinking
        return kw

    def _call(self, kw: dict, streaming: bool):
        if streaming:
            with self._c.messages.stream(**kw) as st:
                return st.get_final_message()
        return self._c.messages.create(**kw)

    def complete(self, turn: Turn, profile: ModelProfile) -> LLMResult:
        kw = self._kwargs(turn, profile)
        try:
            msg = self._call(kw, profile.streaming)
        except Exception as e:
            # 스키마를 거부당하면 형식 제약 없이 한 번 더 간다.
            # 어차피 산출물은 검증기가 다시 대조하므로 계약은 그대로 지켜진다.
            if "format" in kw.get("output_config", {}) and _is_schema_rejection(e):
                log.warning("구조화 출력이 거부되어 형식 제약 없이 재시도한다: %s", e)
                kw["output_config"] = {k: v for k, v in kw["output_config"].items()
                                       if k != "format"}
                msg = self._call(kw, profile.streaming)
            else:
                raise

        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        u = msg.usage
        cr = getattr(u, "cache_read_input_tokens", 0) or 0
        cw = getattr(u, "cache_creation_input_tokens", 0) or 0
        cost = estimate_cost(profile.model, u.input_tokens, u.output_tokens, cr, cw)
        think = getattr(getattr(u, "output_tokens_details", None), "thinking_tokens", 0) or 0

        cap = cost_guard().get("per_assessment_usd_max")
        if cap is not None and cost > cap:
            raise CostGuardExceeded(f"1회 호출 ${cost:.2f} 이 상한 ${cap:.2f} 를 넘었습니다")
        if msg.stop_reason == "max_tokens":
            log.warning("출력이 상한 %s 토큰에서 끊겼습니다 — JSON 이 깨집니다. "
                        "config/models.yaml 의 max_tokens 를 올리십시오.", profile.max_tokens)
        return LLMResult(text=text, model=profile.model, input_tokens=u.input_tokens,
                         output_tokens=u.output_tokens, thinking_tokens=think,
                         cache_read_tokens=cr, cache_write_tokens=cw, cost_usd=cost,
                         stop_reason=msg.stop_reason, max_tokens=profile.max_tokens)


# ─────────────────────────── replay ───────────────────────────
class ReplayClient:
    """저장된 산출물을 돌려준다.

    파일명은 심사번호다: `{dir}/R2026-0002.json`.
    같은 건을 두 번 부르면 두 번째부터는 `-2`, `-3` 을 먼저 찾는다.
    (검증 실패 후 재요청까지 재현하기 위한 것 — 없으면 첫 파일을 다시 준다.)
    """

    def __init__(self, directory: str | Path | None = None):
        self.dir = Path(directory or os.getenv(
            "KRPL_REPLAY_DIR", Path(__file__).resolve().parents[2] / "tests/fixtures/trackb"))
        self._seen: dict[str, int] = {}

    def _key(self, turn: Turn) -> str:
        # 청크 방식에서는 심사번호가 system 블록(지원자 자료)에만 있을 수 있다.
        for blocks in (list(reversed(turn.messages)),
                       [{"content": x} for x in reversed(turn.system)]):
            for m in blocks:
                if k := re.search(r"\bR\d{4}-\d{4}\b", m.get("content", "")):
                    return k.group()
        raise LLMError("재생할 심사번호를 입력에서 찾지 못했습니다")

    @staticmethod
    def _wanted_elements(turn: Turn) -> set[str] | None:
        """청크 요청이면 그 청크가 물은 element_id 만 돌려준다.

        고정자료는 한 건 전체(요소 33개)로 저장돼 있는데 청크는 일부만 묻는다.
        통째로 돌려주면 검증기가 「없는 요소」로 잡는다 —
        재생이 실제 동작을 흉내 내지 못하면 시험의 의미가 없다.
        """
        # **첫** 사용자 메시지를 본다. 재요청(마지막 메시지)에는 지적된 요소만 적혀 있어서
        # 그것으로 자르면 나머지 요소가 사라진다.
        first = turn.messages[0].get("content", "") if turn.messages else ""
        ids = set(re.findall(r"\b\d{10}_\d{2}[vV]\d+\.\d+\b", first))
        return ids or None

    def complete(self, turn: Turn, profile: ModelProfile) -> LLMResult:
        key = self._key(turn)
        if turn.purpose != "assess":
            # 판정이 아닌 보조 호출. 전용 고정자료가 있으면 쓰고, 없으면 빈 결과를 준다.
            # 빈 결과가 안전한 쪽이다 — 부정 진술 매핑이 비면 기이수가 코드로 확정된다.
            aux = self.dir / f"{key}.{turn.purpose}.json"
            body = aux.read_text(encoding="utf-8") if aux.exists() else json.dumps(
                {"negation": {"affected": []},
                 "synthesize": {"prior_learning_review": "(재생) 기이수 반영 소견",
                                "overall_note": "(재생) 전반 소견"},
                 "plan": {"units": []}}[turn.purpose],
                ensure_ascii=False)
            return LLMResult(text=body, model=f"replay:{profile.model}",
                             output_tokens=len(body) // 3, stop_reason="end_turn",
                             max_tokens=profile.max_tokens)

        n = self._seen[key] = self._seen.get(key, 0) + 1
        path = self.dir / f"{key}-{n}.json"
        if not path.exists():
            path = self.dir / f"{key}.json"
        if not path.exists():
            raise LLMError(f"재생할 산출물이 없습니다: {path}")
        text = path.read_text(encoding="utf-8")
        if want := self._wanted_elements(turn):
            d = json.loads(text)
            d["elements"] = [e for e in d.get("elements") or []
                             if e.get("element_id") in want]
            text = json.dumps(d, ensure_ascii=False)
        return LLMResult(text=text, model=f"replay:{profile.model}",
                         output_tokens=len(text) // 3, stop_reason="end_turn",
                         max_tokens=profile.max_tokens)


def get_client(profile: ModelProfile | None = None) -> LLMClient:
    """KRPL_LLM_BACKEND: anthropic | replay.  기본은 키가 있으면 anthropic."""
    backend = os.getenv("KRPL_LLM_BACKEND")
    if backend is None:
        backend = "anthropic" if os.getenv("ANTHROPIC_API_KEY") else "replay"
    if backend == "replay":
        return ReplayClient()
    if backend == "anthropic":
        return AnthropicClient()
    raise LLMError(f"알 수 없는 LLM 백엔드: {backend}")


__all__ = ["LLMClient", "LLMResult", "Turn", "AnthropicClient", "ReplayClient",
           "get_client", "get_model_profile", "estimate_cost", "cost_guard",
           "LLMError", "CostGuardExceeded"]
