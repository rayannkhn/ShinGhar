"""Tests for the per-scene page (/scenes/{id}) and the newer-data reload (POST /reload).

The scene page re-measures a stored file with the pipeline's own functions and must say whether that
agrees with what the run stored. Synthetic files: the 5x5 optical water block from test_webapp_pages.py
(25 px = 0.25 ha, NDWI (300-50)/(300+50) = 0.714) and the 6x6 radar lake from test_pipeline_radar.py
(36 px = 0.36 ha). Conftest KRB scenes: 1 ok 240 ha (file absent), 2 too cloudy, 3 refused, 4 ok 250 ha, 5 too cloudy.
"""
import importlib.util
import re

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sailab import db
from webapp import scene_view
from webapp.main import create_app
from test_webapp_pages import TODAY, visible_text, write_lake_window

KRB = {"centre_lon": 73.7053229, "centre_lat": 36.880833, "growth_distance_limit_m": 2500.0, "boundary_radius_m": 1500.0}


def _tpr():
    spec = importlib.util.spec_from_file_location("tpr", "tests/test_pipeline_radar.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def scenes(source_db, tmp_path):
    """Adds: 6 optical ok 0.25 ha WITH its file; 7 radar ok 0.36 ha WITH its file and DEM; 8 radar ok, file absent."""
    repo = tmp_path / "repo"
    conn = db.connect(source_db)
    s6 = db.insert_scene(conn, 1, "sentinel-2", "2026-09-01T05:58:58+00:00", 1.0, "data/scenes/KRB/opt6.tif")
    db.insert_measurement(conn, s6, 1, "optical", 0.25, "ok")
    s7 = db.insert_scene(conn, 1, "sentinel-1", "2026-11-09T13:05:19+00:00", None, "data/scenes/KRB/rad7.tif")
    db.insert_measurement(conn, s7, 1, "radar", 0.36, "ok")
    s8 = db.insert_scene(conn, 1, "sentinel-1", "2026-11-10T01:05:41+00:00", None, "data/scenes/KRB/rad8.tif")
    db.insert_measurement(conn, s8, 1, "radar", 261.14, "ok")
    conn.close()
    write_lake_window(repo / "data/scenes/KRB/opt6.tif", KRB["centre_lon"], KRB["centre_lat"])
    write_lake_window(repo / "data/scenes/KRB/2026-07-12.tif", KRB["centre_lon"], KRB["centre_lat"])   # scene 4, stored 250 ha
    tpr = _tpr()
    tpr.write_radar(repo / "data/scenes/KRB/rad7.tif", KRB)
    tpr.write_dem(repo / "data/dem/KRB_dem.tif", KRB)
    return TestClient(create_app(source_db=source_db, work_dir=tmp_path / "work", today=lambda: TODAY, repo=repo))


def test_optical_scene_is_recomputed_and_agrees_with_the_stored_area(scenes):
    text = visible_text(scenes.get("/scenes/6").text)
    assert "Stored by the run Usable 0.25 ha" in text
    assert "Recomputed now from the stored file Result Usable 0.25 ha (25 water pixels connected to the centre)" in text
    assert "Same as stored" in text and "Differs from stored" not in text
    assert "25 pixels × 10 m × 10 m = 0.25 ha" in text
    assert "At the lake centre 0.714" in text and "median inside the lake 0.714" in text
    assert "0 cloud or shadow pixels, 0 snow/ice pixels" in text


def test_a_recomputation_that_disagrees_is_shown_as_differing(scenes):
    """Scene 4 is stored as 250 ha but its file holds a 0.25 ha lake: the page must not hide that."""
    text = visible_text(scenes.get("/scenes/4").text)
    assert "Differs from stored stored: ok 250.00 ha" in text and "Same as stored" not in text


@pytest.mark.parametrize("kind", ["truecolour", "ndwi", "checks"])
def test_optical_pictures_are_served(scenes, kind):
    r = scenes.get(f"/scenes/6/{kind}.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert f'src="/scenes/6/{kind}.png"' in scenes.get("/scenes/6").text


def test_radar_scene_shows_threshold_and_slope_mask(scenes):
    text = visible_text(scenes.get("/scenes/7").text)
    assert "Recomputed now from the stored file Result Usable 0.36 ha" in text and "Same as stored" in text
    assert "36 pixels × 10 m × 10 m = 0.36 ha" in text
    assert re.search(r"ground steeper than 10° removed: \d[\d,]* pixels", text)
    assert re.search(r"Otsu threshold -?\d+\.\d\d dB", text.replace("−", "-"))
    assert "Risk score not scored (radar)" in text
    for kind in ("vv", "threshold"):
        assert scenes.get(f"/scenes/7/{kind}.png").status_code == 200
    assert scenes.get("/scenes/7/ndwi.png").status_code == 404          # no NDWI for radar


def test_too_cloudy_scene_says_not_downloaded_and_draws_nothing(scenes):
    html = scenes.get("/scenes/2").text
    assert "Not downloaded: 80.0% of the lake was under cloud, above the 10% limit." in visible_text(html)
    assert "<img" not in html.split("</header>", 1)[1].replace('<img src="/static/logo_mark.png"', "")
    assert scenes.get("/scenes/2/truecolour.png").status_code == 404


def test_missing_file_is_reported_not_faked(scenes):
    text = visible_text(scenes.get("/scenes/8").text)
    assert "The file for this scene is not on this machine ( data/scenes/KRB/rad8.tif )" in text
    assert "Recomputed" not in text
    assert scenes.get("/scenes/8/vv.png").status_code == 404


def test_unknown_scene_is_404(scenes):
    assert scenes.get("/scenes/9999").status_code == 404
    assert scenes.get("/scenes/6/nonsense.png").status_code == 404


def test_every_log_row_links_to_its_scene_page(scenes):
    html = scenes.get("/lakes/KRB").text
    log = html[html.index("<h2>Observation log</h2>"):]
    assert sorted(int(i) for i in re.findall(r'href="/scenes/(\d+)"', log)) == [1, 2, 3, 4, 5, 6, 7, 8]
    assert log.count(">Details</a>") == 2                                # the two too-cloudy scenes


def test_scene_page_links_to_its_neighbours(scenes):
    html = scenes.get("/scenes/6").text                                  # between 4 (Jul 2026) and 5 (Oct 2026)
    assert 'href="/scenes/5">‹ Newer scene' in html and 'href="/scenes/4">Older scene ›' in html


def test_ndwi_colours_water_blue_and_land_not():
    rgb = scene_view.ndwi_colours(np.array([[0.7, -0.3, np.nan]]))
    water, land, nodata = rgb[0]
    assert water[2] > water[0] and land[0] >= land[2] and list(nodata) == [0, 0, 0]


# --- newer data banner and reload --------------------------------------------------------------------
BANNER = "Newer data available."


def test_no_banner_while_the_copy_is_current(scenes):
    assert BANNER not in scenes.get("/").text


def test_banner_appears_after_the_source_changes_and_reload_loads_it(scenes, source_db):
    conn = db.connect(source_db)
    db.insert_scene(conn, 2, "sentinel-2", "2026-11-10T05:50:21+00:00", 99.0, "not_downloaded/ATS/x")   # like a git pull
    conn.close()
    page = scenes.get("/").text
    assert BANNER in page and 'action="/reload"' in page
    assert "Scenes recorded 8 " in visible_text(page)                    # still the old copy
    r = scenes.post("/reload", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    page = scenes.get("/").text
    assert BANNER not in page and "Scenes recorded 9 " in visible_text(page)


def test_reload_is_refused_while_a_live_check_runs(scenes):
    scenes.app.state.live.state = {"status": "running"}
    r = scenes.post("/reload")
    assert r.status_code == 409 and "live check is running" in r.json()["detail"]


def test_reload_never_writes_the_source_database(scenes, source_db):
    before = source_db.read_bytes()
    scenes.post("/reload")
    assert source_db.read_bytes() == before


# --- automatic reload (added 2026-11-10) -------------------------------------------------------------
def _pull(source_db):
    """What a git pull does to the file: a new scene row appears."""
    conn = db.connect(source_db)
    db.insert_scene(conn, 2, "sentinel-2", "2026-11-10T05:50:21+00:00", 99.0, "not_downloaded/ATS/y")
    conn.close()


def test_auto_reload_waits_one_check_then_loads_the_new_file(scenes, source_db):
    tick = scenes.app.state.auto_reload_tick
    assert tick() == "current"
    _pull(source_db)
    assert tick() == "waiting"                                           # changed: not copied yet
    assert "Scenes recorded 8 " in visible_text(scenes.get("/").text)
    assert tick() == "reloaded"                                          # unchanged on the second check
    assert "Scenes recorded 9 " in visible_text(scenes.get("/").text)
    assert tick() == "current"
    p = scenes.get("/api/provenance").json()["auto_reload"]
    assert p["last_result"] == "current" and p["last_reload"] is not None


def test_a_file_still_changing_is_not_copied(scenes, source_db):
    tick = scenes.app.state.auto_reload_tick
    _pull(source_db)
    assert tick() == "waiting"
    _pull(source_db)                                                     # changed again before the next check
    assert tick() == "waiting"
    assert tick() == "reloaded"
    assert "Scenes recorded 10 " in visible_text(scenes.get("/").text)


def test_auto_reload_never_copies_a_broken_file(scenes, source_db):
    tick = scenes.app.state.auto_reload_tick
    source_db.write_bytes(b"not a database, e.g. a half-finished pull")
    assert tick() == "waiting"
    assert tick() == "skipped: source is not a valid database"
    text = visible_text(scenes.get("/").text)
    assert "Scenes recorded 8 " in text and BANNER not in text          # old copy kept, no "newer data" offer


def test_auto_reload_waits_for_a_running_live_check(scenes, source_db):
    tick = scenes.app.state.auto_reload_tick
    _pull(source_db)
    scenes.app.state.live.state = {"status": "running"}
    assert tick() == "waiting"
    assert tick() == "skipped: a live check is running"
    scenes.app.state.live.state = {"status": "idle"}
    assert tick() == "reloaded"


def test_auto_reload_reports_a_missing_source(scenes, source_db):
    source_db.unlink()
    assert scenes.app.state.auto_reload_tick().startswith("skipped: source unreadable")


def test_the_watcher_thread_reloads_by_itself(source_db, tmp_path):
    import time
    app = create_app(source_db=source_db, work_dir=tmp_path / "w2", today=lambda: TODAY, repo=tmp_path / "repo",
                     auto_reload_seconds=0.05)
    try:
        first = app.state.provenance["copied_at"], app.state.provenance["source_sha256"]
        _pull(source_db)
        deadline = time.time() + 5
        while app.state.provenance["source_sha256"] == first[1] and time.time() < deadline:
            time.sleep(0.05)
        assert app.state.auto_reload["last_result"] in ("reloaded", "current")
        assert app.state.provenance["source_sha256"] != first[1]
    finally:
        app.state.auto_reload_stop.set()


def test_pages_carry_the_refresh_script_and_previews_do_not(scenes):
    assert 'fetch("/api/provenance"' in scenes.get("/").text
    assert "<script" not in scenes.get("/preview/confirm-advisory").text.lower()


def test_banner_says_it_will_load_automatically(source_db, tmp_path):
    app = create_app(source_db=source_db, work_dir=tmp_path / "w3", today=lambda: TODAY, repo=tmp_path / "repo",
                     auto_reload_seconds=60)
    try:
        _pull(source_db)
        text = visible_text(TestClient(app).get("/").text)
        assert "It will load automatically within about 2 minutes, unless a live check is running." in text
        assert "Load the newer data now" in text
    finally:
        app.state.auto_reload_stop.set()


# --- 'no lake found' on the pages (added 2026-11-10) ---------------------------------------------------
@pytest.fixture
def drained(source_db, tmp_path):
    """SHP (id 3, detects_drainage): a usable 0.25 ha lake in July 2025, then 'no lake' in June 2026 whose file is
    a window with no water at the centre (so the scene page recomputes the same result)."""
    repo = tmp_path / "repo"
    conn = db.connect(source_db)
    s1 = db.insert_scene(conn, 3, "sentinel-2", "2025-07-01T05:58:58+00:00", 0.0, "data/scenes/SHP/full.tif")
    db.insert_measurement(conn, s1, 3, "optical", 0.25, "ok")
    s2 = db.insert_scene(conn, 3, "sentinel-2", "2026-06-15T05:58:58+00:00", 0.0, "data/scenes/SHP/empty.tif")
    db.insert_measurement(conn, s2, 3, "optical", None, "no_lake_detected")
    conn.close()
    shp = (74.5650, 36.3590)
    write_lake_window(repo / "data/scenes/SHP/full.tif", *shp)
    import rasterio
    write_lake_window(repo / "data/scenes/SHP/empty.tif", *shp)
    with rasterio.open(repo / "data/scenes/SHP/empty.tif", "r+") as dst:       # drain it: no water anywhere
        dst.write(np.full((30, 30), 300, np.uint16), 4)
    return TestClient(create_app(source_db=source_db, work_dir=tmp_path / "work", today=lambda: TODAY, repo=repo)), s2


def test_lake_page_says_no_lake_found_and_marks_it(drained):
    client, sid = drained
    html = client.get("/lakes/SHP").text
    text = visible_text(html)
    assert "No lake found in the latest clear optical scene ( 15 Jun 2026 )" in text
    assert "not an alert: this system sends no alerts" in text
    assert html.count('class="no-lake"') == 1                                   # the × on the chart
    assert ">No lake found at the centre</span>" in html                         # the log chip
    assert "1 usable, 0 refused, 1 no lake found, 0 too cloudy" in text


def test_dashboard_flags_the_lake_with_no_lake_found(drained):
    client, _ = drained
    assert "Latest clear optical scene (15 Jun 2026): no lake found" in visible_text(client.get("/").text)


def test_scene_page_recomputes_no_lake_the_same_way(drained):
    client, sid = drained
    text = visible_text(client.get(f"/scenes/{sid}").text)
    assert "Result No lake found" in text and "Same as stored" in text
    assert "no lake: within 150 m of the centre 0% water" in text


def test_lakes_without_no_lake_results_show_no_banner(scenes):
    text = visible_text(scenes.get("/lakes/KRB").text)
    assert "No lake found" not in text and "no lake found" not in text
