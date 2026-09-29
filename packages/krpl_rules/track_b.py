"""Track B 산출물 검증기 — 순수 함수. DB·LLM 무관.

AI가 낸 판정 근거를 **기계가 다시 확인한다.** 확인하는 것은 세 가지다.

1. **인용 환각** — 없는 조각(fid)을 대거나, 원문에 없는 문장을 인용하지 않았는가.
2. **누락** — 능력단위요소나 KSA가 조용히 빠지지 않았는가.
3. **기준 위반** — 기준서의 철칙(R1 등급요건·R8 부정우선·대면평가 1건)을 어기지 않았는가.

AI에게 「검증했다」고 물어보지 않는다. 여기서 직접 대조한다.
어휘·임계값은 전부 rubric 에서 읽는다. 코드에 숫자를 박지 않는다.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["error", "warn"]
NOT_PASSED = re.compile(r"미실시|미평가|불합격|미이수|해당\s*없음")

# 정도를 말로 때우는 표현. 「50%를 크게 상회」는 몇 %인지 되짚을 수 없다.
# 시간을 다투는 심사에서 「크게」는 근거가 되지 못하므로 숫자로 적게 한다.
VAGUE = re.compile(
    r"[^.。\n]{0,50}"
    r"(크게 상회|상회하|훨씬|웃도[는니]|크게 웃|훌쩍|대폭|상당히|현저히|"
    r"충분히 (?:넘|상회)|한참|대부분 확인|거의 다 확인)"
    r"[^.。\n]{0,50}")


@dataclass(frozen=True)
class Issue:
    code: str
    element_id: str
    detail: str = ""
    severity: Severity = "error"

    def __str__(self) -> str:
        head = f"[{self.code}] {self.element_id}" if self.element_id else f"[{self.code}]"
        return f"{head}: {self.detail}" if self.detail else head


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)
    n_elements: int = 0
    n_expected: int = 0
    n_evidence: int = 0
    counts: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warn"]

    @property
    def passed(self) -> bool:
        return not self.errors

    def by_code(self, severity: Severity | None = None) -> dict[str, int]:
        return dict(Counter(i.code for i in self.issues
                            if severity is None or i.severity == severity))

    def feedback(self, limit: int = 40) -> str:
        """재요청 프롬프트에 붙일 지적 사항. 고칠 수 있을 만큼 구체적으로 쓴다."""
        errs = self.errors
        if not errs:
            return ""
        lines = [f"직전 출력에서 {len(errs)}건의 오류가 확인되었다. 아래를 고쳐 **전체를 다시** 출력하라.", ""]
        for code, n in sorted(Counter(i.code for i in errs).items(), key=lambda x: -x[1]):
            lines.append(f"■ {code} — {n}건")
            for i in [x for x in errs if x.code == code][:limit]:
                lines.append(f"   · {i.element_id or '(전체)'} {i.detail}")
        lines += ["", "지적되지 않은 부분도 함께 다시 출력하라. 일부만 보내면 안 된다."]
        return "\n".join(lines)

    def summary(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "n_elements": self.n_elements, "n_expected": self.n_expected,
            "n_evidence": self.n_evidence,
            "n_errors": len(self.errors), "n_warnings": len(self.warnings),
            "by_code": self.by_code(),
            "counts": self.counts,
            "issues": [{"code": i.code, "element_id": i.element_id,
                        "detail": i.detail, "severity": i.severity} for i in self.issues],
        }


def _refs(items: list) -> set[str]:
    """uncovered_ksa 가 문자열이든 객체든 ref 집합을 돌려준다."""
    out = set()
    for x in items or []:
        out.add(x.get("ref") if isinstance(x, dict) else x)
    return {r for r in out if r}


def validate_track_b(package: dict, out: dict, rubric) -> ValidationReport:
    """패키지(입력)와 AI 산출물을 대조한다."""
    rep = ValidationReport()
    add = lambda c, e, d="", sv="error": rep.issues.append(Issue(c, e, d, sv))  # noqa: E731

    vocab = rubric.output_vocabulary
    RECS = set(rubric.recommendations)
    DIMS = set(rubric.dimensions)
    USTATUS = set(rubric.uncovered_status)
    METHODS = set(rubric.remediation["methods"])
    FACE = set(rubric.remediation["face_to_face"])
    face_max = rubric.remediation["face_to_face_max_per_element"]
    r1_grades = set(rubric.recommendations["R1"]["requires"]["period_backing_grades"])
    r0_floor = rubric.recommendations["R0"]["downgrade_if"]["completed_hours_ratio_below"]
    ksa_min_decided = rubric.is_decided("recommendations.R1.requires.ksa_coverage_min")
    ksa_min = rubric.recommendations["R1"]["requires"].get("ksa_coverage_min")

    frags = {f["fid"]: f for f in package["fragments"]}
    elems: dict[str, dict] = {}
    for u in package["ncs"]["units"]:
        for e in u["elements"]:
            elems[e["element_id"]] = {
                "unit_code": u["unit_code"], "unit_name": u["unit_name"],
                "required_hours": u["required_hours"],
                "refs": {k["ref"] for k in e["ksa"]},
            }

    got = [x.get("element_id") for x in out.get("elements") or []]
    rep.n_elements, rep.n_expected = len(got), len(elems)
    for m in sorted(elems.keys() - set(got)):
        add("element_누락", m, elems[m]["unit_name"])
    for x in sorted(set(got) - elems.keys()):
        add("element_없음", str(x))
    for x, n in Counter(got).items():
        if n > 1:
            add("element_중복", str(x), f"{n}회")

    for el in out.get("elements") or []:
        eid = el.get("element_id")
        if eid not in elems:
            continue
        M = elems[eid]
        rec = el.get("recommendation")

        for fld, ok in (("evidence_level", set(vocab["evidence_level"])),
                        ("recommendation", RECS),
                        ("verification_method", set(vocab["verification_method"])),
                        ("confidence", set(vocab["confidence"]))):
            if el.get(fld) not in ok:
                add(f"{fld}_오류", eid, repr(el.get(fld)))
        for fld in ("proven_dimensions", "missing_dimensions"):
            for d in el.get(fld) or []:
                if d not in DIMS:
                    add("차원명_오류", eid, f"{fld}={d}")

        # ── 인용 ──
        seen: set[str] = set()
        ev_grades: set[str] = set()
        for ev in el.get("evidence") or []:
            rep.n_evidence += 1
            # 모델이 ksa_ref 를 목록으로 돌려준 적이 있다(A1 R2026-9101, 2026-09-28) — set 조회에서
            # TypeError 로 판정 전체가 죽었다. 문자열이 아니면 「없음」 오류로 다루고 다시 요청한다.
            if not isinstance(ev.get("ksa_ref"), str) or ev.get("ksa_ref") not in M["refs"]:
                add("ksa_ref_없음", eid, repr(ev.get("ksa_ref")))
            else:
                seen.add(ev["ksa_ref"])
            fids = ev.get("fids") or []
            if not fids:
                add("fid_없음", eid, f"ksa_ref={ev.get('ksa_ref')}")
            if "evidence_fit" in vocab and ev.get("fit") not in set(vocab["evidence_fit"]):
                add("fit_어휘", eid, f"ksa_ref={ev.get('ksa_ref')} fit={ev.get('fit')!r}")
            for fid in fids:
                if fid not in frags:
                    add("fid_존재하지않음", eid, fid)
                else:
                    ev_grades.add(frags[fid]["grade"])
            q = (ev.get("quote") or "").strip()
            if q and fids and not any(f in frags and q in frags[f]["text"] for f in fids):
                add("인용문_불일치", eid, f"{q[:40]}… ({','.join(fids)})")

        # ── 소속·기간 보증 ──
        pb = el.get("period_backing")
        pb_grades: set[str] = set()
        if pb is None:
            add("period_backing_누락", eid)
        else:
            pb_fids = pb.get("fids") or []
            pgl = pb.get("grades") or []
            pb_grades = set(pgl)
            for f in pb_fids:
                if f not in frags:
                    add("pb_fid없음", eid, f)
            if len(pgl) != len(pb_grades):
                add("pb_등급중복", eid, str(pgl))
            real = {frags[f]["grade"] for f in pb_fids if f in frags}
            if real and pb_grades != real:
                add("pb_등급불일치", eid, f"선언 {sorted(pb_grades)} ↔ 실제 {sorted(real)}")
            if pb_grades and not pb_fids:
                add("pb_근거없이등급선언", eid, str(sorted(pb_grades)))

        # ── 등급 칸 ── (뒷받침과 반박을 섞으면 안 된다)
        sgl = el.get("source_grades") or []
        sg = set(sgl)
        if len(sgl) != len(sg):
            add("source_grades_중복", eid, str(sgl))
        exp = ev_grades | pb_grades
        if exp and sg != exp:
            add("source_grades_불일치", eid, f"선언 {sorted(sg)} ↔ 실제 {sorted(exp)}")
        elif sg and not exp:
            add("source_grades_근거없음", eid, f"뒷받침 자료 없이 {sorted(sg)} 선언")

        neg = el.get("negative_statements") or []
        real_ng = {frags[n["fid"]]["grade"] for n in neg if n.get("fid") in frags}
        ngl = el.get("negative_grades")
        if ngl is None:
            if real_ng:
                add("negative_grades_누락", eid, str(sorted(real_ng)))
        elif set(ngl) != real_ng:
            add("negative_grades_불일치", eid, f"선언 {sorted(set(ngl))} ↔ 실제 {sorted(real_ng)}")
        for ns in neg:
            fid, q = ns.get("fid"), (ns.get("quote") or "").strip()
            if fid not in frags:
                add("부정_fid없음", eid, str(fid))
            elif q and q not in frags[fid]["text"]:
                add("부정_인용불일치", eid, q[:40])

        # ── 증거 없는 KSA ──
        for x in el.get("uncovered_ksa") or []:
            if not isinstance(x, dict):
                add("uncovered_구형식", eid, str(x))
                continue
            if x.get("ref") not in M["refs"]:
                add("uncovered_ref_없음", eid, repr(x.get("ref")))
            if x.get("status") not in USTATUS:
                add("uncovered_status_오류", eid, repr(x.get("status")))
        unc = _refs(el.get("uncovered_ksa"))

        # KSA 전수 배정 — R0 는 기이수로 갈음하므로 제외
        if rec != "R0" and (tot := len(seen | unc)) != len(M["refs"]):
            missing = sorted(M["refs"] - seen - unc)
            add("KSA_합_불일치", eid, f"{tot}/{len(M['refs'])} 빠짐 {missing[:6]}")

        # ── 보완계획 ──
        rem = el.get("remediation")
        face = [r for r in (rem or []) if r.get("method") in FACE]
        if face_max is not None and len(face) > face_max:
            add("대면평가_중복", eid, " + ".join(str(r.get("method")) for r in face))
        if rec == "R0":
            pl = el.get("prior_learning") or {}
            if not pl.get("applies"):
                add("R0_기이수없음", eid)
            else:
                ev_txt = str(pl.get("evaluation") or "")
                if not ev_txt.strip() or NOT_PASSED.search(ev_txt):
                    add("R0_평가미확인", eid, repr(ev_txt[:30]))
                ch, rh = pl.get("completed_hours"), pl.get("required_hours") or M["required_hours"]
                if ch is not None and rh and ch / rh < r0_floor:
                    add("R0_시간미달", eid, f"{ch}/{rh} = {ch / rh:.0%} < {r0_floor:.0%} → R1 로 내려야 함")
            if rem or unc:
                add("R0_보완계획존재", eid, f"보완 {len(rem or [])}건 · 미확보 {len(unc)}개")
        if rem is None and unc:
            add("remediation_누락", eid, f"미확보 {len(unc)}개")
        else:
            covered: set[str] = set()
            for r in rem or []:
                if r.get("method") not in METHODS:
                    add("보완방법_오류", eid, repr(r.get("method")))
                if not (r.get("item") or "").strip():
                    add("보완항목_공백", eid, str(r.get("method")))
                # 면접은 질문지가 전부다. 질문 없는 면접 항목은 심사위원이
                # 무엇을 물어야 할지 알 수 없다 — 실측 R2026-0004 에서 면접
                # 11건에 질문이 하나도 없었고, 내용도 서류 요청이었다.
                # 면접은 질문지가 전부다. 질문 없는 면접 항목은 심사위원이
                # 무엇을 물어야 할지 알 수 없다 — 실측 R2026-0004 에서 면접
                # 11건에 질문이 하나도 없었고 내용도 서류 요청이었다.
                # 지금까지 나온 산출물이 다 그러므로 경고로 둔다. 지침을
                # 고쳤으니 새로 도는 판정부터는 질문이 붙는다.
                if r.get("method") == "면접" and not (r.get("oral_check") or []):
                    add("면접_질문없음", eid, (r.get("item") or "")[:40], "warn")
                for k in r.get("ksa_refs") or []:
                    if k not in M["refs"]:
                        add("보완_ksa없음", eid, k)
                    covered.add(k)
            if covered != unc:
                add("보완계획_불일치", eid,
                    f"배정 {sorted(covered - unc)[:5]} 누락 {sorted(unc - covered)[:5]}")

        # ── 기준서 철칙 ──
        if rec == "R1" and not (pb_grades & r1_grades):
            add("R1철칙_위반", eid, f"기간보증 등급 {sorted(pb_grades)} — {sorted(r1_grades)} 필요")
        if rec == "R1" and ksa_min is not None and M["refs"]:
            # 커버리지 = 근거가 붙은 KSA ÷ 요소의 KSA 전체. uncovered 는 위에서 모았다.
            cov = 1 - len(_refs(el.get("uncovered_ksa"))) / len(M["refs"])
            if cov < ksa_min:
                add("R1_커버리지_미달", eid, f"KSA 커버리지 {cov:.0%} < 하한 {ksa_min:.0%}")
        if rec == "R1" and not ksa_min_decided:
            add("기준미확정_R1", eid, f"쟁점 4 — KSA 커버리지 하한 {ksa_min:.0%} 는 임시값, TF 결정 필요", "warn")
        if (rubric.rules.get("R8_negative_priority", {}).get("enabled", True)
                and el.get("evidence_level") == "부정진술" and rec != "R5"):
            add("R8_불일치", eid, f"부정진술인데 {rec}")

        qn = (el.get("qualitative_note") or "").strip()
        if not qn:
            add("정성소견_누락", eid)
        elif len(qn) < 20:
            add("정성소견_부실", eid, qn[:30])

        # 정도는 말이 아니라 숫자로. 「50%를 크게 상회」는 몇 %인지 되짚을 수 없다.
        # 시간을 다투는 심사에서 「크게」는 근거가 되지 못한다.
        for field in ("recommendation_reason", "qualitative_note"):
            for m in VAGUE.finditer(el.get(field) or ""):
                add("정도표현_모호", eid,
                    f"{field}: …{m.group(0).strip()}… — 비율을 숫자로 적어야 한다",
                    "warn")

    els = out.get("elements") or []
    rep.counts = {
        "권고": dict(Counter(x.get("recommendation") for x in els)),
        "증거수준": dict(Counter(x.get("evidence_level") for x in els)),
        "보완방법": dict(Counter(r.get("method") for x in els for r in (x.get("remediation") or []))),
        "미확보상태": dict(Counter(u.get("status") for x in els
                                for u in (x.get("uncovered_ksa") or []) if isinstance(u, dict))),
    }
    rep.counts["대면평가"] = {
        "건수": sum(1 for x in els for r in (x.get("remediation") or []) if r.get("method") in FACE),
        "대체서류제시": sum(1 for x in els for r in (x.get("remediation") or []) if r.get("alt_document")),
    }
    return rep
