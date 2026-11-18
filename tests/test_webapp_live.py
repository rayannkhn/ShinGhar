"""The live-check button: the three outcomes, run through the REAL run_pipeline_once with only Earth Engine
replaced by a fake client (the real Earth Engine runs are recorded in logs/, not here).

Database: the temporary one from conftest.py. Its newest KRB scene is 2026-10-21; ATS has none.
"""
import hashlib
import sqlite3
import threading
from datetime import date
from math import floor

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin
from rasterio.warp import transform as warp_transform

from sailab import pipeline
from sailab.earth_engine_client import EarthEngineError, SceneInfo
from webapp.main import create_app

TODAY = date(2026, 11, 9)


def write_window(path, lake):
    """6-band, 30x30, 10 m window with a 5x5 water block at the lake centre (0.25 ha)."""
    xs, ys = warp_transform("EPSG:4326", "EPSG:32643", [lake["centre_lon"]], [lake["centre_lat"]])
    x0, y0 = floor(xs[0] / 10) * 10 - 150, floor(ys[0] / 10) * 10 + 160
    green = np.full((30, 30), 100, np.uint16); nir = np.full((30, 30), 300, np.uint16)
    green[13:18, 13:18], nir[13:18, 13:18] = 300, 50
    scl = np.where(green == 300, 6, 5).astype(np.uint16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=30, height=30, count=6, dtype="uint16",
                       crs="EPSG:32643", transform=from_origin(x0, y0, 10, 10)) as dst:
        dst.write(np.stack([green, green, green, nir, nir, scl]))


class FakeEarthEngine:
    def __init__(self, scenes=None, fail=None):
        self.scenes, self.fail = scenes or {}, fail

    def find_new_scenes(self, lake, since_date, until_date=None):
        if self.fail:
            raise EarthEngineError(self.fail)
        return [s for s in self.scenes.get(lake["code"], []) if date.fromisoformat(s.acquired_at[:10]) > since_date]

    def download_scene_window(self, scene, lake, out_path):
        write_window(out_path, lake)


def runner_with(fake):
    return lambda db_path, data_dir, since, **kw: pipeline.run_pipeline_once(db_path, data_dir, since, client=fake, **kw)


def fake_esa(scene_id, sensor):
    return {"products": [{"id": "x", "name": f"S2B_MSIL2A_{scene_id.split('_')[0]}_N0511_R048_T43SCA_X.SAFE",
                          "start": None, "online": True}], "seconds": 0.1}


def make(source_db, tmp_path, runner):
    return TestClient(create_app(source_db=source_db, work_dir=tmp_path / "work", today=lambda: TODAY,
                                 repo=tmp_path / "repo", live_runner=runner, esa_lookup=fake_esa))


def check_now(client, lake="KRB"):
    r = client.post("/live/check", data={"lake": lake}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/live"
    client.app.state.live.wait(30)
    return client.get("/live").text


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


NEW_SCENE = SceneInfo("20261107T054600_X_T43SCA", "KRB", "2026-11-07T05:58:58+00:00", 2.0, 2.0)


# --- outcome 1: a new scene found, downloaded and measured -----------------------------------------
def test_new_scene_is_measured_and_written_to_the_working_copy_only(source_db, tmp_path):
    before = sha(source_db)
    client = make(source_db, tmp_path, runner_with(FakeEarthEngine({"KRB": [NEW_SCENE]})))
    html = check_now(client)

    assert "1 new scene recorded for Karambar Lake." in html and "1 downloaded and measured" in html
    assert "ok 0.25" in html                                              # the pipeline's own log line
    assert sha(source_db) == before                                        # published file untouched
    copy = sqlite3.connect(client.app.state.provenance["working_copy"])
    row = copy.execute("SELECT m.status, m.extent_ha FROM measurement m JOIN scene s ON s.id = m.scene_id "
                       "WHERE s.acquired_at LIKE '2026-11-07%'").fetchone()
    assert row == ("ok", 0.25)
    dashboard = client.get("/").text
    assert "live check, this laptop" in dashboard and "+ 1 live check on this laptop" in dashboard
    assert "0.25 ha on 07 Nov 2026" in dashboard                           # the page now reads the new row
    assert client.get("/lakes/KRB/latest-image.png").status_code == 200   # image found in the live folder


# --- outcome 2: no new scene ---------------------------------------------------------------------
def test_no_new_scene_says_so(source_db, tmp_path):
    client = make(source_db, tmp_path, runner_with(FakeEarthEngine({})))
    html = check_now(client)
    assert "No new image for Karambar" in html
    assert client.app.state.live.snapshot()["status"] == "no_new_scene"
    copy = sqlite3.connect(client.app.state.provenance["working_copy"])
    assert copy.execute("SELECT COUNT(*) FROM run_log").fetchone()[0] == 3     # the check itself is logged
    assert copy.execute("SELECT COUNT(*) FROM scene").fetchone()[0] == 5      # nothing added


# --- outcome 3: a real failure inside the pipeline ---------------------------------------------------
def test_a_failure_shows_the_real_error_and_is_recorded(source_db, tmp_path):
    client = make(source_db, tmp_path, runner_with(FakeEarthEngine(fail="Earth Engine memory capacity exceeded.")))
    html = check_now(client)
    assert "The check could not complete." in html
    assert "Earth Engine memory capacity exceeded." in html
    copy = sqlite3.connect(client.app.state.provenance["working_copy"])
    errors = copy.execute("SELECT errors FROM run_log ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert "memory capacity exceeded" in errors
    # neither the success banner nor the no-new-scene banner may appear for a failed check
    assert "new scene recorded for" not in html and "new scenes recorded for" not in html
    assert "No new image for" not in html


def test_a_crash_outside_the_pipeline_is_shown_too(source_db, tmp_path):
    def broken(*_, **__):
        raise OSError("disk full")
    html = check_now(make(source_db, tmp_path, broken))
    assert "The check could not complete." in html and "OSError: disk full" in html


# --- behaviour ---------------------------------------------------------------------------------------
def test_only_one_check_runs_at_a_time_and_the_page_refreshes_meanwhile(source_db, tmp_path):
    release = threading.Event()

    def slow(db_path, data_dir, since, **kw):
        release.wait(10)
        return pipeline.run_pipeline_once(db_path, data_dir, since, client=FakeEarthEngine({}), **kw)

    client = make(source_db, tmp_path, slow)
    live = client.app.state.live
    assert live.start("KRB") is True
    assert live.start("KRB") is False                                           # second click while running: ignored
    page = client.get("/live").text
    assert '<meta http-equiv="refresh" content="3">' in page and "Checking Karambar" in page
    release.set(); live.wait(10)
    assert live.snapshot()["status"] == "no_new_scene"
    assert len(live.history) == 1


def test_idle_page_and_no_refresh(source_db, tmp_path):
    client = make(source_db, tmp_path, runner_with(FakeEarthEngine({})))
    page = client.get("/live").text
    assert "No live check has run since the app started." in page
    assert "http-equiv=\"refresh\"" not in page


def test_restarting_the_app_forgets_live_checks_with_the_old_copy(source_db, tmp_path):
    first = make(source_db, tmp_path, runner_with(FakeEarthEngine({"KRB": [NEW_SCENE]})))
    check_now(first)
    second = make(source_db, tmp_path, runner_with(FakeEarthEngine({})))   # same work dir, fresh copy
    assert second.app.state.live.history == []
    assert "live check, this laptop" not in second.get("/").text
    assert "0.25 ha" not in second.get("/").text


# --- the plain-language line on a failed check ------------------------------------------------------
REAL_NETWORK_ERROR = ("EarthEngineError: Earth Engine sign-in failed for sailab-glof-bot@kaarigar-507118.iam.gserviceaccount.com: "
                      "ConnectionError: HTTPSConnectionPool(host='oauth2.googleapis.com', port=443): Max retries exceeded with url: "
                      "/token (Caused by ProxyError('Unable to connect to proxy', NewConnectionError(\"HTTPSConnection(host='127.0.0.1', "
                      "port=9): Failed to establish a new connection: [Errno 111] Connection refused\")))")   # captured live, 2026-11-08


@pytest.mark.parametrize("error, expected", [
    (REAL_NETWORK_ERROR, "Could not reach Google's servers"),
    ("EarthEngineError: Too many concurrent aggregations.", "usage limit"),
    ("EarthEngineError: download HTTP 429: quota", "usage limit"),
    ("EarthEngineError: sign-in failed: invalid_grant: Invalid JWT Signature.", "refused the sign-in"),
    ("EEException: Permission 'earthengine.thumbnails.create' denied", "denied permission"),
    ("EarthEngineError: no service-account key: EE_SERVICE_ACCOUNT_KEY is unset", "No Earth Engine key"),
    ("OSError: disk full", "The pipeline reported an error."),
])
def test_failure_explanations_are_chosen_from_the_real_error(error, expected):
    from webapp.live import explain_error
    assert expected in explain_error(error)


def test_failed_page_leads_with_the_plain_line_and_keeps_the_exact_error(source_db, tmp_path):
    client = make(source_db, tmp_path, runner_with(FakeEarthEngine(fail="Too many concurrent aggregations.")))
    html = check_now(client)
    assert "usage limit" in html and "It stopped after" in html
    assert "Technical details: the exact error" in html and "Too many concurrent aggregations." in html


# --- the step-by-step walkthrough --------------------------------------------------------------------
def steps_of(client):
    return client.get("/live/state.json").json()["steps"]


def test_a_new_scene_shows_every_step_with_its_real_result(source_db, tmp_path):
    client = make(source_db, tmp_path, runner_with(FakeEarthEngine({"KRB": [NEW_SCENE]})))
    check_now(client)
    steps = steps_of(client)
    keys = [s["key"] for s in steps if not s["replay"]]
    # search -> ESA -> cloud -> download -> detect -> grow -> area -> score -> saved, in that order
    assert keys == ["search_optical", "esa", "cloud", "download", "detect", "grow", "area", "score", "saved"]
    by = {s["key"]: s for s in steps if not s["replay"]}
    assert "1 scene listed by Earth Engine" in by["search_optical"]["result"]
    assert "S2B_MSIL2A_20261107T054600" in by["esa"]["result"]
    assert "2.0 %" in by["cloud"]["formulas"][0] and by["cloud"]["result"].startswith("Clear enough")
    assert any("sha256" in f for f in by["download"]["formulas"])
    assert "(300 − 50) ÷ (300 + 50) = 0.714" in by["detect"]["formulas"][1]
    assert by["area"]["formulas"] == ["25 px × 100 m² = 2,500 m² = 0.25 ha"] and by["area"]["result"] == "Lake area: 0.25 ha"
    assert by["score"]["result"].startswith("Insufficient history")
    assert by["saved"]["result"].startswith("Saved: scene #")
    for s in steps:                                   # every picture a step names is served
        for p in s["pictures"]:
            r = client.get(p["src"])
            assert r.status_code == 200 and r.headers["content-type"] in ("image/png", "image/gif")
    # the optical scene was measured live, so only radar is replayed (and this test lake has no radar)
    replays = [s for s in steps if s["replay"]]
    assert [s["sensor"] for s in replays] == ["radar"] and replays[0]["result"] == "Nothing to replay"


def test_no_new_scene_replays_the_latest_stored_scene_and_writes_nothing(source_db, tmp_path):
    stored = tmp_path / "repo" / "data" / "scenes" / "KRB"
    copy_lake = dict(sqlite3.connect(source_db).execute(
        "SELECT centre_lon, centre_lat FROM lake WHERE code = 'KRB'").fetchone() and
        zip(("centre_lon", "centre_lat"), sqlite3.connect(source_db).execute(
            "SELECT centre_lon, centre_lat FROM lake WHERE code = 'KRB'").fetchone()))
    latest = sqlite3.connect(source_db).execute(
        "SELECT s.file_path FROM scene s JOIN measurement m ON m.scene_id = s.id WHERE m.status = 'ok' "
        "ORDER BY s.acquired_at DESC LIMIT 1").fetchone()[0]
    write_window(tmp_path / "repo" / latest, copy_lake)
    client = make(source_db, tmp_path, runner_with(FakeEarthEngine({})))
    check_now(client)
    copy = sqlite3.connect(client.app.state.provenance["working_copy"])
    assert copy.execute("SELECT COUNT(*) FROM scene").fetchone()[0] == 5          # nothing written
    steps = steps_of(client)
    optical = [s for s in steps if s["replay"] and s["sensor"] == "optical"]
    assert optical[0]["title"].startswith("Replay: the latest stored optical scene")
    assert [s["key"] for s in optical] == ["replay", "esa", "cloud", "download", "detect", "check", "grow", "area",
                                           "score", "saved"]
    # the stored file here is a 0.25 ha test window, not the stored 250 ha: the page says they differ
    assert "Recomputation differs" in [s["title"] for s in optical]
    assert optical[-1]["title"] == "Nothing saved: this was a replay"
    assert all(s["replay"] for s in steps if s["key"] not in ("search_optical", "search_radar"))


def test_unknown_lake_is_refused(source_db, tmp_path):
    client = make(source_db, tmp_path, runner_with(FakeEarthEngine({})))
    assert client.post("/live/check", data={"lake": "XYZ"}).status_code == 400
    assert client.app.state.live.snapshot()["status"] == "idle"


def test_step_pictures_cannot_reach_outside_their_folder(source_db, tmp_path):
    client = make(source_db, tmp_path, runner_with(FakeEarthEngine({})))
    assert client.get("/live/steps/..%2F..%2F/live_checks.json").status_code == 404
    assert client.get("/live/steps/x/../../working.db").status_code == 404


def test_esa_not_answering_is_shown_and_the_check_carries_on(source_db, tmp_path):
    client = TestClient(create_app(source_db=source_db, work_dir=tmp_path / "work", today=lambda: TODAY,
                                   repo=tmp_path / "repo", live_runner=runner_with(FakeEarthEngine({"KRB": [NEW_SCENE]})),
                                   esa_lookup=lambda sid, sensor: {"error": "ConnectionError: timed out", "seconds": 10.0}))
    check_now(client)
    steps = steps_of(client)
    esa = next(s for s in steps if s["key"] == "esa")
    assert esa["tone"] == "warn" and "did not answer (ConnectionError: timed out)" in esa["result"]
    assert any(s["key"] == "area" and not s["replay"] for s in steps)


def test_esa_filters_match_the_real_product_names_found_on_2026_11_13():
    from webapp.walkthrough import esa_filter, esa_lookup
    f = esa_filter("20260921T054639_20260921T055822_T43SCA", "optical")
    assert "contains(Name,'MSIL2A_20260921T054639')" in f and "contains(Name,'_T43SCA_')" in f
    assert "ContentDate/Start gt 2026-09-21T05:44:39.000Z" in f and "ContentDate/Start lt 2026-09-21T05:48:39.000Z" in f
    f = esa_filter("S1D_IW_GRDH_1SDV_20261110T010541_20261110T010606_005398_00A4C0_EE4D", "radar")
    assert "startswith(Name,'S1D_IW_GRDH_1SDV_20261110T010541_20261110T010606_005398_00A4C0_EE4D')" in f
    assert "error" in esa_lookup("not-a-scene-id", "optical")          # never raises


# --- part 2 (2026-11-18): Copernicus links and offline mode -----------------------------------------------
def test_copernicus_links_use_the_browsers_own_parameters():
    from urllib.parse import parse_qs, urlparse
    from webapp.walkthrough import copernicus_url
    u = urlparse(copernicus_url(36.64219, 73.40701, "2026-09-21T05:58:58+00:00", "optical"))
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert u.netloc == "browser.dataspace.copernicus.eu"
    assert q == {"zoom": "14", "lat": "36.64219", "lng": "73.40701", "fromTime": "2026-09-21T00:00:00.000Z",
                 "toTime": "2026-09-21T23:59:59.999Z", "dateMode": "SINGLE", "datasetId": "S2_L2A_CDAS",
                 "layerId": "1_TRUE_COLOR", "cloudCoverage": "100"}
    r = {k: v[0] for k, v in parse_qs(urlparse(copernicus_url(36.6, 73.4, "2026-11-10T01:05:41+00:00", "radar")).query).items()}
    assert r["datasetId"] == "S1_CDAS_IW_VVVH" and r["fromTime"].startswith("2026-11-10") and "layerId" not in r


def test_new_image_steps_link_to_copernicus(source_db, tmp_path):
    client = make(source_db, tmp_path, runner_with(FakeEarthEngine({"KRB": [NEW_SCENE]})))
    check_now(client)
    by = {s["key"]: s for s in steps_of(client) if not s["replay"]}
    for key in ("esa", "download"):
        assert by[key]["links"][0]["href"].startswith("https://browser.dataspace.copernicus.eu/?")
        assert "fromTime=2026-11-07T00" in by[key]["links"][0]["href"]


def _stored_window(source_db, tmp_path):
    lake = dict(zip(("centre_lon", "centre_lat"), sqlite3.connect(source_db).execute(
        "SELECT centre_lon, centre_lat FROM lake WHERE code = 'KRB'").fetchone()))
    latest = sqlite3.connect(source_db).execute(
        "SELECT s.file_path FROM scene s JOIN measurement m ON m.scene_id = s.id WHERE m.status = 'ok' "
        "ORDER BY s.acquired_at DESC LIMIT 1").fetchone()[0]
    write_window(tmp_path / "repo" / latest, lake)


def test_offline_switch_uses_stored_data_and_writes_nothing(source_db, tmp_path):
    _stored_window(source_db, tmp_path)
    log = tmp_path / "repo" / "logs" / "runs" / "2026-11-08T230000Z.log"
    log.parent.mkdir(parents=True)
    log.write_text("2026-11-08 23:00:00,000 INFO run_once: mode: scheduled/normal, data dir: x\n"
                   "2026-11-08 23:00:00,100 INFO sailab.pipeline: run 2 started\n"
                   "2026-11-08 23:00:01,000 INFO sailab.pipeline: signed in to Earth Engine as bot@example.iam.gserviceaccount.com\n"
                   "2026-11-08 23:00:02,000 INFO sailab.pipeline: KRB: 1 scenes listed after 2026-10-20\n"
                   "2026-11-08 23:00:02,001 INFO sailab.pipeline: KRB 20261021T0546_1_T43SCA: already recorded, skipped\n"
                   "2026-11-08 23:00:02,300 INFO sailab.pipeline: KRB: 0 radar scenes listed after 2026-10-20\n")
    called = []
    client = make(source_db, tmp_path, lambda *a, **k: called.append(1))       # the pipeline must not run
    before = sqlite3.connect(client.app.state.provenance["working_copy"]).execute("SELECT COUNT(*) FROM run_log").fetchone()[0]
    r = client.post("/live/check", data={"lake": "KRB", "offline": "1"}, follow_redirects=False)
    assert r.status_code == 303
    client.app.state.live.wait(30)
    st = client.get("/live/state.json").json()
    assert st["status"] == "offline" and called == []
    keys = [s["key"] for s in st["steps"]]
    assert keys[:4] == ["offline", "sign_in", "search_optical", "search_radar"]
    assert all(s["offline"] for s in st["steps"])
    assert "Signed in as bot@example.iam.gserviceaccount.com at 2026-11-08 23:00 UTC" == st["steps"][1]["result"]
    assert st["steps"][2]["result"] == "1 optical scene listed after 2026-10-20 · 20261021T0546_1_T43SCA already stored"
    assert any(s["key"] == "area" for s in st["steps"])                         # measuring still runs, from the file
    copy = sqlite3.connect(client.app.state.provenance["working_copy"])
    assert copy.execute("SELECT COUNT(*) FROM run_log").fetchone()[0] == before  # nothing written
    assert "Offline: Karambar Lake from stored data." in client.get("/live").text


def test_no_connection_switches_to_offline_by_itself(source_db, tmp_path):
    _stored_window(source_db, tmp_path)
    client = make(source_db, tmp_path, lambda *a, **k: (_ for _ in ()).throw(AssertionError("pipeline ran")))
    client.app.state.live.reachable = lambda: "ConnectionError: Failed to establish a new connection"
    check_now(client)
    st = client.get("/live/state.json").json()
    assert st["status"] == "offline" and "switched to offline mode by itself" in st["offline_reason"]
    assert st["steps"][1]["title"] == "Sign in (not available offline)"         # no nightly log in this test repo
    esa = next(s for s in st["steps"] if s["key"] == "esa")                      # nothing saved yet: said plainly
    assert esa["result"] == "Not checked now (offline), and no saved ESA answer for this image yet."
    assert any(s["key"] == "area" for s in st["steps"])                          # and the check still finishes


def test_esa_answers_are_saved_and_used_offline(tmp_path):
    from webapp.walkthrough import CachedESA
    calls = []
    esa = CachedESA(tmp_path / "esa.json", lambda sid, sensor: calls.append(sid) or fake_esa(sid, sensor))
    online = esa("20261107T054600_X_T43SCA", "optical")
    assert calls == ["20261107T054600_X_T43SCA"]
    offline = esa("20261107T054600_X_T43SCA", "optical", offline=True)
    assert calls == ["20261107T054600_X_T43SCA"] and offline["saved"] and offline["products"] == online["products"]
    assert "no saved ESA answer" in esa("other", "optical", offline=True)["error"]


# --- part 3 (2026-11-18): run-time method choice -------------------------------------------------------
def test_chosen_method_adds_a_compare_step_and_changes_nothing_stored(source_db, tmp_path):
    client = make(source_db, tmp_path, runner_with(FakeEarthEngine({"KRB": [NEW_SCENE]})))
    r = client.post("/live/check", data={"lake": "KRB", "algo_optical": "all", "algo_radar": "edge_otsu"},
                    follow_redirects=False)
    assert r.status_code == 303
    client.app.state.live.wait(30)
    steps = steps_of(client)
    cmp_ = next(s for s in steps if s["key"] == "compare" and not s["replay"])
    assert [row[0] for row in cmp_["table"]["rows"]] == ["NDWI > 0.2 (pipeline, stored)", "MNDWI > 0", "NDWI, Otsu cutoff",
                                                         "MNDWI, Otsu cutoff"]
    assert cmp_["table"]["rows"][0][1] == "0.25 ha"
    assert len(cmp_["pictures"]) == 3
    keys = [s["key"] for s in steps if not s["replay"]]
    assert keys.index("area") < keys.index("compare") < keys.index("score")
    copy = sqlite3.connect(client.app.state.provenance["working_copy"])
    assert copy.execute("SELECT extent_ha FROM measurement WHERE scene_id = (SELECT MAX(id) FROM scene)").fetchone()[0] == 0.25


def test_unknown_method_is_refused(source_db, tmp_path):
    client = make(source_db, tmp_path, runner_with(FakeEarthEngine({})))
    assert client.post("/live/check", data={"lake": "KRB", "algo_optical": "otsu"}).status_code == 400     # radar method for optical
    assert client.post("/live/check", data={"lake": "KRB", "algo_radar": "awei"}).status_code == 400
