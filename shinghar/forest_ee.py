"""Fetch the forest-layer rasters for a valley from Earth Engine, as one 10 m UTM stack (downloaded in tiles).

Bands (all stored as int16 in the GeoTIFF; scale factors below):
  ndvi_before, ndvi_after  x10000  Sentinel-2 SR harmonized, SCL-masked median NDVI, Jun-Sep of each year
  worldcover               class   ESA WorldCover v200 (2021), class 10 = tree cover
  treecover2000            %       Hansen GFC 2025 v1.13
  lossyear                 year-2000  Hansen GFC 2025 v1.13 (0 = no loss, 1 = 2001 ... 25 = 2025)
  slope                    x10 deg Copernicus GLO-30 DEM 2024 release (same DEM as the SailAb pipeline)
  dem                      m       same DEM
  built                    m2 per 100 m cell  JRC GHSL P2023A GHS_BUILT_S epoch 2020
  water_occurrence         %       JRC Global Surface Water v1.4 occurrence (0-100)
Hansen and WorldCover are resampled to 10 m by nearest neighbour (no new values are created).
"""
from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from sailab import earth_engine_client as c

HANSEN_ASSET = "UMD/hansen/global_forest_change_2025_v1_13"
WORLDCOVER = "ESA/WorldCover/v200"
GHSL_BUILT = "JRC/GHSL/P2023A/GHS_BUILT_S/2020"
GSW = "JRC/GSW1_4/GlobalSurfaceWater"
BANDS = ("ndvi_before", "ndvi_after", "worldcover", "treecover2000", "lossyear", "slope", "dem", "built",
         "water_occurrence")
SCALE = {"ndvi_before": 1e-4, "ndvi_after": 1e-4, "slope": 0.1}
# SCL classes kept for NDVI: 4 vegetation, 5 not vegetated, 6 water, 7 unclassified. Dropped: 0 no data,
# 1 saturated/defective, 2 dark/topographic shadow, 3 cloud shadow, 8/9 cloud, 10 cirrus, 11 snow/ice.
SCL_KEEP = (4, 5, 6, 7)
TILE_M = 5000
PIXEL_M = 10


def _summer_ndvi(ee, region, year: int, months=(6, 9)):
    col = (ee.ImageCollection(c.COLLECTION).filterBounds(region)
           .filterDate(f"{year}-{months[0]:02d}-01", f"{year}-{months[1] + 1:02d}-01"))

    def prep(img):
        scl = img.select("SCL")
        keep = scl.eq(SCL_KEEP[0])
        for k in SCL_KEEP[1:]:
            keep = keep.Or(scl.eq(k))
        return img.normalizedDifference(["B8", "B4"]).rename("ndvi").updateMask(keep)

    return col.map(prep).median(), col.size()


def build_stack(ee, region, before_year: int, after_year: int):
    """The server-side multi-band image (see module docstring). Masked pixels become -32768 in the download."""
    nb, n_before = _summer_ndvi(ee, region, before_year)
    na, n_after = _summer_ndvi(ee, region, after_year)
    hansen = ee.Image(HANSEN_ASSET)
    dem_col = ee.ImageCollection(c.DEM_COLLECTION).select("DEM")
    dem = dem_col.mosaic().setDefaultProjection(dem_col.first().projection())
    img = ee.Image.cat([
        nb.multiply(10000).rename("ndvi_before"),
        na.multiply(10000).rename("ndvi_after"),
        ee.ImageCollection(WORLDCOVER).first().rename("worldcover"),
        hansen.select("treecover2000"),
        hansen.select("lossyear").unmask(0),   # Hansen masks lossyear where there was no loss; 0 = no loss
        ee.Terrain.slope(dem).multiply(10).rename("slope"),
        dem.rename("dem"),
        ee.Image(GHSL_BUILT).select("built_surface").rename("built"),
        ee.Image(GSW).select("occurrence").unmask(0).rename("water_occurrence"),
    ]).toInt16().unmask(-32768)
    return img, n_before, n_after


def tile_grid(bbox: tuple[float, float, float, float]) -> tuple[int, float, float, int, int]:
    """UTM grid covering bbox (lon_min, lat_min, lon_max, lat_max): (epsg, x0, y0_top, width_px, height_px)."""
    from rasterio.warp import transform

    lon_c, lat_c = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    epsg = c.utm_epsg(lon_c, lat_c)
    xs, ys = transform("EPSG:4326", f"EPSG:{epsg}", [bbox[0], bbox[0], bbox[2], bbox[2]],
                       [bbox[1], bbox[3], bbox[1], bbox[3]])
    x0 = np.floor(min(xs) / 60) * 60
    y1 = np.ceil(max(ys) / 60) * 60
    w = int(np.ceil((max(xs) - x0) / PIXEL_M))
    h = int(np.ceil((y1 - min(ys)) / PIXEL_M))
    return epsg, float(x0), float(y1), w, h


def fetch_stack(bbox, before_year: int, after_year: int, out_path: str | Path, workers: int = 6,
                log=print) -> dict:
    """Download the stack for bbox in TILE_M tiles, mosaic locally, write one GeoTIFF. Returns metadata."""
    import ee
    import rasterio
    import requests
    from rasterio.transform import from_origin

    c.initialize()
    region = ee.Geometry.Rectangle(list(bbox))
    img, n_before, n_after = build_stack(ee, region, before_year, after_year)
    counts = ee.Dictionary({"before": n_before, "after": n_after}).getInfo()
    epsg, x0, y_top, w, h = tile_grid(bbox)
    stack = np.full((len(BANDS), h, w), -32768, dtype=np.int16)
    tpx = TILE_M // PIXEL_M
    jobs = [(r, col) for r in range(0, h, tpx) for col in range(0, w, tpx)]

    def one(job):
        r, col = job
        th, tw = min(tpx, h - r), min(tpx, w - col)
        params = {"bands": list(BANDS), "crs": f"EPSG:{epsg}", "format": "GEO_TIFF",
                  "crs_transform": [PIXEL_M, 0, x0 + col * PIXEL_M, 0, -PIXEL_M, y_top - r * PIXEL_M],
                  "dimensions": f"{tw}x{th}"}
        for attempt in range(3):
            try:
                url = img.getDownloadURL(params)
                resp = requests.get(url, timeout=300)
                if resp.status_code == 200 and resp.content[:4] in (b"II*\x00", b"MM\x00*"):
                    with rasterio.open(io.BytesIO(resp.content)) as src:
                        stack[:, r:r + th, col:col + tw] = src.read()
                    return None
                err = f"HTTP {resp.status_code}: {resp.text[:200]}"
            except Exception as exc:  # noqa: BLE001 - reported, then retried
                err = f"{type(exc).__name__}: {exc}"
        return f"tile r{r} c{col}: {err}"

    with ThreadPoolExecutor(workers) as pool:
        errors = [e for e in pool.map(one, jobs) if e]
    if errors:
        raise c.EarthEngineError(f"{len(errors)} of {len(jobs)} tiles failed; first: {errors[0]}")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    profile = {"driver": "GTiff", "dtype": "int16", "count": len(BANDS), "width": w, "height": h,
               "crs": f"EPSG:{epsg}", "transform": from_origin(x0, y_top, PIXEL_M, PIXEL_M), "nodata": -32768,
               "compress": "deflate", "tiled": True}
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(stack)
        for i, b in enumerate(BANDS, start=1):
            dst.set_band_description(i, b)
        dst.update_tags(bbox=str(bbox), before_year=before_year, after_year=after_year,
                        s2_images_before=counts["before"], s2_images_after=counts["after"], hansen=HANSEN_ASSET)
    meta = {"bbox": list(bbox), "epsg": epsg, "width": w, "height": h, "tiles": len(jobs),
            "s2_images_before": counts["before"], "s2_images_after": counts["after"]}
    log(f"stack written: {out_path} {meta}")
    return meta


def read_stack(path: str | Path) -> tuple[dict[str, np.ndarray], dict]:
    """Read the stack back as float arrays with scale factors applied; nodata -> NaN. Returns (bands, meta)."""
    import rasterio

    with rasterio.open(path) as src:
        raw = src.read()
        meta = {"transform": src.transform, "crs": src.crs.to_string(), "epsg": src.crs.to_epsg(), **src.tags()}
    out = {}
    for i, b in enumerate(BANDS):
        a = raw[i].astype("float64")
        a[raw[i] == -32768] = np.nan
        out[b] = a * SCALE.get(b, 1.0)
    return out, meta
