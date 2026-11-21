"""ShinGhar Step 1: which villages lie on each candidate lake's downhill path?
Copernicus GLO-30 2024 DEM at 30 m (UTM 43N) for the Kalam area, sink-filled and traced with the SailAb FYP's own
sailab.terrain.fill_sinks / trace_flood_path_2d (D8, steepest descent) from each lake centre. Reports, per lake, the
villages (GHSL clusters named via OpenStreetMap Nominatim, settlements_named.json) within 500 m of the path, with the
distance along the path. Usage: .venv/bin/python flow_paths.py out.json
"""
import io
import json
import sys

import numpy as np

sys.path.insert(0, "/home/rayannn/Documents/ShinGhar")
from sailab import earth_engine_client as c
from sailab.terrain import fill_sinks, trace_flood_path_2d

c.initialize()
import ee
import rasterio
import requests
from rasterio.warp import transform

BBOX = (72.20, 35.36, 72.72, 35.70)
LAKES = {"SA": (72.34591, 35.36737), "SB": (72.29714, 35.63584), "SC": (72.23468, 35.60824),
         "SD": (72.45197, 35.43385), "SE": (72.43293, 35.41921), "SF": (72.51194, 35.64618), "SI": (72.59834, 35.60281)}
EPSG = 32643
PX = 30
xs, ys = transform("EPSG:4326", f"EPSG:{EPSG}", [BBOX[0], BBOX[2], BBOX[0], BBOX[2]], [BBOX[1], BBOX[1], BBOX[3], BBOX[3]])
x0, y1 = np.floor(min(xs) / PX) * PX, np.ceil(max(ys) / PX) * PX
w, h = int((max(xs) - x0) / PX) + 1, int((y1 - min(ys)) / PX) + 1
col = ee.ImageCollection(c.DEM_COLLECTION).select("DEM")
dem_img = col.mosaic().setDefaultProjection(col.first().projection()).toFloat()
url = dem_img.getDownloadURL({"crs": f"EPSG:{EPSG}", "crs_transform": [PX, 0, x0, 0, -PX, y1], "dimensions": f"{w}x{h}",
                              "format": "GEO_TIFF"})
with rasterio.open(io.BytesIO(requests.get(url, timeout=300).content)) as src:
    dem = src.read(1).astype(float)
print("DEM", dem.shape, flush=True)
filled = fill_sinks(dem)
print("filled", flush=True)

villages = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else []
vx, vy = transform("EPSG:4326", f"EPSG:{EPSG}", [v["lon"] for v in villages], [v["lat"] for v in villages])
out = {}
for code, (lon, lat) in LAKES.items():
    lx, ly = transform("EPSG:4326", f"EPSG:{EPSG}", [lon], [lat])
    start = (int((y1 - ly[0]) / PX), int((lx[0] - x0) / PX))
    path = trace_flood_path_2d(filled, start)
    px_ = np.array([[x0 + (cc + 0.5) * PX, y1 - (r + 0.5) * PX] for r, cc in path])
    along = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(px_, axis=0).T))])
    hits = []
    for v, x, y in zip(villages, vx, vy):
        d = np.hypot(px_[:, 0] - x, px_[:, 1] - y)
        i = int(d.argmin())
        if d[i] <= 500:
            hits.append({"village": v["name"], "min_dist_to_path_m": round(float(d[i])), "along_path_km": round(float(along[i]) / 1000, 1),
                         "elev_drop_m": round(float(dem[path[0]] - dem[path[i]]))})
    hits.sort(key=lambda hh: hh["along_path_km"])
    end_lon, end_lat = transform(f"EPSG:{EPSG}", "EPSG:4326", [px_[-1, 0]], [px_[-1, 1]])
    out[code] = {"path_km": round(float(along[-1]) / 1000, 1), "end": [round(end_lon[0], 4), round(end_lat[0], 4)], "villages": hits}
    print(code, out[code], flush=True)
json.dump(out, open(sys.argv[1], "w"), indent=1)
