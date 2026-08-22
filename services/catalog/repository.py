"""NCS 카탈로그 조회. 읽기 전용."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from krpl_rules.track_a import HeldUnit, RequiredUnit


@dataclass(frozen=True)
class ProgramInfo:
    program_id: str
    official_name: str | None
    official_status: str | None
    total_hours: int
    n_units: int
    daebunryu: str | None
    qc_status: str | None


class CatalogRepo:
    def __init__(self, session: Session):
        self.s = session

    # ── 종목 ──
    def get_program(self, program_id: str) -> ProgramInfo | None:
        r = self.s.execute(text("""
            SELECT program_id, official_name, official_status, total_hours,
                   n_units, daebunryu, qc_status
            FROM catalog_wsd_program WHERE program_id = :p"""), {"p": program_id}).first()
        return ProgramInfo(*r) if r else None

    def search_programs(self, q: str | None = None, active_only: bool = True,
                        limit: int = 50) -> list[ProgramInfo]:
        sql = """SELECT program_id, official_name, official_status, total_hours,
                        n_units, daebunryu, qc_status
                 FROM catalog_wsd_program WHERE 1=1"""
        p: dict = {"lim": limit}
        if active_only:
            sql += " AND official_status = '유효'"
        if q:
            sql += " AND (program_id ILIKE :q OR official_name ILIKE :q)"
            p["q"] = f"%{q}%"
        sql += " ORDER BY program_id LIMIT :lim"
        return [ProgramInfo(*r) for r in self.s.execute(text(sql), p)]

    def required_units(self, program_id: str) -> list[RequiredUnit]:
        return [RequiredUnit(*r) for r in self.s.execute(text("""
            SELECT unit_code, COALESCE(unit_name, unit_code), required_hours, min_hours
            FROM catalog_wsd_required WHERE program_id = :p
            ORDER BY required_hours DESC, unit_code"""), {"p": program_id})]

    # ── 자격 ──
    def get_qualification(self, qual_id: str) -> dict | None:
        r = self.s.execute(text("""
            SELECT qual_id, grade, version, total_a, essential_b, n_units, qc_status
            FROM catalog_cbq_qual WHERE qual_id = :q"""), {"q": qual_id}).mappings().first()
        return dict(r) if r else None

    def search_qualifications(self, q: str | None = None, limit: int = 50) -> list[dict]:
        sql = "SELECT qual_id, grade, total_a, essential_b, n_units FROM catalog_cbq_qual WHERE 1=1"
        p: dict = {"lim": limit}
        if q:
            sql += " AND qual_id ILIKE :q"
            p["q"] = f"%{q}%"
        sql += " ORDER BY qual_id LIMIT :lim"
        return [dict(r) for r in self.s.execute(text(sql), p).mappings()]

    def held_units(self, qual_ids: list[str]) -> list[HeldUnit]:
        """복수 자격 보유 시 능력단위별 최대 편성시간을 채택한다."""
        if not qual_ids:
            return []
        rows = self.s.execute(text("""
            SELECT DISTINCT ON (unit_code)
                   unit_code, composed_hours, composed_hours_min, qual_id
            FROM catalog_cbq_composed
            WHERE qual_id = ANY(:ids)
            ORDER BY unit_code, composed_hours DESC"""), {"ids": qual_ids})
        return [HeldUnit(*r) for r in rows]

    # ── 추천 (목표 종목 미정 시) ──
    def recommend_programs(self, qual_ids: list[str], floor: float, limit: int = 10) -> list[dict]:
        if not qual_ids:
            return []
        return [dict(r) for r in self.s.execute(text("""
            SELECT * FROM (
              SELECT w.program_id, g.official_name, g.total_hours,
                count(b.unit_code) AS common_units, g.n_units,
                sum(CASE WHEN b.composed_hours >= w.required_hours
                         THEN w.required_hours ELSE 0 END) AS h_full,
                sum(CASE WHEN b.composed_hours >= w.required_hours * :floor
                         THEN w.required_hours ELSE 0 END) AS h_adj
              FROM catalog_wsd_required w
              JOIN catalog_wsd_program g ON g.program_id = w.program_id
              LEFT JOIN (
                SELECT DISTINCT ON (unit_code) unit_code, composed_hours
                FROM catalog_cbq_composed WHERE qual_id = ANY(:ids)
                ORDER BY unit_code, composed_hours DESC) b ON b.unit_code = w.unit_code
              WHERE g.official_status = '유효' AND g.total_hours > 0
              GROUP BY w.program_id, g.official_name, g.total_hours, g.n_units
              HAVING count(b.unit_code) > 0) s
            ORDER BY h_adj::numeric / total_hours DESC, common_units DESC
            LIMIT :lim"""), {"ids": qual_ids, "floor": floor, "lim": limit}).mappings()]
