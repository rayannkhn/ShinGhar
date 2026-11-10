"""For each lake: median Sentinel-2 SR image in a date range when the lake held water -> NDWI > 0.2 ->
the connected water patch nearest a seed point -> its centroid, area, and the farthest point from the centroid."""
import sys
sys.path.insert(0, "/home/rayannn/Documents/SAILAB_FYP1_FINAL")
from sailab import earth_engine_client as c
c.initialize()
import ee
CASES = [  # name, seed (lon, lat) read off the images, date range with water, search radius m
 ("Shishper lake (full, before the May 2022 outburst)", (74.568, 36.359), "2022-04-01", "2022-05-05", 3000),
 ("Shishper lake (2019 lake, before its outburst)", (74.568, 36.359), "2019-05-01", "2019-06-20", 3000),
 ("Khurdopin lake (2019)", (75.489, 36.338), "2019-05-01", "2019-08-31", 4000),
 ("Passu glacier lake", (74.880, 36.457), "2025-07-01", "2025-09-15", 1500),
 ("Borith Lake", (74.862, 36.4305), "2025-07-01", "2025-09-15", 1500),
 ("Attabad Lake", (74.86, 36.34), "2025-07-01", "2025-09-15", 9000),
 ("Ghulkin glacier pond", (74.8246, 36.4233), "2025-07-01", "2025-09-15", 1500),
]
for name, seed, start, end, r in CASES:
    p = ee.Geometry.Point(seed); aoi = p.buffer(r)
    col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(aoi).filterDate(start, end)
           .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 40)))
    n = col.size().getInfo()
    if n == 0:
        print(f"{name}: no Sentinel-2 SR image {start}..{end}"); continue
    img = col.median()
    water = img.normalizedDifference(["B3", "B8"]).gt(0.2).selfMask().clip(aoi)
    vec = water.reduceToVectors(geometry=aoi, scale=10, eightConnected=False, maxPixels=1e9, bestEffort=True)
    near = vec.map(lambda f: f.set("d", f.geometry().distance(p, 10), "a", f.geometry().area(10)))
    big = near.filter(ee.Filter.gt("a", 20000)).sort("d").limit(1)
    if big.size().getInfo() == 0:
        print(f"{name}: {n} images, no water patch over 2 ha within {r} m"); continue
    f = ee.Feature(big.first()); g = f.geometry()
    cen = g.centroid(10)
    far = g.coordinates().flatten()
    info = ee.Dictionary({"a": f.get("a"), "d": f.get("d"), "cen": cen.coordinates(),
                          "bounds": g.bounds(10).coordinates(),
                          "inside": g.contains(cen, 10)}).getInfo()
    bx = info["bounds"][0]; lons = [q[0] for q in bx]; lats = [q[1] for q in bx]
    print(f"{name}: {n} images; patch {info['a']/1e4:.1f} ha, {info['d']:.0f} m from seed; centroid {info['cen'][1]:.5f} N {info['cen'][0]:.5f} E "
          f"(inside the lake: {info['inside']}); extent lon {min(lons):.4f}-{max(lons):.4f}, lat {min(lats):.4f}-{max(lats):.4f}")
