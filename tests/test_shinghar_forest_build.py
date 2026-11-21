"""shinghar.forest_build on a small synthetic stack: one feature per patch (regression: a diagonally connected patch was
exported as two polygons with the same attributes, and the risk step counted its area twice)."""
import json

import numpy as np
import rasterio
from rasterio.transform import from_origin

from shinghar import forest_build
from shinghar.forest_ee import BANDS


def write_stack(path, n=60):
    b = {k: np.zeros((n, n), dtype=np.int16) for k in BANDS}
    b["worldcover"][:] = 10                       # all forest
    b["treecover2000"][:] = 80
    b["ndvi_before"][:] = 8000
    b["ndvi_after"][:] = 8000
    b["ndvi_after"][10:20, 10:20] = 4000          # 1.0 ha block of NDVI loss ...
    b["ndvi_after"][20:30, 20:30] = 4000          # ... touching a second block only at a corner (8-connected)
    b["dem"][:] = 2500
    b["slope"][:] = 300                           # 30.0 degrees (x10)
    with rasterio.open(path, "w", driver="GTiff", dtype="int16", count=len(BANDS), width=n, height=n,
                       crs="EPSG:32643", transform=from_origin(600000, 3930000, 10, 10), nodata=-32768) as dst:
        dst.write(np.stack([b[k] for k in BANDS]))
        dst.update_tags(before_year=2019, after_year=2025)


def test_one_feature_per_patch_and_area_counted_once(tmp_path):
    stack = tmp_path / "stack.tif"
    write_stack(stack)
    s = forest_build.build(stack, [{"name": "V", "lon": 73.9, "lat": 35.5}], [], tmp_path / "out")
    feats = json.loads((tmp_path / "out" / "forest_patches.geojson").read_text())["features"]
    assert s["patches"] == 1 and len(feats) == 1
    assert feats[0]["geometry"]["type"] == "MultiPolygon" and len(feats[0]["geometry"]["coordinates"]) >= 1
    p = feats[0]["properties"]
    assert p["area_ha"] == 2.0 and p["source"] == "ndvi_only" and p["mean_slope_deg"] == 30.0
    assert s["ours_loss_ha"] == 2.0 and s["hansen_loss_ha"] == 0.0
