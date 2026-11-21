"""Build every cached ShinGhar result for the pilot valley (run by hand; the dashboard only reads the outputs).

  .venv/bin/python -m shinghar.build_valley [--skip-forest] [--skip-voice]

Reads   data/shinghar/valley.json, data/shinghar/forest_stack.tif (shinghar/forest_ee.py), sailab_glof.db (read only)
Writes  data/shinghar/: forest_* (shinghar/forest_build.py), lake_paths.geojson, glacier.json, risk.json,
        alerts.json (review state is KEPT for alerts whose text did not change), audio/*.mp3, build_log.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from sailab.terrain import fill_sinks, trace_flood_path_2d
from shinghar import alerts as A
from shinghar import forest_build, glacier
from shinghar import risk as R
from shinghar.forest_ee import read_stack

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data" / "shinghar"
DB = REPO / "sailab_glof.db"
PATH_GRID_M = 30                       # DEM resampled (block mean of 3x3 10 m cells) for the flow-path trace
UPSTREAM_PATH_MAX_M = 1500.0           # a lake counts as "upstream" of a village whose centre is this close to its path
PATH_MAX_HEIGHT_ABOVE_M = 50.0         # ...and no more than this above the path there (a village high on a slope is not on it)
VILLAGE_BUILT_RADIUS_M = 1000.0        # a village's built-up cells (GHSL) = built cells within this distance of its centre
BUILT_MIN_M2 = 500                     # GHSL built surface per 100 m cell counted as "built"
# Which loss patches feed the risk score (decided with the project owner, 2026-11-20): NDVI OR Hansen. In this valley
# Hansen maps 0.93 ha for 2020-2025 while a visual check of the top 8 NDVI patches found 7 real visible changes
# (logs/2026-11-20_shinghar_forest_check/). Shown on screen as "vegetation loss in forest areas", cause unknown.
RISK_LOSS_SOURCES = ("both", "ndvi_only", "hansen_only")


def _utm(epsg, lons, lats):
    from rasterio.warp import transform
    return transform("EPSG:4326", f"EPSG:{epsg}", list(lons), list(lats))


def _lonlat(epsg, xs, ys):
    from rasterio.warp import transform
    return transform(f"EPSG:{epsg}", "EPSG:4326", list(xs), list(ys))


def lake_paths(stack_path, lakes, epsg_hint=None) -> dict:
    """D8 downhill path from each lake centre (SailAb FYP terrain code) on the stack's DEM at PATH_GRID_M."""
    b, meta = read_stack(stack_path)
    tr, epsg = meta["transform"], meta["epsg"]
    k = int(PATH_GRID_M / abs(tr.a))
    dem = b["dem"]
    h, w = (dem.shape[0] // k) * k, (dem.shape[1] // k) * k
    coarse = np.nanmean(dem[:h, :w].reshape(h // k, k, w // k, k), axis=(1, 3))
    coarse = np.where(np.isfinite(coarse), coarse, np.nanmax(coarse))
    filled = fill_sinks(coarse)
    x0, y0 = tr.c, tr.f
    out = {}
    for lake in lakes:
        lx, ly = _utm(epsg, [lake["lon"]], [lake["lat"]])
        r, c = int((y0 - ly[0]) / PATH_GRID_M), int((lx[0] - x0) / PATH_GRID_M)
        if not (0 <= r < filled.shape[0] and 0 <= c < filled.shape[1]):
            out[lake["code"]] = None
            continue
        cells = trace_flood_path_2d(filled, (r, c))
        xy = np.array([[x0 + (cc + 0.5) * PATH_GRID_M, y0 - (rr + 0.5) * PATH_GRID_M] for rr, cc in cells])
        along = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))])
        out[lake["code"]] = {"xy": xy, "along_m": along, "elev": [float(coarse[rr, cc]) for rr, cc in cells], "epsg": epsg}
    return out


def build(skip_forest=False, skip_voice=False) -> dict:
    cfg = json.loads((OUT / "valley.json").read_text())
    stack = OUT / "forest_stack.tif"
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    lakes = [dict(r) for r in conn.execute("SELECT * FROM lake WHERE code IN (%s)" % ",".join("?" * len(cfg["lakes"])),
                                           cfg["lakes"])]
    lake_pts = [{"code": l["code"], "name": l["name"], "lon": l["centre_lon"], "lat": l["centre_lat"]} for l in lakes]
    villages = cfg["villages"]
    log = {"started": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    # Forest layer
    if not skip_forest:
        log["forest"] = forest_build.build(stack, [{"name": v["name"], "lon": v["lon"], "lat": v["lat"]} for v in villages],
                                           lake_pts, OUT, dw_path=OUT / "dw_stack.tif")
    forest = json.loads((OUT / "forest_agreement.json").read_text())
    patches = json.loads((OUT / "forest_patches.geojson").read_text())["features"]

    # Glacier layer
    gl = {}
    for l in lakes:
        t = glacier.summer_trend(glacier.lake_values(conn, l["id"]))
        n_ok = conn.execute("SELECT COUNT(*) FROM measurement WHERE lake_id=? AND status='ok' AND sensor='optical'",
                            (l["id"],)).fetchone()[0]
        n_scenes = conn.execute("SELECT COUNT(*) FROM scene WHERE lake_id=? AND source='sentinel-2'", (l["id"],)).fetchone()[0]
        last = conn.execute("SELECT MAX(s.acquired_at) FROM scene s WHERE s.lake_id=?", (l["id"],)).fetchone()[0]
        gl[l["code"]] = {"name": l["name"], "lon": l["centre_lon"], "lat": l["centre_lat"], "trend": t.__dict__,
                         "anomaly": glacier.latest_anomaly(conn, l["id"]), "optical_ok": n_ok,
                         "optical_scenes": n_scenes, "newest_scene": last}
    (OUT / "glacier.json").write_text(json.dumps(gl, indent=1))

    # Flow paths
    paths = lake_paths(stack, lake_pts)
    feats = []
    for code, p in paths.items():
        if p is None:
            continue
        lons, lats = _lonlat(p["epsg"], p["xy"][:, 0], p["xy"][:, 1])
        feats.append({"type": "Feature", "properties": {"code": code, "length_km": round(float(p["along_m"][-1]) / 1000, 1)},
                      "geometry": {"type": "LineString", "coordinates": [[round(a, 5), round(b, 5)] for a, b in zip(lons, lats)]}})
    (OUT / "lake_paths.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))

    # Risk per village
    epsg = next(p["epsg"] for p in paths.values() if p)
    vx, vy = _utm(epsg, [v["lon"] for v in villages], [v["lat"] for v in villages])
    # Each village's built-up cells (so riverside houses count, not only the cluster's centre point)
    from scipy.spatial import cKDTree
    sb, smeta = read_stack(stack)
    str_ = smeta["transform"]
    rows, cols = np.nonzero(np.nan_to_num(sb["built"], nan=0) >= BUILT_MIN_M2)
    bx = str_.c + (cols + 0.5) * str_.a
    by = str_.f + (rows + 0.5) * str_.e
    belev = sb["dem"][rows, cols]
    del sb
    path_trees = {code: cKDTree(p["xy"]) for code, p in paths.items() if p is not None}
    risk_patches = [f["properties"] for f in patches if f["properties"]["source"] in RISK_LOSS_SOURCES]
    px_, py_ = _utm(epsg, [p["lon"] for p in risk_patches], [p["lat"] for p in risk_patches]) if risk_patches else ([], [])
    results = []
    for v, x, y in zip(villages, vx, vy):
        upstream = []
        mine = np.hypot(bx - x, by - y) <= VILLAGE_BUILT_RADIUS_M
        cx, cy, ce = np.append(bx[mine], x), np.append(by[mine], y), np.append(belev[mine], v["elev_m"])  # + the centre
        for code, tree in path_trees.items():
            p = paths[code]
            d, idx = tree.query(np.column_stack([cx, cy]))
            above = ce - np.asarray(p["elev"])[idx]
            ok = (d <= UPSTREAM_PATH_MAX_M) & (above <= PATH_MAX_HEIGHT_ABOVE_M)
            if ok.any():
                j = int(np.where(ok, d, np.inf).argmin())
                upstream.append({"code": code, "dist_to_path_m": float(d[j]), "along_km": float(p["along_m"][idx[j]]) / 1000,
                                 "height_above_path_m": round(float(above[j])), "built_cells_checked": int(mine.sum())})
        raw, det, na = {}, {}, {}
        if upstream:
            near = min(upstream, key=lambda u: u["dist_to_path_m"])
            raw["flood_path"] = near["dist_to_path_m"]
            ups_sorted = sorted(upstream, key=lambda u: u["along_km"])
            names = [f"{gl[u['code']]['name'].split(' (')[0]} ({u['along_km']:.0f} km upstream)" for u in ups_sorted]
            det["flood_path"] = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
            growths = [(gl[u["code"]]["trend"]["growth_pct_per_yr"], u["code"]) for u in upstream
                       if gl[u["code"]]["trend"]["growth_pct_per_yr"] is not None]
            if growths:
                gv, gc = max(growths)
                raw["lake_growth"] = gv
                det["lake_growth"] = gl[gc]["name"]
            zs = [(gl[u["code"]]["anomaly"]["z"], u["code"]) for u in upstream if gl[u["code"]]["anomaly"]]
            if zs:
                zv, zc = max(zs)
                raw["lake_anomaly"] = zv
                det["lake_anomaly"] = f"{gl[zc]['name']} ({gl[zc]['anomaly']['date']})"
        else:
            why = "not on the downhill path of a monitored lake (" + ", ".join(cfg["lakes"]) + "); unmonitored lakes may exist"
            na = {"lake_growth": why, "lake_anomaly": why, "flood_path": why}
        ups = [p for p, a, b in zip(risk_patches, px_, py_)
               if np.hypot(a - x, b - y) <= R.FOREST_RADIUS_M and (p["mean_elev_m"] or -1) > v["elev_m"]]
        area = sum(p["area_ha"] for p in ups)
        raw["forest_loss_upslope"] = area
        det["forest_loss_upslope"] = f"in {len(ups)} patch{'es' if len(ups) != 1 else ''}"
        if ups:
            raw["loss_slope"] = sum(p["area_ha"] * (p["mean_slope_deg"] or 0) for p in ups) / area
            det["loss_slope"] = "upslope"
        else:
            na["loss_slope"] = "no vegetation loss upslope"
        res = R.fuse(v["name"], raw, det, not_applicable=na)
        results.append({"village": v, "upstream": upstream, "upstream_lakes": [u["code"] for u in upstream],
                        "loss_patch_ids": [p["patch_id"] for p in ups],
                        "score": res.score, "band": res.band, "coverage": res.coverage, "reasons": res.reasons,
                        "missing": res.missing, "not_applicable": res.not_applicable,
                        "components": [c.__dict__ for c in res.components]})
    results.sort(key=lambda r: -r["score"])
    (OUT / "risk.json").write_text(json.dumps({"weights": R.WEIGHTS, "scales": R.SCALES, "bands": R.BANDS,
                                               "forest_radius_m": R.FOREST_RADIUS_M, "upstream_path_max_m": UPSTREAM_PATH_MAX_M,
                                               "path_max_height_above_m": PATH_MAX_HEIGHT_ABOVE_M,
                                               "risk_loss_sources": RISK_LOSS_SOURCES, "results": results},
                                              indent=1, ensure_ascii=False))

    # Risk per forest site: could this loss site matter for people below it?
    all_props = [f["properties"] for f in patches]
    ax, ay = _utm(epsg, [p["lon"] for p in all_props], [p["lat"] for p in all_props]) if all_props else ([], [])
    sites = []
    for p, x, y in zip(all_props, ax, ay):
        lower = [(float(np.hypot(vx_ - x, vy_ - y)), v["name"]) for v, vx_, vy_ in zip(villages, vx, vy)
                 if p["mean_elev_m"] is not None and v["elev_m"] < p["mean_elev_m"]]
        raw, det, na = {"site_area": p["area_ha"], "loss_slope": p["mean_slope_deg"]}, {}, {}
        det["site_area"] = {"both": "our NDVI and Hansen", "ndvi_only": "our NDVI only",
                            "hansen_only": "Hansen only"}[p["source"]]
        det["loss_slope"] = "at this site"
        if lower:
            d, name = min(lower)
            raw["village_below"] = d
            det["village_below"] = name
        else:
            na["village_below"] = "no listed village is lower than this site"
        raw["near_water"] = p["dist_water_m"]
        res = R.fuse(f"site {p['rank']}", raw, det, weights=R.SITE_WEIGHTS, not_applicable=na)
        sites.append({"patch_id": p["patch_id"], "rank": p["rank"], "lat": p["lat"], "lon": p["lon"],
                      "score": res.score, "band": res.band, "coverage": res.coverage, "reasons": res.reasons,
                      "components": [c.__dict__ for c in res.components]})
    sites.sort(key=lambda r: -r["score"])
    (OUT / "site_risk.json").write_text(json.dumps({"weights": R.SITE_WEIGHTS, "scales": {k: R.SCALES[k] for k in R.SITE_WEIGHTS},
                                                    "bands": R.BANDS, "results": sites}, indent=1, ensure_ascii=False))

    # Alerts (watch + high only); keep review state where the text is unchanged
    store = A.AlertStore(OUT / "alerts.json")
    old = store.load()
    newest = max((g["newest_scene"] or "")[:10] for g in gl.values()) or "none stored yet"
    as_of = (f"built {datetime.now(timezone.utc):%Y-%m-%d}; newest lake image {newest}; "
             f"vegetation change summer {forest.get('before_year')} vs {forest.get('after_year')}")
    alerts = {}
    for r in results:
        if r["band"] == "low":
            continue
        v = r["village"]
        aid = f"{v['name'].lower().replace(' ', '-')}-{r['band']}"
        brief = A.briefing_en(f"{v['name']} ({v['area']})", f"{cfg['tehsil']}, {cfg['district']}", r["score"], r["band"],
                              r["coverage"], r["reasons"], as_of)
        al = A.Alert(aid, v["name"], r["band"], r["score"], brief, A.community_message("ur", r["band"], v["name_local"]),
                     A.community_message("ps", r["band"], v["name_local"]))
        prev = old.get(aid)
        if prev and (prev.briefing_en, prev.message_ur, prev.message_ps) == (al.briefing_en, al.message_ur, al.message_ps):
            al.state, al.history = prev.state, prev.history
        for lang in ("ur", "ps"):
            text = getattr(al, f"message_{lang}")
            mp3 = OUT / "audio" / f"{aid}_{lang}.mp3"
            stamp = mp3.with_suffix(".txt")
            if not skip_voice and text and not (mp3.exists() and stamp.exists() and stamp.read_text(encoding="utf-8") == text):
                A.synthesize(text, lang, mp3)
                stamp.write_text(text, encoding="utf-8")
            if mp3.exists() and stamp.exists() and stamp.read_text(encoding="utf-8") == text:
                setattr(al, f"audio_{lang}", f"audio/{mp3.name}")
        alerts[aid] = al
    store.save(alerts)
    log["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log["alerts"] = {a.alert_id: a.state for a in alerts.values()}
    (OUT / "build_log.json").write_text(json.dumps(log, indent=1, default=str))
    return log


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-forest", action="store_true")
    ap.add_argument("--skip-voice", action="store_true")
    a = ap.parse_args()
    print(json.dumps(build(a.skip_forest, a.skip_voice), indent=1, default=str)[:3000])
