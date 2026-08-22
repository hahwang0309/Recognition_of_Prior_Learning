"""assess 워커 진입점.  python -m services.assess.worker"""
from __future__ import annotations

import logging

from krpl_core.worker import Worker
from services.assess.track_a_service import run_track_a
from services.assess.track_b_service import run_track_b

HANDLERS = {
    "track_a": lambda s, p: run_track_a(s, p["submission_id"]),
    "track_b": lambda s, p: run_track_b(s, p["submission_id"],
                                        profile_name=p.get("profile")),
}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    Worker(HANDLERS).run_forever()
