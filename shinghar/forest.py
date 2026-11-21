"""ShinGhar forest layer: tree-cover loss patches, ranked for ranger visits.

Two independent sources of "tree cover loss" on one 10 m grid:
  1. Hansen Global Forest Change (University of Maryland), annual loss 2001-2025 at 30 m (resampled, nearest).
     Hansen counts ANY loss of tree canopy (logging, fire, landslides, disease, ...), so we say "tree cover loss",
     never "deforestation".
  2. Our own change detection: Sentinel-2 NDVI = (B8 - B4) / (B8 + B4), cloud-masked (SCL) summer medians,
     before vs after; a pixel is "loss" when it was forest and its NDVI dropped by more than NDVI_DROP_THRESHOLD.

This file holds only the numpy logic (unit-tested in tests/test_shinghar_forest.py). Fetching the rasters from Earth
Engine lives in shinghar/forest_ee.py.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import hypot

import numpy as np
from scipy import ndimage

# Judgement-call settings (stated on screen and in DEMO.md; not calibrated):
NDVI_DROP_THRESHOLD = 0.20      # NDVI(before) - NDVI(after) above this = our "loss"
HANSEN_FOREST_MIN_COVER = 30    # Hansen treecover2000 >= 30 % counts as forest (Hansen's own common threshold)
WORLDCOVER_TREES = 10           # ESA WorldCover v200 class 10 = "Tree cover"
MIN_PATCH_HA = 0.5              # smaller connected patches are not reported
PIXEL_SIZE_M = 10.0

# Ranking for ranger visits: transparent weights, each component normalised to 0..1 within the valley.
RANK_WEIGHTS = {"area": 0.40, "slope": 0.30, "near_settlement": 0.30}
NEAR_SETTLEMENT_SCALE_M = 5000.0   # distance at which the "near settlement" component reaches 0


def ndvi(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    """NDVI = (NIR - red) / (NIR + red); NaN where NIR + red is 0 or either input is NaN."""
    nir = np.asarray(nir, dtype="float64")
    red = np.asarray(red, dtype="float64")
    total = nir + red
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (nir - red) / total
    out[~np.isfinite(out)] = np.nan
    return out


def forest_mask(worldcover: np.ndarray, hansen_treecover2000: np.ndarray) -> np.ndarray:
    """Forest = WorldCover 'tree cover' (2021) OR Hansen treecover2000 >= HANSEN_FOREST_MIN_COVER."""
    return (np.asarray(worldcover) == WORLDCOVER_TREES) | (np.asarray(hansen_treecover2000) >= HANSEN_FOREST_MIN_COVER)


def ndvi_loss(ndvi_before: np.ndarray, ndvi_after: np.ndarray, forest: np.ndarray,
              drop_threshold: float = NDVI_DROP_THRESHOLD) -> np.ndarray:
    """Our loss: forest pixels whose NDVI fell by MORE than drop_threshold. NaN (cloud/no data) is never loss."""
    drop = np.asarray(ndvi_before, dtype="float64") - np.asarray(ndvi_after, dtype="float64")
    with np.errstate(invalid="ignore"):
        return np.asarray(forest, dtype=bool) & np.isfinite(drop) & (drop > drop_threshold)


def hansen_loss(lossyear: np.ndarray, first_year: int, last_year: int, treecover2000: np.ndarray) -> np.ndarray:
    """Hansen loss in [first_year, last_year] (lossyear 1 = 2001) inside Hansen forest (treecover2000 >= 30 %)."""
    ly = np.asarray(lossyear)
    return (ly >= first_year - 2000) & (ly <= last_year - 2000) & (ly > 0) & \
        (np.asarray(treecover2000) >= HANSEN_FOREST_MIN_COVER)


def agreement(ours: np.ndarray, hansen: np.ndarray, valid: np.ndarray) -> dict:
    """Pixel agreement between our loss and Hansen loss, counted only where both could be judged (valid).

    Returns counts and three plain shares (None when the denominator is 0, never a made-up 0):
      both / ours  : share of our loss that Hansen also maps
      both / hansen: share of Hansen's loss that we also find
      iou          : both / (ours OR hansen)
    """
    v = np.asarray(valid, dtype=bool)
    o = np.asarray(ours, dtype=bool) & v
    h = np.asarray(hansen, dtype=bool) & v
    both, n_o, n_h, either = int((o & h).sum()), int(o.sum()), int(h.sum()), int((o | h).sum())
    share = lambda a, b: (a / b) if b else None
    return {"valid_px": int(v.sum()), "ours_px": n_o, "hansen_px": n_h, "both_px": both, "either_px": either,
            "ours_confirmed_by_hansen": share(both, n_o), "hansen_found_by_ours": share(both, n_h),
            "iou": share(both, either)}


@dataclass
class Patch:
    patch_id: int
    area_ha: float
    centroid_row: float
    centroid_col: float
    lon: float | None = None
    lat: float | None = None
    source: str = ""                         # "both", "ndvi_only", "hansen_only"
    ndvi_share: float = 0.0                  # share of the patch's pixels in our NDVI loss
    hansen_share: float = 0.0                # share of the patch's pixels in Hansen loss
    hansen_main_year: int | None = None      # most common Hansen loss year inside the patch
    mean_slope_deg: float | None = None
    mean_elev_m: float | None = None
    dist_settlement_m: float | None = None
    nearest_settlement: str | None = None
    dist_water_m: float | None = None
    rank_score: float | None = None
    rank: int | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def label_patches(loss_any: np.ndarray, ours: np.ndarray, hansen: np.ndarray, lossyear: np.ndarray | None = None,
                  slope_deg: np.ndarray | None = None, dem: np.ndarray | None = None, pixel_size_m: float = PIXEL_SIZE_M,
                  min_area_ha: float = MIN_PATCH_HA) -> tuple[np.ndarray, list[Patch]]:
    """8-connected patches of loss_any (ours OR Hansen), at least min_area_ha. Returns (label image, patches)."""
    labels, n = ndimage.label(np.asarray(loss_any, dtype=bool), structure=np.ones((3, 3), dtype=int))
    px_ha = pixel_size_m * pixel_size_m / 1e4
    patches: list[Patch] = []
    keep = np.zeros(n + 1, dtype=bool)
    if n == 0:
        return np.zeros_like(labels), patches
    counts = np.bincount(labels.ravel(), minlength=n + 1)
    objects = ndimage.find_objects(labels)
    for idx in range(1, n + 1):
        area = counts[idx] * px_ha
        if area < min_area_ha:
            continue
        keep[idx] = True
        sl = objects[idx - 1]
        m = labels[sl] == idx
        rows, cols = np.nonzero(m)
        o_share = float(np.asarray(ours)[sl][m].mean())
        h_share = float(np.asarray(hansen)[sl][m].mean())
        source = "both" if (o_share > 0 and h_share > 0) else ("ndvi_only" if o_share > 0 else "hansen_only")
        year = None
        if lossyear is not None:
            ly = np.asarray(lossyear)[sl][m]
            ly = ly[ly > 0]
            if ly.size:
                year = 2000 + int(np.bincount(ly.astype(int)).argmax())
        slope = None
        if slope_deg is not None:
            s = np.asarray(slope_deg, dtype="float64")[sl][m]
            s = s[np.isfinite(s)]
            slope = float(s.mean()) if s.size else None
        elev = None
        if dem is not None:
            e = np.asarray(dem, dtype="float64")[sl][m]
            e = e[np.isfinite(e)]
            elev = float(e.mean()) if e.size else None
        patches.append(Patch(patch_id=idx, area_ha=round(area, 3), centroid_row=float(rows.mean() + sl[0].start),
                             centroid_col=float(cols.mean() + sl[1].start), source=source,
                             ndvi_share=round(o_share, 3), hansen_share=round(h_share, 3),
                             hansen_main_year=year, mean_slope_deg=slope, mean_elev_m=elev))
    kept = np.where(keep[labels], labels, 0)
    return kept, patches


def nearest(points_xy: list[tuple[str, float, float]], x: float, y: float) -> tuple[str | None, float | None]:
    """(name, distance) of the nearest named point, in the same planar units as x, y; (None, None) if no points."""
    best = (None, None)
    for name, px, py in points_xy:
        d = hypot(px - x, py - y)
        if best[1] is None or d < best[1]:
            best = (name, d)
    return best


def _norm(values: list[float | None]) -> list[float]:
    """Min-max to 0..1 over the non-missing values; missing -> 0 (counts for nothing, never invents a value)."""
    real = [v for v in values if v is not None]
    if not real:
        return [0.0 for _ in values]
    lo, hi = min(real), max(real)
    return [0.0 if v is None else (1.0 if hi == lo else (v - lo) / (hi - lo)) for v in values]


def rank_patches(patches: list[Patch], weights: dict[str, float] = RANK_WEIGHTS) -> list[Patch]:
    """Rank for ranger visits: weighted sum (0-100) of normalised area, mean slope and closeness to a settlement.

    closeness = max(0, 1 - distance / NEAR_SETTLEMENT_SCALE_M), so a patch 5 km or more away scores 0 on it.
    Ties keep a stable order by larger area. Returns the patches sorted, rank 1 first.
    """
    if not patches:
        return []
    area = _norm([p.area_ha for p in patches])
    slope = _norm([p.mean_slope_deg for p in patches])
    near = [0.0 if p.dist_settlement_m is None else max(0.0, 1.0 - p.dist_settlement_m / NEAR_SETTLEMENT_SCALE_M)
            for p in patches]
    for p, a, s, n in zip(patches, area, slope, near):
        p.rank_score = round(100.0 * (weights["area"] * a + weights["slope"] * s + weights["near_settlement"] * n), 1)
    ordered = sorted(patches, key=lambda p: (-p.rank_score, -p.area_ha))
    for i, p in enumerate(ordered, start=1):
        p.rank = i
    return ordered
