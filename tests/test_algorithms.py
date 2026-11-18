"""Run-time water-detection methods (webapp/algorithms.py).

The key test runs the two baseline entries against the pipeline's own functions on the REAL image files stored in the
repository (data/scenes/, data/dem/) and requires identical status and area, so the comparison table can only ever
differ from the stored record because of the method chosen, never because of a second implementation.
"""
from pathlib import Path

import pytest

from sailab import db
from sailab.pipeline import RADAR_SLOPE_LIMIT_DEG, measure_scene
from sailab.radar import load_slope, measure_radar_scene
from webapp import algorithms as A

REPO = Path(__file__).resolve().parent.parent


def lakes():
    """The real seeded lake rows (centres, window radius, growth limit), from a fresh database."""
    import sqlite3
    import tempfile
    c = db.connect(Path(tempfile.mkdtemp()) / "s.db")
    db.seed_lakes(c)
    c.row_factory = sqlite3.Row
    return {r["code"]: dict(r) for r in c.execute("SELECT * FROM lake")}


REAL = sorted((REPO / "data" / "scenes").glob("*/*.tif"))


@pytest.mark.skipif(not REAL, reason="no stored scenes in this checkout")
def test_baseline_entries_reproduce_the_pipeline_on_real_stored_images():
    seeded, checked = lakes(), 0
    for tif in REAL:
        lake = seeded[tif.parent.name]
        if tif.name.startswith("S1"):
            dem = REPO / "data" / "dem" / f"{lake['code']}_dem.tif"
            want = measure_radar_scene(tif, lake, load_slope(dem), RADAR_SLOPE_LIMIT_DEG)
            got = A.run("otsu", tif, lake, dem)
            assert got.threshold == pytest.approx(want.threshold_db) if want.threshold_db is not None else True
        else:
            want, got = measure_scene(tif, lake), A.run("ndwi", tif, lake)
        assert (got.status, got.extent_ha) == (want.status, want.extent_ha), tif.name
        checked += 1
    assert checked == len(REAL)


def test_every_method_runs_and_reports_honestly(tmp_path):
    import importlib.util
    from test_webapp_pages import write_lake_window
    spec = importlib.util.spec_from_file_location("tpr", Path(__file__).parent / "test_pipeline_radar.py")
    tpr = importlib.util.module_from_spec(spec); spec.loader.exec_module(tpr)
    krb = lakes()["KRB"]
    opt, rad, dem = tmp_path / "o.tif", tmp_path / "r.tif", tmp_path / "dem.tif"
    write_lake_window(opt, krb["centre_lon"], krb["centre_lat"])
    tpr.write_radar(rad, krb)
    tpr.write_dem(dem, krb)
    for a in A.OPTICAL:
        r = A.run(a.key, opt, krb)
        assert r.status in ("ok", "insufficient_observation") and r.picture is not None
    for a in A.RADAR:
        r = A.run(a.key, rad, krb, dem)
        assert r.status in ("ok", "insufficient_observation")
        if r.status != "ok":
            assert r.reason                                    # a refusal always says why
    assert {u[0].split(" ")[0] for u in A.UNAVAILABLE} == {"AWEI", "Random", "Geo-foundation"}


def test_bimodality_tells_one_class_from_two():
    import numpy as np
    one = np.random.default_rng(1).normal(-10, 1, 900)
    two = np.concatenate([np.random.default_rng(2).normal(-20, 1, 450), np.random.default_rng(3).normal(-8, 1, 450)])
    assert A._bimodality(one) < 0.75 < A._bimodality(two)
