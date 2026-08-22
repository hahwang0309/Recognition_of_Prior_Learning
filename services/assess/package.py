"""AI 입력 패키지 조립 — DB에서 읽어 한 덩어리 JSON으로 만든다.

여기에는 판단이 없다. 조회와 배치만 한다.
「매칭기는 AI가 처리하기 편하도록 정보를 전처리하는 정도여야 한다」는 원칙에 따른다.

패키지 구성
  documents       제출 자료 목록 (유형·신뢰도등급·발급처)
  fragments       자료를 쪼갠 조각. AI 인용의 유일한 단위
  prior_learning  기이수 능력단위 (Track A 방식으로 대조할 대상)
  ncs             목표 종목이 요구하는 능력단위 → 요소 → 수행준거 → KSA
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from krpl_parsers.structuring import Fragment, extract_prior_learning


def _units(s: Session, program_id: str) -> list[dict]:
    """종목이 요구하는 능력단위와 그 하위 구조. 판(version)은 훈련기준을 따른다."""
    req = list(s.execute(text("""
        SELECT r.unit_code, COALESCE(r.unit_name, u.unit_name, r.unit_code) AS unit_name,
               r.required_hours, r.min_hours,
               COALESCE(r.unit_version, u.latest_version) AS unit_version
        FROM catalog_wsd_required r
        LEFT JOIN catalog_ncs_unit u ON u.unit_code = r.unit_code
        WHERE r.program_id = :p
        ORDER BY r.required_hours DESC, r.unit_code"""), {"p": program_id}).mappings())
    if not req:
        return []

    codes = [r["unit_code"] for r in req]
    els: dict[str, list[dict]] = {}
    for r in s.execute(text("""
        SELECT unit_code, element_no, element_id, element_name
        FROM catalog_ncs_element WHERE unit_code = ANY(:c)
        ORDER BY unit_code, element_no"""), {"c": codes}).mappings():
        els.setdefault(r["unit_code"], []).append(dict(r))

    pcs: dict[tuple[str, int], list[str]] = {}
    for uc, en, txt in s.execute(text("""
        SELECT unit_code, element_no, pc_text FROM catalog_ncs_pc
        WHERE unit_code = ANY(:c) ORDER BY unit_code, element_no, pc_no"""), {"c": codes}):
        pcs.setdefault((uc, en), []).append(txt)

    # KSA 는 수행준거마다 반복 수록된다. (유형, 번호) 로 중복을 걷어낸다.
    ksa: dict[tuple[str, int], dict[str, str]] = {}
    for uc, en, kt, kn, txt in s.execute(text("""
        SELECT unit_code, element_no, ksa_type, ksa_no, ksa_text FROM catalog_ncs_ksa
        WHERE unit_code = ANY(:c) ORDER BY unit_code, element_no, ksa_type, ksa_no"""),
        {"c": codes}):
        ksa.setdefault((uc, en), {}).setdefault(f"{kt}{kn}", txt)

    out = []
    for r in req:
        uc = r["unit_code"]
        out.append({
            "unit_code": uc, "unit_name": r["unit_name"],
            "required_hours": r["required_hours"], "min_hours": r["min_hours"],
            "unit_version": r["unit_version"],
            "elements": [{
                "element_id": e["element_id"], "element_name": e["element_name"],
                "performance_criteria": pcs.get((uc, e["element_no"]), []),
                "ksa": [{"ref": k, "text": v}
                        for k, v in sorted(ksa.get((uc, e["element_no"]), {}).items(),
                                           key=lambda x: (x[0][:2], int(x[0][2:])))],
            } for e in els.get(uc, [])],
        })
    return out


def build_package(s: Session, submission_id: int) -> dict:
    """접수 건 하나를 AI 입력 패키지로 만든다."""
    sub = s.execute(text("""
        SELECT case_number, track, target_program_id, note
        FROM submission WHERE id = :i"""), {"i": submission_id}).mappings().first()
    if sub is None:
        # 접수 건이 지워졌는데 큐에 작업이 남은 경우. 다시 시도해도 소용없다.
        raise LookupError(f"접수 건이 없습니다: submission_id={submission_id}")

    docs = [dict(r) for r in s.execute(text("""
        SELECT doc_key AS doc_id, doc_type, grade, issuer, issued_on AS issued,
               parsed_format AS format
        FROM document WHERE submission_id = :i ORDER BY doc_key"""),
        {"i": submission_id}).mappings()]

    frags = [dict(r) for r in s.execute(text("""
        SELECT fid, doc_key AS doc_id, doc_type, grade, text, stype, freq
        FROM fragment WHERE submission_id = :i ORDER BY fid"""),
        {"i": submission_id}).mappings()]

    units = _units(s, sub["target_program_id"])
    hours = {u["unit_code"]: (u["unit_name"], u["required_hours"]) for u in units}

    # 기이수는 저장된 조각에서 다시 뽑는다 — 수집 때와 같은 결정론적 절차다.
    by_doc: dict[str, list[Fragment]] = {}
    for f in frags:
        by_doc.setdefault(f["doc_id"], []).append(
            Fragment(fid=f["fid"], text=f["text"], stype=f["stype"], freq=f["freq"]))
    grade = {d["doc_id"]: d["grade"] for d in docs}
    dtype = {d["doc_id"]: d["doc_type"] for d in docs}

    pl: dict[str, dict] = {}
    for doc_id, fl in by_doc.items():
        for x in extract_prior_learning(fl, doc_id, set(hours)):
            name, req = hours.get(x.unit_code, (x.unit_code, None))
            cand = {"unit_code": x.unit_code, "unit_name": name, "required_hours": req,
                    "completed_hours": x.completed_hours, "evaluation": x.evaluation,
                    "evaluated": x.evaluated, "fid": x.fid, "doc_id": doc_id,
                    "doc_type": dtype.get(doc_id), "grade": grade.get(doc_id),
                    "source_text": x.source_text}
            prev = pl.get(x.unit_code)
            if prev is None or (cand["completed_hours"] or 0) > (prev["completed_hours"] or 0):
                pl[x.unit_code] = cand

    return {
        "applicant_id": sub["case_number"],
        "target_program": sub["target_program_id"],
        "applicant_type": sub["note"],
        "documents": docs,
        "fragments": frags,
        "prior_learning": sorted(pl.values(), key=lambda x: -(x["completed_hours"] or 0)),
        "ncs": {"program": sub["target_program_id"], "units": units},
    }


SHARED_KEYS = ("applicant_id", "target_program", "applicant_type",
               "documents", "fragments", "prior_learning")


def shared_part(package: dict) -> dict:
    """청크마다 똑같이 들어가는 부분 — 지원자가 낸 것 전부.

    이 덩어리를 캐시되는 자리에 두면 두 번째 청크부터 10% 가격이 된다.
    분량은 패키지의 20% 남짓이다 (나머지 79% 는 NCS 요구사항이라 청크마다 갈린다).
    """
    return {k: package[k] for k in SHARED_KEYS}


def split_package(package: dict) -> list[dict]:
    """능력단위마다 하나씩 쪼갠다.

    쪼개도 지원자 자료는 통째로 들어간다 — 어느 능력단위의 근거가 어느 문서에
    있을지 미리 알 수 없기 때문이다. 갈리는 것은 NCS 요구사항뿐이다.
    """
    shared = shared_part(package)
    return [dict(shared, ncs={"program": package["ncs"]["program"], "units": [u]})
            for u in package["ncs"]["units"]]


def package_hash(package: dict) -> str:
    """같은 입력이면 같은 값. 재현성 기록에 쓴다."""
    core = {k: package[k] for k in ("target_program", "documents", "fragments", "prior_learning")}
    return hashlib.sha256(
        json.dumps(core, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def package_stats(package: dict) -> dict:
    n_el = sum(len(u["elements"]) for u in package["ncs"]["units"])
    n_ksa = sum(len(e["ksa"]) for u in package["ncs"]["units"] for e in u["elements"])
    return {"n_documents": len(package["documents"]), "n_fragments": len(package["fragments"]),
            "n_units": len(package["ncs"]["units"]), "n_elements": n_el, "n_ksa": n_ksa,
            "n_prior_learning": len(package["prior_learning"])}
