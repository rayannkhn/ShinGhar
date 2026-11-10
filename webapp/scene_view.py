"""One stored scene, re-measured from its own file, with pictures of each step.

Optical (Sentinel-2): true colour, the NDWI map, and the cloud/snow map that checks C and D read.
Radar (Sentinel-1): VV backscatter, and the threshold map (steep ground removed, pixels darker than the
Otsu threshold, the grown lake).

The status and area shown as "recomputed" come from the pipeline's OWN unchanged functions
(sailab.pipeline.measure_scene, sailab.radar.measure_radar_scene) run on the stored file when the page is
opened. They are shown next to what the run stored, so a viewer can see that the two agree, or that they
do not. Nothing is filled in when a file is missing or the recomputation fails: the page says which.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import floor
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image

from sailab.measurement import Pixel, classify_water_ndwi, ndwi, region_grow
from sailab.pipeline import (GREEN_BAND_INDEX, NIR_BAND_INDEX, OPTICAL_CLOUD_LIMIT_PERCENT, RADAR_SLOPE_LIMIT_DEG,
                             SCL_BAND_INDEX, SCL_CLOUD_CLASSES, SCL_SNOW_ICE, lake_centre_in_pixels, measure_scene,
                             no_lake_evidence)
from sailab.radar import load_slope, measure_radar_scene

REGION_RGB = (255, 196, 0)          # same outline colour as webapp/images.py
NDWI_CUTOFF = 0.2                   # the pipeline's default cutoff (measure_scene(cutoff=0.2))
PICTURES = {"sentinel-2": ("truecolour", "ndwi", "checks"), "sentinel-1": ("vv", "threshold")}


@dataclass
class SceneAnalysis:
    status: str                     # recomputed: 'ok' / 'insufficient_observation'
    extent_ha: float | None
    reason: str
    region_px: int | None           # pixels in the drawn lake region (None when no region was grown)
    pixel_size_m: float
    threshold_db: float | None = None
    masked_steep_px: int | None = None
    slope_limit_deg: float | None = None
    ndwi_cutoff: float | None = None
    window_px: tuple[int, int] = (0, 0)
    stats: dict[str, Any] = field(default_factory=dict)
    pictures: dict[str, np.ndarray] = field(default_factory=dict, repr=False)


def _edge(inside: np.ndarray) -> np.ndarray:
    return inside & ~(np.roll(inside, 1, 0) & np.roll(inside, -1, 0) & np.roll(inside, 1, 1) & np.roll(inside, -1, 1))


def _mask(region, shape) -> np.ndarray:
    inside = np.zeros(shape, dtype=bool)
    for p in region or ():
        inside[p.row, p.col] = True
    return inside


def _outlined(rgb: np.ndarray, inside: np.ndarray) -> np.ndarray:
    out = rgb.copy()
    out[_edge(inside)] = REGION_RGB
    return out.astype(np.uint8)


def ndwi_colours(index: np.ndarray, cutoff: float = NDWI_CUTOFF) -> np.ndarray:
    """Water (NDWI > cutoff) in blues, darker = wetter; land in browns to pale; no data black."""
    rgb = np.zeros(index.shape + (3,), dtype=float)
    valid = np.isfinite(index)
    water = valid & (index > cutoff)
    land = valid & ~water
    t = np.clip((index - cutoff) / (1 - cutoff), 0, 1)                 # 0 at the cutoff, 1 at NDWI = 1
    for i, (light, dark) in enumerate(((150, 8), (200, 48), (255, 140))):
        rgb[..., i] = np.where(water, light + (dark - light) * t, rgb[..., i])
    u = np.clip((index + 1) / (1 + cutoff), 0, 1)                      # 0 at NDWI = -1, 1 at the cutoff
    for i, (low, high) in enumerate(((110, 232), (80, 226), (50, 214))):
        rgb[..., i] = np.where(land, low + (high - low) * u, rgb[..., i])
    return rgb


def analyse_optical(tif: Path, lake: Mapping[str, Any], acquired_on: date | None = None) -> SceneAnalysis:
    import rasterio

    with rasterio.open(tif) as src:
        b2, b3, b4, b8 = (src.read(i).astype(float) for i in (1, GREEN_BAND_INDEX, 3, NIR_BAND_INDEX))
        scl = src.read(SCL_BAND_INDEX) if src.count >= SCL_BAND_INDEX else None
        pixel_size_m = float(src.res[0])
    outcome = measure_scene(tif, lake, cutoff=NDWI_CUTOFF, scl_checks=scl is not None)
    status, reason = outcome.status, outcome.reason
    # Same rule as the pipeline's _process_scene: a refused "centre not water" can be 'no lake detected'.
    if acquired_on is not None and status == "insufficient_observation" and reason.startswith("centre pixel") \
            and "is not water" in reason:
        why = no_lake_evidence(tif, lake, acquired_on)
        if why is not None:
            status, reason = "no_lake_detected", f"{reason}; {why}"
    rows, cols = b3.shape

    # The same region the pipeline grew (same functions, same seed), drawn even when a later check refused it,
    # so the picture shows what touched cloud, snow or the window edge.
    row_f, col_f = lake_centre_in_pixels(tif, lake["centre_lon"], lake["centre_lat"])
    seed = Pixel(floor(row_f), floor(col_f))
    region = None
    if 0 <= seed.row < rows and 0 <= seed.col < cols and classify_water_ndwi(b3[seed.row, seed.col], b8[seed.row, seed.col], NDWI_CUTOFF):
        is_water = {Pixel(r, c): classify_water_ndwi(b3[r, c], b8[r, c], NDWI_CUTOFF) for r in range(rows) for c in range(cols)}
        region = region_grow(is_water, seed, (row_f * pixel_size_m, col_f * pixel_size_m), pixel_size_m,
                             float(lake["growth_distance_limit_m"]))
    inside = _mask(region, (rows, cols))

    index = np.full((rows, cols), np.nan)
    for r in range(rows):
        for c in range(cols):
            v = ndwi(b3[r, c], b8[r, c])
            if v is not None:
                index[r, c] = v
    rgb = np.clip(np.stack([b4, b3, b2], axis=-1) / 3000.0, 0, 1) ** 0.6 * 255
    pictures = {"truecolour": _outlined(rgb, inside), "ndwi": _outlined(ndwi_colours(index), inside)}
    stats: dict[str, Any] = {"water_px_in_window": int(np.nansum(index > NDWI_CUTOFF)),
                             "ndwi_at_centre": float(index[seed.row, seed.col]) if 0 <= seed.row < rows and 0 <= seed.col < cols and np.isfinite(index[seed.row, seed.col]) else None}
    if region:
        stats["ndwi_in_lake_median"] = float(np.nanmedian(index[inside]))
    if scl is not None:
        grey = rgb.mean(axis=-1, keepdims=True) * 0.55 + 40
        checks = np.repeat(grey, 3, axis=-1)
        cloud, snow = np.isin(scl, SCL_CLOUD_CLASSES), scl == SCL_SNOW_ICE
        checks[cloud] = (214, 51, 132)
        checks[snow] = (64, 200, 230)
        pictures["checks"] = _outlined(checks, inside)
        stats["cloud_px_in_window"], stats["snow_px_in_window"] = int(cloud.sum()), int(snow.sum())
    return SceneAnalysis(status, outcome.extent_ha, reason, len(region) if region else None,
                         pixel_size_m, ndwi_cutoff=NDWI_CUTOFF, window_px=(cols, rows), stats=stats, pictures=pictures)


def analyse_radar(tif: Path, lake: Mapping[str, Any], dem: Path) -> SceneAnalysis:
    import rasterio

    slope = load_slope(dem)
    outcome = measure_radar_scene(tif, lake, slope, RADAR_SLOPE_LIMIT_DEG)
    with rasterio.open(tif) as src:
        names = list(src.descriptions)
        vv = src.read(names.index("VV") + 1 if "VV" in names else 1).astype(float)
        pixel_size_m = float(src.res[0])
    rows, cols = vv.shape
    region = outcome.region if outcome.region else None
    inside = _mask(region, (rows, cols))
    grey = np.clip((np.nan_to_num(vv, nan=-30.0) + 30.0) / 35.0, 0, 1) * 255
    pictures = {"vv": _outlined(np.stack([grey] * 3, axis=-1), inside)}

    no_data = ~np.isfinite(vv)
    steep = slope > RADAR_SLOPE_LIMIT_DEG
    t = np.zeros((rows, cols, 3))
    t[:] = (226, 226, 222)                                    # flat ground, brighter than the threshold
    t[steep] = (150, 110, 95)                                 # removed by the slope mask
    if outcome.threshold_db is not None:
        t[~steep & ~no_data & (vv < outcome.threshold_db)] = (40, 110, 200)   # darker than the threshold
    t[no_data] = (0, 0, 0)
    pictures["threshold"] = _outlined(t, inside)
    stats: dict[str, Any] = {"vv_median_window_db": float(np.nanmedian(vv))}
    if region:
        stats["vv_median_lake_db"] = float(np.nanmedian(vv[inside]))
    flat = ~steep & ~no_data & ~inside
    if flat.any():
        stats["vv_median_flat_ground_db"] = float(np.nanmedian(vv[flat]))
    return SceneAnalysis(outcome.status, outcome.extent_ha, outcome.reason, len(region) if region else None,
                         pixel_size_m, threshold_db=outcome.threshold_db, masked_steep_px=outcome.masked_steep_px,
                         slope_limit_deg=RADAR_SLOPE_LIMIT_DEG, window_px=(cols, rows), stats=stats, pictures=pictures)


def save_png(rgb: np.ndarray, out_path: Path) -> None:
    rows, cols = rgb.shape[:2]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    scale = max(1, 480 // max(rows, cols))
    Image.fromarray(rgb.astype(np.uint8)).resize((cols * scale, rows * scale), Image.NEAREST).save(out_path)


def compare(stored_status: str | None, stored_ha: float | None, a: SceneAnalysis) -> str:
    """'same' when the recomputation gives the stored status and area (to 0.01 ha, one 10 m pixel), else 'differs'."""
    if stored_status != a.status:
        return "differs"
    if stored_ha is None and a.extent_ha is None:
        return "same"
    if stored_ha is None or a.extent_ha is None:
        return "differs"
    return "same" if abs(stored_ha - a.extent_ha) < 0.005 else "differs"


CLOUD_LIMIT_PERCENT = OPTICAL_CLOUD_LIMIT_PERCENT
