"""Read-only queries behind the GUI. Every number a screen shows comes from one of these functions.

Nothing here writes to the database or invents a value: a missing row is returned as None / an empty
list, and the screen must show it as missing. Each function takes an open sqlite3 connection, so the
same code runs against the real database copy and against a temporary test database.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

NOT_DOWNLOADED_PREFIX = "not_downloaded/"   # same marker pipeline.py writes for too-cloudy scenes


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r is not None else None


def list_lakes(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM lake ORDER BY id")]


def get_lake(conn: sqlite3.Connection, code: str) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM lake WHERE code = ?", (code,)).fetchone())


SOURCE_FOR_SENSOR = {"optical": "sentinel-2", "radar": "sentinel-1"}


def _sensor_summary(conn: sqlite3.Connection, lake_id: int, today: date, sensor: str) -> dict[str, Any]:
    """Counts, newest usable measurement and newest score for ONE sensor (optical or radar)."""
    source = SOURCE_FOR_SENSOR[sensor]
    counts = conn.execute(
        f"""SELECT COUNT(*) AS scenes,
                   COALESCE(SUM(s.file_path LIKE '{NOT_DOWNLOADED_PREFIX}%'), 0) AS too_cloudy,
                   COALESCE(SUM(m.status = 'ok'), 0) AS measured_ok,
                   COALESCE(SUM(m.status = 'insufficient_observation'), 0) AS insufficient_observation,
                   COALESCE(SUM(m.status = 'no_lake_detected'), 0) AS no_lake_detected
            FROM scene s LEFT JOIN measurement m ON m.scene_id = s.id
            WHERE s.lake_id = ? AND s.source = ?""", (lake_id, source)).fetchone()
    # The newest scene this sensor could judge (usable, or no lake found): refusals say nothing about the lake.
    latest_judged = conn.execute(
        """SELECT s.id AS scene_id, s.acquired_at, m.status, m.extent_ha FROM measurement m JOIN scene s ON s.id = m.scene_id
           WHERE m.lake_id = ? AND m.sensor = ? AND m.status IN ('ok', 'no_lake_detected')
           ORDER BY s.acquired_at DESC, m.id DESC LIMIT 1""", (lake_id, sensor)).fetchone()
    latest_ok = conn.execute(
        """SELECT m.id AS measurement_id, s.acquired_at, m.extent_ha, s.cloud_fraction, s.file_path
           FROM measurement m JOIN scene s ON s.id = m.scene_id
           WHERE m.lake_id = ? AND m.status = 'ok' AND m.sensor = ? ORDER BY s.acquired_at DESC, m.id DESC LIMIT 1""",
        (lake_id, sensor)).fetchone()
    latest_score = conn.execute(
        """SELECT r.status, r.baseline_ha, r.deviation_score, r.scored_at, s.acquired_at, m.extent_ha, m.id AS measurement_id
           FROM risk_score r JOIN measurement m ON m.id = r.measurement_id JOIN scene s ON s.id = m.scene_id
           WHERE r.lake_id = ? AND m.sensor = ? ORDER BY s.acquired_at DESC, r.id DESC LIMIT 1""",
        (lake_id, sensor)).fetchone()
    days = None if latest_ok is None else (today - date.fromisoformat(latest_ok["acquired_at"][:10])).days
    return {"counts": dict(counts), "latest_ok_measurement": _row(latest_ok), "latest_judged": _row(latest_judged),
            "latest_risk_score": _row(latest_score), "days_since_last_ok": days}


def lake_summary(conn: sqlite3.Connection, lake_id: int, today: date) -> dict[str, Any]:
    """Everything the dashboard shows for one lake.

    The top-level keys are OPTICAL (Sentinel-2) values, as before radar existed; summary["radar"] holds the
    same keys for Sentinel-1. The two are never combined into one number: they measure the lake slightly
    differently (logs/2026-11-09_radar_validation.log) and are scored against separate baselines.
    """
    optical = _sensor_summary(conn, lake_id, today, "optical")
    latest_scene = conn.execute(
        f"""SELECT s.id, s.source, s.acquired_at, s.cloud_fraction, s.file_path,
                   s.file_path LIKE '{NOT_DOWNLOADED_PREFIX}%' AS too_cloudy, m.status AS measurement_status
            FROM scene s LEFT JOIN measurement m ON m.scene_id = s.id
            WHERE s.lake_id = ? AND s.source = 'sentinel-2' ORDER BY s.acquired_at DESC, s.id DESC LIMIT 1""",
        (lake_id,)).fetchone()
    return {**optical, "latest_scene": _row(latest_scene), "radar": _sensor_summary(conn, lake_id, today, "radar")}


def lake_history(conn: sqlite3.Connection, lake_id: int) -> list[dict[str, Any]]:
    """One row per scene, oldest first: what the satellite saw and what the pipeline did with it."""
    rows = conn.execute(
        f"""SELECT s.id AS scene_id, s.source, s.acquired_at, s.cloud_fraction, s.file_path, s.downloaded_at,
                   s.file_path LIKE '{NOT_DOWNLOADED_PREFIX}%' AS too_cloudy,
                   m.id AS measurement_id, m.sensor, m.status AS measurement_status, m.extent_ha,
                   r.status AS risk_status, r.baseline_ha, r.deviation_score
            FROM scene s
            LEFT JOIN measurement m ON m.scene_id = s.id
            LEFT JOIN risk_score r ON r.measurement_id = m.id
            WHERE s.lake_id = ? ORDER BY s.acquired_at, s.id""", (lake_id,)).fetchall()
    return [dict(r) for r in rows]


def run_log(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM run_log ORDER BY id DESC LIMIT ?", (limit,))]


def latest_run(conn: sqlite3.Connection) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM run_log ORDER BY id DESC LIMIT 1").fetchone())


def database_totals(conn: sqlite3.Connection) -> dict[str, int]:
    out = {}
    for table in ("lake", "scene", "measurement", "risk_score", "run_log"):
        out[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    out["too_cloudy"] = conn.execute(
        f"SELECT COUNT(*) FROM scene WHERE file_path LIKE '{NOT_DOWNLOADED_PREFIX}%'").fetchone()[0]
    for sensor, source in SOURCE_FOR_SENSOR.items():
        out[f"{sensor}_scenes"] = conn.execute("SELECT COUNT(*) FROM scene WHERE source = ?", (source,)).fetchone()[0]
        out[f"{sensor}_measurements"] = conn.execute(
            "SELECT COUNT(*) FROM measurement WHERE sensor = ?", (sensor,)).fetchone()[0]
        out[f"{sensor}_ok"] = conn.execute(
            "SELECT COUNT(*) FROM measurement WHERE sensor = ? AND status = 'ok'", (sensor,)).fetchone()[0]
    return out


def same_month_inputs(conn: sqlite3.Connection, lake_id: int, acquired_on: date,
                      exclude_measurement_id: int | None = None, sensor: str = "optical") -> dict[str, Any]:
    """The earlier usable values the seasonal baseline for this scene could use: same sensor, same calendar
    month, observed strictly before the scene (the same inputs pipeline.py's check F counts)."""
    rows = conn.execute(
        """SELECT s.acquired_at, m.extent_ha FROM measurement m JOIN scene s ON s.id = m.scene_id
           WHERE m.lake_id = ? AND m.status = 'ok' AND m.sensor = ? AND m.id IS NOT ? ORDER BY s.acquired_at""",
        (lake_id, sensor, exclude_measurement_id)).fetchall()
    earlier = [r for r in rows if date.fromisoformat(r["acquired_at"][:10]) < acquired_on
               and date.fromisoformat(r["acquired_at"][:10]).month == acquired_on.month]
    return {"count": len(earlier), "years": sorted({int(r["acquired_at"][:4]) for r in earlier}),
            "values": [(r["acquired_at"][:10], r["extent_ha"]) for r in earlier]}


def recent_ok_extents(conn: sqlite3.Connection, lake_id: int, n: int = 15, sensor: str = "optical") -> list[float]:
    rows = conn.execute(
        """SELECT m.extent_ha FROM measurement m JOIN scene s ON s.id = m.scene_id
           WHERE m.lake_id = ? AND m.status = 'ok' AND m.sensor = ? ORDER BY s.acquired_at DESC LIMIT ?""",
        (lake_id, sensor, n)).fetchall()
    return [r[0] for r in reversed(rows)]
