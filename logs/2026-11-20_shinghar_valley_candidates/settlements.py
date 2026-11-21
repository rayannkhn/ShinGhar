"""ShinGhar Step 1: district of each Upper Swat lake candidate (FAO GAUL 2015 level 2) and the built-up clusters
(villages) in the Upper Swat search area from JRC GHSL P2023A GHS_BUILT_S epoch 2020 (100 m), with tree cover around
each village (ESA WorldCover v200 class 10 within 3 km) and Hansen 2025 v1.13 loss 2001-2025 within 3 km.
Usage: .venv/bin/python settlements.py out.json
"""
import json
import sys

sys.path.insert(0, "/home/rayannn/Documents/ShinGhar")
from sailab import earth_engine_client as c

c.initialize()
import ee

BOX = ee.Geometry.Rectangle([72.15, 35.35, 72.85, 35.85])
LAKES = {"SA": (72.34591, 35.36737), "SB": (72.29714, 35.63584), "SC": (72.23468, 35.60824),
         "SD": (72.45197, 35.43385), "SE": (72.43293, 35.41921), "SF": (72.51194, 35.64618),
         "SG": (72.64245, 35.83381), "SH": (72.79789, 35.62430), "SI": (72.59834, 35.60281),
         "SJ": (72.82686, 35.61287)}
gaul = ee.FeatureCollection("FAO/GAUL/2015/level2")
dem = ee.ImageCollection("COPERNICUS/DEM/GLO30_2024_1").select("DEM").mosaic()
built = ee.Image("JRC/GHSL/P2023A/GHS_BUILT_S/2020").select("built_surface")
wc = ee.ImageCollection("ESA/WorldCover/v200").first()
hansen = ee.Image("UMD/hansen/global_forest_change_2025_v1_13")
area = ee.Image.pixelArea()

out = {"lakes": {}, "settlements": []}
for code, (lon, lat) in LAKES.items():
    p = ee.Geometry.Point([lon, lat])
    f = gaul.filterBounds(p).first()
    out["lakes"][code] = ee.Dictionary({"province": f.get("ADM1_NAME"), "district": f.get("ADM2_NAME")}).getInfo()
    print(code, out["lakes"][code], flush=True)

# Built-up clusters: pixels with >= 500 m2 built surface per 100 m cell, 8-connected, >= 3 cells.
mask = built.gte(500).selfMask()
vecs = mask.reduceToVectors(geometry=BOX, scale=100, geometryType="polygon", eightConnected=True,
                            maxPixels=1e9, bestEffort=True, crs="EPSG:32643")

def info(f):
    g = f.geometry()
    ring = g.buffer(3000)
    s = ee.Image.cat([built.rename("built"), area.updateMask(wc.eq(10)).rename("trees"),
                      area.updateMask(hansen.select("loss").eq(1).And(hansen.select("treecover2000").gte(30))).rename("loss"),
                      area.rename("ring")]).reduceRegion(ee.Reducer.sum(), ring, 30, maxPixels=1e9)
    adm = gaul.filterBounds(g.centroid(10)).first()
    return f.set({"cells": g.area(10).divide(1e4), "cen": g.centroid(10).coordinates(),
                  "elev": dem.reduceRegion(ee.Reducer.median(), g, 30).get("DEM"),
                  "built_ha": ee.Number(built.reduceRegion(ee.Reducer.sum(), g, 100).get("built_surface")).divide(1e4),
                  "trees_3km_ha": ee.Number(s.get("trees")).divide(1e4),
                  "ring_ha": ee.Number(s.get("ring")).divide(1e4),
                  "loss_3km_ha": ee.Number(s.get("loss")).divide(1e4),
                  "district": adm.get("ADM2_NAME")})

big = vecs.map(lambda f: f.set("a", f.geometry().area(10))).filter(ee.Filter.gte("a", 30000)).sort("a", False).limit(25).map(info)
for f in big.getInfo()["features"]:
    p = f["properties"]
    row = {k: p[k] for k in ("built_ha", "cen", "elev", "trees_3km_ha", "ring_ha", "loss_3km_ha", "district")}
    out["settlements"].append(row)
    print(f"built {row['built_ha']:6.2f} ha  {row['cen'][1]:.4f} N {row['cen'][0]:.4f} E  elev {row['elev']:5.0f} m  "
          f"trees<=3km {row['trees_3km_ha']:7.0f} ha ({100*row['trees_3km_ha']/row['ring_ha']:4.1f}%)  "
          f"Hansen loss<=3km {row['loss_3km_ha']:5.2f} ha  {row['district']}", flush=True)
json.dump(out, open(sys.argv[1], "w"), indent=1)
