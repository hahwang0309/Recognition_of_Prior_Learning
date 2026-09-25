"""접수 건 삭제 — 되돌릴 수 없다. 그래서 확인을 두 번 받고 흔적을 남긴다.

## 왜 필요한가

시험 삼아 넣은 접수, 잘못 받은 접수가 할 일 목록에 영영 남는다. 닫을 방법이
없어 「근거 분석을 돌리는 수밖에 없는」 상태가 됐다(실측 R2026-9103).

## 무엇을 지우나

DB 는 `submission` 한 행을 지우면 문서·조각·판정·요소·검토·산출물 색인·최종 판정이
외래키 CASCADE 로 함께 사라진다.

파일은 둘로 나눈다.

    storage/uploads/{심사번호}   지원자가 낸 원본 — **항상 지운다**. 개인정보다.
    storage/audit/{심사번호}     마스킹된 조각·AI 입출력·판정 근거 — **기본은 남긴다**

감사 산출물을 남기는 이유: 잘못 지웠을 때 무엇을 보고 판정했는지가 마지막으로
남는 자리이기 때문이다. 정말 흔적까지 없애야 하면 `purge_audit` 로 함께 지운다.

## 남는 것

`audit_log` 는 외래키가 없어 살아남는다. 지울 때 무엇을 지웠는지(문서 수·판정 수·
최종 판정 유무)를 한 줄 더 적는다 — 「있었다가 지워졌다」는 사실 자체가 기록이다.

## ⚠ 순서 — 파일은 DB 가 확정된 **뒤**에 지운다

DB 는 예외가 나면 롤백되지만 지워진 파일은 돌아오지 않는다. 전에는 파일을 먼저
지우고 그 뒤 줄에서 예외가 나, **접수는 살아 있는데 감사 산출물만 사라졌다**
(실제 사고: R2026-9103 의 수집 기록 4건). 그래서 커밋을 확인한 뒤에만 파일을 건드린다.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from krpl_core.audit import audit_root
from krpl_core.config import get_settings


def _safe(name: str) -> str:
    """경로에 쓸 수 있는 이름만 남긴다 — 심사번호로 상위 폴더를 타지 못하게."""
    return "".join(c for c in (name or "") if c.isalnum() or c in "-_")


def preview(s: Session, submission_id: int) -> dict[str, Any] | None:
    """지우면 무엇이 사라지는지. 화면이 먼저 보여 주고 확인을 받는다."""
    sub = s.execute(text("""SELECT id, case_number, track, status, target_program_id
                            FROM submission WHERE id=:i"""),
                    {"i": submission_id}).mappings().first()
    if sub is None:
        return None
    one = lambda q: s.execute(text(q), {"i": submission_id}).scalar() or 0   # noqa: E731
    case = _safe(sub["case_number"])
    up = Path(get_settings().storage.local_path).resolve() / "uploads" / case
    ad = audit_root() / case
    return {
        **dict(sub),
        "n_documents": one("SELECT count(*) FROM document WHERE submission_id=:i"),
        "n_fragments": one("SELECT count(*) FROM fragment WHERE submission_id=:i"),
        "n_assessments": one("SELECT count(*) FROM assessment WHERE submission_id=:i"),
        "n_reviews": one("""SELECT count(*) FROM element_review r
                            JOIN assessment a ON a.id = r.assessment_id
                            WHERE a.submission_id=:i"""),
        "has_decision": bool(one("SELECT count(*) FROM final_decision WHERE submission_id=:i")),
        "uploads": str(up) if up.exists() else None,
        "audit": str(ad) if ad.exists() else None,
    }


def remove(s: Session, submission_id: int, confirm: str,
           purge_audit: bool = False, actor: str | None = None) -> dict[str, Any]:
    """접수 건을 지운다. `confirm` 이 심사번호와 정확히 같아야 한다.

    번호를 직접 치게 하는 이유: 목록에서 잘못 누른 한 번으로 지워지면 안 되기 때문이다.
    """
    info = preview(s, submission_id)
    if info is None:
        raise LookupError("접수 건을 찾을 수 없습니다")
    if (confirm or "").strip() != info["case_number"]:
        raise ValueError(f"심사번호가 다릅니다 — 지우려면 「{info['case_number']}」 를 그대로 적으십시오")

    s.execute(text("""INSERT INTO audit_log (entity, entity_id, action, actor, detail)
                      VALUES ('submission', :i, 'removed', :w, CAST(:d AS jsonb))"""),
              {"i": str(submission_id), "w": actor or "user",
               "d": json.dumps({**info, "purge_audit": purge_audit}, ensure_ascii=False, default=str)})
    s.execute(text("DELETE FROM submission WHERE id=:i"), {"i": submission_id})

    # 여기서 확정한다. 실패하면 예외가 나고 **파일은 아직 그대로다.**
    s.commit()

    gone = []
    if info["uploads"]:                      # 개인정보 원본은 언제나 지운다
        shutil.rmtree(info["uploads"], ignore_errors=True)
        gone.append("uploads")
    if purge_audit and info["audit"]:
        shutil.rmtree(info["audit"], ignore_errors=True)
        gone.append("audit")
    return {"case_number": info["case_number"], "removed_files": gone,
            "audit_kept": bool(info["audit"]) and not purge_audit}
