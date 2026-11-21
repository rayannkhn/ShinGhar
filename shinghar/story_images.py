"""Images for the ShinGhar story page, rendered once and cached (the page then works offline).

  rgb_stack.tif         Sentinel-2 SR harmonized, SCL-masked (clouds, shadows, snow removed) median of Jun-Sep, true colour
                        (B4, B3, B2) for the "before" and "after" summers, on the SAME 10 m grid as forest_stack.tif
  story/valley_<year>.jpg   the whole valley box, downsampled for the screen
  story/site_<rank>_<year>.jpg  before/after chips around the top forest sites, with the site outline
  story/lake_<code>_<year>.jpg  a lake from the very scene the pipeline measured, with the measured outline
  story/story_images.json   pixel positions for the labels, image sizes and every input used (traceable)

One fixed brightness stretch is used for both years, so a change in colour is a change on the ground, not in the display.
"""
from __future__ import annotations

import json
import sqlite3
from math import floor
from pathlib import Path

import numpy as np

from shinghar import forest_ee as E

RGB_BANDS = ("r_before", "g_before", "b_before", "r_after", "g_after", "b_after")
VALLEY_MAX_PX = 2400
CHIP_M = 1200          # forest-site chip: 1.2 km x 1.2 km
CHIP_PX = 720


def fetch_rgb(bbox, before_year: int, after_year: int, out_path, workers: int = 6, log=print) -> dict:
    import ee

    E.c.initialize()
    region = ee.Geometry.Rectangle(list(bbox))

    def rgb(year):
        col = (ee.ImageCollection(E.c.COLLECTION).filterBounds(region).filterDate(f"{year}-06-01", f"{year}-10-01"))

        def prep(img):
            scl = img.select("SCL")
            keep = scl.eq(E.SCL_KEEP[0])
            for k in E.SCL_KEEP[1:]:
                keep = keep.Or(scl.eq(k))
            return img.select(["B4", "B3", "B2"]).updateMask(keep)

        return col.map(prep).median(), col.size()

    b, nb = rgb(before_year)
    a, na = rgb(after_year)
    img = ee.Image.cat([b.rename(list(RGB_BANDS[:3])), a.rename(list(RGB_BANDS[3:]))]).toInt16().unmask(-32768)
    counts = ee.Dictionary({"before": nb, "after": na}).getInfo()
    stack, epsg, x0, y_top = E._download_tiles(img, RGB_BANDS, bbox, workers)
    E._write(out_path, stack, RGB_BANDS, epsg, x0, y_top,
             dict(bbox=str(bbox), before_year=before_year, after_year=after_year,
                  s2_images_before=counts["before"], s2_images_after=counts["after"],
                  what="Sentinel-2 SR harmonized B4,B3,B2 median Jun-Sep, SCL classes 4-7 kept"))
    log(f"rgb stack written: {out_path} images {counts}")
    return counts


def read_rgb(path):
    import rasterio

    with rasterio.open(path) as src:
        raw = src.read()
        meta = {"transform": src.transform, "epsg": src.crs.to_epsg(), **src.tags()}
    out = raw.astype("float32")
    out[raw == -32768] = np.nan
    return out, meta


def stretch_limits(arr: np.ndarray) -> tuple[float, float]:
    """One stretch for both years: 1st and 90th percentile of all valid values (snow and bright rock saturate to white,
    so forest and bare ground stay readable)."""
    v = arr[np.isfinite(arr)]
    return float(np.percentile(v, 1)), float(np.percentile(v, 90))


def to_uint8(rgb: np.ndarray, lo: float, hi: float, gamma: float = 0.85) -> np.ndarray:
    """rgb: (3, h, w) reflectance x10000 -> (h, w, 3) uint8 with a fixed linear stretch + gamma. No data = dark grey."""
    t = np.clip((rgb - lo) / (hi - lo), 0, 1) ** gamma
    img = np.transpose(t, (1, 2, 0)) * 255
    img[~np.isfinite(img)] = 40
    return img.astype("uint8")


def _utm(epsg, lons, lats):
    from rasterio.warp import transform
    return transform("EPSG:4326", f"EPSG:{epsg}", list(lons), list(lats))


def render_valley(rgb, meta, lo, hi, out_dir: Path, valley: dict, lakes: list[dict], patches: list[dict]) -> dict:
    from PIL import Image

    tr, epsg = meta["transform"], meta["epsg"]
    h, w = rgb.shape[1:]
    k = min(1.0, VALLEY_MAX_PX / max(h, w))
    size = (int(w * k), int(h * k))
    out = {}
    for key, sl in (("before", slice(0, 3)), ("after", slice(3, 6))):
        year = meta[f"{key}_year"]
        Image.fromarray(to_uint8(rgb[sl], lo, hi)).resize(size, Image.LANCZOS).save(out_dir / f"valley_{year}.jpg", quality=88)
        out[key] = f"valley_{year}.jpg"

    def place(lon, lat):
        x, y = _utm(epsg, [lon], [lat])
        col, row = ~tr @ (x[0], y[0])
        return round(col * k, 1), round(row * k, 1)

    return {"files": out, "width": size[0], "height": size[1], "scale_m_per_px": round(abs(tr.a) / k, 2),
            "lakes": [{"code": l["code"], "name": l["name"], "xy": place(l["lon"], l["lat"])} for l in lakes],
            "villages": [{"name": v["name"], "xy": place(v["lon"], v["lat"])} for v in valley["villages"]],
            "sites": [{"rank": p["rank"], "area_ha": p["area_ha"], "xy": place(p["lon"], p["lat"])} for p in patches]}


def _outline(mask: np.ndarray) -> np.ndarray:
    from scipy import ndimage
    return mask & ~ndimage.binary_erosion(mask)


def render_sites(rgb, meta, lo, hi, out_dir: Path, features: list[dict], n: int = 3) -> list[dict]:
    """Before/after chips around the top n sites (by rank), with the site outline drawn on both years."""
    from PIL import Image
    from rasterio import features as rf

    tr, epsg = meta["transform"], meta["epsg"]
    half = int(CHIP_M / abs(tr.a) / 2)
    out = []
    for f in sorted(features, key=lambda f: f["properties"]["rank"])[:n]:
        p = f["properties"]
        x, y = _utm(epsg, [p["lon"]], [p["lat"]])
        col, row = ~tr @ (x[0], y[0])
        r0, c0 = int(row) - half, int(col) - half
        from rasterio.windows import Window, transform as win_transform
        win_tr = win_transform(Window(c0, r0, 2 * half, 2 * half), tr)
        from rasterio.warp import transform_geom
        geom = transform_geom("EPSG:4326", f"EPSG:{epsg}", f["geometry"])
        mask = rf.rasterize([(geom, 1)], out_shape=(2 * half, 2 * half), transform=win_tr, dtype="uint8").astype(bool)
        # outline drawn at screen resolution (1 chip pixel = CHIP_PX / (2 * half) screen pixels)
        up = CHIP_PX // (2 * half) or 1
        from scipy import ndimage
        edge = ndimage.binary_dilation(_outline(np.kron(mask, np.ones((up, up), dtype=bool))), iterations=1)
        files = {}
        for key, sl in (("before", slice(0, 3)), ("after", slice(3, 6))):
            chip = to_uint8(rgb[sl, r0:r0 + 2 * half, c0:c0 + 2 * half], lo, hi)
            big = np.array(Image.fromarray(chip).resize((2 * half * up, 2 * half * up), Image.BICUBIC))
            big[edge] = (255, 230, 0)
            name = f"site_{p['rank']}_{meta[f'{key}_year']}.jpg"
            Image.fromarray(big).resize((CHIP_PX, CHIP_PX), Image.NEAREST).save(out_dir / name, quality=90)
            files[key] = name
        out.append({"rank": p["rank"], "patch_id": p["patch_id"], "files": files, "chip_m": CHIP_M})
    return out


def lake_region(path, lake_row) -> tuple[np.ndarray, dict]:
    """The pipeline's own water region for one stored scene (same functions as sailab.pipeline.measure_scene)."""
    import rasterio
    from sailab import measurement as M
    from sailab.pipeline import GREEN_BAND_INDEX, NIR_BAND_INDEX, lake_centre_in_pixels

    with rasterio.open(path) as src:
        green = src.read(GREEN_BAND_INDEX).astype(float)
        nir = src.read(NIR_BAND_INDEX).astype(float)
        rgb = np.stack([src.read(i).astype(float) for i in (3, 2, 1)])   # B4, B3, B2
        px = float(src.res[0])
    rows, cols = green.shape
    row_f, col_f = lake_centre_in_pixels(path, lake_row["centre_lon"], lake_row["centre_lat"])
    is_water = {M.Pixel(r, c): M.classify_water_ndwi(green[r, c], nir[r, c], 0.2) for r in range(rows) for c in range(cols)}
    region = M.region_grow(is_water, M.Pixel(floor(row_f), floor(col_f)), (row_f * px, col_f * px), px,
                           float(lake_row["growth_distance_limit_m"]))
    mask = np.zeros((rows, cols), dtype=bool)
    for p in region:
        mask[p.row, p.col] = True
    return mask, {"rgb": rgb, "area_ha": round(M.extent_area_m2(region, px) / 1e4, 2), "row": row_f, "col": col_f}


def pick_lake_scene(conn, lake_id: int, year: int):
    """A clear summer (Jul-Sep) scene the pipeline measured as 'ok', closest to that summer's median area."""
    rows = conn.execute(
        "SELECT s.file_path, s.acquired_at, m.extent_ha FROM measurement m JOIN scene s ON s.id = m.scene_id "
        "WHERE m.lake_id = ? AND m.status = 'ok' AND m.sensor = 'optical' AND substr(s.acquired_at, 1, 4) = ? "
        "AND substr(s.acquired_at, 6, 2) IN ('07', '08', '09') ORDER BY s.acquired_at", (lake_id, str(year))).fetchall()
    if not rows:
        return None
    med = float(np.median([r[2] for r in rows]))
    return min(rows, key=lambda r: abs(r[2] - med))


def render_lake(conn, repo: Path, lake_row, years, out_dir: Path, lo: float, hi: float) -> dict:
    from PIL import Image

    out = {"code": lake_row["code"], "years": {}}
    for year in years:
        pick = pick_lake_scene(conn, lake_row["id"], year)
        if pick is None:
            out["years"][str(year)] = None
            continue
        path = repo / pick[0]
        mask, info = lake_region(path, lake_row)
        crop = 60   # +-600 m around the lake centre
        r, c = int(info["row"]), int(info["col"])
        sl = (slice(max(0, r - crop), r + crop), slice(max(0, c - crop), c + crop))
        chip = to_uint8(info["rgb"][:, sl[0], sl[1]], lo, hi)
        up = 6
        big = np.array(Image.fromarray(chip).resize((chip.shape[1] * up, chip.shape[0] * up), Image.BICUBIC))
        edge = _outline(np.kron(mask[sl], np.ones((up, up), dtype=bool)))
        from scipy import ndimage
        big[ndimage.binary_dilation(edge, iterations=1)] = (255, 230, 0)
        name = f"lake_{lake_row['code']}_{year}.jpg"
        Image.fromarray(big).save(out_dir / name, quality=90)
        out["years"][str(year)] = {"file": name, "scene": Path(pick[0]).name, "date": pick[1][:10],
                                   "db_area_ha": round(pick[2], 2), "outline_area_ha": info["area_ha"]}
    return out


def build(repo: Path, out_dir: Path, lake_code: str = "KLN", n_sites: int = 3) -> dict:
    data = repo / "data" / "shinghar"
    out_dir.mkdir(parents=True, exist_ok=True)
    rgb, meta = read_rgb(data / "rgb_stack.tif")
    lo, hi = stretch_limits(rgb)
    valley = json.loads((data / "valley.json").read_text())
    feats = json.loads((data / "forest_patches.geojson").read_text())["features"]
    conn = sqlite3.connect(f"file:{repo / 'sailab_glof.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    lakes = [dict(r) for r in conn.execute("SELECT * FROM lake WHERE code IN (%s)" % ",".join("?" * len(valley["lakes"])),
                                           valley["lakes"])]
    lake_pts = [{"code": l["code"], "name": l["name"], "lon": l["centre_lon"], "lat": l["centre_lat"]} for l in lakes]
    summary = {
        "source": {"rgb": "Sentinel-2 SR harmonized, Jun-Sep median, clouds/shadows/snow masked (SCL)",
                   "before_year": meta["before_year"], "after_year": meta["after_year"],
                   "images_before": meta.get("s2_images_before"), "images_after": meta.get("s2_images_after"),
                   "stretch": [round(lo), round(hi)]},
        "valley": render_valley(rgb, meta, lo, hi, out_dir, valley, lake_pts,
                                [f["properties"] for f in feats]),
        "sites": render_sites(rgb, meta, lo, hi, out_dir, feats, n_sites),
        "lake": render_lake(conn, repo, next(l for l in lakes if l["code"] == lake_code),
                            (int(meta["before_year"]), int(meta["after_year"])), out_dir, lo, hi),
    }
    (out_dir / "story_images.json").write_text(json.dumps(summary, indent=1))
    return summary


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fetch", action="store_true", help="download rgb_stack.tif from Earth Engine first")
    a = ap.parse_args()
    REPO = Path(__file__).resolve().parent.parent
    if a.fetch:
        cfg = json.loads((REPO / "data" / "shinghar" / "valley.json").read_text())
        fetch_rgb(tuple(cfg["bbox"]), 2019, 2025, REPO / "data" / "shinghar" / "rgb_stack.tif")
    print(json.dumps(build(REPO, REPO / "data" / "shinghar" / "story"), indent=1)[:3000])
