"""The dashboard's note on the latest nightly run (webapp/run_note.py).

Log lines below are copied in the exact format of the real nightly logs in logs/runs/ (2026-11-10T224252Z.log,
run 12, and 2026-11-13T230615Z.log, run 15); only run numbers and scene ids are the test's own.
"""
import sqlite3

from fastapi.testclient import TestClient

from sailab import db
from webapp.main import create_app
from webapp.run_note import build, parse_log

HEAD = ("2026-11-14 23:06:15,001 INFO run_once: mode: scheduled/normal, data dir: /home/runner/work/x/data/scenes\n"
        "2026-11-14 23:06:15,200 INFO sailab.pipeline: run {run} started\n"
        "2026-11-14 23:06:16,000 INFO sailab.pipeline: signed in to Earth Engine as bot@example.iam.gserviceaccount.com\n")


def write_log(repo, name, run, body):
    path = repo / "logs" / "runs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEAD.format(run=run) + body)
    return path


def nightly_run(conn, errors=None, add=None):
    """A run_log row with fixed times; scenes added by `add` are stamped inside its window, like a real run's."""
    before = conn.execute("SELECT COALESCE(MAX(id), 0) FROM scene").fetchone()[0]
    run = db.start_run_log(conn, "2030-01-01T23:06:15+00:00")
    if add:
        add(conn)
        conn.execute("UPDATE scene SET downloaded_at = '2030-01-01T23:06:20+00:00' WHERE id > ?", (before,))
    db.finish_run_log(conn, run, 6, 0, errors, finished_at="2030-01-01T23:06:25+00:00")
    conn.commit()
    return run


def opened(source_db):
    conn = sqlite3.connect(source_db)
    conn.row_factory = sqlite3.Row
    return conn


def test_nothing_new_says_what_earth_engine_listed(source_db, tmp_path):
    conn = opened(source_db)
    run = nightly_run(conn)
    write_log(tmp_path, "2026-11-14T230615Z.log", run,
              "2026-11-14 23:06:17,000 INFO sailab.pipeline: KRB: 1 scenes listed after 2026-10-20\n"
              "2026-11-14 23:06:17,001 INFO sailab.pipeline: KRB 20261021T0546_1_T43SCA: already recorded, skipped\n"
              "2026-11-14 23:06:17,300 INFO sailab.pipeline: KRB: 0 radar scenes listed after 2026-10-20\n")
    n = build(conn, tmp_path)
    assert n["run_id"] == run and n["scheduled"] and n["headline"] == "Completed, nothing new"
    assert n["summary"].startswith("Earth Engine was checked for every lake.")
    krb = next(l for l in n["lakes"] if l["code"] == "KRB")["items"][0]["text"]
    assert krb.startswith("nothing new · optical: Earth Engine listed 1 after 20 Oct, already stored")
    assert "radar: Earth Engine had no image after 20 Oct" in krb
    ats = next(l for l in n["lakes"] if l["code"] == "ATS")["items"][0]["text"]
    assert ats == "not checked in this run"                    # ATS has no line in this log


def test_new_images_are_described_one_by_one_with_reason_and_score(source_db, tmp_path):
    conn = opened(source_db)

    def add(c):
        cloudy = db.insert_scene(c, 1, "sentinel-2", "2026-11-14T05:58:58+00:00", 92.1, "not_downloaded/KRB/20261114T0546_9_T43SCA")
        clear = db.insert_scene(c, 1, "sentinel-2", "2026-11-15T05:58:58+00:00", 2.0, "data/scenes/KRB/20261115T0546_9_T43SCA.tif")
        m = db.insert_measurement(c, clear, 1, "optical", 251.0, "ok")
        db.insert_risk_score(c, 1, m, "anomaly_detector", "ok", 245.0, 2.4)
        refused = db.insert_scene(c, 2, "sentinel-2", "2026-11-15T05:58:58+00:00", 1.0, "data/scenes/ATS/20261115T0546_9_T43SCA.tif")
        db.insert_measurement(c, refused, 2, "optical", None, "insufficient_observation")
        radar = db.insert_scene(c, 2, "sentinel-1", "2026-11-15T01:05:41+00:00", None, "data/scenes/ATS/S1D_X_EE4D.tif")
        db.insert_measurement(c, radar, 2, "radar", 98.05, "ok")

    run = nightly_run(conn, add=add)
    write_log(tmp_path, "2026-11-14T230615Z.log", run,
              "2026-11-14 23:06:18,000 INFO sailab.pipeline: ATS 20261115T0546_9_T43SCA: insufficient_observation None "
              "(check C: 64% of the lake circle is snow/ice (limit 50%))\n"
              "2026-11-14 23:06:19,000 INFO sailab.pipeline: ATS S1D_X_EE4D: radar ok 98.05 (9805 px below -15.05 dB connected to the centre)\n")
    n = build(conn, tmp_path)
    assert n["headline"] == "Completed: 4 new images, 2 measured" and n["tone"] == "ok" and n["summary"] is None
    krb = [i["text"] for i in next(l for l in n["lakes"] if l["code"] == "KRB")["items"]]
    assert krb == ["new optical image (14 Nov): too cloudy over the lake (92%), recorded but not measured",
                   "new optical image (15 Nov): measured 251.00 ha, score +2.40 (2 or more spreads from the usual November area)"]
    ats = [i["text"] for i in next(l for l in n["lakes"] if l["code"] == "ATS")["items"]]
    assert ats == ["new optical image (15 Nov): not measured (check C: 64% of the lake circle is snow/ice (limit 50%))",
                   "new radar image (15 Nov): measured 98.05 ha (radar is not risk-scored yet)"]


def test_a_failed_run_leads_with_the_plain_reason(source_db, tmp_path):
    conn = opened(source_db)
    err = "EarthEngineError: download HTTP 503: Earth Engine memory capacity exceeded.\nTraceback ..."
    run = nightly_run(conn, errors=err)
    write_log(tmp_path, "2026-11-14T230615Z.log", run,
              f"2026-11-14 23:06:30,000 ERROR sailab.pipeline: run {run} failed: {err.splitlines()[0]}\n")
    from webapp.live import explain_error
    n = build(conn, tmp_path, explain_error)
    assert n["tone"] == "error" and n["headline"] == "The run stopped with an error"
    assert n["error_line"] == "EarthEngineError: download HTTP 503: Earth Engine memory capacity exceeded."
    assert "usage limit" in n["error_plain"]


def test_a_log_whose_run_is_not_in_this_database_yet_is_skipped(source_db, tmp_path):
    conn = opened(source_db)
    run = nightly_run(conn)
    write_log(tmp_path, "2026-11-14T230615Z.log", run, "")
    write_log(tmp_path, "2026-11-15T230615Z.log", run + 1, "")     # pulled, but the GUI copy is older
    assert build(conn, tmp_path)["run_id"] == run
    assert build(conn, tmp_path / "no-logs-here") is None


def test_parse_log_reads_the_real_formats():
    from pathlib import Path
    real = Path(__file__).resolve().parent.parent / "logs" / "runs" / "2026-11-10T224252Z.log"
    log = parse_log(real)
    assert log["run_id"] == 12 and log["mode"] == "scheduled/normal"
    assert log["cloud"]["20261110T055049_20261110T055844_T43SCA"] > 10
    assert log["reasons"]["S1D_IW_GRDH_1SDV_20261110T010541_20261110T010606_005398_00A4C0_EE4D"].endswith("connected to the centre")


def test_dashboard_shows_the_note_and_a_live_check_never_replaces_it(source_db, tmp_path):
    repo = tmp_path / "repo"
    conn = opened(source_db)
    run = nightly_run(conn)
    conn.commit(); conn.close()
    write_log(repo, "2026-11-14T230615Z.log", run,
              "2026-11-14 23:06:17,000 INFO sailab.pipeline: KRB: 0 scenes listed after 2026-10-20\n")
    client = TestClient(create_app(source_db=source_db, work_dir=tmp_path / "work", repo=repo))
    html = client.get("/").text
    assert f"Last night&#39;s run: run {run}" in html and "Completed, nothing new" in html
    assert "optical: Earth Engine had no image after 20 Oct" in html
    # a live check adds a run_log row to the working copy but no log file: the note stays on the nightly run
    copy = sqlite3.connect(client.app.state.provenance["working_copy"])
    copy.execute("INSERT INTO run_log (started_at, finished_at) VALUES ('2026-11-15T10:00:00+00:00', '2026-11-15T10:00:20+00:00')")
    copy.commit(); copy.close()
    assert f"Last night&#39;s run: run {run}" in client.get("/").text
