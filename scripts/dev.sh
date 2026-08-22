#!/usr/bin/env bash
# 개발 실행 스크립트.  사용:  ./scripts/dev.sh {env|up|db|migrate|seed|api|worker|ingest|test|report|demo|assess|review|audit|walk|fixtures}
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/opt/postgresql@15/bin:$PATH"
export LC_ALL=C                       # macOS PostgreSQL 기동 필수 (multithreaded 오류 방지)
# editable 설치로 PYTHONPATH 불필요
PY=.venv/bin/python

case "${1:-}" in
  up)      # API + 워커를 함께 띄운다. 담당자 화면을 쓰려면 둘 다 필요하다
           $PY -m services.assess.worker & echo "워커 $!"
           .venv/bin/uvicorn services.gateway.api:app --reload --port 8000 ;;
  env)     $PY scripts/env_check.py ;;
  db)      pg_ctl -D /opt/homebrew/var/postgresql@15 -l /tmp/pg15.log start || true
           sleep 2 && pg_isready -h localhost -p 5432 ;;
  migrate) .venv/bin/alembic upgrade head ;;
  seed)    $PY db/seeds/load_catalog.py "${@:2}" ;;
  api)     .venv/bin/uvicorn services.gateway.api:app --reload --port 8000 ;;
  walk)    $PY scripts/walkthrough.py "${@:2}" ;;
  worker)  $PY -m services.assess.worker ;;
  ingest)  $PY -m services.ingest.worker ;;
  test)    $PY -m pytest -q ;;
  report)  $PY scripts/make_report.py "${@:2}" ;;
  demo)    $PY scripts/load_demo.py "${@:2}" ;;
  assess)  $PY scripts/assess.py "${@:2}" ;;
  review)  $PY scripts/review_demo.py "${@:2}" ;;
  audit)   $PY scripts/audit.py "${@:2}" ;;
  fixtures) $PY scripts/make_fixtures.py ;;
  *)       echo "사용: $0 {env|up|db|migrate|seed|api|worker|ingest|test|report|demo|assess|review|audit|walk|fixtures}"; exit 1 ;;
esac
