"""올라온 파일을 받아 저장한다. 수집(파싱·마스킹)은 그다음이다.

파일을 먼저 디스크에 두고 그 경로로 수집을 부른다. 두 가지 이유다.
  ① 원본이 남아야 나중에 「그때 뭘 받았느냐」에 답할 수 있다
  ② 수집이 실패해도 파일은 남아 다시 시도할 수 있다

크기·확장자 제한은 config/settings.yaml 의 storage 절이 정한다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from krpl_core.config import get_settings

SAFE = re.compile(r"[^0-9A-Za-z가-힣._-]+")


class UploadRejected(ValueError):
    pass


@dataclass(frozen=True)
class Stored:
    doc_key: str
    original_name: str
    path: Path
    n_bytes: int


def _safe_name(name: str) -> str:
    """올라온 이름을 그대로 쓰지 않는다 — 경로 조작·이상한 문자를 막는다.

    점이 없으면 확장자가 없는 것이다. `rpartition` 은 그럴 때
    통째로 확장자로 넘겨주므로 그대로 쓰면 `R2026-0005.r2026-0005` 가 된다.
    """
    name = unicodedata.normalize("NFC", Path(name).name)
    stem, dot, ext = name.rpartition(".")
    if not dot:                       # 점이 없다 — 이름 전체가 stem
        stem, ext = name, ""
    stem = SAFE.sub("_", stem)[:60].strip("_. ")
    if not stem.strip("."):           # 점·밑줄만 남았다 — `..` 같은 경로 조각
        stem = "file"
    ext = SAFE.sub("", ext).lower().strip(".")[:10]
    return f"{stem}.{ext}" if ext else stem


def submission_dir(case_number: str) -> Path:
    s = get_settings().storage
    d = Path(s.local_path).resolve() / "uploads" / _safe_name(case_number)
    d.mkdir(parents=True, exist_ok=True)
    return d


def store(case_number: str, filename: str, data: bytes, seq: int) -> Stored:
    """파일 하나를 저장한다. 이름은 `D01_원본이름` 꼴로 둔다."""
    s = get_settings().storage
    ext = Path(filename).suffix.lstrip(".").lower()
    if ext not in s.allowed_extensions:
        raise UploadRejected(
            f"받지 않는 형식입니다: .{ext} (가능: {', '.join(s.allowed_extensions)})")
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise UploadRejected(
            f"파일이 너무 큽니다: {len(data) / 1024 / 1024:.1f}MB "
            f"(상한 {s.max_upload_mb}MB)")
    if not data:
        raise UploadRejected("빈 파일입니다")

    doc_key = f"D{seq:02d}"
    path = submission_dir(case_number) / f"{doc_key}_{_safe_name(filename)}"
    path.write_bytes(data)
    return Stored(doc_key=doc_key, original_name=filename, path=path,
                  n_bytes=len(data))
