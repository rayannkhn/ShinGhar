"""Smoke test of candidate lakes with the pipeline's OWN functions: list scenes, lake-window cloud,
download the 6-band window, measure_scene (NDWI 0.2 + region growing + checks C/D). Scratch files only;
the real database is not touched."""
import sys, json
from datetime import date
from pathlib import Path
sys.path.insert(0, "/home/rayannn/Documents/SAILAB_FYP1_FINAL")
from sailab import earth_engine_client as c
from sailab.pipeline import measure_scene, OPTICAL_CLOUD_LIMIT_PERCENT
c.initialize()
OUT = Path(sys.argv[1]); OUT.mkdir(exist_ok=True)
LAKES = [
 ("SHP", "Shishper lake", 74.5650, 36.3590, 1500, 1500, [(date(2019,5,1), date(2019,6,30)), (date(2022,4,1), date(2022,5,6)), (date(2025,7,1), date(2025,9,30))]),
 ("KDP", "Khurdopin lake", 75.48893, 36.33775, 2000, 2000, [(date(2019,6,1), date(2019,9,30)), (date(2025,7,1), date(2025,9,30))]),
 ("PSU", "Passu glacier lake", 74.87979, 36.45744, 1000, 1000, [(date(2025,7,1), date(2025,9,30))]),
 ("BRT", "Borith Lake", 74.86214, 36.43053, 1000, 1000, [(date(2025,7,1), date(2025,9,30))]),
 ("GLK", "Ghulkin glacier pond", 74.82459, 36.42329, 1000, 1000, [(date(2025,7,1), date(2025,9,30))]),
]
summary = {}
for code, name, lon, lat, radius, growth, periods in LAKES:
    lake = {"code": code, "name": name, "centre_lon": lon, "centre_lat": lat, "boundary_radius_m": radius, "growth_distance_limit_m": growth}
    rows = []
    for since, until in periods:
        scenes = c.find_new_scenes(lake, since, until)
        clear = [s for s in scenes if s.lake_cloud_percent is not None and s.lake_cloud_percent <= OPTICAL_CLOUD_LIMIT_PERCENT]
        print(f"{code} {since}..{until}: {len(scenes)} scenes, {len(clear)} clear over the lake")
        for s in sorted(clear, key=lambda s: s.lake_cloud_percent)[:4]:
            path = OUT / code / f"{s.scene_id}.tif"
            path.parent.mkdir(exist_ok=True)
            if not path.exists():
                c.download_scene_window(s, lake, path)
            o = measure_scene(path, lake)
            rows.append((s.acquired_at[:10], s.lake_cloud_percent, o.status, o.extent_ha, o.reason))
            print(f"   {s.acquired_at[:10]} cloud {s.lake_cloud_percent:4.1f}%  {o.status:24s} {o.extent_ha if o.extent_ha is None else round(o.extent_ha,2)}  {o.reason}")
    summary[code] = rows
json.dump(summary, open(OUT / "smoke.json", "w"), indent=1)
