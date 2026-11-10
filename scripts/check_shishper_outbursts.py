"""Does the stored record of Shishper glacier lake (SHP) show its known outbursts?

For each published outburst date, lists every OPTICAL result from 45 days before to 45 days after it
(usable area, no lake found, refused, too cloudy), and states, from the stored rows only:
  - the last usable area before the date, and
  - the first scene after the date that could judge the lake (usable or no lake found).
An outburst is "seen" when the lake had a usable area before and the first judged scene after shows no lake
or a much smaller area (under half). Reads sailab_glof.db read-only.

Published dates (sources in the docstring of each entry):
  2019-06-22  first breach (Springer 2020, doi 10.1007/s11356-020-11929-z; some sources give 23 June)
  2020-05-29  second outburst (same study)
  2021-05-18  listed in one thesis only (PIDE, Karim 2019 thesis update); NOT in the Journal of Glaciology
              paper: treated as uncertain
  2022-05-07  drained, Hassanabad KKH bridge washed away (Journal of Glaciology; Dawn, 8 May 2022)
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EVENTS = [(date(2019, 6, 22), "first breach (22-23 June 2019)", True),
          (date(2020, 5, 29), "second outburst", True),
          (date(2021, 5, 18), "listed in one thesis only (uncertain)", False),
          (date(2022, 5, 7), "drained; KKH bridge destroyed", True)]
WINDOW = timedelta(days=45)


def main() -> int:
    conn = sqlite3.connect(f"file:{REPO / 'sailab_glof.db'}?mode=ro", uri=True)
    lake = conn.execute("SELECT id FROM lake WHERE code = 'SHP'").fetchone()
    if lake is None:
        print("SHP is not in the database"); return 2
    rows = conn.execute(
        """SELECT substr(s.acquired_at, 1, 10), s.cloud_fraction, s.file_path LIKE 'not_downloaded/%', m.status, m.extent_ha
           FROM scene s LEFT JOIN measurement m ON m.scene_id = s.id
           WHERE s.lake_id = ? AND s.source = 'sentinel-2' ORDER BY s.acquired_at""", (lake[0],)).fetchall()
    first, last = rows[0][0], rows[-1][0]
    print(f"SHP optical record: {len(rows)} scenes, {first} to {last}")
    seen = 0
    for day, label, confirmed in EVENTS:
        print(f"\n== {day} {label} ==")
        before_ok, after_judged = None, None
        for d, cloud, cloudy, status, ha in rows:
            dd = date.fromisoformat(d)
            # Both sides only within WINDOW of the event: a value from a year earlier says nothing about it.
            if day - WINDOW <= dd < day and status == "ok":
                before_ok = (d, ha)
            if day < dd <= day + WINDOW and after_judged is None and status in ("ok", "no_lake_detected"):
                after_judged = (d, status, ha)
            if day - WINDOW <= dd <= day + WINDOW:
                what = "too cloudy" if cloudy else (f"usable {ha:.2f} ha" if status == "ok" else
                                                    "NO LAKE FOUND" if status == "no_lake_detected" else "refused")
                print(f"   {d} {'before' if dd < day else 'after '}  cloud {cloud if cloud is not None else float('nan'):5.1f}%  {what}")
        print(f"   last usable before: {before_ok}")
        print(f"   first judged after: {after_judged}")
        verdict = f"no usable area in the {WINDOW.days} days before: cannot tell"
        if before_ok and after_judged:
            if after_judged[1] == "no_lake_detected":
                verdict = f"SEEN: {before_ok[1]:.2f} ha on {before_ok[0]}, no lake on {after_judged[0]}"
            elif after_judged[2] < before_ok[1] / 2:
                verdict = f"SEEN: {before_ok[1]:.2f} ha on {before_ok[0]} -> {after_judged[2]:.2f} ha on {after_judged[0]}"
            else:
                verdict = f"NOT seen: {before_ok[1]:.2f} ha on {before_ok[0]} -> {after_judged[2]:.2f} ha on {after_judged[0]}"
        elif before_ok:
            verdict = f"no usable or no-lake scene in the {WINDOW.days} days after: cannot tell"
        if confirmed and verdict.startswith("SEEN"):
            seen += 1
        print(f"   verdict: {verdict}")
    print(f"\nConfirmed outbursts seen in the stored record: {seen} of {sum(1 for e in EVENTS if e[2])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
