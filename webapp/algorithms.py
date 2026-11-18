"""Water-detection algorithms the viewer can pick at run time, applied to a stored or freshly downloaded image and shown
next to the pipeline's own result. The nightly record and its risk scores always use NDWI (optical) and slope mask +
Otsu (radar), so the history never mixes methods; these results are computed for display only and never stored.

Only the "is this pixel water?" test differs between methods. Everything after it is the pipeline's own, unchanged:
region_grow() from the lake centre with the same distance limit, extent_area_m2(), otsu_threshold(), and the same
refusal checks (no-data, cloud/shadow or snow/ice touching the lake, more than half the lake circle snowed in).
The baseline entries ("ndwi", "otsu") reproduce sailab.pipeline.measure_scene and sailab.radar.measure_radar_scene;
a test checks that on stored images.

Sources (from docs: SailAb_GLOF_Old_vs_Latest_Research_Papers, rows 9 and 11):
  NDWI   McFeeters, S. K. (1996), Int. J. Remote Sensing 17(7). Cutoff 0.2, as the pipeline uses.
  MNDWI  Xu, H. (2006), Int. J. Remote Sensing 27(14): green and SWIR-1 (Sentinel-2 B3, B11). Cutoff 0.
  Otsu on the index: the cutoff chosen per image by Otsu (1979) instead of fixed (adaptive thresholding).
  Edge Otsu  Donchyts et al. (2016) and Markert et al. (2020), Remote Sensing 12(15) 2469: Otsu only on pixels near
             the edges of a first water map, where both classes are present in similar numbers.
  Bmax Otsu  Markert et al. (2020): Otsu only on tiles whose histogram is clearly two-peaked (normalised between-class
             variance >= BMAX_LIMIT); an image with no such tile is refused instead of thresholded.
Simplifications, stated: Edge Otsu uses the edges of the first water map (no Canny filter, no edge-length filter) and a
100 m buffer; Bmax Otsu uses 300 m tiles (the window is only 2-5 km wide) and a 0.75 limit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import floor
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np

from sailab.measurement import Pixel, extent_area_m2, otsu_threshold, region_grow

NDWI_CUTOFF = 0.2          # the pipeline's
MNDWI_CUTOFF = 0.0         # Xu (2006)
EDGE_BUFFER_M = 100.0
BMAX_TILE_PX = 30          # 300 m at 10 m pixels
BMAX_LIMIT = 0.75


@dataclass
class AlgoResult:
    key: str
    label: str
    status: str                       # 'ok' / 'insufficient_observation'
    extent_ha: float | None
    reason: str
    threshold: float | None
    water_px: int
    region_px: int | None
    notes: list[str] = field(default_factory=list)
    picture: np.ndarray | None = field(default=None, repr=False)


@dataclass(frozen=True)
class Algorithm:
    key: str
    label: str
    sensor: str                       # 'optical' / 'radar'
    source: str
    baseline: bool = False


OPTICAL = [
    Algorithm("ndwi", "NDWI > 0.2 (ours)", "optical", "McFeeters 1996", baseline=True),
    Algorithm("mndwi", "MNDWI > 0", "optical", "Xu 2006"),
    Algorithm("ndwi_otsu", "NDWI, Otsu cutoff", "optical", "adaptive threshold (Otsu 1979)"),
    Algorithm("mndwi_otsu", "MNDWI, Otsu cutoff", "optical", "Xu 2006 + Otsu 1979"),
]
RADAR = [
    Algorithm("otsu", "Slope mask + Otsu (ours)", "radar", "Otsu 1979", baseline=True),
    Algorithm("edge_otsu", "Edge Otsu", "radar", "Donchyts 2016; Markert 2020"),
    Algorithm("bmax_otsu", "Bmax Otsu", "radar", "Markert 2020"),
]
# Shown in the dropdown but not selectable, with the honest reason.
UNAVAILABLE = [
    ("AWEI (Feyisa 2014)", "optical", "needs band B12 (SWIR-2), which the pipeline does not download"),
    ("Random forest, S1 + S2 (Wangchuk & Bolch 2020)", "both", "needs a trained model; no training data has been labelled yet"),
    ("Geo-foundation model (Jiang et al. 2025)", "optical", "needs a large pre-trained model and a GPU"),
]
BY_KEY = {a.key: a for a in OPTICAL + RADAR}


def choices(sensor: str) -> list[Algorithm]:
    return OPTICAL if sensor == "optical" else RADAR


# ---------------------------------------------------------------------------
# shared steps (the pipeline's own functions)
# ---------------------------------------------------------------------------
def _grow(water: np.ndarray, path: Path, lake: Mapping[str, Any], pixel_size_m: float):
    from sailab.pipeline import lake_centre_in_pixels

    rows, cols = water.shape
    row_f, col_f = lake_centre_in_pixels(path, lake["centre_lon"], lake["centre_lat"])
    seed = Pixel(floor(row_f), floor(col_f))
    if not (0 <= seed.row < rows and 0 <= seed.col < cols):
        return seed, None, f"lake centre {seed} is outside the {cols}x{rows} window"
    if not water[seed.row, seed.col]:
        return seed, None, f"centre pixel {seed} is not water for this method"
    is_water = {Pixel(r, c): bool(water[r, c]) for r in range(rows) for c in range(cols)}
    region = region_grow(is_water, seed, (row_f * pixel_size_m, col_f * pixel_size_m), pixel_size_m,
                         float(lake["growth_distance_limit_m"]))
    return seed, region, None


def _mask(region, shape) -> np.ndarray:
    m = np.zeros(shape, dtype=bool)
    for p in region or ():
        m[p.row, p.col] = True
    return m


def _picture(base_rgb: np.ndarray, water: np.ndarray, region_mask: np.ndarray) -> np.ndarray:
    """Dimmed image, water pixels in blue, the grown lake outlined in yellow (same colour as the scene pages)."""
    from webapp.scene_view import _edge
    out = base_rgb.astype(float) * 0.6 + 30
    out[water] = (60, 140, 230)
    out[region_mask] = (20, 90, 200)
    out[_edge(region_mask)] = (255, 196, 0)
    return np.clip(out, 0, 255).astype(np.uint8)


def _otsu_np(values: np.ndarray) -> float:
    return otsu_threshold([float(v) for v in values.ravel()])


def _bimodality(values: np.ndarray, n_bins: int = 256) -> float:
    """Largest between-class variance over total variance (0 = one class, 1 = two perfectly separated classes)."""
    v = values[np.isfinite(values)]
    if v.size < 2 or v.min() == v.max():
        return 0.0
    hist, edges = np.histogram(v, bins=n_bins)
    centres = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist).astype(float)
    w1 = w0[-1] - w0
    s0 = np.cumsum(hist * centres)
    m0 = np.divide(s0, w0, out=np.zeros_like(s0), where=w0 > 0)
    m1 = np.divide(s0[-1] - s0, w1, out=np.zeros_like(s0), where=w1 > 0)
    bcv = w0 * w1 * (m0 - m1) ** 2 / (w0[-1] ** 2)
    return float(bcv.max() / v.var()) if v.var() > 0 else 0.0


# ---------------------------------------------------------------------------
# optical
# ---------------------------------------------------------------------------
def run_optical(key: str, path: Path, lake: Mapping[str, Any]) -> AlgoResult:
    import rasterio
    from sailab.pipeline import (GREEN_BAND_INDEX, NIR_BAND_INDEX, SCL_BAND_INDEX, SCL_CLOUD_CLASSES, SCL_SNOW_ICE,
                                 SNOW_COVER_LIMIT, _inside_circle, _pixels_touching, lake_centre_in_pixels)

    algo = BY_KEY[key]
    with rasterio.open(path) as src:
        green = src.read(GREEN_BAND_INDEX).astype(float)
        nir = src.read(NIR_BAND_INDEX).astype(float)
        swir = src.read(5).astype(float)                     # B11 (SWIR-1), band 5 of every download
        blue, red = src.read(1).astype(float), src.read(3).astype(float)
        scl = src.read(SCL_BAND_INDEX) if src.count >= SCL_BAND_INDEX else None
        pixel_size_m = float(src.res[0])
    other = nir if key.startswith("ndwi") else swir
    with np.errstate(invalid="ignore", divide="ignore"):
        index = np.where(green + other != 0, (green - other) / (green + other), np.nan)
    valid = np.isfinite(index)
    notes = []
    if key in ("ndwi", "mndwi"):
        cutoff = NDWI_CUTOFF if key == "ndwi" else MNDWI_CUTOFF
    else:
        cutoff = _otsu_np(index[valid])
        notes.append(f"Otsu chose the cutoff {cutoff:.3f} from this image's own {'NDWI' if key.startswith('ndwi') else 'MNDWI'} values")
    water = valid & (index > cutoff)
    seed, region, why = _grow(water, path, lake, pixel_size_m)
    base = np.clip(np.stack([red, green, blue], axis=-1) / 3000.0, 0, 1) ** 0.6 * 255
    mask = _mask(region, water.shape)
    result = AlgoResult(key, algo.label, "insufficient_observation", None, why or "", cutoff, int(water.sum()),
                        len(region) if region else None, notes, _picture(base, water, mask))
    if region is None:
        return result
    no_data = (green == 0) & (nir == 0)
    checks = [(_pixels_touching(region, no_data), f"lake region ({len(region)} px) borders no-data pixels; it may be cut off")]
    if scl is not None:
        checks += [(_pixels_touching(region, np.isin(scl, SCL_CLOUD_CLASSES)), f"check D: lake region ({len(region)} px) borders cloud/shadow"),
                   (_pixels_touching(region, scl == SCL_SNOW_ICE), f"check C: lake region ({len(region)} px) borders snow/ice")]
    for n, reason in checks:
        if n:
            result.reason = reason
            return result
    if scl is not None:
        row_f, col_f = lake_centre_in_pixels(path, lake["centre_lon"], lake["centre_lat"])
        rows, cols = water.shape
        circle = _inside_circle(rows, cols, row_f, col_f, float(lake["boundary_radius_m"]) / pixel_size_m) & (scl != 0)
        share = float(((scl == SCL_SNOW_ICE) & circle).sum()) / max(int(circle.sum()), 1)
        if share > SNOW_COVER_LIMIT:
            result.reason = f"check C: {share:.0%} of the lake circle is snow/ice"
            return result
    result.status, result.extent_ha = "ok", extent_area_m2(region, pixel_size_m) / 10_000
    result.reason = f"{len(region)} water pixels connected to the centre"
    return result


# ---------------------------------------------------------------------------
# radar
# ---------------------------------------------------------------------------
def run_radar(key: str, path: Path, lake: Mapping[str, Any], slope: np.ndarray, slope_limit_deg: float) -> AlgoResult:
    import rasterio

    algo = BY_KEY[key]
    with rasterio.open(path) as src:
        names = list(src.descriptions)
        vv = src.read(names.index("VV") + 1 if "VV" in names else 1).astype(float)
        pixel_size_m = float(src.res[0])
    rows, cols = vv.shape
    no_data = ~np.isfinite(vv)
    usable = ~no_data & ~(slope > slope_limit_deg)
    notes: list[str] = []
    grey = np.clip((np.nan_to_num(vv, nan=-30.0) + 30.0) / 35.0, 0, 1) * 255
    base = np.stack([grey] * 3, axis=-1)
    if not usable.any():
        return AlgoResult(key, algo.label, "insufficient_observation", None, "no valid flat radar pixels", None, 0, None, notes, base.astype(np.uint8))
    threshold = _otsu_np(vv[usable])                        # the pipeline's threshold: Otsu over flat ground
    if key == "edge_otsu":
        first = usable & (vv < threshold)
        edge = np.zeros_like(first)
        edge[1:, :] |= first[1:, :] != first[:-1, :]
        edge[:-1, :] |= first[1:, :] != first[:-1, :]
        edge[:, 1:] |= first[:, 1:] != first[:, :-1]
        edge[:, :-1] |= first[:, 1:] != first[:, :-1]
        from scipy.ndimage import binary_dilation
        near = binary_dilation(edge & usable, iterations=max(1, int(EDGE_BUFFER_M / pixel_size_m))) & usable
        if near.sum() < 50:
            return AlgoResult(key, algo.label, "insufficient_observation", None, "too few pixels near water edges for Edge Otsu",
                              None, 0, None, notes, base.astype(np.uint8))
        threshold = _otsu_np(vv[near])
        notes.append(f"Otsu over the {int(near.sum()):,} flat pixels within {EDGE_BUFFER_M:.0f} m of the first water map's edges")
    elif key == "bmax_otsu":
        chosen = np.zeros_like(usable)
        tiles = picked = 0
        for r0 in range(0, rows, BMAX_TILE_PX):
            for c0 in range(0, cols, BMAX_TILE_PX):
                u = usable[r0:r0 + BMAX_TILE_PX, c0:c0 + BMAX_TILE_PX]
                if u.sum() < 0.5 * u.size:
                    continue
                tiles += 1
                if _bimodality(vv[r0:r0 + BMAX_TILE_PX, c0:c0 + BMAX_TILE_PX][u]) >= BMAX_LIMIT:
                    chosen[r0:r0 + BMAX_TILE_PX, c0:c0 + BMAX_TILE_PX] |= u
                    picked += 1
        notes.append(f"{picked} of {tiles} tiles ({BMAX_TILE_PX * pixel_size_m:.0f} m) clearly two-peaked (limit {BMAX_LIMIT})")
        if picked == 0:
            return AlgoResult(key, algo.label, "insufficient_observation", None,
                              "refused: no tile shows clear water and land, so a threshold would be meaningless",
                              None, 0, None, notes, base.astype(np.uint8))
        threshold = _otsu_np(vv[chosen])
    water = usable & (vv < threshold)
    seed, region, why = _grow(water, path, lake, pixel_size_m)
    mask = _mask(region, water.shape)
    result = AlgoResult(key, algo.label, "insufficient_observation", None, why or "", threshold, int(water.sum()),
                        len(region) if region else None, notes, _picture(base, water, mask))
    if region is None:
        return result
    touching = sum(1 for p in region for r, c in ((p.row - 1, p.col), (p.row + 1, p.col), (p.row, p.col - 1), (p.row, p.col + 1))
                   if 0 <= r < rows and 0 <= c < cols and no_data[r, c])        # same rule as sailab.radar
    if touching:
        result.reason = f"lake region ({len(region)} px) borders no-data pixels; it may be cut off"
        return result
    result.status, result.extent_ha = "ok", extent_area_m2(region, pixel_size_m) / 10_000
    result.reason = f"{len(region)} px below {threshold:.2f} dB connected to the centre"
    return result


def run(key: str, path: Path, lake: Mapping[str, Any], dem: Path | None = None) -> AlgoResult:
    """Apply one algorithm to one image file. Radar needs the lake's stored DEM (for the same slope mask)."""
    algo = BY_KEY[key]
    if algo.sensor == "optical":
        return run_optical(key, path, lake)
    from sailab.pipeline import RADAR_SLOPE_LIMIT_DEG
    from sailab.radar import load_slope
    return run_radar(key, path, lake, load_slope(dem), RADAR_SLOPE_LIMIT_DEG)
