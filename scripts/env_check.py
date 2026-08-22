"""지금 무엇이 실제로 반영돼 있는지 보여준다.

  python scripts/env_check.py

.env 에 값을 넣었는데 왜 안 먹지, 를 없애기 위한 것이다.
어디서 온 값인지(.env / 실제 환경변수 / 기본값)까지 함께 표시한다.
비밀값은 가린다.
"""
from __future__ import annotations

import os

from dotenv import dotenv_values

from krpl_core.config import ENV_FILE, get_model_profile, get_rubric, get_settings

KEYS = ["KRPL_ENV", "KRPL_DATABASE_URL", "KRPL_LLM_BACKEND",
        "ANTHROPIC_API_KEY", "KRPL_REPLAY_DIR"]
SECRET = {"ANTHROPIC_API_KEY", "KRPL_DATABASE_URL"}


def hide(k: str, v: str | None) -> str:
    if not v:
        return "(비어 있음)"
    if k not in SECRET:
        return v
    if k == "KRPL_DATABASE_URL" and "@" in v:            # 비밀번호만 가린다
        head, tail = v.split("://", 1)
        cred, host = tail.split("@", 1)
        user = cred.split(":", 1)[0]
        return f"{head}://{user}:****@{host}"
    return f"{v[:7]}…{v[-4:]} ({len(v)}자)" if len(v) > 14 else "****"


def main() -> int:
    dotenv = dotenv_values(ENV_FILE) if ENV_FILE.exists() else {}
    print(f"\n.env 파일  {ENV_FILE}"
          f"  {'있음' if ENV_FILE.exists() else '없음 — cp .env.example .env'}\n")

    print(f"{'항목':22} {'적용된 값':46} 출처")
    print("─" * 92)
    for k in KEYS:
        cur = os.getenv(k)
        blank_in_file = k in dotenv and not (dotenv[k] or "").strip()
        if cur is None:
            src = ".env 에 빈 값 → 기본값" if blank_in_file else "기본값"
        elif k in dotenv and dotenv[k] == cur:
            src = ".env"
        elif k in dotenv:
            src = "환경변수 (.env 를 덮어씀)"
        else:
            src = "환경변수"
        print(f"{k:22} {hide(k, cur):46} {src}")

    s, rb = get_settings(), get_rubric()
    prof = get_model_profile()
    from krpl_core.llm import get_client
    try:
        backend = type(get_client(prof)).__name__.replace("Client", "")
        err = ""
    except Exception as ex:                                   # noqa: BLE001
        backend, err = "선택 실패", f"  → {ex}"

    print(f"\n{'실제 동작':22}")
    print("─" * 92)
    print(f"{'환경':22} {s.env}  (config/environments/{s.env}.yaml)")
    print(f"{'저장 위치':22} {s.storage.local_path}")
    print(f"{'LLM 백엔드':22} {backend}{err}")
    print(f"{'모델 (설정값)':22} {prof.model} · effort {prof.effort} · "
          f"최대 {prof.max_tokens} 토큰")
    print(f"{'심사 기준':22} v{rb.version} · 미확정 {len(rb.pending_decisions)}건"
          + (f" (중대: {', '.join(p.issue for p in rb.critical_pending)})"
             if rb.critical_pending else ""))
    if s.rubric.fail_on_pending and rb.pending_decisions:
        print("\n⚠ 이 환경은 미확정 기준이 있으면 기동을 거부합니다.")

    if backend == "Anthropic":
        print("\n⚠ 실제 Claude API 를 부릅니다.")
        print("  실측(2026-08-22, 4건 평균): 청크 $2.63·6분25초 / 단일 $1.67·12분06초.")
        print("  비용은 시도 수에 비례합니다 — 1건 = 1회가 아닙니다.")
        print("  돈이 나가지 않게 하려면 .env 에 KRPL_LLM_BACKEND=replay 를 넣으십시오.")
    elif backend == "Replay":
        print("\n저장된 산출물을 되돌려 줍니다. 비용은 들지 않습니다.")
        if not os.getenv("ANTHROPIC_API_KEY"):
            print("  실제 호출을 하려면 .env 의 ANTHROPIC_API_KEY 를 채우십시오.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
