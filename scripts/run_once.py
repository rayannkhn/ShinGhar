"""Entry point for one automatic pipeline run (called daily by GitHub Actions, or by hand).

Exit code 0 only for a clean run. Any error recorded in run_log makes this exit 1,
so the GitHub Actions run is marked failed (red), never falsely green.
Every run writes its own timestamped log file to logs/runs/.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from sailab import db  # noqa: E402
from sailab.pipeline import run_pipeline_once  # noqa: E402

DB_PATH = REPO / "sailab_glof.db"
DATA_DIR = REPO / "data" / "scenes"          # scheduled runs: committed to git as evidence
BACKFILL_DIR = REPO / "data" / "backfill"     # one-off historical backfill: kept locally, not committed
LOG_DIR = REPO / "logs" / "runs"

# For a lake with no scenes stored yet, look for scenes acquired after this date (i.e. from 2023-01-01).
# Agreed with the project owner on 2026-11-08: gives 2023, 2024 and 2025 values for every calendar month,
# enough for the seasonal baseline. In practice this only applies to the one-off backfill run (and to
# any lake added later); after that, each lake continues from its newest stored scene.
INITIAL_SINCE_DATE: date | None = date(2022, 12, 31)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backfill", action="store_true",
                        help="one-off historical run started by hand: same pipeline, files saved to data/backfill/")
    parser.add_argument("--lakes", default=None,
                        help="comma-separated lake codes to run (default: every lake), e.g. for the backfill of "
                             "newly added lakes: --backfill --lakes SHP,DKT,BRT,PSU")
    args = parser.parse_args()
    data_dir = BACKFILL_DIR if args.backfill else DATA_DIR

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    log_file = LOG_DIR / f"{started:%Y-%m-%dT%H%M%SZ}{'_backfill' if args.backfill else ''}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
    )
    logging.Formatter.converter = __import__("time").gmtime   # log timestamps in UTC
    # GDAL prints format notices about Earth Engine's TIFFs (ExtraSamples, legacy Deflate id) on every read.
    # They are not errors (the files pass check_downloaded_window); hide them so real warnings stay visible.
    logging.getLogger("rasterio._env").setLevel(logging.ERROR)
    log = logging.getLogger("run_once")
    log.info("mode: %s, data dir: %s", "BACKFILL (started by hand)" if args.backfill else "scheduled/normal", data_dir)

    if INITIAL_SINCE_DATE is None:
        log.error("INITIAL_SINCE_DATE is not set in scripts/run_once.py; refusing to guess a start date")
        return 2

    conn = db.connect(DB_PATH)
    db.seed_lakes(conn)   # no-op when the lakes exist; raises if a stored coordinate was changed
    lake_ids = None
    if args.lakes:
        codes = [c.strip() for c in args.lakes.split(",") if c.strip()]
        found = {row["code"]: row["id"] for row in conn.execute("SELECT id, code FROM lake")}
        unknown = [c for c in codes if c not in found]
        if unknown:
            log.error("unknown lake code(s): %s (known: %s)", ", ".join(unknown), ", ".join(sorted(found)))
            conn.close()
            return 2
        lake_ids = [found[c] for c in codes]
        log.info("lakes: %s", ", ".join(codes))
    conn.close()

    result = run_pipeline_once(DB_PATH, data_dir, INITIAL_SINCE_DATE, lakes=lake_ids)
    log.info("summary: run_id=%s lakes=%s scenes_recorded=%s downloaded=%s measurements=%s risk_scores=%s",
             result.run_id, result.lakes_processed, result.scenes_recorded, result.scenes_downloaded,
             result.measurements, result.risk_scores)
    if result.errors:
        log.error("run FAILED, recorded in run_log %s:\n%s", result.run_id, result.errors)
        return 1
    log.info("run OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
