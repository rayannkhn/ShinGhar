"""ShinGhar Step 1: candidate pilot valleys in KP (Chitral, Upper Swat).

Per search box (broad boxes around the named places, drawn by hand from the place coordinates):
  - water bodies in JRC Global Surface Water v1.4 (max_extent), > 5 ha, with median elevation (Copernicus GLO-30
    2024 DEM), mean occurrence, centroid, and distance to the nearest GLIMS glacier outline;
  - tree cover: Hansen GFC 2025 v1.13 treecover2000 >= 30 % (ha), ESA WorldCover v200 class 10 'trees' (ha),
    and Hansen loss 2001-2025 inside treecover2000 >= 30 % (ha);
  - built-up surface: JRC GHSL P2023A GHS_BUILT_S, epoch 2020 (ha of built surface).
Usage: .venv/bin/python find_candidates.py out.json
"""
import json
import sys

sys.path.insert(0, "/home/rayannn/Documents/ShinGhar")
from sailab import earth_engine_client as c

c.initialize()
import ee

BOXES = {  # (lon_min, lat_min, lon_max, lat_max)
    "Chitral: Golen": (71.80, 35.90, 72.20, 36.12),
    "Chitral: Reshun-Booni": (71.95, 36.12, 72.35, 36.40),
    "Chitral: Brep (Yarkhun)": (72.45, 36.35, 72.85, 36.60),
    "Chitral: Laspur": (72.35, 35.95, 72.75, 36.25),
    "Upper Swat: Utror-Gabral": (72.15, 35.35, 72.50, 35.70),
    "Upper Swat: Kalam-Ushu-Mahodand": (72.50, 35.45, 72.85, 35.85),
}
MIN_LAKE_M2 = 50_000  # 5 ha

gsw = ee.Image("JRC/GSW1_4/GlobalSurfaceWater")
dem = ee.ImageCollection("COPERNICUS/DEM/GLO30_2024_1").select("DEM").mosaic()
hansen = ee.Image("UMD/hansen/global_forest_change_2025_v1_13")
worldcover = ee.ImageCollection("ESA/WorldCover/v200").first()
built = ee.Image("JRC/GHSL/P2023A/GHS_BUILT_S/2020").select("built_surface")
glims = ee.FeatureCollection("GLIMS/current")
area = ee.Image.pixelArea()

out = {}
for name, box in BOXES.items():
    geom = ee.Geometry.Rectangle(list(box))
    glaciers = glims.filterBounds(geom.buffer(5000))
    water = gsw.select("max_extent").eq(1).selfMask()
    vecs = water.reduceToVectors(geometry=geom, scale=30, geometryType="polygon", eightConnected=True,
                                 maxPixels=1e9, bestEffort=True)

    def info(f):
        g = f.geometry()
        occ = gsw.select("occurrence").reduceRegion(ee.Reducer.mean(), g, 30, maxPixels=1e8).get("occurrence")
        el = dem.reduceRegion(ee.Reducer.median(), g, 30, maxPixels=1e8).get("DEM")
        near = glaciers.filterBounds(g.buffer(3000))
        dist = ee.Algorithms.If(near.size().gt(0), near.geometry().distance(g, 10), -1)
        return f.set({"area_ha": g.area(10).divide(1e4), "occ": occ, "elev": el,
                      "cen": g.centroid(10).coordinates(), "glacier_dist_m": dist})

    lakes = (vecs.map(lambda f: f.set("a", f.geometry().area(10))).filter(ee.Filter.gt("a", MIN_LAKE_M2))
             .sort("a", False).limit(12).map(info))
    rows = [{k: f["properties"][k] for k in ("area_ha", "occ", "elev", "cen", "glacier_dist_m")}
            for f in lakes.getInfo()["features"]]

    stats = ee.Image.cat([
        area.updateMask(hansen.select("treecover2000").gte(30)).rename("hansen_tc30"),
        area.updateMask(worldcover.eq(10)).rename("wc_trees"),
        area.updateMask(hansen.select("treecover2000").gte(30).And(hansen.select("loss").eq(1))).rename("hansen_loss"),
        area.rename("box"),
    ]).reduceRegion(ee.Reducer.sum(), geom, 30, maxPixels=1e10, bestEffort=True)
    b = built.reduceRegion(ee.Reducer.sum(), geom, 100, maxPixels=1e10).get("built_surface")
    g_area = glaciers.filterBounds(geom).geometry().intersection(geom, 100).area(100)
    s = ee.Dictionary(stats).set("built_m2", b).set("glacier_m2", g_area).getInfo()
    out[name] = {"box": box, "lakes": rows, **{k: (v / 1e4 if v is not None else None) for k, v in s.items()}}
    print(f"\n{name}: box {s['box']/1e6:.0f} km2, glacier {s['glacier_m2']/1e6:.0f} km2, "
          f"Hansen tc>=30% {s['hansen_tc30']/1e4:.0f} ha, WorldCover trees {s['wc_trees']/1e4:.0f} ha, "
          f"Hansen loss 2001-25 {s['hansen_loss']/1e4:.1f} ha, built {(s['built_m2'] or 0)/1e4:.1f} ha")
    for r in rows:
        print(f"   max {r['area_ha']:7.1f} ha  occ {r['occ'] or 0:5.1f}%  elev {r['elev'] or 0:5.0f} m  "
              f"glacier {r['glacier_dist_m']:7.0f} m  {r['cen'][1]:.5f} N {r['cen'][0]:.5f} E")
json.dump(out, open(sys.argv[1], "w"), indent=1)
