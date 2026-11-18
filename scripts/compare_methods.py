"""Every water-detection method in webapp/algorithms.py on every stored usable summer image, per lake.

Optical: all stored 'ok' Sentinel-2 measurements (any month). Radar: stored 'ok' Sentinel-1 measurements from July to
September (the most reliable radar months, from the 2026-11 error analysis). For each image and method: status and
area. Prints, per lake and method: images measured, images refused, median area, and the median difference from the
stored (pipeline) area. Also counts how often the baseline entries ('ndwi', 'otsu') differ from the stored value
(expected: never). Reads sailab_glof.db read-only; writes nothing but its own output.
Usage: .venv/bin/python scripts/compare_methods.py [LAKE_CODE ...]
"""
from __future__ import annotations

import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path
from statistics import median

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from webapp import algorithms as A  # noqa: E402


def main() -> int:
    conn = sqlite3.connect(f"file:{REPO / 'sailab_glof.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    codes = set(sys.argv[1:])
    started = time.time()
    baseline_differs = 0
    for lake in conn.execute("SELECT * FROM lake ORDER BY id"):
        lake = dict(lake)
        if codes and lake["code"] not in codes:
            continue
        dem = REPO / "data" / "dem" / f"{lake['code']}_dem.tif"
        for sensor, source, months in (("optical", "sentinel-2", None), ("radar", "sentinel-1", ("07", "08", "09"))):
            rows = conn.execute("""SELECT s.file_path, s.acquired_at, m.extent_ha FROM scene s JOIN measurement m ON m.scene_id = s.id
                                   WHERE s.lake_id = ? AND s.source = ? AND m.status = 'ok' ORDER BY s.acquired_at""",
                                (lake["id"], source)).fetchall()
            rows = [r for r in rows if (months is None or r["acquired_at"][5:7] in months) and (REPO / r["file_path"]).is_file()]
            if not rows:
                print(f"{lake['code']} {sensor}: no stored usable image files")
                continue
            areas, refused, diffs = defaultdict(list), defaultdict(int), defaultdict(list)
            for r in rows:
                for algo in A.choices(sensor):
                    res = A.run(algo.key, REPO / r["file_path"], lake, dem)
                    if res.status != "ok":
                        refused[algo.key] += 1
                        if algo.baseline:
                            baseline_differs += 1
                        continue
                    areas[algo.key].append(res.extent_ha)
                    diffs[algo.key].append((res.extent_ha - r["extent_ha"]) / r["extent_ha"] * 100)
                    if algo.baseline and abs(res.extent_ha - r["extent_ha"]) >= 0.005:
                        baseline_differs += 1
            print(f"\n{lake['code']} {lake['name']}, {sensor}: {len(rows)} stored usable images")
            print(f"  {'method':28s} {'measured':>8s} {'refused':>8s} {'median ha':>10s} {'median diff vs stored':>22s}")
            for algo in A.choices(sensor):
                a, d = areas[algo.key], diffs[algo.key]
                print(f"  {algo.label:28s} {len(a):8d} {refused[algo.key]:8d} {median(a) if a else float('nan'):10.2f} "
                      f"{(f'{median(d):+.1f}%') if d else '—':>22s}")
            sys.stdout.flush()
    print(f"\nBaseline entries differing from the stored value: {baseline_differs} (expected 0)")
    print(f"Took {time.time() - started:.0f} s")
    return 0 if baseline_differs == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
