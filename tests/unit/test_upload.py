"""올라온 파일을 어디에 어떤 이름으로 두는가.

이름을 그대로 쓰면 경로 조작(`../../etc/passwd`)이나 이상한 문자가 그대로 들어온다.
반대로 너무 깎으면 담당자가 나중에 그 파일이 뭐였는지 못 알아본다.
"""
from __future__ import annotations

import pytest

from krpl_core.config import get_settings
from services.ingest.upload import UploadRejected, _safe_name, store, submission_dir


@pytest.mark.parametrize("given,expect", [
    ("경력증명서.txt", "경력증명서.txt"),          # 한글은 살린다
    ("career report.PDF", "career_report.pdf"),   # 공백·대문자 정리
    ("../../etc/passwd", "passwd"),               # 경로 조작
    ("/tmp/x/이수증.hwp", "이수증.hwp"),
    ("R2026-0005", "R2026-0005"),                 # 점이 없으면 확장자가 없는 것
    ("..", "file"),
    ("a" * 200 + ".pdf", "a" * 60 + ".pdf"),      # 길이 제한
    ("샘플;rm -rf.txt", "샘플_rm_-rf.txt"),
])
def test_safe_name(given, expect):
    assert _safe_name(given) == expect


def test_submission_dir_is_a_plain_folder():
    """심사번호로 폴더를 만든다. 확장자가 붙으면 안 된다 —
    한때 `R2026-0005.r2026-0005` 가 만들어졌다."""
    d = submission_dir("R2026-0005")
    assert d.name == "R2026-0005" and d.is_dir()
    assert d.parent.name == "uploads"
    d.rmdir()


def test_store_keeps_the_original_and_numbers_it(tmp_path):
    st = store("R2026-9999", "경력증명서.txt", "근무기간: 2020~2026".encode(), 3)
    try:
        assert st.doc_key == "D03"
        assert st.path.name == "D03_경력증명서.txt"
        assert st.path.read_text(encoding="utf-8").startswith("근무기간")
        assert st.n_bytes == len("근무기간: 2020~2026".encode())
        assert st.original_name == "경력증명서.txt"
    finally:
        st.path.unlink()
        st.path.parent.rmdir()


def test_rejects_what_the_parser_cannot_read():
    with pytest.raises(UploadRejected, match="받지 않는 형식"):
        store("R2026-9999", "스캔본.png", b"\x89PNG", 1)


def test_rejects_oversize_and_empty():
    mb = get_settings().storage.max_upload_mb
    with pytest.raises(UploadRejected, match="너무 큽니다"):
        store("R2026-9999", "big.txt", b"x" * (mb * 1024 * 1024 + 1), 1)
    with pytest.raises(UploadRejected, match="빈 파일"):
        store("R2026-9999", "empty.txt", b"", 1)


def test_allowed_extensions_are_all_parseable():
    """받기로 한 형식을 파서가 정말 읽는가.
    한때 8개 중 5개(docx·xlsx·jpg·jpeg·png)를 받았는데 파서는 못 읽었다."""
    from krpl_parsers import supported_extensions
    allowed = set(get_settings().storage.allowed_extensions)
    assert allowed and allowed <= set(supported_extensions())
