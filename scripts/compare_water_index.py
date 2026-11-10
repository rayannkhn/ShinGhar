"""NDWI > 0.2 (the project's unchanged water test) vs MNDWI > 0 (green and shortwave infrared, B3 and B11),
with the SAME region growing from the SAME lake centre, on the 12 newest stored Jul-Sep optical scenes of each
lake (any stored status). Radar Jul-Sep median shown for comparison. Reads sailab_glof.db read-only; changes nothing.
B11 is 20 m (Earth Engine resamples it to the 10 m window), so MNDWI edges are coarser.
Usage: .venv/bin/python scripts/compare_water_index.py
"""
import sqlite3
import statistics
import sys
from math import floor
from pathlib import Path

import numpy as np
import rasterio

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from sailab import queries  # noqa: E402
from sailab.measurement import Pixel, region_grow  # noqa: E402
from sailab.pipeline import lake_centre_in_pixels  # noqa: E402


def grow(mask, lake, path, px):
    rf, cf = lake_centre_in_pixels(path, lake["centre_lon"], lake["centre_lat"])
    seed = Pixel(floor(rf), floor(cf))
    if not mask[seed.row, seed.col]:
        return None
    water = {Pixel(r, c): bool(mask[r, c]) for r in range(mask.shape[0]) for c in range(mask.shape[1])}
    return len(region_grow(water, seed, (rf * px, cf * px), px, float(lake["growth_distance_limit_m"]))) * px * px / 1e4


def summary(values):
    ok = [v for v in values if v is not None]
    if not ok:
        return f" 0/{len(values)} found"
    return f"{len(ok):2d}/{len(values)} found, median {statistics.median(ok):7.2f} ha, range {min(ok):.2f}-{max(ok):.2f}"


def main() -> int:
    conn = sqlite3.connect(f"file:{REPO / 'sailab_glof.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    for lake in queries.list_lakes(conn):
        radar = [r[0] for r in conn.execute(
            """SELECT m.extent_ha FROM measurement m JOIN scene s ON s.id = m.scene_id WHERE m.lake_id = ? AND m.sensor = 'radar'
               AND m.status = 'ok' AND substr(s.acquired_at, 6, 2) IN ('07', '08', '09')""", (lake["id"],))]
        rows = conn.execute(
            """SELECT s.file_path FROM scene s JOIN measurement m ON m.scene_id = s.id WHERE s.lake_id = ? AND m.sensor = 'optical'
               AND substr(s.acquired_at, 6, 2) IN ('07', '08', '09') ORDER BY s.acquired_at DESC LIMIT 12""", (lake["id"],)).fetchall()
        ndwi, mndwi = [], []
        for (file_path,) in rows:
            path = REPO / file_path
            if not path.is_file():
                continue
            with rasterio.open(path) as src:
                green, nir, swir = (src.read(i).astype(float) for i in (2, 4, 5))
                px = float(src.res[0])
            ndwi.append(grow((green - nir) / np.maximum(green + nir, 1) > 0.2, lake, path, px))
            mndwi.append(grow((green - swir) / np.maximum(green + swir, 1) > 0.0, lake, path, px))
        med = f"{statistics.median(radar):.2f} ha (n={len(radar)})" if radar else "none"
        print(f"{lake['code']}: radar Jul-Sep median {med}")
        print(f"     NDWI>0.2 : {summary(ndwi)}")
        print(f"     MNDWI>0  : {summary(mndwi)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
