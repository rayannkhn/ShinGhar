"""ShinGhar Step 1: smoke test of the Upper Swat lake candidates with the pipeline's OWN functions (as in
logs/2026-11-18_nepal_lake_candidates/smoke_others.py): list Sentinel-2 scenes, lake-window cloud, download the 6-band
window, measure_scene (NDWI 0.2 + region growing + checks C/D). Summer (Jul-Sep) 2024 and 2025, 4 clearest per season.
Centres: JRC GSW v1.4 max_extent centroids from find_candidates.py. Scratch files only; the database is not touched.
Usage: .venv/bin/python smoke.py OUT_DIR
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, "/home/rayannn/Documents/ShinGhar")
from sailab import earth_engine_client as c
from sailab.pipeline import OPTICAL_CLOUD_LIMIT_PERCENT, measure_scene

c.initialize()
OUT = Path(sys.argv[1])
OUT.mkdir(exist_ok=True)
SEASONS = [(date(2024, 6, 30), date(2024, 9, 30)), (date(2025, 6, 30), date(2025, 9, 30))]
LAKES = [  # code, label, lon, lat (JRC centroids), radius/growth limit (m)
    ("SA", "Utror-Gabral 77.5 ha, 3535 m", 72.34591, 35.36737, 1000),
    ("SB", "Utror-Gabral 31.6 ha, 4077 m", 72.29714, 35.63584, 1000),
    ("SC", "Utror-Gabral 18.7 ha, 3865 m", 72.23468, 35.60824, 1000),
    ("SD", "Utror-Gabral 18.3 ha, 3183 m", 72.45197, 35.43385, 1000),
    ("SE", "Utror-Gabral 45.3 ha, 3028 m", 72.43293, 35.41921, 1000),
    ("SF", "Kalam 34.2 ha, 3345 m", 72.51194, 35.64618, 1000),
    ("SG", "Kalam 23.9 ha, 4509 m", 72.64245, 35.83381, 1000),
    ("SH", "Kalam 20.4 ha, 4271 m", 72.79789, 35.62430, 1000),
    ("SI", "Kalam 18.3 ha, 3887 m", 72.59834, 35.60281, 1000),
    ("SJ", "Kalam 17.7 ha, 4563 m", 72.82686, 35.61287, 1000),
]
only = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
summary = {}
for code, label, lon, lat, radius in LAKES:
    if only and code not in only:
        continue
    lake = {"code": code, "name": label, "centre_lon": lon, "centre_lat": lat,
            "boundary_radius_m": float(radius), "growth_distance_limit_m": float(radius)}
    rows = []
    total = 0
    for since, until in SEASONS:
        try:
            scenes = c.find_new_scenes(lake, since, until)
        except c.EarthEngineError as exc:
            print(f"{code} {since}..{until}: EarthEngineError {exc}", flush=True)
            continue
        total += len(scenes)
        clear = [s for s in scenes if s.lake_cloud_percent is not None and s.lake_cloud_percent <= OPTICAL_CLOUD_LIMIT_PERCENT]
        print(f"{code} ({label}) {since}..{until}: {len(scenes)} scenes, {len(clear)} clear over the lake", flush=True)
        for s in sorted(clear, key=lambda s: s.lake_cloud_percent)[:4]:
            path = OUT / code / f"{s.scene_id}.tif"
            path.parent.mkdir(exist_ok=True)
            try:
                if not path.exists():
                    c.download_scene_window(s, lake, path)
                o = measure_scene(path, lake)
            except Exception as exc:  # report, never hide
                print(f"   {s.acquired_at[:10]} ERROR {type(exc).__name__}: {exc}", flush=True)
                rows.append((s.acquired_at[:10], s.lake_cloud_percent, "error", None, str(exc)))
                continue
            rows.append((s.acquired_at[:10], s.lake_cloud_percent, o.status, o.extent_ha, o.reason))
            ha = None if o.extent_ha is None else round(o.extent_ha, 2)
            print(f"   {s.acquired_at[:10]} cloud {s.lake_cloud_percent:4.1f}%  {o.status:24s} {ha}  {o.reason}", flush=True)
    summary[code] = {"label": label, "lon": lon, "lat": lat, "scenes_listed": total, "tested": rows}
    json.dump(summary, open(OUT / "smoke.json", "w"), indent=1)
