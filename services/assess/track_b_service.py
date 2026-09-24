"""Track B 판정 오케스트레이션 — 패키지 → LLM → 검증 → (실패 시) 재요청 → 저장.

## 능력단위마다 따로 부른다

한 번에 33개 요소를 받으면 요소 하나가 틀려도 전체를 다시 받아야 한다.
실측에서 KSA 하나가 빠진 것 때문에 33개를 통째로 재생성했다 — $1.3 낭비.
능력단위로 나누면 틀린 단위(요소 3개)만 다시 받는다.

나눠도 지원자 자료는 통째로 들어간다. 어느 능력단위의 근거가 어느 문서에 있을지
미리 알 수 없기 때문이다. 그 대신 그 덩어리를 **캐시되는 자리(system)** 에 두어
두 번째 청크부터 10% 가격이 되게 한다.

    system [캐시]  분석지침 · 기준요약 · 지원자 자료      9,367 토큰
    user           이 능력단위의 NCS 요구사항만          약 2,000 토큰

실측 입력은 3.9배로 늘지만 캐시가 먹으면 1.3배에 그치고, 재시도가 싸져 총비용은 내려간다.
`chunk_by: none` 으로 두면 예전처럼 한 번에 부른다.

## 왜 검증 루프인가

AI에게 「검증했느냐」고 묻지 않는다. 스스로 통과했다는 보고는 믿을 수 없다.
산출물을 받으면 기계가 원문과 직접 대조하고, 틀린 곳을 **구체적으로 적어 되돌려준다.**
정해진 횟수 안에 통과하지 못하면 판정을 확정하지 않고 전문가 검토로 넘긴다.

## 멈추지 않는 것과 멈추는 것

- 경고(예: 미확정 기준에 걸린 R1)는 **멈추지 않는다.** 기록에 남기고 보고서에 표시한다.
- 오류는 재요청한다. 소진되면 `manual_review` 로 두되 **마지막 산출물은 그대로 저장한다.**
  전문가가 볼 것이 아무것도 없는 상태가 가장 나쁘다.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from krpl_core.audit import AuditStore
from krpl_core.config import CONFIG_DIR, get_model_profile, get_rubric, get_settings
from krpl_core.llm import LLMClient, LLMError, Turn, cost_guard, get_client
from krpl_rules import (
    ValidationReport, build_r0_elements, eligible_units, validate_track_b,
)
from services.assess.package import (
    build_package, package_hash, package_stats, shared_part, split_package,
)

log = logging.getLogger(__name__)


def _prompt(name: str) -> str:
    return (CONFIG_DIR / "prompts" / f"{name}.md").read_text(encoding="utf-8")


def _rubric_brief(rb) -> str:
    """기준 가운데 AI가 지켜야 할 값만 추려 넘긴다. 캐시 대상이므로 고정 문자열이다."""
    return json.dumps({
        "version": rb.version,
        "grades": {k: v["label"] for k, v in rb.grades.items()},
        "dimensions": rb.dimensions,
        "recommendations": {k: v.get("label") for k, v in rb.recommendations.items()},
        "R0_성립": rb.recommendations["R0"]["requires"],
        "R0_하향": rb.recommendations["R0"]["downgrade_if"],
        "R1_기간보증등급": rb.recommendations["R1"]["requires"]["period_backing_grades"],
        "출력어휘": rb.output_vocabulary,
        "보완": {k: rb.remediation[k] for k in
                ("methods", "face_to_face", "burden_order",
                 "face_to_face_max_per_element", "practical_exemption_forbidden")},
        "미확보상태": rb.uncovered_status,
    }, ensure_ascii=False, indent=1)




def _without(pkg: dict, settled: set[str]) -> dict:
    """이미 확정된 요소를 뺀 패키지. 빈 능력단위는 통째로 뺀다."""
    if not settled:
        return pkg
    units = []
    for u in pkg["ncs"]["units"]:
        rest = [e for e in u["elements"] if e["element_id"] not in settled]
        if rest:
            units.append({**u, "elements": rest})
    return dict(pkg, ncs={"program": pkg["ncs"]["program"], "units": units})


def set_progress(aid: int, **fields: Any) -> None:
    """진행 상황을 **별도 세션에서 즉시 커밋**한다.

    판정은 한 트랜잭션 안에서 도는데, 그 트랜잭션은 끝나야 커밋된다.
    같은 세션으로 진행률을 써도 밖에서는 판정이 끝날 때까지 아무것도 못 본다.
    화면이 12~28분 동안 「판정 중」만 보여 주던 이유다.
    """
    from krpl_core.db import session_scope
    try:
        with session_scope() as s2:
            n = s2.execute(
                text("UPDATE assessment SET progress = CAST(:p AS jsonb) WHERE id=:i"),
                {"i": aid, "p": json.dumps(fields, ensure_ascii=False)}).rowcount
        if not n:
            # 대상 행이 안 보인다는 뜻 — 아직 커밋되지 않았을 때 이런 일이 생긴다.
            # 조용히 넘기면 화면이 영영 「시작 중」에 머문다.
            log.warning("진행 상황을 적을 판정 %s 이 보이지 않습니다 (커밋 전?)", aid)
    except Exception as e:                       # noqa: BLE001
        log.debug("진행 상황 기록 실패(무시): %s", e)


def _applicant_brief(pkg: dict) -> str:
    """지원자가 낸 것 전부. 청크마다 그대로 반복되므로 캐시되는 자리에 둔다."""
    return json.dumps(shared_part(pkg), ensure_ascii=False)


def _unit_of(pkg: dict) -> tuple[str, str]:
    u = pkg["ncs"]["units"][0]
    return u["unit_code"], u["unit_name"]


@dataclass
class Usage:
    inp: int = 0
    out: int = 0
    think: int = 0
    cache: int = 0
    cost: float = 0.0

    def add(self, r) -> None:
        self.inp += r.input_tokens
        self.out += r.output_tokens
        self.think += r.thinking_tokens
        self.cache += r.cache_read_tokens
        self.cost += r.cost_usd

    def merge(self, o: "Usage") -> None:
        for k in ("inp", "out", "think", "cache", "cost"):
            setattr(self, k, getattr(self, k) + getattr(o, k))

    def as_dict(self) -> dict:
        return {"입력": self.inp, "출력": self.out, "사고": self.think,
                "캐시읽기": self.cache, "비용_usd": round(self.cost, 6)}


@dataclass
class ChunkResult:
    """청크 하나의 결과. DB 를 건드리지 않으므로 병렬로 돌 수 있다."""
    label: str
    package: dict
    out: dict | None = None
    report: ValidationReport | None = None
    attempts: int = 0
    usage: Usage = field(default_factory=Usage)
    error: str | None = None
    models: set[str] = field(default_factory=set)   # **실제로 응답한** 모델
    # 감사용 — (이름, 내용, 비고). 호출한 쪽에서 한꺼번에 파일로 남긴다.
    trace: list[tuple[str, Any, str]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.report is not None and self.report.passed


def _solve(client: LLMClient, profile, sysblocks: list[str], pkg: dict,
           rb, max_try: int, label: str) -> ChunkResult:
    """패키지 하나를 통과시킬 때까지 부른다. **DB 를 건드리지 않는다.**

    호출·검증·재요청만 하고, 남길 것은 trace 에 모아 돌려준다.
    DB 쓰기를 밖으로 뺀 덕에 청크를 병렬로 돌릴 수 있고,
    네트워크 대기 중에 트랜잭션을 붙잡지 않는다.
    """
    res = ChunkResult(label=label, package=pkg)
    ask = (f"아래 패키지를 분석해 JSON 하나만 출력하라.\n"
           f"심사번호 {pkg['applicant_id']} · 목표 종목 {pkg['target_program']} · "
           f"능력단위요소 {package_stats(pkg)['n_elements']}개\n\n"
           + json.dumps(pkg["ncs"], ensure_ascii=False))
    turn = Turn(system=sysblocks, messages=[{"role": "user", "content": ask}])

    for attempt in range(1, max_try + 1):
        res.attempts = attempt
        try:
            r = client.complete(turn, profile)
        except LLMError as e:
            res.trace.append((f"{attempt}차_호출실패", str(e), ""))
            res.error = f"호출 실패: {e}"
            if attempt == max_try:
                return res
            continue

        res.usage.add(r)
        res.models.add(r.model)
        # 파싱보다 **먼저** 남긴다. 해석에 실패한 응답이야말로 봐야 할 물건이다.
        res.trace.append((f"{attempt}차_AI응답", r.text,
                          f"{r.model} · 출력 {r.output_tokens:,} 토큰 "
                          f"(사고 {r.thinking_tokens:,} · 상한 대비 "
                          f"{(1 - r.headroom) * 100:.0f}%) · ${r.cost_usd:.4f} "
                          f"· 종료 {r.stop_reason}"
                          + (" · ⚠ 상한에서 끊김" if r.truncated else "")))
        try:
            out = r.json()
        except LLMError as e:
            res.trace.append((f"{attempt}차_해석실패", str(e),
                              f"응답 {len(r.text):,}자 · 종료 {r.stop_reason}"))
            res.error = f"해석 실패: {e}"
            log.warning("%s 시도 %d/%d — 응답 해석 실패: %s", label, attempt, max_try, e)
            if attempt == max_try:
                return res
            continue

        rep = validate_track_b(pkg, out, rb)
        res.out, res.report, res.error = out, rep, None
        res.trace.append((f"{attempt}차_검증결과", rep.summary(),
                          ("통과" if rep.passed else f"오류 {len(rep.errors)}건")
                          + f" · 경고 {len(rep.warnings)}건"))
        log.info("%s 시도 %d/%d — 오류 %d 경고 %d",
                 label, attempt, max_try, len(rep.errors), len(rep.warnings))
        if rep.passed or attempt == max_try:
            return res

        repair = _prompt("trackb_repair") + "\n\n" + rep.feedback()
        res.trace.append((f"{attempt}차_재요청", repair, "검증에 걸린 내용을 이렇게 되돌려 보냈다"))
        turn.messages += [{"role": "assistant", "content": r.text},
                          {"role": "user", "content": repair}]
    return res


def _synthesize(client: LLMClient, profile, sysblocks: list[str],
                pkg: dict, elements: list[dict]) -> tuple[str, str, Usage]:
    """전체 소견을 따로 받는다.

    청크로 나누면 각 단위가 서로를 모른다. 그 손실을 여기서 메운다 —
    모든 요소의 권고·사유만 모아 짧게 보내므로 입력도 출력도 작다.
    """
    brief = [{"요소": e["element_id"], "권고": e.get("recommendation"),
              "사유": e.get("recommendation_reason")} for e in elements]
    ask = ("아래는 한 지원자의 능력단위요소별 권고를 모은 것이다. "
           "다음 두 가지만 순수 JSON 으로 출력하라. 다른 항목은 넣지 마라.\n"
           '{"prior_learning_review": "기이수 교육과정을 어떻게 반영했는지 3~5문장", '
           '"overall_note": "전반 소견 4~6문장"}\n\n'
           f"심사번호 {pkg['applicant_id']} · 목표 종목 {pkg['target_program']}\n"
           + json.dumps(brief, ensure_ascii=False))
    u = Usage()
    try:
        r = client.complete(Turn(system=sysblocks,
                                 messages=[{"role": "user", "content": ask}],
                                 purpose="synthesize"), profile)
        u.add(r)
        d = r.json()
        return d.get("prior_learning_review") or "", d.get("overall_note") or "", u
    except LLMError as e:
        log.warning("전체 소견 종합 실패: %s", e)
        return "", f"(전체 소견을 만들지 못했습니다: {e})", u


def map_negations(client: LLMClient, profile, sysblocks: list[str],
                  pkg: dict, candidates: list[dict]) -> tuple[set[str], dict, Usage]:
    """「하지 않았다」는 진술이 어느 요소를 가리키는지 짚는다.

    기이수(R0)는 코드로 확정하지만, 부정 진술이 걸린 요소만은 사람이 읽어야 한다.
    그 범위를 좁히는 **작은 호출 하나**다 — 요소 이름 목록만 보내므로 입력도 출력도 작다.
    부정 진술이 없으면 부르지 않는다.
    """
    u = Usage()
    negs = [f for f in pkg["fragments"] if f["stype"] == "부정"]
    if not negs or not candidates:
        return set(), {"부정조각": len(negs), "후보요소": len(candidates),
                       "영향요소": [], "호출": False}, u

    ask = ("아래 부정 진술이 어느 능력단위요소를 가리키는지 짚어라.\n\n"
           "[부정 진술]\n"
           + json.dumps([{"fid": f["fid"], "출처": f["doc_type"], "text": f["text"]}
                         for f in negs], ensure_ascii=False, indent=1)
           + "\n\n[대상 요소]\n"
           + json.dumps(candidates, ensure_ascii=False, indent=1))
    try:
        r = client.complete(Turn(system=[_prompt("negation_map"), sysblocks[-1]],
                                 messages=[{"role": "user", "content": ask}],
                                 purpose="negation"), profile)
        u.add(r)
        ids = {x["element_id"] for x in (r.json().get("affected") or [])
               if isinstance(x, dict) and x.get("element_id")}
        valid = {c["element_id"] for c in candidates}
        hit, bogus = ids & valid, ids - valid
        return hit, {"부정조각": len(negs), "후보요소": len(candidates),
                     "영향요소": sorted(hit), "없는요소": sorted(bogus),
                     "호출": True, "응답": r.json().get("affected")}, u
    except LLMError as e:
        # 못 짚으면 **전부 사람이 보게 한다.** 놓치는 것보다 한 번 더 보는 편이 낫다.
        log.warning("부정 진술 매핑 실패 — 기이수 요소를 전부 AI 판정으로 돌린다: %s", e)
        return {c["element_id"] for c in candidates}, {
            "부정조각": len(negs), "후보요소": len(candidates), "호출": True,
            "오류": str(e), "조치": "전부 AI 판정으로"}, u


def _normalize_conflicts(el: dict) -> None:
    """상충 기록을 한 가지 모양으로 맞춘다 (보고서가 읽기 위한 것)."""
    out = []
    for c in el.get("conflicts") or []:
        if isinstance(c, str):
            out.append({"topic": None, "adopted": c, "rejected": None, "note": None})
        elif isinstance(c, dict):
            out.append({"topic": c.get("topic") or c.get("issue"),
                        "adopted": c.get("adopted"), "rejected": c.get("rejected"),
                        "note": c.get("note") or c.get("reason")})
    el["conflicts"] = out


def _prior_elements(s: Session, assessment_id: int) -> dict[str, dict]:
    """이전 판정의 요소별 산출물. 다시 부르지 않고 그대로 싣기 위한 것이다."""
    return {r[0]: r[1] for r in s.execute(text(
        "SELECT element_id, payload FROM assessment_element WHERE assessment_id=:a"),
        {"a": assessment_id}) if isinstance(r[1], dict)}


def _carry_review(s: Session, old_aid: int, new_aid: int,
                  redo: set[str]) -> tuple[int, int]:
    """검토 기록을 새 판정으로 옮긴다. (요소 판단 수, 보완 항목 결과 수)

    다시 볼 요소(`redo`)의 판단은 **옮기지 않는다.** 새 자료를 보고 다시
    정해야 하기 때문이다. 옮기지 않으면 그 요소만 1단계에 다시 나타난다.

    보완 항목 결과는 전부 옮긴다 — 열쇠가 항목 글의 해시라, 같은 항목이면
    같은 열쇠다. 새 판정에 없어진 항목의 결과는 그냥 쓰이지 않는다.
    """
    n1 = s.execute(text("""
        INSERT INTO element_review (assessment_id, element_id, decision,
                                    ai_recommendation, note, reviewer, reviewed_at)
        SELECT :new, element_id, decision, ai_recommendation, note, reviewer, reviewed_at
        FROM element_review WHERE assessment_id=:old
          AND NOT (element_id = ANY(:redo))
        ON CONFLICT (assessment_id, element_id) DO NOTHING"""),
        {"new": new_aid, "old": old_aid, "redo": sorted(redo)}).rowcount
    n2 = s.execute(text("""
        INSERT INTO remediation_result (assessment_id, item_key, method, item,
                                        result, note, decided_by, decided_at)
        SELECT :new, item_key, method, item, result, note, decided_by, decided_at
        FROM remediation_result WHERE assessment_id=:old
        ON CONFLICT (assessment_id, item_key) DO NOTHING"""),
        {"new": new_aid, "old": old_aid}).rowcount
    return n1, n2


def _store(s: Session, aid: int, out: dict, rep: ValidationReport) -> None:
    s.execute(text("DELETE FROM assessment_element WHERE assessment_id=:a"), {"a": aid})
    rows = []
    warned = {i.element_id for i in rep.warnings}
    for el in out.get("elements") or []:
        _normalize_conflicts(el)
        payload = dict(el)
        payload["needs_expert_review"] = el["element_id"] in warned
        rows.append({"a": aid, "e": el["element_id"],
                     "r": el.get("recommendation") or "?",
                     "v": el.get("evidence_level"), "m": el.get("verification_method"),
                     "c": el.get("confidence"),
                     "p": json.dumps(payload, ensure_ascii=False)})
    if rows:
        s.execute(text("""
            INSERT INTO assessment_element
                (assessment_id, element_id, recommendation, evidence_level,
                 verification_method, confidence, payload)
            VALUES (:a, :e, :r, :v, :m, :c, CAST(:p AS jsonb))"""), rows)


def run_track_b(s: Session, submission_id: int, *,
                client: LLMClient | None = None, profile_name: str | None = None,
                keep_from: int | None = None,
                focus: list[str] | None = None) -> int:
    """접수 건을 분석하고 assessment 를 만든다. assessment_id 반환.

    ## 다시 돌릴 때 — `keep_from` 과 `focus`

    2단계에서 추가 서류를 받으면 그 자료를 반영해 다시 봐야 한다. 그렇다고
    서른세 개 요소를 통째로 다시 돌리면 비용도 크고, 이미 사람이 판단한
    것까지 흔들린다.

      `keep_from`  이전 판정(assessment_id). 그 결과를 그대로 싣는다.
      `focus`      다시 볼 요소. 새 서류가 풀려던 것들만이다.

    나머지 요소는 AI 를 부르지 않고 이전 판정을 옮겨 싣는다. 검토 기록
    (요소 판단·보완 항목 결과)도 함께 옮긴다 — 다시 볼 요소의 판단만 뺀다.
    새 자료를 보고 다시 정해야 하기 때문이다.
    """
    cfg = get_settings()
    rb = get_rubric()
    profile = get_model_profile(profile_name)
    client = client or get_client(profile)

    pkg = build_package(s, submission_id)
    case = pkg["applicant_id"]
    if not pkg["fragments"]:
        raise ValueError(f"조각이 없습니다 (문서 수집을 먼저 하세요): submission_id={submission_id}")
    if not pkg["ncs"]["units"]:
        raise ValueError(f"종목의 요구 능력단위가 없습니다: {pkg['target_program']}")

    pv = cfg.prompt["trackb_version"]
    ac = cfg.assessment
    now = datetime.now(timezone.utc)

    # 판정 행은 **따로 커밋한다.** 본 트랜잭션은 끝나야 커밋되므로,
    # 그 안에서 만들면 밖에서는 판정이 끝날 때까지 행이 존재하지 않는다.
    # 진행률을 적을 대상도 없고, 도중에 죽으면 흔적조차 남지 않는다.
    from krpl_core.db import session_scope as _scope
    with _scope() as s0:
        aid = s0.execute(text("""
            INSERT INTO assessment (submission_id, kind, status, rubric_version, prompt_version,
                                    model, effort, input_hash, attempts, started_at)
            VALUES (:s, 'evidence', 'running', :rv, :pv, :m, :ef, :h, 0, :t) RETURNING id"""),
            {"s": submission_id, "rv": rb.version, "pv": pv, "m": profile.model,
             "ef": profile.effort, "h": package_hash(pkg), "t": now}).scalar_one()
        s0.execute(text("UPDATE submission SET status='assessing' WHERE id=:i"),
                   {"i": submission_id})
    store = AuditStore(s, case, submission_id, aid)

    # 캐시되는 자리에 고정 블록 셋을 둔다 — 청크마다 그대로 반복되는 부분이다.
    sysblocks = [_prompt(pv), _rubric_brief(rb), _applicant_brief(pkg)]
    store.write("package", "AI입력패키지", pkg, seq=1,
                note=f"해시 {package_hash(pkg)[:16]} · "
                     + json.dumps(package_stats(pkg), ensure_ascii=False))
    store.write("package", "분석지침", sysblocks[0], seq=2, note=f"프롬프트 {pv}")
    store.write("package", "기준요약", sysblocks[1], seq=3, note=f"기준 v{rb.version}")

    # ── ① 기이수 인정(R0)은 코드가 확정한다 ──────────────────────────
    # 훈련이수증에 능력단위코드·시간·평가결과가 있으면 판단할 것이 없다.
    # AI 에 맡겼더니 같은 지원자가 실행마다 R0 15·15·12 로 갈렸다.
    # 다만 「하지 않았다」는 진술이 걸린 요소는 읽어 봐야 하므로 AI 로 넘긴다.
    credits = eligible_units(pkg, rb)
    cand = [{"element_id": e["element_id"], "element_name": e.get("element_name"),
             "unit_name": u["unit_name"]}
            for u in pkg["ncs"]["units"] if u["unit_code"] in credits
            for e in u["elements"]]
    negated, neg_info, neg_usage = map_negations(client, profile, sysblocks, pkg, cand)
    r0_elements, r0_info = build_r0_elements(pkg, rb, exclude=negated)
    settled = {e["element_id"] for e in r0_elements}
    store.write("package", "기이수_확정", {"부정진술_매핑": neg_info, **r0_info}, seq=5,
                note=f"코드로 확정 {len(r0_elements)}요소 · "
                     f"부정 진술로 AI 판정 {len(negated)}요소")
    if r0_elements:
        log.info("판정 %s — 기이수 %d요소를 코드로 확정 (AI 판정 대상에서 제외)",
                 case, len(r0_elements))

    # ── ①-2 다시 볼 요소만 남긴다 ────────────────────────────────
    carried: dict[str, dict] = {}
    if keep_from:
        want = set(focus or [])
        carried = {eid: pl for eid, pl in _prior_elements(s, keep_from).items()
                   if eid not in want and eid not in settled}
        settled |= set(carried)
        store.write("package", "재분석_범위",
                    {"이전판정": keep_from, "다시볼요소": sorted(want),
                     "이월요소": sorted(carried)}, seq=4,
                    note=f"이전 판정 {keep_from} 에서 {len(carried)}요소 이월 · "
                         f"{len(want)}요소 재판정")
        log.info("판정 %s — 재분석: %d요소 이월, %d요소 다시 봄",
                 case, len(carried), len(want))

    # ── ② 남은 요소만 AI 에 보낸다 ────────────────────────────────
    ai_pkg = _without(pkg, settled)
    if not ai_pkg["ncs"]["units"]:
        chunks, labels = [], []
    else:
        chunks = split_package(ai_pkg) if ac.chunk_by == "unit" else [ai_pkg]
        labels = [f"{case}/{_unit_of(c)[1]}" if ac.chunk_by == "unit" else case
                  for c in chunks]
    store.write("package", "청크분할", [
        {"능력단위": _unit_of(c)[1], "코드": _unit_of(c)[0],
         "요소": package_stats(c)["n_elements"]} for c in chunks] if ac.chunk_by == "unit"
        else [{"방식": "한 번에 전부", "요소": package_stats(ai_pkg)["n_elements"]}], seq=6,
        note=f"{ac.chunk_by} · {len(chunks)}개 · 동시 {ac.chunk_concurrency} · "
             f"AI 판정 대상 {package_stats(ai_pkg)['n_elements']}"
             f"/{package_stats(pkg)['n_elements']}요소")

    max_try = max(1, ac.validation_max_retries)
    log.info("판정 %s — %s 방식 %d개 청크 · 동시 %d",
             case, ac.chunk_by, len(chunks), ac.chunk_concurrency)

    def solve(x):
        return _solve(client, profile, sysblocks, x[0], rb, max_try, x[1])

    work = list(zip(chunks, labels))
    names = [_unit_of(c)[1] if ac.chunk_by == "unit" else "전체" for c in chunks]
    done_n = 0
    set_progress(aid, 단계="분석", 전체=len(work), 완료=0, 확정=len(r0_elements),
                 남은=[n for n in names], 끝난=[])

    def mark(i: int, r: ChunkResult) -> None:
        """청크 하나가 끝날 때마다 밖에서 보이게 적는다."""
        nonlocal done_n
        done_n += 1
        set_progress(aid, 단계="분석", 전체=len(work), 완료=done_n,
                     확정=len(r0_elements),
                     끝난=[{"이름": names[j], "통과": bool(rr and rr.passed),
                           "시도": rr.attempts if rr else 0}
                          for j, rr in enumerate(slots) if rr is not None],
                     남은=[names[j] for j, rr in enumerate(slots) if rr is None])

    slots: list[ChunkResult | None] = [None] * len(work)
    if ac.chunk_concurrency > 1 and len(work) > 1:
        # LLM 호출만 병렬로 돈다. DB 는 아래에서 단일 스레드로 쓴다.
        # as_completed 로 받아 **끝나는 대로** 진행률을 적는다 (순서는 slots 로 지킨다).
        with ThreadPoolExecutor(max_workers=min(ac.chunk_concurrency, len(work))) as ex:
            futs = {ex.submit(solve, w): i for i, w in enumerate(work)}
            for f in as_completed(futs):
                i = futs[f]
                slots[i] = f.result()
                mark(i, slots[i])
    else:
        for i, w in enumerate(work):
            slots[i] = solve(w)
            mark(i, slots[i])
    results = [r for r in slots if r is not None]

    # ── 여기서부터 DB. 청크 순서대로 기록한다 ──
    usage = Usage()
    usage.merge(neg_usage)
    elements: list[dict] = list(r0_elements) + list(carried.values())
    issues: list[dict] = []
    models: set[str] = set()
    for n, r in enumerate(results, 1):
        usage.merge(r.usage)
        models |= r.models
        for name, body, note in r.trace:
            store.write("llm" if "응답" in name or "실패" in name else "validate",
                        (f"{n:02d}_{_unit_of(r.package)[0]}_" if ac.chunk_by == "unit" else "")
                        + name, body, seq=n * 100 + len(r.trace), note=note)
        if r.out:
            # 코드가 확정한 요소는 AI 결과로 덮지 않는다.
            elements += [e for e in (r.out.get("elements") or [])
                         if e.get("element_id") not in settled]
        if r.report:
            issues += [{"청크": r.label} | i for i in r.report.summary()["issues"]]
        if r.error:
            issues.append({"청크": r.label, "code": "청크_실패", "element_id": "",
                           "detail": r.error, "severity": "error"})

    # 청크가 하나라도 못 끝냈으면 그 사실을 숨기지 않는다.
    failed = [r.label for r in results if not r.passed]
    merged = {"applicant_id": case, "target_program": pkg["target_program"],
              "elements": elements, "prior_learning_review": "", "overall_note": ""}

    if elements and ac.synthesize_overall and (ac.chunk_by == "unit" or r0_elements):
        set_progress(aid, 단계="종합", 전체=len(work), 완료=len(work),
                     확정=len(r0_elements))
        plr, note_txt, u = _synthesize(client, profile, sysblocks[:2], pkg, elements)
        usage.merge(u)
        merged["prior_learning_review"], merged["overall_note"] = plr, note_txt
    elif results and results[0].out:
        merged["prior_learning_review"] = results[0].out.get("prior_learning_review") or ""
        merged["overall_note"] = results[0].out.get("overall_note") or ""

    # 합친 결과를 **전체 패키지로 다시 검증한다.** 청크별 통과만으로는
    # 능력단위 하나가 통째로 빠진 것을 잡을 수 없다.
    set_progress(aid, 단계="대조", 전체=len(work), 완료=len(work),
                 확정=len(r0_elements))
    rep = validate_track_b(pkg, merged, rb)
    store.write("validate", "합본_검증결과", rep.summary(), seq=900,
                note=("통과" if rep.passed else f"오류 {len(rep.errors)}건")
                     + f" · 경고 {len(rep.warnings)}건"
                     + (f" · 미완료 청크 {len(failed)}개" if failed else ""))

    for n, r in enumerate(results, 1):
        s.execute(text("""INSERT INTO validation_log (assessment_id, attempt, passed,
                          error_count, errors) VALUES (:a,:n,:p,:c,CAST(:e AS jsonb))"""),
                  {"a": aid, "n": n, "p": r.passed,
                   "c": 0 if r.passed else len(r.report.errors) if r.report else 1,
                   "e": json.dumps({"청크": r.label, "시도": r.attempts,
                                    **(r.report.summary() if r.report
                                       else {"by_code": {"청크_실패": 1},
                                             "issues": [{"code": "청크_실패",
                                                         "element_id": "",
                                                         "detail": r.error or "",
                                                         "severity": "error"}]})},
                                   ensure_ascii=False)})
    s.execute(text("""INSERT INTO validation_log (assessment_id, attempt, passed,
                      error_count, errors) VALUES (:a,:n,:p,:c,CAST(:e AS jsonb))"""),
              {"a": aid, "n": len(results) + 1, "p": rep.passed and not failed,
               "c": len(rep.errors) + len(failed),
               "e": json.dumps({"청크": "합본", **rep.summary()}, ensure_ascii=False)})

    ok = rep.passed and not failed
    status = "done" if ok else cfg.assessment.on_validation_exhausted
    if not elements:
        status = "failed"
    _store(s, aid, merged, rep)

    # 다시 돌린 것이면 검토 기록을 옮긴다. 옮기지 않으면 서류 한 장 때문에
    # 서른세 개를 처음부터 다시 판단하게 된다.
    if keep_from and ok:
        n1, n2 = _carry_review(s, keep_from, aid, set(focus or []))
        log.info("판정 %s — 검토 이월: 요소 판단 %d건, 보완 항목 결과 %d건", case, n1, n2)

    # 설정된 모델이 아니라 **실제로 응답한 것**을 기록한다.
    # 재생(replay)으로 돌린 것을 Opus 5 가 돌린 것처럼 남기면 감사 기록이 거짓이 된다.
    actual = ", ".join(sorted(models)) or profile.model
    if actual != profile.model:
        s.execute(text("UPDATE assessment SET model=:m WHERE id=:i"),
                  {"m": actual[:60], "i": aid})

    total_attempts = sum(r.attempts for r in results)
    note = {
        "실행": {"설정모델": profile.model, "실제모델": actual,
               "effort": profile.effort, "지침": pv, "기준": rb.version,
               "분할": ac.chunk_by, "청크": len(chunks), "동시": ac.chunk_concurrency,
               "기이수_코드확정": len(r0_elements),
               "재분석": ({"이전판정": keep_from, "이월요소": len(carried),
                        "다시본요소": sorted(focus or [])} if keep_from else None),
               "부정진술로_AI판정": sorted(negated),
               "호출": total_attempts, "검증": "통과" if ok else "미통과",
               "미완료청크": failed, "토큰": usage.as_dict() | {"출력상한": profile.max_tokens}},
        "prior_learning_review": merged["prior_learning_review"],
        "overall_note": merged["overall_note"],
        "validation": rep.summary(),
        "청크별": [{"청크": r.label, "시도": r.attempts, "통과": r.passed,
                 "요소": len(r.out.get("elements") or []) if r.out else 0,
                 "비용_usd": round(r.usage.cost, 4)} for r in results],
        "기이수": {"부정진술_매핑": neg_info, **r0_info},
        "package": package_stats(pkg),
        "attempts": total_attempts,
    }
    store.write("llm", "최종채택_요소", elements, seq=990,
                note=f"{status} · 청크 {len(chunks)}개 · 호출 {total_attempts}회 · "
                     + ("검증 통과" if ok else f"오류 {len(rep.errors)}건"))
    store.write("llm", "실행요약", note, seq=980,
                note=f"토큰 입력 {usage.inp:,} 출력 {usage.out:,} "
                     f"(사고 {usage.think:,} · 캐시읽기 {usage.cache:,}) · ${usage.cost:.4f}")

    cap = cost_guard().get("per_assessment_usd_max")
    if cap is not None and usage.cost > cap:
        log.warning("판정 %s 누적 비용 $%.2f 이 상한 $%.2f 를 넘었습니다", case, usage.cost, cap)

    s.execute(text("""
        UPDATE assessment SET status=:st, attempts=:n, finished_at=:t,
               input_tokens=:it, output_tokens=:ot, cache_read_tokens=:ct,
               cost_usd=:cu, overall_note=:o WHERE id=:i"""),
        {"st": status, "n": total_attempts, "t": datetime.now(timezone.utc),
         "it": usage.inp, "ot": usage.out, "ct": usage.cache,
         "cu": round(usage.cost, 4), "o": json.dumps(note, ensure_ascii=False), "i": aid})
    s.execute(text("UPDATE assessment SET progress=NULL WHERE id=:i"), {"i": aid})
    s.execute(text("UPDATE submission SET status=:s WHERE id=:i"),
              {"s": "assessed" if ok else "needs_review" if elements else "failed",
               "i": submission_id})
    s.execute(text("""INSERT INTO audit_log (entity, entity_id, action, actor, detail)
                      VALUES ('assessment', :i, 'track_b', 'system', CAST(:d AS jsonb))"""),
              {"i": str(aid), "d": json.dumps(
                  {"status": status, "청크": len(chunks), "호출": total_attempts,
                   "cost_usd": round(usage.cost, 4), "validation": rep.by_code()},
                  ensure_ascii=False)})
    if not elements:
        raise LLMError(f"모든 청크가 실패했습니다: {failed}")
    return aid
