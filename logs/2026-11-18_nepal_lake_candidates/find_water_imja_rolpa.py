"""Search areas (broad boxes around the named places) -> water bodies in JRC Global Surface Water v1.4.
Reports each body's max-extent area, its permanent-ish area (occurrence >= 50%), centroid, and elevation."""
import json, sys
sys.path.insert(0, "/home/rayannn/Documents/SAILAB_FYP1_FINAL")
from sailab import earth_engine_client as c
c.initialize()
import ee
gsw = ee.Image("JRC/GSW1_4/GlobalSurfaceWater")
dem = ee.ImageCollection("COPERNICUS/DEM/GLO30").select("DEM").mosaic()
AREAS = {
 "Imja (Khumbu)": (86.88, 27.86, 86.97, 27.93),
 "Tsho Rolpa (Rolwaling)": (86.43, 27.83, 86.51, 27.89),
}
out = {}
for name, box in AREAS.items():
    geom = ee.Geometry.Rectangle(list(box))
    water = gsw.select("max_extent").eq(1).selfMask()
    vecs = water.reduceToVectors(geometry=geom, scale=30, geometryType="polygon", eightConnected=True,
                                 maxPixels=1e9, bestEffort=True)
    def info(f):
        g = f.geometry()
        occ = gsw.select("occurrence").reduceRegion(ee.Reducer.mean(), g, 30, maxPixels=1e8).get("occurrence")
        perm = gsw.select("occurrence").gte(50).multiply(ee.Image.pixelArea()).reduceRegion(ee.Reducer.sum(), g, 30, maxPixels=1e8).get("occurrence")
        el = dem.reduceRegion(ee.Reducer.median(), g, 30, maxPixels=1e8).get("DEM")
        cen = g.centroid(10).coordinates()
        return f.set({"area_ha": g.area(10).divide(1e4), "occ": occ, "perm_ha": ee.Number(perm).divide(1e4), "elev": el, "cen": cen})
    big = vecs.map(lambda f: f.set("a", f.geometry().area(10))).filter(ee.Filter.gt("a", 50000)).sort("a", False).limit(6).map(info)
    rows = big.getInfo()["features"]
    out[name] = [{k: f["properties"][k] for k in ("area_ha", "perm_ha", "occ", "elev", "cen")} for f in rows]
    print(name)
    for r in out[name]:
        print(f"   max {r['area_ha']:8.1f} ha  occ>=50% {r['perm_ha'] or 0:8.1f} ha  mean occ {r['occ'] or 0:5.1f}%  elev {r['elev'] or 0:5.0f} m  centroid {r['cen'][1]:.5f} N {r['cen'][0]:.5f} E")
json.dump(out, open(sys.argv[1], "w"), indent=1)
