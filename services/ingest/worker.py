"""ingest 워커 진입점.  python -m services.ingest.worker"""
from __future__ import annotations

import logging

from krpl_core.worker import Worker
from services.ingest.service import ingest_submission

HANDLERS = {
    "ingest": lambda s, p: ingest_submission(s, p["submission_id"], p["documents"]),
}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    Worker(HANDLERS).run_forever()
