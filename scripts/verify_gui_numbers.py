"""Check every number on the Dashboard and Lake Detail screens against the database, independently.

Run before a demo:   .venv/bin/python scripts/verify_gui_numbers.py
It starts the app in-process on a fresh copy of sailab_glof.db (exactly as `uvicorn app:app` does),
renders each page, and looks for every number computed here with separate SQL (none of the app's query
code is reused). Prints a table and exits 1 if any number is missing or different.
"""
from __future__ import annotations

import re
import sqlite3
import sys
import tempfile
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from webapp import images  # noqa: E402
from webapp.main import create_app  # noqa: E402

PKT = timezone(timedelta(hours=5))


def page_text(client: TestClient, url: str) -> str:
    html = client.get(url).text
    html = re.sub(r"<svg.*?</svg>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def main() -> int:
    today = datetime.now(timezone.utc).date()
    client = TestClient(create_app(work_dir=Path(tempfile.mkdtemp(prefix="sailab_verify_"))))
    db = sqlite3.connect(REPO / "sailab_glof.db")
    db.row_factory = sqlite3.Row
    q = lambda sql, *a: db.execute(sql, a).fetchone()  # noqa: E731
    fd = lambda iso: datetime.fromisoformat(iso).strftime("%d %b %Y")  # noqa: E731
    rows: list[str] = []
    failures = 0

    def check(screen: str, label: str, text: str, expected: str, source: str) -> None:
        nonlocal failures
        found = expected in text
        failures += not found
        rows.append(f"| {screen} | {label} | `{expected}` | {source} | {'yes' if found else 'NO'} |")

    dash = page_text(client, "/")
    count = lambda sql, *a: q(sql, *a)[0]  # noqa: E731
    n_scene = count("SELECT COUNT(*) FROM scene")
    n_opt = count("SELECT COUNT(*) FROM scene WHERE source = 'sentinel-2'")
    n_rad = count("SELECT COUNT(*) FROM scene WHERE source = 'sentinel-1'")
    n_cloudy = count("SELECT COUNT(*) FROM scene WHERE file_path LIKE 'not_downloaded/%'")
    m = {sen: (count("SELECT COUNT(*) FROM measurement WHERE sensor = ?", sen),
               count("SELECT COUNT(*) FROM measurement WHERE sensor = ? AND status = 'ok'", sen)) for sen in ("optical", "radar")}
    first, last = q("SELECT MIN(acquired_at), MAX(acquired_at) FROM scene")
    check("Dashboard", "Lakes monitored", dash, f"Lakes monitored {count('SELECT COUNT(*) FROM lake')}", "COUNT(lake)")
    check("Dashboard", "Scenes recorded", dash, f"Scenes recorded {n_scene} {n_opt} optical, {n_rad} radar; {fd(first)} to {fd(last)}",
          "COUNT(scene) by source, MIN/MAX(acquired_at)")
    check("Dashboard", "Too cloudy", dash, f"{round(100 * n_cloudy / n_opt)}% {n_cloudy} of {n_opt} optical scenes",
          "not_downloaded scenes / optical scenes")
    check("Dashboard", "Usable measurements", dash,
          f"Usable measurements {m['optical'][1] + m['radar'][1]} {m['optical'][1] + m['radar'][1]} of "
          f"{m['optical'][0] + m['radar'][0]} measurement attempts passed every check (optical {m['optical'][1]} of "
          f"{m['optical'][0]}, radar {m['radar'][1]} of {m['radar'][0]}). Not a scene count: the {n_cloudy} too-cloudy "
          f"optical scenes were never measured.", "measurement rows by sensor and status; not_downloaded scenes")
    run = q("SELECT * FROM run_log ORDER BY id DESC LIMIT 1")
    check("Dashboard", "Last pipeline run", dash,
          "Last pipeline run " + datetime.fromisoformat(run["started_at"]).astimezone(PKT).strftime("%d %b %Y, %H:%M PKT"),
          f"run_log {run['id']}.started_at")

    for lake in db.execute("SELECT * FROM lake ORDER BY id").fetchall():
        lid, code = lake["id"], lake["code"]
        detail = page_text(client, f"/lakes/{code}")
        counts = {}
        for sensor, source in (("optical", "sentinel-2"), ("radar", "sentinel-1")):
            label = sensor.capitalize()
            latest = q("""SELECT s.acquired_at, m.extent_ha, s.file_path FROM measurement m JOIN scene s ON s.id = m.scene_id
                          WHERE m.lake_id = ? AND m.status = 'ok' AND m.sensor = ? ORDER BY s.acquired_at DESC LIMIT 1""", lid, sensor)
            counts[sensor] = q("""SELECT COUNT(*) n, COALESCE(SUM(s.file_path LIKE 'not_downloaded/%'), 0) cloudy,
                     COALESCE(SUM(m.status = 'ok'), 0) ok, COALESCE(SUM(m.status = 'insufficient_observation'), 0) refused,
                     COALESCE(SUM(m.status = 'no_lake_detected'), 0) no_lake
                     FROM scene s LEFT JOIN measurement m ON m.scene_id = s.id WHERE s.lake_id = ? AND s.source = ?""", lid, source)
            if latest is None:
                check("Dashboard", f"{code} {sensor} latest", dash, f"{label}: No usable measurement yet", "no ok measurement")
                continue
            days = (today - datetime.fromisoformat(latest[0]).date()).days
            check("Dashboard", f"{code} {sensor} latest", dash, f"{label}: {latest[1]:.2f} ha on {fd(latest[0])}, {days} days ago",
                  f"newest ok {sensor} measurement")
            check("Lake Detail", f"{code} {sensor} latest", detail,
                  f"Latest usable area, {sensor} {latest[1]:.2f} ha {fd(latest[0])}, {days} days ago", f"newest ok {sensor} measurement")
            score = q("""SELECT r.status, r.baseline_ha, r.deviation_score, s.acquired_at, m.extent_ha FROM risk_score r
                         JOIN measurement m ON m.id = r.measurement_id JOIN scene s ON s.id = m.scene_id
                         WHERE r.lake_id = ? AND m.sensor = ? ORDER BY s.acquired_at DESC LIMIT 1""", lid, sensor)
            if sensor == "radar":
                # radar risk scoring is off (pipeline.SCORE_RADAR): no radar score may exist, and the page must say so
                none_stored = score is None
                failures += not none_stored
                rows.append(f"| Database | {code} radar risk scores | none | risk_score rows for radar measurements | "
                            f"{'yes (none stored)' if none_stored else 'NO: radar scores found'} |")
                check("Dashboard", f"{code} radar chip", dash, "Radar not scored", "SCORE_RADAR is off")
            elif score is not None:
                chip = (f"{label} insufficient history" if score["status"] == "insufficient_history"
                        else f"{label} deviation {score['deviation_score']:+.2f}".replace("-", "−"))
                check("Dashboard", f"{code} {sensor} score", dash, chip, f"newest {sensor} risk_score")
                when = datetime.fromisoformat(score["acquired_at"])
                earlier = db.execute("""SELECT substr(s.acquired_at, 1, 4) FROM measurement mm JOIN scene s ON s.id = mm.scene_id
                                        WHERE mm.lake_id = ? AND mm.status = 'ok' AND mm.sensor = ? AND substr(s.acquired_at, 6, 2) = ?
                                        AND s.acquired_at < ?""", (lid, sensor, when.strftime("%m"), score["acquired_at"][:10])).fetchall()
                years = len({r[0] for r in earlier})
                check("Lake Detail", f"{code} {sensor} score inputs", detail,
                      f"Scene {fd(score['acquired_at'])} Measured area {score['extent_ha']:.2f} ha Earlier {when.strftime('%B')} {sensor} values "
                      f"{len(earlier)} from {years} year{'s' if years != 1 else ''}", f"newest {sensor} risk_score and its inputs")
                if score["status"] == "ok":
                    check("Lake Detail", f"{code} {sensor} baseline/score", detail,
                          f"Seasonal baseline {score['baseline_ha']:.2f} ha Deviation score {score['deviation_score']:+.2f}".replace("-", "−"),
                          "risk_score.baseline_ha / deviation_score")
            tif, dem = REPO / latest[2], REPO / "data" / "dem" / f"{code}_dem.tif"
            if tif.is_file() and (sensor == "optical" or dem.is_file()):
                out = Path(tempfile.mkdtemp()) / "x.png"
                px = (images.render_scene_png(tif, dict(lake), out) if sensor == "optical"
                      else images.render_radar_png(tif, dict(lake), dem, out))
                same = px is not None and abs(px / 100 - latest[1]) < 1e-9
                failures += not same
                rows.append(f"| Lake Detail | {code} {sensor} image outline | `{px} px` | recomputed from {latest[2]}, stored "
                            f"{latest[1]:.2f} ha | {'yes' if same else 'NO'} |")
            else:
                rows.append(f"| Lake Detail | {code} {sensor} image outline | (file not on this machine) | {latest[2]} | skipped |")
        o, r = counts["optical"], counts["radar"]
        check("Lake Detail", f"{code} scene counts", detail,
              f"Scenes recorded {o['n'] + r['n']} optical {o['n']}: {o['ok']} usable, {o['refused']} refused, "
              f"{str(o['no_lake']) + ' no lake found, ' if o['no_lake'] else ''}{o['cloudy']} too cloudy "
              f"radar {r['n']}: {r['ok']} usable, {r['refused']} refused", "scene + measurement counts by source")
        latest_judged = q("""SELECT s.acquired_at, m.status FROM measurement m JOIN scene s ON s.id = m.scene_id
                             WHERE m.lake_id = ? AND m.sensor = 'optical' AND m.status IN ('ok', 'no_lake_detected')
                             ORDER BY s.acquired_at DESC, m.id DESC LIMIT 1""", lid)
        if latest_judged is not None and latest_judged["status"] == "no_lake_detected":
            check("Lake Detail", f"{code} no-lake banner", detail,
                  f"No lake found in the latest clear optical scene ( {fd(latest_judged['acquired_at'])} )",
                  "newest optical ok/no_lake_detected measurement")
        check("Lake Detail", f"{code} settings", detail,
              f"window {lake['boundary_radius_m']:.0f} m, growth limit {lake['growth_distance_limit_m']:.0f} m", "lake row")

    print(f"checked {datetime.now(timezone.utc).isoformat(timespec='seconds')}, database commit "
          f"{client.get('/api/provenance').json()['git_commit']}\n")
    print("| Screen | Number | Expected on page | Source | Found |\n|---|---|---|---|---|")
    print("\n".join(rows))
    print(f"\n{len(rows) - failures} of {len(rows)} checks passed." + ("" if not failures else f" {failures} FAILED."))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
