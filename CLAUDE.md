# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

이 저장소(`App/`)는 **자체 git 저장소**다. 연구 맥락·데이터 위치·사례 세트 제작 규칙은
상위 디렉터리의 `../CLAUDE.md` 에 있다. 여기서는 **앱 코드**만 다룬다.
화면·판정·실측 수치의 상세 설명은 `README.md`(1,088줄)에 있고, 이 파일은 그 요약이 아니라
**여러 파일을 읽어야 알 수 있는 것**만 적는다.

## 명령

```bash
./scripts/dev.sh db                     # PostgreSQL 기동 (macOS 는 LC_ALL=C 필수 — 스크립트에 포함)
./scripts/dev.sh migrate                # alembic upgrade head
./scripts/dev.sh seed                   # NCS 카탈로그 적재 (271만 행, 1회)
./scripts/dev.sh up                     # API(8000) + 판정 워커. 화면을 쓰려면 둘 다 필요
./scripts/dev.sh ingest                 # 문서 수집 워커 (별도 프로세스)
./scripts/dev.sh test                   # 전체 시험
./scripts/dev.sh env                    # 설정이 실제로 어떻게 합쳐졌는지 (키는 가림)
./scripts/dev.sh walk                   # ①→⑥ 전 단계 + 산출물 해시 대조
```

**시험 한 건**은 `dev.sh` 를 거치지 않고 직접 부른다:

```bash
.venv/bin/python -m pytest tests/unit/test_track_a.py -q
.venv/bin/python -m pytest tests/integration/test_review_flow.py::test_이름 -q
.venv/bin/python -m pytest -k coverage -q
```

- 시험은 **PostgreSQL 이 떠 있어야 한다.** `tests/conftest.py` 가 `KRPL_ENV=test` 와 `krpl_test` DB 를
  강제하고, DB 이름이 `_test` 로 끝나지 않으면 **시작하지 않는다**. `storage/audit/` 는 건드리지 않는다.
- `ruff` 설정(`pyproject.toml`, line-length 100 · py312)은 있으나 `.venv` 에 설치돼 있지 않다.
  필요하면 `pip install -e '.[dev]'`.
- 판정 실행: `.venv/bin/python scripts/assess.py <심사번호> [--force] [--profile …] [--chunk-by none]`.
  **실호출은 건당 $1 이상이다.** 비용을 막으려면 `KRPL_LLM_BACKEND=replay` 를 앞에 붙인다.
- `scripts/load_candidate.py`(DB 접수)는 **사용자 허락 없이 실행하지 않는다**(상위 CLAUDE.md).

## 구조 — 무엇이 무엇을 아는가

```
config/           ★ 모든 숫자·규칙·프롬프트의 단일 출처 (코드에 상수를 두지 않는다)
packages/         DB·웹을 모르는 순수 계층
  krpl_core/      설정 로더 · ORM · 큐 · 워커 · llm.py(호출) · audit.py(산출물 보존)
  krpl_rules/     판정 엔진 — track_a(시간 규칙) · track_b(AI 산출물 검증) · prior_credit
  krpl_parsers/   hwp/hwpx/pdf/docx/txt 파싱 → masking → structuring(조각화)
services/         DB·HTTP 를 아는 계층
  catalog/        NCS 조회 (읽기 전용)
  ingest/         수집 워커 · classify(파일명→서류종류 추정) · upload
  assess/         판정 오케스트레이션 · case_state(진행 상태의 유일한 답) · 워커
  review/         전문가 검토 — coverage · stages · triage · plan · time_axis · context
  report/         화면(HTML) — layout 에 색·간격 한 벌, 화면은 자기 CSS 만 얹는다
  gateway/        FastAPI (api.py 하나에 전 라우트)
```

의존 방향은 **services → packages** 한쪽뿐이다. `krpl_rules` 는 DB 를 import 하지 않는다 —
판정 로직을 고칠 때 DB 세션이 필요해졌다면 설계가 틀린 것이다.

### 두 트랙 (`assessment.kind`)

| | Track A `time` | Track B `evidence` |
|---|---|---|
| 무엇 | 능력단위 코드 일치 + 이수/요구 비율 | 제출 문서 조각을 NCS KSA 에 배치 |
| AI | 안 씀 (결정론) | 씀 (능력단위별 청크 호출) |
| 시점 | 문서 수집이 끝나면 **자동** | `scripts/assess.py` 로 **명시적으로** |
| 위원 화면 | `/assessments/{aid}/review` | `/assessments/{aid}/panel` → 제출 → `/plan` |

### Track B 호출 흐름

능력단위마다 따로 부른다. 지원자 자료는 캐시되는 system 블록에, 그 단위의 NCS 요구사항만 user 로.
**AI 에게 「검증했느냐」고 묻지 않는다** — `krpl_rules/track_b.py` 가 산출물을 원문과 글자 단위로
대조한다(없는 fid 인용 · quote 가 원문의 연속 부분문자열인지 · KSA 전수 배정 · 기준 위반).
걸리면 그 단위만 재요청(최대 3회), 3회 실패해도 **산출물은 저장하고** `manual_review` 로 둔다.
JSON 스키마 강제(`output_config.format`)는 문법 한도 초과로 **쓰지 않는다** — 스키마 파일은 계약 문서로만 남는다.

## 고칠 때 반드시 지키는 것

1. **기준 숫자는 `config/rubric/v0.2.yaml` 에만 있다.** 판정 임계값·어휘·묶음을 코드에 쓰지 않는다.
   미확정 항목은 `pending_decisions` 에 넣고 `rubric.is_decided(key)` 로 게이트한다.
   `prod` 환경은 미확정 항목이 있으면 **기동을 거부**한다.
2. **같은 숫자를 두 곳에서 세지 않는다.** 진행 상태는 `services/assess/case_state.py`,
   시간 배분은 `ReviewContext.hour_split()`, 커버리지·묶음은 `services/review/coverage.py`,
   검토 대상 선별은 `services/review/triage.py`,
   부족 단위의 시간 인정·면제 게이트는 `services/review/unit_hours.py` — 각각 유일한 자리다.
   면제는 합산이 아니라 게이트다: 인정시간(이수+위원) ÷ 요구 ≥ 50% 면 **요구시간 전체**, 미만이면 0.
   근거 분석은 Track B 가 아니라 **Track A 의 2단계**다 — A·B 는 접수부터 다른 경로다.
   화면이 자기 계산을 따로 하면 반드시 어긋난다(실제로 네 군데가 갈라졌던 이력이 README 에 있다).
3. **마스킹 정규식을 고치면 `tests/unit/test_masking.py` 의 `MUST_KEEP` 을 먼저 늘린다.**
   과잉 탐지가 과소 탐지보다 위험하다 — 날짜가 계좌번호로 오탐돼 판정 근거가 소실된 적이 있다.
4. **`docs/formats/` 의 보고서 원본은 연구팀 확정본이다.** 보기 좋게 바꾸지 않는다.
   `tests/integration/test_report_format.py` 32건이 원본과 구현을 나란히 대조한다.
5. **감사 산출물은 파일 그대로 남기고 손대지 않는다.** 다시 돌리면 새 `판정{N}` 폴더가 생긴다.
   DB 의 `artifact` 표는 색인일 뿐이다. 기록하는 모델명은 **설정값이 아니라 실제 응답한 쪽**(`replay:…` 포함).
6. **마스킹 이전 원문은 저장하지 않는다.** 가려진 값이 감사 기록에 새지 않는지 시험이 막는다.
7. **설정 우선순위**는 `config/settings.yaml` < `config/environments/{env}.yaml` < `.env` < 실행 시 환경변수.
   `.env` 는 `krpl_core/config.py` 가 `os.environ` 에 실어 준다(`os.getenv` 로 읽는 값에 닿게 하려고).
   빈 값(`KEY=`)은 「설정하지 않음」으로 본다. `tests/unit/test_env.py` 가 별도 프로세스로 회귀를 막는다.
8. **화면 문구에 내부 용어를 쓰지 않는다.** `evidence_level`·`confidence` 같은 필드명 노출은 시험이 잡는다.
   R0~R5 를 쓸 때는 항상 뜻을 붙인다. Track A = 「기록 확인」, Track B = 「근거 분석」.
9. **워커**: 작업을 집는 순간 `running` 커밋 → 워커가 죽으면 잡힌 채 남는다.
   `worker_alive()` 는 상태가 아니라 **최근 잠금 흔적**을 보고, `reclaim_stale()` 이 5분마다 되돌린다.
   대상이 사라진 작업은 재시도하지 않고 바로 접는다.

## 커밋

한국어 현재형 한 줄로 **무엇이 달라졌는지**를 쓴다(예: `실패한 작업이 영영 재시도되던 것을 고친다`).
기능 단위로 묶고, 기준·수치를 바꿨으면 `README.md` 와 상위 `../CLAUDE.md` §3 도 같이 고친다.
