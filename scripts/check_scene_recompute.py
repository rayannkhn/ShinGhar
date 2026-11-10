"""Re-measure every stored scene that has a file on this laptop, with the scene page's code
(webapp.scene_view, which calls the pipeline's own measurement functions), and compare with the stored row.

Prints one line per scene that differs, then totals per lake and sensor. Reads sailab_glof.db read-only.
Usage: .venv/bin/python scripts/check_scene_recompute.py [LAKE_CODE ...]   (no codes: every lake)
"""
from __future__ import annotations

import sqlite3
import sys
import time
from datetime import date
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from sailab import queries  # noqa: E402
from webapp import scene_view  # noqa: E402


def main() -> int:
    conn = sqlite3.connect(f"file:{REPO / 'sailab_glof.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    lakes = {l["id"]: l for l in queries.list_lakes(conn)}
    codes = set(sys.argv[1:])
    rows = [r for r in conn.execute("""SELECT s.id, s.lake_id, s.source, s.acquired_at, s.file_path, m.status, m.extent_ha
                           FROM scene s JOIN measurement m ON m.scene_id = s.id ORDER BY s.lake_id, s.acquired_at""").fetchall()
            if not codes or lakes[r["lake_id"]]["code"] in codes]
    tally: Counter = Counter()
    started = time.time()
    for r in rows:
        lake = lakes[r["lake_id"]]
        key = (lake["code"], "radar" if r["source"] == "sentinel-1" else "optical")
        tif = REPO / r["file_path"]
        if not tif.is_file():
            tally[key + ("file missing",)] += 1
            continue
        try:
            a = (scene_view.analyse_radar(tif, lake, REPO / "data" / "dem" / f"{lake['code']}_dem.tif")
                 if r["source"] == "sentinel-1" else scene_view.analyse_optical(tif, lake, date.fromisoformat(r["acquired_at"][:10])))
        except Exception as exc:
            tally[key + ("error",)] += 1
            print(f"ERROR scene {r['id']} {lake['code']} {r['acquired_at'][:10]}: {type(exc).__name__}: {exc}")
            continue
        verdict = scene_view.compare(r["status"], r["extent_ha"], a)
        tally[key + (verdict,)] += 1
        if verdict != "same":
            print(f"DIFFERS scene {r['id']} {lake['code']} {r['acquired_at'][:10]} {r['source']}: stored {r['status']} "
                  f"{r['extent_ha']}, recomputed {a.status} {a.extent_ha} ({a.reason})")
    print(f"\n{len(rows)} measured scenes checked in {time.time() - started:.0f} s")
    for k in sorted(tally):
        print(f"  {k[0]} {k[1]:8s} {k[2]:13s} {tally[k]}")
    return 0 if not any(k[2] in ("differs", "error") for k in tally) else 1


if __name__ == "__main__":
    raise SystemExit(main())
