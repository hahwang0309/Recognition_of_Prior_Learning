"""단계별 중간 산출물 보존.

## 왜

「잘 됐습니다」라는 말만 남으면 확인할 방법이 없다.
각 단계가 **실제로 무엇을 받아 무엇을 내놨는지** 파일로 남긴다.
감사자는 앱을 거치지 않고 파일만 열어 봐도 된다.

## 어디에

    storage/audit/{심사번호}/{단계}/{순번}_{이름}.{확장자}

파일은 손대지 않는다. 다시 돌리면 새 회차 폴더가 생긴다.
DB 의 `artifact` 표는 색인일 뿐이다 — 무엇이 언제 어떤 해시로 만들어졌는지.

## 개인정보

마스킹 **이전** 원문은 저장하지 않는다. 저장하면 마스킹한 의미가 없다.
대신 「어디서 어떤 유형이 몇 글자 가려졌는지」를 값 없이 기록한다.
가려진 값 자체는 어디에도 남지 않는다.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from krpl_core.config import get_settings

# 단계 이름 — 화면·CLI 가 이 순서로 보여준다
STAGES = ["ingest", "package", "llm", "validate", "review", "panel", "plan", "decide"]   # panel·plan: 위원 제출·확인 계획 (2026-09-24)
STAGE_KO = {"ingest": "① 문서 수집", "package": "② AI 입력 조립", "llm": "③ AI 분석",
            "validate": "④ 기계 검증", "review": "⑤ 전문가 검토", "decide": "⑥ 최종 판정"}


def audit_root() -> Path:
    return Path(get_settings().storage.local_path).resolve() / "audit"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@dataclass
class AuditStore:
    """한 접수 건의 산출물 보관함.

    run 을 나누면 같은 단계를 다시 돌려도 이전 것이 덮이지 않는다.
    (판정 재실행 시 run = assessment_id)
    """
    session: Session
    case_number: str
    submission_id: int
    assessment_id: int | None = None

    @property
    def base(self) -> Path:
        p = audit_root() / self.case_number
        return p / f"판정{self.assessment_id}" if self.assessment_id else p

    def write(self, stage: str, name: str, data: Any, *,
              seq: int = 0, note: str | None = None) -> int:
        """산출물 하나를 남기고 artifact id 를 돌려준다.

        data 가 str 이면 그대로, 아니면 JSON 으로 적는다.
        """
        if stage not in STAGES:
            raise ValueError(f"모르는 단계: {stage} (가능: {STAGES})")
        if isinstance(data, str):
            body, ext = data, "md" if name.endswith(("지침", "요청", "프롬프트")) else "txt"
        else:
            body, ext = json.dumps(data, ensure_ascii=False, indent=1), "json"

        d = self.base / stage
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{seq:02d}_{name}.{ext}"
        raw = body.encode("utf-8")
        path.write_bytes(raw)

        rel = str(path.relative_to(audit_root()))
        key = {"s": self.submission_id, "a": self.assessment_id,
               "g": stage, "q": seq, "n": name}
        # ON CONFLICT 를 쓰지 않는다. 수집 단계는 assessment_id 가 NULL 인데
        # PostgreSQL 의 UNIQUE 는 NULL 을 서로 다른 값으로 보므로 충돌이 잡히지 않는다.
        # 그러면 다시 수집할 때마다 색인 행이 쌓이고 옛 행이 낡은 해시를 물고 남는다.
        vals = key | {"p": rel, "h": _sha(raw), "b": len(raw), "o": note}
        if self.assessment_id is not None:
            # 판정이 있는 단계는 UNIQUE 키에 NULL 이 없으므로 ON CONFLICT 가 잡힌다.
            # 위원 화면이 저장을 연달아 보내면(라디오 + 근거 체크) 두 요청이 겹쳐
            # DELETE→INSERT 사이에 서로 끼어들어 중복 키 오류(500)가 났다 (2026-09-23 실측).
            return self.session.execute(text("""
                INSERT INTO artifact (submission_id, assessment_id, stage, seq, name,
                                      path, sha256, n_bytes, note)
                VALUES (:s, :a, :g, :q, :n, :p, :h, :b, :o)
                ON CONFLICT (submission_id, assessment_id, stage, seq, name) DO UPDATE
                SET path=EXCLUDED.path, sha256=EXCLUDED.sha256, n_bytes=EXCLUDED.n_bytes,
                    note=EXCLUDED.note, created_at=now()
                RETURNING id"""), vals).scalar_one()
        self.session.execute(text("""
            DELETE FROM artifact
            WHERE submission_id=:s AND assessment_id IS NOT DISTINCT FROM :a
              AND stage=:g AND seq=:q AND name=:n"""), key)
        return self.session.execute(text("""
            INSERT INTO artifact (submission_id, assessment_id, stage, seq, name,
                                  path, sha256, n_bytes, note)
            VALUES (:s, :a, :g, :q, :n, :p, :h, :b, :o)
            RETURNING id"""), vals).scalar_one()

    def manifest(self) -> dict[str, Any]:
        """이 건에 남은 산출물 목록. 해시를 붙여 위·변조를 확인할 수 있게 한다."""
        rows = list(self.session.execute(text("""
            SELECT id, assessment_id, stage, seq, name, path, sha256, n_bytes, note, created_at
            FROM artifact WHERE submission_id=:s
            ORDER BY assessment_id NULLS FIRST, stage, seq, name"""),
            {"s": self.submission_id}).mappings())
        return {"case_number": self.case_number, "submission_id": self.submission_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "root": str(audit_root()),
                "artifacts": [dict(r) | {"created_at": r["created_at"].isoformat()}
                              for r in rows]}


def read_artifact(s: Session, artifact_id: int) -> tuple[dict, str | None]:
    """산출물 하나를 읽는다. 저장 당시 해시와 다르면 알려 준다."""
    r = s.execute(text("""
        SELECT a.*, sub.case_number FROM artifact a
        JOIN submission sub ON sub.id = a.submission_id WHERE a.id=:i"""),
        {"i": artifact_id}).mappings().first()
    if r is None:
        raise LookupError(f"산출물을 찾을 수 없습니다: {artifact_id}")
    p = audit_root() / r["path"]
    if not p.exists():
        return dict(r) | {"integrity": "파일 없음"}, None
    raw = p.read_bytes()
    ok = _sha(raw) == r["sha256"]
    return dict(r) | {"integrity": "일치" if ok else "⚠ 해시 불일치"}, raw.decode("utf-8")


def masking_report(counts: dict[str, int], hits: list[dict]) -> dict[str, Any]:
    """마스킹 감사 기록. 가려진 값은 넣지 않는다 — 넣으면 마스킹한 의미가 없다."""
    return {
        "설명": "마스킹된 값 자체는 저장하지 않는다. 어디서 무엇이 몇 글자 가려졌는지만 남긴다.",
        "총계": counts,
        "건수": len(hits),
        "내역": hits,
    }
