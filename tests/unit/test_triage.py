"""보고서에서 전문가 검토로 넘길 것을 추리는 규칙."""
from __future__ import annotations

from services.review import JUDGE, LOOK, SETTLED, bucket, counts, needs_judgment, split


def _p(**kw):
    base = {"conflicts": [], "negative_statements": [], "needs_expert_review": False}
    return base | kw


def test_rule_decided_needs_no_judgment():
    """훈련이수증에 코드·시간·평가결과가 적혀 있으면 판단할 여지가 없다."""
    p = _p(decided_by="rule")
    assert bucket(p) == SETTLED
    assert not needs_judgment(p)


def test_ai_decided_needs_judgment():
    p = _p(decided_by="ai")
    assert bucket(p) == JUDGE
    assert needs_judgment(p)


def test_conflict_goes_first():
    assert bucket(_p(decided_by="ai", conflicts=[{"topic": "x"}])) == LOOK


def test_expert_flag_goes_first():
    assert bucket(_p(decided_by="ai", needs_expert_review=True)) == LOOK


def test_rule_decided_with_a_denial_goes_first():
    """규칙으로 확정됐는데 「그건 안 했다」는 진술이 같이 있으면 그냥 넘기지 않는다.

    이것이 선별의 핵심이다. 「부정 진술이 있음」만으로 잡으면 절반이 걸려
    선별이 되지 않는다 — 결정과 **어긋나는** 것만 골라낸다.
    """
    p = _p(decided_by="rule", negative_statements=[{"quote": "담당한 바 없습니다"}])
    assert bucket(p) == LOOK
    assert needs_judgment(p)


def test_ai_decided_with_a_denial_is_ordinary_judgment():
    """AI 가 판단한 것에 부정 진술이 있는 건 흔한 일이라 따로 앞세우지 않는다."""
    p = _p(decided_by="ai", negative_statements=[{"quote": "해 본 적 없습니다"}])
    assert bucket(p) == JUDGE


def test_missing_keys_do_not_crash():
    assert bucket({}) == JUDGE
    assert needs_judgment({})


def test_split_always_has_every_bucket():
    out = split([{"payload": _p(decided_by="rule")}])
    assert set(out) == {LOOK, JUDGE, SETTLED}
    assert out[LOOK] == [] and out[JUDGE] == []
    assert len(out[SETTLED]) == 1


def test_counts_add_up():
    els = [{"payload": _p(decided_by="rule")},
           {"payload": _p(decided_by="ai")},
           {"payload": _p(decided_by="ai", conflicts=[{"topic": "x"}])}]
    c = counts(els)
    assert c == {LOOK: 1, JUDGE: 1, SETTLED: 1}
    assert sum(c.values()) == len(els)
