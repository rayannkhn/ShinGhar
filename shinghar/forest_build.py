"""Build the cached forest layer for a valley from the downloaded stack (shinghar/forest_ee.py).

Outputs (all in out_dir, so the dashboard runs offline):
  forest_patches.geojson  one polygon per loss patch (EPSG:4326), with every attribute of shinghar.forest.Patch
  forest_patches.csv      the same attributes, ranked for ranger visits
  forest_agreement.json   pixel agreement between our NDVI loss and Hansen loss, plus the settings used
  forest_overview.png     hillshade + forest + loss (ours / Hansen / both) + settlements + lakes
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
from scipy import ndimage

from shinghar import forest as F
from shinghar.forest_ee import read_stack

WATER_OCCURRENCE_MIN = 50     # JRC occurrence >= 50 % = mapped surface water (lakes, wide rivers)


def _to_pixels(transform, x: float, y: float) -> tuple[float, float]:
    col, row = ~transform * (x, y)
    return row, col


def _lonlat_to_utm(epsg: int, lons, lats):
    from rasterio.warp import transform
    return transform("EPSG:4326", f"EPSG:{epsg}", list(lons), list(lats))


def _utm_to_lonlat(epsg: int, xs, ys):
    from rasterio.warp import transform
    return transform(f"EPSG:{epsg}", "EPSG:4326", list(xs), list(ys))


def build(stack_path: str | Path, settlements: list[dict], lakes: list[dict], out_dir: str | Path,
          hansen_years: tuple[int, int] = (2020, 2025)) -> dict:
    """settlements: [{"name", "lon", "lat"}]; lakes: [{"code", "name", "lon", "lat"}]. Returns the summary dict."""
    from rasterio import features

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    b, meta = read_stack(stack_path)
    tr, epsg = meta["transform"], meta["epsg"]
    px = abs(tr.a)
    tc = np.nan_to_num(b["treecover2000"], nan=0)
    forest = F.forest_mask(np.nan_to_num(b["worldcover"], nan=0), tc)
    valid = np.isfinite(b["ndvi_before"]) & np.isfinite(b["ndvi_after"])
    ours = F.ndvi_loss(b["ndvi_before"], b["ndvi_after"], forest)
    ly = np.nan_to_num(b["lossyear"], nan=0).astype(int)
    hansen = F.hansen_loss(ly, hansen_years[0], hansen_years[1], tc)
    agree = F.agreement(ours, hansen, valid & forest)
    labels, patches = F.label_patches(ours | hansen, ours, hansen, ly, b["slope"], b["dem"], pixel_size_m=px)

    # distances, in metres on the UTM grid
    sx, sy = _lonlat_to_utm(epsg, [s["lon"] for s in settlements], [s["lat"] for s in settlements])
    s_pts = [(s["name"], x, y) for s, x, y in zip(settlements, sx, sy)]
    water = np.nan_to_num(b["water_occurrence"], nan=0) >= WATER_OCCURRENCE_MIN
    water_dist = ndimage.distance_transform_edt(~water) * px if water.any() else None
    for p in patches:
        x, y = tr * (p.centroid_col + 0.5, p.centroid_row + 0.5)
        p.nearest_settlement, d = F.nearest(s_pts, x, y)
        p.dist_settlement_m = None if d is None else round(d)
        if water_dist is not None:
            p.dist_water_m = round(float(water_dist[int(p.centroid_row), int(p.centroid_col)]))
        lon, lat = _utm_to_lonlat(epsg, [x], [y])
        p.lon, p.lat = round(lon[0], 5), round(lat[0], 5)
        if p.mean_slope_deg is not None:
            p.mean_slope_deg = round(p.mean_slope_deg, 1)
        if p.mean_elev_m is not None:
            p.mean_elev_m = round(p.mean_elev_m)
    ranked = F.rank_patches(patches)

    # GeoJSON polygons (UTM -> lon/lat)
    # One feature per patch: a patch is 8-connected, so its outline can be several polygons (MultiPolygon).
    by_id = {p.patch_id: p for p in ranked}
    polys: dict[int, list] = {}
    for geom, value in features.shapes(labels.astype("int32"), mask=labels > 0, transform=tr, connectivity=8):
        if int(value) not in by_id:
            continue
        rings = []
        for ring in geom["coordinates"]:
            lons, lats = _utm_to_lonlat(epsg, [c[0] for c in ring], [c[1] for c in ring])
            rings.append([[round(a, 6), round(c, 6)] for a, c in zip(lons, lats)])
        polys.setdefault(int(value), []).append(rings)
    feats = [{"type": "Feature", "geometry": {"type": "MultiPolygon", "coordinates": polys[p.patch_id]},
              "properties": p.as_dict()} for p in ranked if p.patch_id in polys]
    (out_dir / "forest_patches.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    with open(out_dir / "forest_patches.csv", "w", newline="") as fh:
        if ranked:
            w = csv.DictWriter(fh, fieldnames=list(ranked[0].as_dict()))
            w.writeheader()
            for p in ranked:
                w.writerow(p.as_dict())

    forest_ha = float(forest.sum()) * px * px / 1e4
    summary = {
        "stack": str(stack_path), "epsg": epsg, "pixel_m": px,
        "before_year": meta.get("before_year"), "after_year": meta.get("after_year"),
        "s2_images_before": meta.get("s2_images_before"), "s2_images_after": meta.get("s2_images_after"),
        "hansen_asset": meta.get("hansen"), "hansen_years": list(hansen_years),
        "settings": {"ndvi_drop_threshold": F.NDVI_DROP_THRESHOLD, "hansen_forest_min_cover": F.HANSEN_FOREST_MIN_COVER,
                     "min_patch_ha": F.MIN_PATCH_HA, "rank_weights": F.RANK_WEIGHTS,
                     "near_settlement_scale_m": F.NEAR_SETTLEMENT_SCALE_M, "water_occurrence_min": WATER_OCCURRENCE_MIN},
        "forest_ha": round(forest_ha, 1),
        "valid_forest_share": round(float((valid & forest).sum()) / max(1, int(forest.sum())), 3),
        "ours_loss_ha": round(agree["ours_px"] * px * px / 1e4, 2),
        "hansen_loss_ha": round(agree["hansen_px"] * px * px / 1e4, 2),
        "both_loss_ha": round(agree["both_px"] * px * px / 1e4, 2),
        "agreement": agree,
        "patches": len(ranked),
        "patches_by_source": {s: sum(1 for p in ranked if p.source == s) for s in ("both", "ndvi_only", "hansen_only")},
    }
    (out_dir / "forest_agreement.json").write_text(json.dumps(summary, indent=1))
    overview_png(b, forest, ours, hansen, tr, epsg, settlements, lakes, out_dir / "forest_overview.png")
    return summary


def overview_png(b, forest, ours, hansen, tr, epsg, settlements, lakes, path, max_px: int = 1600) -> None:
    """Static map from our own data only (works offline): hillshade, forest, loss, settlements, lakes."""
    from PIL import Image, ImageDraw

    dem = np.nan_to_num(b["dem"], nan=np.nanmean(b["dem"]))
    gy, gx = np.gradient(dem, abs(tr.a))
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = np.radians(315), np.radians(45)
    shade = np.clip(np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect), 0, 1)
    rgb = np.stack([shade * 200 + 40] * 3, axis=-1)
    rgb[forest] = rgb[forest] * 0.45 + np.array([30, 120, 50]) * 0.55
    water = np.nan_to_num(b["water_occurrence"], nan=0) >= WATER_OCCURRENCE_MIN
    rgb[water] = [70, 130, 200]
    grow = lambda m: ndimage.binary_dilation(m, iterations=2)  # make 10 m loss visible at overview scale
    rgb[grow(hansen) & ~grow(ours)] = [250, 170, 30]
    rgb[grow(ours) & ~grow(hansen)] = [200, 40, 200]
    rgb[grow(ours) & grow(hansen)] = [220, 30, 30]
    img = Image.fromarray(rgb.clip(0, 255).astype("uint8"))
    h, w = rgb.shape[:2]
    k = min(1.0, max_px / max(h, w))
    img = img.resize((int(w * k), int(h * k)), Image.BILINEAR)
    d = ImageDraw.Draw(img)
    def mark(lon, lat, colour, label, r=5):
        xs, ys = _lonlat_to_utm(epsg, [lon], [lat])
        row, col = _to_pixels(tr, xs[0], ys[0])
        x, y = col * k, row * k
        d.ellipse([x - r, y - r, x + r, y + r], fill=colour, outline=(0, 0, 0))
        d.text((x + r + 2, y - r - 2), label, fill=(0, 0, 0))
    for s in settlements:
        mark(s["lon"], s["lat"], (255, 255, 255), s["name"])
    for l in lakes:
        mark(l["lon"], l["lat"], (40, 90, 220), l["code"], r=6)
    legend = [((30, 120, 50), "forest (WorldCover trees or Hansen >=30%)"), ((220, 30, 30), "loss: both methods"),
              ((200, 40, 200), "loss: our NDVI only"), ((250, 170, 30), "loss: Hansen only"),
              ((70, 130, 200), "surface water (JRC >=50%)")]
    for i, (col, txt) in enumerate(legend):
        d.rectangle([8, 8 + i * 16, 20, 20 + i * 16], fill=col, outline=(0, 0, 0))
        d.text((26, 8 + i * 16), txt, fill=(0, 0, 0))
    img.save(path)
