"""`.env` 가 실제로 먹는지 확인한다.

여기서 확인할 것은 「파일을 읽는다」가 아니라
**키를 .env 에 넣었을 때 앱이 실제로 그 키를 쓰는가**이다.

한때 그렇지 않았다. `pydantic-settings` 의 `env_file` 은 `Settings` 필드에만 닿고
`os.getenv` 로 읽는 값(ANTHROPIC_API_KEY·KRPL_LLM_BACKEND)에는 닿지 않아서,
키를 넣어도 조용히 재생(replay) 백엔드로 돌았다. 가장 나쁜 실패 방식이다.

import 시점 동작이라 별도 프로세스로 확인한다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2]
PROBE = """
import json, os, sys
from krpl_core.config import get_settings
from krpl_core.llm import get_client
s = get_settings()
try:
    backend = type(get_client()).__name__
except Exception as e:
    backend = f"ERROR: {e}"
print("@@" + json.dumps({
    "env": s.env, "storage": s.storage.local_path, "db": s.database_url,
    "key": os.getenv("ANTHROPIC_API_KEY"),
    "backend_var": os.getenv("KRPL_LLM_BACKEND"),
    "replay_dir": os.getenv("KRPL_REPLAY_DIR"),
    "backend": backend}, ensure_ascii=False))
"""


def probe(env_text: str | None, **env: str) -> dict:
    """임시 .env 를 놓고 별도 프로세스로 실제 기동 결과를 받아 온다."""
    envfile = APP / ".env"
    backup = envfile.read_text(encoding="utf-8") if envfile.exists() else None
    try:
        if env_text is None:
            envfile.unlink(missing_ok=True)
        else:
            envfile.write_text(env_text, encoding="utf-8")
        e = {k: v for k, v in os.environ.items()
             if not k.startswith("KRPL_") and k != "ANTHROPIC_API_KEY"}
        e.update(env)
        r = subprocess.run([sys.executable, "-c", PROBE], cwd="/", env=e,
                           capture_output=True, text=True)
        line = next((x for x in r.stdout.splitlines() if x.startswith("@@")), None)
        assert line, f"탐침 실패\nstdout={r.stdout}\nstderr={r.stderr[-2000:]}"
        return json.loads(line[2:])
    finally:
        if backup is None:
            envfile.unlink(missing_ok=True)
        else:
            envfile.write_text(backup, encoding="utf-8")


def test_example_file_exists_and_covers_every_variable():
    """견본에 빠진 변수가 있으면 사용자는 그게 있는 줄도 모른다."""
    text = (APP / ".env.example").read_text(encoding="utf-8")
    for k in ("KRPL_ENV", "KRPL_DATABASE_URL", "KRPL_LLM_BACKEND",
              "ANTHROPIC_API_KEY", "KRPL_REPLAY_DIR"):
        assert f"\n{k}=" in text, f"견본에 {k} 없음"
    assert "cp .env.example .env" in text


def test_example_ships_no_real_secret():
    text = (APP / ".env.example").read_text(encoding="utf-8")
    assert "\nANTHROPIC_API_KEY=\n" in text, "견본에 키가 채워져 있으면 안 된다"
    assert "sk-ant-" not in text


def test_env_is_gitignored():
    assert "\n.env\n" in "\n" + (APP / ".gitignore").read_text(encoding="utf-8")


def test_api_key_from_dotenv_actually_selects_anthropic():
    """이게 이 파일의 핵심 — 키를 넣으면 실제 호출 경로로 가는가."""
    d = probe("ANTHROPIC_API_KEY=sk-ant-test-0123456789\n")
    assert d["key"] == "sk-ant-test-0123456789"
    assert d["backend"] == "AnthropicClient"


def test_no_key_falls_back_to_replay():
    d = probe("KRPL_ENV=local\n")
    assert d["key"] is None and d["backend"] == "ReplayClient"


def test_real_env_beats_dotenv():
    """실행할 때 직접 준 값이 이겨야 한다.
    `KRPL_LLM_BACKEND=replay ./scripts/dev.sh assess …` 로 돈을 막을 수 있어야 한다."""
    d = probe("KRPL_LLM_BACKEND=anthropic\nANTHROPIC_API_KEY=sk-ant-test-0123456789\n",
              KRPL_LLM_BACKEND="replay")
    assert d["backend_var"] == "replay" and d["backend"] == "ReplayClient"


@pytest.mark.parametrize("var", ["KRPL_LLM_BACKEND", "KRPL_REPLAY_DIR"])
def test_blank_value_means_unset(var):
    """`KEY=` 를 「빈 문자열」로 두면 기동이 죽는다. 견본이 비워 두라고 안내하는 항목들이다."""
    d = probe(f"{var}=\nKRPL_ENV=local\n")
    assert d[{"KRPL_LLM_BACKEND": "backend_var", "KRPL_REPLAY_DIR": "replay_dir"}[var]] is None
    assert d["backend"] == "ReplayClient"


def test_the_shipped_example_boots():
    """견본을 그대로 .env 로 복사해도 기동돼야 한다. 사용자가 처음 하는 일이다."""
    d = probe((APP / ".env.example").read_text(encoding="utf-8"))
    assert d["env"] == "local"
    assert d["backend"] == "ReplayClient"          # 키를 안 채웠으니 돈이 나가지 않는다
    assert d["db"].startswith("postgresql+psycopg://")


def test_env_selects_the_overlay_file():
    """KRPL_ENV 는 어느 환경 파일을 덧씌울지 정한다 — 한때 .env 로는 안 먹었다."""
    assert probe("KRPL_ENV=test\n")["storage"].endswith("_test")
    assert probe("KRPL_ENV=local\n")["storage"] == "./storage"


def test_dotenv_found_from_any_directory():
    """탐침은 cwd=/ 에서 돈다. 상대경로로 읽었다면 여기서 드러난다."""
    assert probe("KRPL_ENV=test\n")["storage"].endswith("_test")


def test_missing_dotenv_is_not_an_error():
    d = probe(None)
    assert d["env"] == "local" and d["backend"] == "ReplayClient"
