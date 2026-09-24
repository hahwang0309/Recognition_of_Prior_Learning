"""assess 워커 진입점.  python -m services.assess.worker"""
from __future__ import annotations

import logging

from krpl_core.worker import Worker
from services.assess.track_a_service import run_track_a
from services.assess.track_b_service import run_track_b

HANDLERS = {
    "track_a": lambda s, p: run_track_a(s, p["submission_id"]),
    # keep_from/focus 는 추가 서류를 받아 다시 돌릴 때만 온다.
    "track_b": lambda s, p: run_track_b(s, p["submission_id"],
                                        profile_name=p.get("profile"),
                                        keep_from=p.get("keep_from"),
                                        focus=p.get("focus")),
}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    Worker(HANDLERS).run_forever()
