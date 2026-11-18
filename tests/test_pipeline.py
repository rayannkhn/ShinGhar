"""Tests for sailab.pipeline.

Earth Engine is replaced by FakeClient, which writes small synthetic GeoTIFFs
georeferenced around the real seeded lake coordinates, so every number below
can be worked out by hand. The database is a real SQLite file.

The last two tests run measure_scene on the ORIGINAL real GeoTIFFs (tests/data/,
byte-identical copies from the proof package) and must reproduce the reported
237.2 ha and 76.51 ha.
"""
import sys
from datetime import date
from math import floor
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform as warp_transform

from sailab import db, pipeline
from sailab.earth_engine_client import EarthEngineError, SceneInfo

DATA = Path(__file__).parent / "data"
WATER = (300, 50)    # (green, nir): NDWI = 250/350 = 0.714 -> water
LAND = (100, 300)    # NDWI = -0.5 -> not water


def write_window(path: Path, lake, *, centre_is_water=True, no_data=None, offset_m=0.0, scl=None, bands=6):
    """30x30 window, 10 m pixels, EPSG:32643, with the lake centre at about row 15, col 15.
    Water: a 5x5 block, rows/cols 13-17 (25 px = 0.25 ha) plus a separate 2x2 pond at rows/cols 1-2
    that is NOT connected to the lake and must not be counted.
    SCL band (6th): 5 (bare) everywhere, 6 (water) on the water pixels, unless `scl` says otherwise."""
    xs, ys = warp_transform("EPSG:4326", "EPSG:32643", [lake["centre_lon"]], [lake["centre_lat"]])
    x0 = floor(xs[0] / 10) * 10 - 150 + offset_m
    y0 = floor(ys[0] / 10) * 10 + 160
    green = np.full((30, 30), LAND[0], np.uint16)
    nir = np.full((30, 30), LAND[1], np.uint16)
    for r0, r1, c0, c1 in [(13, 18, 13, 18), (1, 3, 1, 3)]:
        green[r0:r1, c0:c1], nir[r0:r1, c0:c1] = WATER
    if not centre_is_water:
        green[13:18, 13:18], nir[13:18, 13:18] = LAND
    if no_data == "edge_border":        # zero border like the real exports' clip slivers: harmless
        for edge in (np.s_[0:2, :], np.s_[-2:, :], np.s_[:, 0:2], np.s_[:, -2:]):
            green[edge] = nir[edge] = 0
    elif no_data == "touching_lake":    # one missing pixel directly above the lake block: lake may be cut off
        green[12, 15] = nir[12, 15] = 0
    classes = np.full((30, 30), 5, np.uint16)
    classes[(green == WATER[0]) & (nir == WATER[1])] = 6
    if scl == "snow_touching_lake":        # one snow/ice pixel directly above the lake block
        classes[12, 15] = 11
    elif scl == "cloud_touching_lake":     # one cloud pixel directly above the lake block
        classes[12, 15] = 9
    elif scl == "shadow_touching_lake":    # one cloud-shadow pixel directly below the lake block
        classes[18, 15] = 3
    elif scl == "snow_and_cloud_far_away":  # snow and cloud in the far corner, not touching the lake: harmless
        classes[25:30, 25:30] = 11
        classes[25:30, 20:24] = 9
    elif scl == "snow_majority":           # everything snow except the lake and a 1-pixel bare ring around it
        classes[:, :] = 11
        classes[12:19, 12:19] = 5
        classes[13:18, 13:18] = 6
    stack = np.stack([green, green, green, nir, nir, classes])[:bands]   # B2 B3 B4 B8 B11 SCL
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=30, height=30, count=bands, dtype="uint16",
                       crs="EPSG:32643", transform=from_origin(x0, y0, 10, 10)) as dst:
        dst.write(stack)


def scene(code, day, cloud, n=1):
    return SceneInfo(scene_id=f"{day.replace('-', '')}T0546_{n}_T43SCA", lake_code=code,
                     acquired_at=f"{day}T05:58:58+00:00", tile_cloud_percent=cloud, lake_cloud_percent=cloud)


class FakeClient:
    def __init__(self, scenes_by_code, window_kwargs=None, fail_listing=(), fail_download=(), ignore_since=False):
        self.scenes_by_code = scenes_by_code
        self.ignore_since = ignore_since   # simulate a scene arriving out of date order
        self.window_kwargs = window_kwargs or {}
        self.fail_listing = set(fail_listing)
        self.fail_download = set(fail_download)
        self.listing_calls: list[tuple[str, date]] = []
        self.downloads: list[str] = []

    def find_new_scenes(self, lake, since_date, until_date=None):
        self.listing_calls.append((lake["code"], since_date))
        if lake["code"] in self.fail_listing:
            raise EarthEngineError("Earth Engine memory capacity exceeded.")
        return [s for s in self.scenes_by_code.get(lake["code"], [])
                if self.ignore_since or date.fromisoformat(s.acquired_at[:10]) > since_date]

    def download_scene_window(self, scene_info, lake, out_path):
        if scene_info.scene_id in self.fail_download:
            raise EarthEngineError("download HTTP 429: quota")
        self.downloads.append(scene_info.scene_id)
        write_window(Path(out_path), lake, **self.window_kwargs)


@pytest.fixture
def repo(tmp_path):
    db_path = tmp_path / "sailab_glof.db"
    conn = db.connect(db_path)
    db.seed_lakes(conn)          # the real KRB (id 1) and ATS (id 2) rows
    conn.close()
    return tmp_path, db_path


def run(repo, client, data_subdir="scenes", initial_since_date=date(2026, 10, 1), **kwargs):
    tmp_path, db_path = repo
    return pipeline.run_pipeline_once(db_path, tmp_path / "data" / data_subdir, initial_since_date=initial_since_date,
                                      client=client, **kwargs)


def rows(db_path, sql):
    conn = db.connect(db_path)
    out = [dict(r) for r in conn.execute(sql).fetchall()]
    conn.close()
    return out


# --- the full path -------------------------------------------------------------
def test_one_clear_and_one_cloudy_scene(repo):
    """KRB: a clear scene (lake cloud 10%) and a cloudy one (98.86%). Expected: both recorded as scenes;
    only the clear one downloaded and measured (0.25 ha: the 5x5 block, not the separate pond);
    one risk score, 'insufficient_history' (no past data). Run log closed clean."""
    client = FakeClient({"KRB": [scene("KRB", "2026-10-21", 10.0), scene("KRB", "2026-10-26", 98.86)]})

    result = run(repo, client)

    assert result.errors is None
    assert (result.lakes_processed, result.scenes_recorded, result.scenes_downloaded,
            result.measurements, result.risk_scores) == (8, 2, 1, 1, 1)
    assert client.downloads == ["20261021T0546_1_T43SCA"]
    _, db_path = repo
    scenes = rows(db_path, "SELECT * FROM scene ORDER BY acquired_at")
    assert scenes[0]["file_path"] == "data/scenes/KRB/20261021T0546_1_T43SCA.tif"
    assert scenes[0]["cloud_fraction"] == 10.0
    assert scenes[1]["file_path"] == "not_downloaded/KRB/20261026T0546_1_T43SCA"
    [m] = rows(db_path, "SELECT * FROM measurement")
    assert (m["sensor"], m["status"], m["extent_ha"]) == ("optical", "ok", pytest.approx(0.25))
    [r] = rows(db_path, "SELECT * FROM risk_score")
    assert (r["status"], r["method"], r["baseline_ha"], r["deviation_score"]) == \
        ("insufficient_history", "anomaly_detector", None, None)
    [log_row] = rows(db_path, "SELECT * FROM run_log")
    assert log_row["finished_at"] is not None and log_row["errors"] is None
    assert (log_row["lakes_processed"], log_row["scenes_downloaded"]) == (8, 1)
    assert not pipeline.resume_state_path(db_path).exists()


def test_a_second_run_does_not_duplicate_anything(repo):
    scenes = {"KRB": [scene("KRB", "2026-10-21", 10.0), scene("KRB", "2026-10-26", 98.86)]}
    run(repo, FakeClient(scenes))
    second = FakeClient(scenes)
    result = run(repo, second)

    _, db_path = repo
    assert result.errors is None
    assert second.downloads == []
    assert len(rows(db_path, "SELECT * FROM scene")) == 2
    assert len(rows(db_path, "SELECT * FROM measurement")) == 1
    assert len(rows(db_path, "SELECT * FROM run_log")) == 2
    # second run asks for scenes after the day before the newest stored KRB scene (2026-10-26 - 1 day)
    assert ("KRB", date(2026, 10, 25)) in second.listing_calls
    assert ("ATS", date(2026, 10, 1)) in second.listing_calls     # ATS still has none: initial date


FIVE_JULY_VALUES = [("2023-07-10", 0.10), ("2023-07-25", 0.20), ("2024-07-18", 0.20),
                    ("2025-07-10", 0.20), ("2025-07-25", 0.30)]


def test_seasonal_baseline_is_scored_from_stored_history(repo):
    """Stored July extents 0.10, 0.20 (2023), 0.20 (2024), 0.20, 0.30 (2025); new July 2026 scene: 0.25 ha.
    Baseline = 1.00/5 = 0.20; squared deviations 0.01+0+0+0+0.01 = 0.02; sample variance 0.02/4 = 0.005;
    stdev = 0.0707107; score = (0.25 - 0.20) / 0.0707107 = 0.7071068.
    (5 values from 3 years: passes check F. Before check F this test used 3 values and expected 1.0.)"""
    _, db_path = repo
    conn = db.connect(db_path)
    for day, extent in FIVE_JULY_VALUES:
        sid = db.insert_scene(conn, 1, "sentinel-2", day, 5.0, f"history/{day}.tif")
        db.insert_measurement(conn, sid, 1, "optical", extent, "ok")
    conn.close()

    result = run(repo, FakeClient({"KRB": [scene("KRB", "2026-07-18", 2.0)]}),
                 until_date=date(2026, 11, 8))

    assert result.errors is None
    [r] = rows(db_path, "SELECT * FROM risk_score")
    assert r["status"] == "ok"
    assert r["baseline_ha"] == pytest.approx(0.20)
    assert r["deviation_score"] == pytest.approx(0.7071068)


def test_a_scheduled_run_does_not_redownload_what_the_backfill_already_has(repo):
    """Backfill files go to data/backfill/, scheduled ones to data/scenes/. The scheduled run re-lists the
    newest backfilled scene (it looks from the day before), and must recognise it by scene id."""
    scenes = {"KRB": [scene("KRB", "2026-10-21", 10.0), scene("KRB", "2026-10-26", 98.86)]}
    run(repo, FakeClient(scenes), data_subdir="backfill")
    scheduled = FakeClient(scenes)
    result = run(repo, scheduled, data_subdir="scenes")

    _, db_path = repo
    assert result.errors is None
    assert scheduled.downloads == []
    assert [r["file_path"] for r in rows(db_path, "SELECT file_path FROM scene ORDER BY id")] == \
        ["data/backfill/KRB/20261021T0546_1_T43SCA.tif", "not_downloaded/KRB/20261026T0546_1_T43SCA"]


def test_scoring_never_uses_data_from_after_the_scene(repo):
    """History has the same five July values as the test above plus a July 2027 value of 9.0 ha. Scoring a
    July 2026 scene must ignore 2027: baseline stays 0.20 and the score 0.7071068, as in the test above."""
    _, db_path = repo
    conn = db.connect(db_path)
    for day, extent in FIVE_JULY_VALUES + [("2027-07-18", 9.0)]:
        sid = db.insert_scene(conn, 1, "sentinel-2", day, 5.0, f"history/{day}.tif")
        db.insert_measurement(conn, sid, 1, "optical", extent, "ok")
    conn.close()

    run(repo, FakeClient({"KRB": [scene("KRB", "2026-07-18", 2.0)]}, ignore_since=True))

    risk = rows(db_path, "SELECT * FROM risk_score")
    assert len(risk) == 1
    assert risk[0]["baseline_ha"] == pytest.approx(0.20)
    assert risk[0]["deviation_score"] == pytest.approx(0.7071068)


def test_each_download_is_logged_with_its_real_sha256(repo, caplog):
    import hashlib
    caplog.set_level("INFO", logger="sailab.pipeline")
    run(repo, FakeClient({"KRB": [scene("KRB", "2026-10-21", 10.0)]}))
    tmp_path, _ = repo
    expected = hashlib.sha256((tmp_path / "data/scenes/KRB/20261021T0546_1_T43SCA.tif").read_bytes()).hexdigest()
    assert f"sha256={expected}" in caplog.text


@pytest.mark.parametrize("cloud, downloaded", [(0.0, True), (10.0, True), (10.01, False), (34.7, False), (None, False)])
def test_the_10_percent_lake_cloud_limit(repo, cloud, downloaded):
    """10% is the limit (inclusive, as in choose_sensor). 34.7% is the real Karambar 2026-08-29 scene that
    measured 79.65 ha instead of ~256 ha. None (no valid pixels) falls back to radar, as before."""
    client = FakeClient({"KRB": [scene("KRB", "2026-10-21", cloud)]})
    result = run(repo, client)
    assert result.errors is None
    assert (client.downloads != []) is downloaded
    _, db_path = repo
    assert len(rows(db_path, "SELECT * FROM scene")) == 1          # recorded either way
    assert len(rows(db_path, "SELECT * FROM measurement")) == (1 if downloaded else 0)


# --- insufficient observation: recorded as missing, never as zero ----------------
@pytest.mark.parametrize("window_kwargs, reason", [
    ({"centre_is_water": False}, "not water"),
    ({"no_data": "touching_lake"}, "no-data"),
    ({"offset_m": 5000.0}, "outside"),
])
def test_unusable_windows_are_insufficient_observation(repo, window_kwargs, reason):
    client = FakeClient({"KRB": [scene("KRB", "2026-10-21", 10.0)]}, window_kwargs=window_kwargs)
    result = run(repo, client)

    _, db_path = repo
    assert result.errors is None
    [m] = rows(db_path, "SELECT * FROM measurement")
    assert (m["status"], m["extent_ha"]) == ("insufficient_observation", None)
    assert rows(db_path, "SELECT * FROM risk_score") == []        # nothing to score


def test_a_zero_border_away_from_the_lake_is_harmless(tmp_path):
    """The real exports have a thin zero border; the lake (5x5 block) does not touch it, so the
    measurement stands at 0.25 ha. (The 2x2 pond at rows/cols 1-2 is under the border here, and
    is not connected to the lake either way.)"""
    lake = {"centre_lon": 73.7053229, "centre_lat": 36.880833, "growth_distance_limit_m": 2500.0,
            "boundary_radius_m": 2500.0}
    write_window(tmp_path / "w.tif", lake, no_data="edge_border")
    outcome = pipeline.measure_scene(tmp_path / "w.tif", lake)
    assert (outcome.status, outcome.extent_ha) == ("ok", pytest.approx(0.25))


def test_measure_scene_reason_text(tmp_path):
    lake = {"centre_lon": 73.7053229, "centre_lat": 36.880833, "growth_distance_limit_m": 2500.0,
            "boundary_radius_m": 2500.0}
    write_window(tmp_path / "w.tif", lake, centre_is_water=False)
    outcome = pipeline.measure_scene(tmp_path / "w.tif", lake)
    assert outcome.status == "insufficient_observation" and "not water" in outcome.reason


# --- failures: recorded, visible, resumable ------------------------------------
def test_a_failure_is_recorded_and_the_next_run_resumes_after_the_last_finished_lake(repo):
    _, db_path = repo
    scenes = {"KRB": [scene("KRB", "2026-10-21", 10.0)], "ATS": [scene("ATS", "2026-10-21", 3.8)]}

    failed = run(repo, FakeClient(scenes, fail_listing={"ATS"}))

    assert "memory capacity exceeded" in failed.errors
    [log_row] = rows(db_path, "SELECT * FROM run_log")
    assert log_row["finished_at"] is not None, "a failed run must still be closed"
    assert "memory capacity exceeded" in log_row["errors"]
    assert log_row["lakes_processed"] == 1
    assert len(rows(db_path, "SELECT * FROM measurement")) == 1      # KRB's work was kept
    assert pipeline.load_resume_state(db_path).last_completed_lake_id == 1

    retry = FakeClient(scenes)
    resumed = run(repo, retry)

    assert resumed.errors is None
    assert [code for code, _ in retry.listing_calls] == ["ATS", "SHP", "DKT", "BRT", "PSU", "TRL", "THU"], "KRB was finished and must not be redone"
    assert any("resuming after lake 1" in n for n in resumed.notes)
    assert len(rows(db_path, "SELECT * FROM measurement")) == 2
    assert not pipeline.resume_state_path(db_path).exists()


def test_a_lake_that_keeps_failing_does_not_starve_the_lakes_before_it(repo):
    _, db_path = repo
    scenes = {"KRB": [scene("KRB", "2026-10-21", 10.0)]}
    run(repo, FakeClient(scenes, fail_listing={"ATS"}))                 # day 1: ATS fails
    run(repo, FakeClient(scenes, fail_listing={"ATS"}))                 # day 2: resumed, ATS fails again
    assert not pipeline.resume_state_path(db_path).exists()

    day3 = FakeClient(scenes, fail_listing={"ATS"})
    run(repo, day3)
    assert [code for code, _ in day3.listing_calls] == ["KRB", "ATS"], "day 3 must check KRB again"


def test_a_download_failure_records_the_error_and_no_scene_row(repo):
    _, db_path = repo
    bad = scene("KRB", "2026-10-21", 10.0)
    result = run(repo, FakeClient({"KRB": [bad]}, fail_download={bad.scene_id}))

    assert "HTTP 429" in result.errors
    assert rows(db_path, "SELECT * FROM scene") == []
    [log_row] = rows(db_path, "SELECT * FROM run_log")
    assert "HTTP 429" in log_row["errors"] and log_row["finished_at"] is not None


# --- real data: the original GeoTIFFs must give the originally reported areas -----
def test_real_karambar_original_file_reproduces_237_2_ha():
    lake = {"centre_lon": 73.7053229, "centre_lat": 36.880833, "growth_distance_limit_m": 2500.0}
    outcome = pipeline.measure_scene(DATA / "KarambarLake_Sentinel2_RAW.tif", lake, scl_checks=False)  # 5-band original
    assert outcome.status == "ok"
    assert outcome.extent_ha == pytest.approx(237.22)          # 23,722 px x 100 m2; reported as 237.2
    assert round(outcome.extent_ha, 1) == 237.2


def test_real_atro_sar_original_file_is_flagged_as_cut_off_by_the_window():
    """The original Atro Sar export gives the same 7,651 px (= the reported 76.51 ha), but that region
    touches the window's no-data border: the lake runs off the left edge of the 800 m window (visible in
    the proof package's AtroSar_Measurement_TrueColour_vs_Detected.png). So the pipeline must NOT report
    76.51 ha as the lake's extent; it reports insufficient_observation. This test is a real finding,
    first caught on 2026-11-08 when the edge rule was added, and is kept on purpose."""
    lake = {"centre_lon": 73.65037, "centre_lat": 36.64458, "growth_distance_limit_m": 1200.0}
    outcome = pipeline.measure_scene(DATA / "AtroSar_Sentinel2_RAW.tif", lake, scl_checks=False)  # 5-band original
    assert outcome.status == "insufficient_observation"
    assert outcome.extent_ha is None
    assert "lake region (7651 px) borders 49 no-data pixels" in outcome.reason


# --- sign-in (bug found by the first real backfill, 2026-11-08: run_once never signed in) ------------
def test_the_real_client_is_signed_in_and_a_sign_in_failure_is_recorded(repo, monkeypatch):
    from sailab import earth_engine_client as eec
    calls = []
    monkeypatch.setattr(eec, "initialize", lambda: calls.append("init") or (_ for _ in ()).throw(
        EarthEngineError("Earth Engine sign-in failed for bot@x: invalid_grant")))
    monkeypatch.setattr(eec, "find_new_scenes", lambda *a, **k: pytest.fail("must not list scenes without signing in"))
    tmp_path, db_path = repo

    result = pipeline.run_pipeline_once(db_path, tmp_path / "data", initial_since_date=date(2026, 10, 1))

    assert calls == ["init"]
    assert "invalid_grant" in result.errors
    [log_row] = rows(db_path, "SELECT * FROM run_log")
    assert "invalid_grant" in log_row["errors"] and log_row["finished_at"] is not None


def test_the_real_client_signs_in_before_listing(repo, monkeypatch):
    from sailab import earth_engine_client as eec
    order = []
    monkeypatch.setattr(eec, "initialize", lambda: order.append("init") or "bot@x")
    monkeypatch.setattr(eec, "find_new_scenes", lambda lake, *a, **k: order.append(lake["code"]) or [])
    monkeypatch.setattr(eec, "find_new_s1_scenes", lambda lake, *a, **k: order.append(lake["code"] + " radar") or [])
    tmp_path, db_path = repo

    result = pipeline.run_pipeline_once(db_path, tmp_path / "data", initial_since_date=date(2026, 10, 1))

    assert result.errors is None
    assert order == ["init"] + [x for c in ["KRB", "ATS", "SHP", "DKT", "BRT", "PSU", "TRL", "THU"] for x in (c, c + " radar")]


# --- check F: enough same-month history before scoring ------------------------------------------
@pytest.mark.parametrize("history, expected_status", [
    ([("2023-07-10", 0.2), ("2023-07-25", 0.2), ("2024-07-10", 0.2), ("2025-07-10", 0.2)], "insufficient_history"),
    ([("2025-07-01", 0.2), ("2025-07-05", 0.2), ("2025-07-10", 0.2), ("2025-07-15", 0.2), ("2025-07-20", 0.2)],
     "insufficient_history"),                                   # 5 values but all from one year
    ([("2024-07-10", 0.2), ("2025-07-01", 0.2), ("2025-07-05", 0.25), ("2025-07-10", 0.2), ("2025-07-15", 0.15)],
     "ok"),                                                     # 5 values from 2 years: scored
    ([("2023-06-10", 0.2), ("2023-08-10", 0.2), ("2024-06-10", 0.2), ("2024-08-10", 0.2), ("2025-06-10", 0.2)],
     "insufficient_history"),                                   # plenty of history, but none in July
])
def test_check_F_needs_5_same_month_values_from_2_years(repo, history, expected_status):
    _, db_path = repo
    conn = db.connect(db_path)
    for day, extent in history:
        sid = db.insert_scene(conn, 1, "sentinel-2", day, 5.0, f"history/{day}.tif")
        db.insert_measurement(conn, sid, 1, "optical", extent, "ok")
    conn.close()

    result = run(repo, FakeClient({"KRB": [scene("KRB", "2026-07-18", 2.0)]}, ignore_since=True))

    assert result.errors is None
    [r] = rows(db_path, "SELECT * FROM risk_score")
    assert r["status"] == expected_status
    if expected_status == "insufficient_history":
        assert (r["baseline_ha"], r["deviation_score"]) == (None, None)


def test_a_value_from_the_same_day_is_not_part_of_the_baseline(repo):
    """Two scenes can share a date (e.g. Karambar, 26 Oct 2025). Only values from STRICTLY earlier days may
    form the baseline. Here 4 earlier July values + 1 stored on the scene's own day: with the same-day value
    wrongly included there would be 5 and a score; correctly there are 4, so insufficient_history.
    (Added after mutation P1, '<' changed to '<=', survived the whole suite.)"""
    _, db_path = repo
    conn = db.connect(db_path)
    for day in ("2024-07-10", "2024-07-20", "2025-07-05", "2025-07-15", "2026-07-18"):
        sid = db.insert_scene(conn, 1, "sentinel-2", day, 5.0, f"history/{day}.tif")
        db.insert_measurement(conn, sid, 1, "optical", 0.2, "ok")
    conn.close()

    result = run(repo, FakeClient({"KRB": [scene("KRB", "2026-07-18", 2.0)]}, ignore_since=True))

    assert result.errors is None
    [r] = rows(db_path, "SELECT * FROM risk_score")
    assert r["status"] == "insufficient_history"


# --- checks C and D: snow/ice and cloud touching the lake ------------------------------------------
@pytest.mark.parametrize("scl, expected_status, reason", [
    (None, "ok", None),                                          # clean scene: measured, 0.25 ha
    ("snow_and_cloud_far_away", "ok", None),                     # snow/cloud elsewhere in the window: harmless
    ("cloud_touching_lake", "insufficient_observation", "check D"),
    ("shadow_touching_lake", "insufficient_observation", "check D"),
    ("snow_touching_lake", "insufficient_observation", "check C"),
    ("snow_majority", "insufficient_observation", "of the lake circle is snow/ice"),
])
def test_checks_C_and_D(tmp_path, scl, expected_status, reason):
    """snow_majority: 900 px window, all snow except a 7x7 block (lake + bare ring) = 851 snow px.
    The lake circle (2500 m) covers the whole 300 m window, so 851/900 = 95% snow > 50%; the ring
    keeps snow from touching the lake, so this exercises the 'more than half' rule on its own."""
    lake = {"centre_lon": 73.7053229, "centre_lat": 36.880833, "growth_distance_limit_m": 2500.0,
            "boundary_radius_m": 2500.0}
    write_window(tmp_path / "w.tif", lake, scl=scl)
    outcome = pipeline.measure_scene(tmp_path / "w.tif", lake)
    assert outcome.status == expected_status
    if expected_status == "ok":
        assert outcome.extent_ha == pytest.approx(0.25)
    else:
        assert outcome.extent_ha is None and reason in outcome.reason


def test_a_file_without_the_SCL_band_is_an_error_not_a_silent_skip(tmp_path):
    lake = {"centre_lon": 73.7053229, "centre_lat": 36.880833, "growth_distance_limit_m": 2500.0,
            "boundary_radius_m": 2500.0}
    write_window(tmp_path / "w.tif", lake, bands=5)
    with pytest.raises(ValueError, match="no SCL band"):
        pipeline.measure_scene(tmp_path / "w.tif", lake)


# --- drained lakes and per-lake history start (added 2026-11-10) -----------------------------------
# SHP (Shishper) is seeded with detects_drainage = 1 and history_since 2018-12-31; KRB has neither.
def test_a_drained_lake_is_recorded_as_no_lake_not_as_a_refusal(repo):
    client = FakeClient({"SHP": [scene("SHP", "2026-06-15", 0.0)]}, window_kwargs={"centre_is_water": False})
    result = run(repo, client)
    assert result.errors is None
    [m] = rows(repo[1], "SELECT * FROM measurement")
    assert (m["status"], m["extent_ha"], m["sensor"]) == ("no_lake_detected", None, "optical")   # no invented 0 ha
    assert rows(repo[1], "SELECT * FROM risk_score") == []                                       # nothing scored


def test_a_lake_that_is_there_is_still_measured_normally(repo):
    run(repo, FakeClient({"SHP": [scene("SHP", "2026-06-15", 0.0)]}))
    [m] = rows(repo[1], "SELECT * FROM measurement")
    assert (m["status"], m["extent_ha"]) == ("ok", 0.25)


def test_no_lake_is_never_claimed_in_winter(repo):
    """November to April a frozen or snowed-in lake also shows no water: stays a plain refusal."""
    run(repo, FakeClient({"SHP": [scene("SHP", "2026-01-15", 0.0)]}, window_kwargs={"centre_is_water": False}))
    [m] = rows(repo[1], "SELECT * FROM measurement")
    assert m["status"] == "insufficient_observation"


@pytest.mark.parametrize("scl", ["snow_touching_lake", "cloud_touching_lake", "shadow_touching_lake"])
def test_no_lake_needs_a_clear_snow_free_view_of_the_centre(repo, scl):
    run(repo, FakeClient({"SHP": [scene("SHP", "2026-06-15", 0.0)]}, window_kwargs={"centre_is_water": False, "scl": scl}))
    [m] = rows(repo[1], "SELECT * FROM measurement")
    assert m["status"] == "insufficient_observation"


def test_no_lake_needs_missing_data_to_be_absent_near_the_centre(repo, monkeypatch):
    real = write_window

    def with_gap(path, lake, **kw):
        real(path, lake, **kw)
        with rasterio.open(path, "r+") as dst:
            for band in (2, 4):
                a = dst.read(band); a[14, 14] = 0; dst.write(a, band)
    monkeypatch.setattr(sys.modules[__name__], "write_window", with_gap)
    run(repo, FakeClient({"SHP": [scene("SHP", "2026-06-15", 0.0)]}, window_kwargs={"centre_is_water": False}))
    [m] = rows(repo[1], "SELECT * FROM measurement")
    assert m["status"] == "insufficient_observation"


def test_lakes_without_drainage_detection_never_report_no_lake(repo):
    """KRB (and the silty Passu lake) keep 'centre not water' as a refusal: NDWI can miss their water."""
    run(repo, FakeClient({"KRB": [scene("KRB", "2026-06-15", 0.0)]}, window_kwargs={"centre_is_water": False}),
        initial_since_date=date(2026, 1, 1))
    [m] = rows(repo[1], "SELECT * FROM measurement")
    assert m["status"] == "insufficient_observation"


def test_a_lake_with_its_own_history_start_is_listed_from_that_date(repo):
    client = FakeClient({})
    run(repo, client, initial_since_date=date(2022, 12, 31))
    since = dict(client.listing_calls)
    assert since["SHP"] == date(2018, 12, 31)          # Shishper: from 2019, for its own outbursts
    assert since["KRB"] == since["DKT"] == date(2022, 12, 31)


def test_no_lake_evidence_needs_the_lake_flag_and_the_season(tmp_path):
    lake = {"centre_lon": 74.5650, "centre_lat": 36.3590, "growth_distance_limit_m": 1500.0, "detects_drainage": 1}
    write_window(tmp_path / "w.tif", lake, centre_is_water=False)
    assert pipeline.no_lake_evidence(tmp_path / "w.tif", lake, date(2026, 7, 1)).startswith("no lake: within 150 m")
    assert pipeline.no_lake_evidence(tmp_path / "w.tif", {**lake, "detects_drainage": 0}, date(2026, 7, 1)) is None
    assert pipeline.no_lake_evidence(tmp_path / "w.tif", lake, date(2026, 11, 1)) is None
    write_window(tmp_path / "w5.tif", lake, centre_is_water=False, bands=5)                 # no SCL band
    assert pipeline.no_lake_evidence(tmp_path / "w5.tif", lake, date(2026, 7, 1)) is None


# --- the optional step observer (web app's live check) ------------------------------------------------
def test_step_observer_sees_each_step_in_order_and_cannot_change_or_break_the_run(repo, tmp_path):
    scenes = {"KRB": [scene("KRB", "2026-10-21", 2.0), scene("KRB", "2026-10-26", 98.86)]}
    seen = []

    def observer(kind, data):
        seen.append((kind, data.get("sensor"), (data.get("scene") or {}).get("scene_id")))
        raise RuntimeError("display broke")           # must be logged, never fail the run

    result = run(repo, FakeClient(scenes), lakes=[1], on_step=observer)
    assert result.errors is None and result.scenes_recorded == 2 and result.measurements == 1
    clear, cloudy = (s.scene_id for s in scenes["KRB"])
    assert [k for k, *_ in seen] == ["searched", "cloud_checked", "downloaded", "measured", "scored", "saved",
                                     "cloud_checked", "saved"]
    assert seen[1][2] == clear and seen[6][2] == cloudy

    # the same run without an observer stores exactly the same rows
    other = (tmp_path / "other"); other.mkdir()
    db_path = other / "sailab_glof.db"; conn = db.connect(db_path); db.seed_lakes(conn); conn.close()
    run((other, db_path), FakeClient(scenes), lakes=[1])
    q = "SELECT s.acquired_at, m.status, m.extent_ha FROM scene s LEFT JOIN measurement m ON m.scene_id = s.id ORDER BY 1"
    assert rows(repo[1], q) == rows(db_path, q)
