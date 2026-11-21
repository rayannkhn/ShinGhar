"""Persistent storage (SQLite) for the Acquisition, Measurement and Risk Scoring stages.

A minimal subset of the project's 16-table data model: only the five tables
these three stages actually read or write. SQLite is a single file, so it can
be committed back to the repository by the scheduled GitHub Actions run, which
gives a public, timestamped history of every row the pipeline has written.

Every insert commits immediately. That is deliberate: if a run crashes part way
through, everything written before the crash is already on disk, which is what
lets the next run resume instead of redoing completed work (FR-04).
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from sailab.risk import ExtentRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS lake (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    centre_lon REAL NOT NULL,
    centre_lat REAL NOT NULL,
    boundary_radius_m REAL NOT NULL,
    growth_distance_limit_m REAL NOT NULL DEFAULT 2500,
    history_since TEXT,
    detects_drainage INTEGER NOT NULL DEFAULT 0,
    country TEXT NOT NULL DEFAULT 'Pakistan'
);

CREATE TABLE IF NOT EXISTS scene (
    id INTEGER PRIMARY KEY,
    lake_id INTEGER NOT NULL REFERENCES lake(id),
    source TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    cloud_fraction REAL,
    file_path TEXT NOT NULL,
    downloaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS measurement (
    id INTEGER PRIMARY KEY,
    scene_id INTEGER NOT NULL UNIQUE REFERENCES scene(id),
    lake_id INTEGER NOT NULL REFERENCES lake(id),
    sensor TEXT NOT NULL,
    extent_ha REAL,
    status TEXT NOT NULL,
    measured_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_score (
    id INTEGER PRIMARY KEY,
    lake_id INTEGER NOT NULL REFERENCES lake(id),
    measurement_id INTEGER NOT NULL REFERENCES measurement(id),
    method TEXT NOT NULL,
    status TEXT NOT NULL,
    baseline_ha REAL,
    deviation_score REAL,
    scored_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_log (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    lakes_processed INTEGER NOT NULL DEFAULT 0,
    scenes_downloaded INTEGER NOT NULL DEFAULT 0,
    errors TEXT
);
"""

SCENE_SOURCES = ("sentinel-2", "sentinel-1")
SENSORS = ("optical", "radar")
# 'no_lake_detected' (added 2026-11-10): a clear, snow-free summer scene with no water at the lake centre, for
# lakes where this is trustworthy (lake.detects_drainage = 1). It carries NO area: it is not a measured 0 ha.
MEASUREMENT_STATUSES = ("ok", "insufficient_observation", "no_lake_detected")
NO_AREA_STATUSES = ("insufficient_observation", "no_lake_detected")
RISK_STATUSES = ("ok", "insufficient_history")
RISK_METHODS = ("anomaly_detector",)

# The two lakes this build starts with. These are the literal values the
# project's existing real results (Karambar 237.2 ha, Atro Sar 76.51 ha) were
# computed from. They must not be "corrected" or rounded: new measurements are
# only comparable with the old ones if they use exactly these coordinates.
SEED_LAKES = (
    {
        "code": "KRB",
        "name": "Karambar Lake",
        "centre_lon": 73.7053229,
        "centre_lat": 36.880833,
        "boundary_radius_m": 2500.0,
        "growth_distance_limit_m": 2500.0,
        "history_since": None,
        "detects_drainage": 0,
    },
    {
        # Centre unchanged. Window and growth limit changed on 2026-11-08 from 800 m / 1200 m to
        # 1500 m / 1500 m, agreed with the project owner: the original 800 m export cut the lake off
        # at the window's left edge (76.51 ha was only the part inside the window), and 1200 m growth
        # also stopped short (98.47 ha). On the same 2026-07-18 scene, radii of 1500, 2000 and 2500 m
        # all give 105.82 ha. Evidence: logs/2026-11-08_step5_atro_sar_radius_check.log
        "code": "ATS",
        "name": "Atro Sar",
        "centre_lon": 73.65037,
        "centre_lat": 36.64458,
        "boundary_radius_m": 1500.0,
        "growth_distance_limit_m": 1500.0,
        "history_since": None,
        "detects_drainage": 0,
    },
    # Added 2026-11-10, agreed with the project owner. Each was tested first with the pipeline's own download and
    # measurement on real scenes: logs/2026-11-10_new_lake_candidates/README.md. history_since = the date the
    # backfill starts after (None: scripts/run_once.py's INITIAL_SINCE_DATE, 2022-12-31).
    {
        # Ice-dammed lake beside the surging Shishper glacier above Hassanabad, Hunza; outbursts incl. 7 May 2022
        # (KKH bridge destroyed). Centre: inside both the 2019 and the April 2022 lake outlines (Sentinel-2).
        # History from 2019 so the lake's own outbursts are in the record. detects_drainage: when the lake was
        # there its water was seen by NDWI; since the 2022 outburst there is none (correctly "no lake").
        "code": "SHP",
        "name": "Shishper glacier lake",
        "centre_lon": 74.5650,
        "centre_lat": 36.3590,
        "boundary_radius_m": 1500.0,
        "growth_distance_limit_m": 1500.0,
        "history_since": "2018-12-31",
        "detects_drainage": 1,
    },
    {
        # Darkut glacial lake ("Ghamu Bar"), Yasin valley, at the Darkut glacier tongue; grown from 4.5 to 15.4 ha
        # (Amin et al. 2020, Meteorological Applications, doi 10.1002/met.1877). Centre: the published position
        # 36 38'31.90" N, 73 24'25.22" E (PMD study). Clear water: 6 of 6 summer optical and 6 of 6 radar scenes usable.
        "code": "DKT",
        "name": "Darkut glacial lake",
        "centre_lon": 73.40701,
        "centre_lat": 36.64219,
        "boundary_radius_m": 1000.0,
        "growth_distance_limit_m": 1000.0,
        "history_since": None,
        "detects_drainage": 1,
    },
    {
        # Borith (Borit) Lake near Ghulkin and Passu glaciers, Hunza; named a possible future GLOF source
        # (Iqbal et al. 2023). Centre: JRC Global Surface Water centroid. Radar stable (10.7-11.3 ha); optical
        # only partly (2 of 4 summer scenes), so no drainage detection.
        "code": "BRT",
        "name": "Borith Lake",
        "centre_lon": 74.86214,
        "centre_lat": 36.43053,
        "boundary_radius_m": 1000.0,
        "growth_distance_limit_m": 1000.0,
        "history_since": None,
        "detects_drainage": 0,
    },
    {
        # Proglacial lake at the Passu glacier snout, Hunza; past outbursts (e.g. Jan 2008) and a May 2022
        # meltwater release that damaged a KKH bridge (ICIMOD). Silty water: NDWI does not see it (0 of 4 summer
        # optical scenes); radar measured 3 of 6. Kept so the system shows that limit honestly; no drainage detection.
        "code": "PSU",
        "name": "Passu glacier lake",
        "centre_lon": 74.87979,
        "centre_lat": 36.45744,
        "boundary_radius_m": 1000.0,
        "growth_distance_limit_m": 1000.0,
        "history_since": None,
        "detects_drainage": 0,
    },
    # Added 2026-11-18 at the supervisor's request (international test lakes), agreed with the project owner. Both were
    # tested first with the pipeline's own download and measurement on real autumn 2024/2025 scenes, against four other
    # Nepal candidates (Imja Tsho, Dig Tsho, Tam Pokhari, Lower Barun): logs/2026-11-18_nepal_lake_candidates/README.md.
    # Both are among ICIMOD's highest-risk lakes in Nepal and have published areas to check our measurements against.
    {
        # Tsho Rolpa, Rolwaling valley, Dolakha: moraine-dammed, on the Trakarding glacier; lowered 3 m in 2000 to cut
        # its outburst risk. Published 1.55 km2 (1999) and about 1.6 km2 (ICIMOD); measured 165.41 and 165.25 ha
        # (Oct 2024). Centre: JRC Global Surface Water centroid (max extent 162.0 ha, water 97% of the time, 4,546 m).
        "code": "TRL",
        "name": "Tsho Rolpa",
        "centre_lon": 86.47656,
        "centre_lat": 27.86090,
        "boundary_radius_m": 2500.0,
        "growth_distance_limit_m": 2500.0,
        "history_since": "2018-12-31",
        "detects_drainage": 0,
        "country": "Nepal",
    },
    {
        # Thulagi (Dona) lake, below Manaslu, Gorkha/Lamjung: moraine-dammed, rated potentially dangerous (ICIMOD).
        # Published 0.94 km2 (ICIMOD, 2009) and 0.89 km2 (Oct 2017 survey; Remote Sensing 10(5) 798, 2018); measured
        # 96.9-97.7 ha on 6 of 8 clear autumn days 2024-2025. Centre: JRC centroid (max 102.8 ha, 93.7%, 3,988 m).
        "code": "THU",
        "name": "Thulagi lake",
        "centre_lon": 84.48544,
        "centre_lat": 28.48859,
        "boundary_radius_m": 1500.0,
        "growth_distance_limit_m": 1500.0,
        "history_since": "2018-12-31",
        "detects_drainage": 0,
        "country": "Nepal",
    },
    # ShinGhar pilot valley (added 2026-11-20, agreed with the project owner): Utror-Kalam, Kalam Tehsil, Swat District,
    # Khyber Pakhtunkhwa. Chosen and smoke-tested with the pipeline's own download + measure_scene on real summer
    # 2024/2025 scenes: logs/2026-11-20_shinghar_valley_candidates/README.md. Centres: JRC GSW v1.4 max_extent
    # centroids. No name in OpenStreetMap at any of the three centres; local names still to be confirmed.
    # History from 2019 so the summer-median growth trend has 7 summers. detects_drainage 0: not validated here.
    {
        # Candidate "SE": max extent 45.3 ha, water in 92.5 % of JRC observations, 3,028 m; 7 of 8 test scenes usable
        # (42.0-45.4 ha). Downhill path passes Kass (Utror) after 11.6 km.
        "code": "UTA",
        "name": "Utror lake A (unnamed, 3,028 m)",
        "centre_lon": 72.43293,
        "centre_lat": 35.41921,
        "boundary_radius_m": 1000.0,
        "growth_distance_limit_m": 1000.0,
        "history_since": "2018-12-31",
        "detects_drainage": 0,
    },
    {
        # Candidate "SD": max extent 18.3 ha, 87.6 %, 3,183 m; 6 of 8 usable (17.1-17.9 ha). Path passes Kass after 9.8 km.
        "code": "UTB",
        "name": "Utror lake B (unnamed, 3,183 m)",
        "centre_lon": 72.45197,
        "centre_lat": 35.43385,
        "boundary_radius_m": 1000.0,
        "growth_distance_limit_m": 1000.0,
        "history_since": "2018-12-31",
        "detects_drainage": 0,
    },
    {
        # Candidate "SF": max extent 34.2 ha, 93.3 %, 3,345 m, north of Kalam; 3 of 8 usable (29.6-30.5 ha; the
        # others refused for snow touching the lake).
        "code": "KLN",
        "name": "Kalam north lake (unnamed, 3,345 m)",
        "centre_lon": 72.51194,
        "centre_lat": 35.64618,
        "boundary_radius_m": 1000.0,
        "growth_distance_limit_m": 1000.0,
        "history_since": "2018-12-31",
        "detects_drainage": 0,
    },
)


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string, to the second (e.g. 2026-11-07T06:00:12+00:00)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the database file and make sure every table exists."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite ignores REFERENCES unless this is on
    conn.executescript(SCHEMA)
    # Columns added after the first databases were created (2026-11-10): add them to an older file in place.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(lake)")}
    if "history_since" not in columns:
        conn.execute("ALTER TABLE lake ADD COLUMN history_since TEXT")
    if "detects_drainage" not in columns:
        conn.execute("ALTER TABLE lake ADD COLUMN detects_drainage INTEGER NOT NULL DEFAULT 0")
    if "country" not in columns:                   # added 2026-11-18 with the Nepal test lakes
        conn.execute("ALTER TABLE lake ADD COLUMN country TEXT NOT NULL DEFAULT 'Pakistan'")
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Inserts
# ---------------------------------------------------------------------------
def insert_lake(conn: sqlite3.Connection, code: str, name: str, centre_lon: float, centre_lat: float,
                boundary_radius_m: float, growth_distance_limit_m: float = 2500.0,
                history_since: str | None = None, detects_drainage: int = 0, country: str = "Pakistan") -> int:
    if not (-180.0 <= centre_lon <= 180.0) or not (-90.0 <= centre_lat <= 90.0):
        raise ValueError(f"lake {code}: coordinates out of range (lon={centre_lon}, lat={centre_lat})")
    if history_since is not None:
        date.fromisoformat(history_since)      # raises ValueError if not an ISO date
    if detects_drainage not in (0, 1):
        raise ValueError(f"lake {code}: detects_drainage must be 0 or 1, got {detects_drainage!r}")
    cursor = conn.execute(
        "INSERT INTO lake (code, name, centre_lon, centre_lat, boundary_radius_m, growth_distance_limit_m, "
        "history_since, detects_drainage, country) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (code, name, centre_lon, centre_lat, boundary_radius_m, growth_distance_limit_m, history_since, detects_drainage,
         country),
    )
    conn.commit()
    return cursor.lastrowid


def insert_scene(conn: sqlite3.Connection, lake_id: int, source: str, acquired_at: str,
                 cloud_fraction: float | None, file_path: str, downloaded_at: str | None = None) -> int:
    if source not in SCENE_SOURCES:
        raise ValueError(f"scene source must be one of {SCENE_SOURCES}, got {source!r}")
    date.fromisoformat(acquired_at[:10])  # raises ValueError if acquired_at is not an ISO date
    cursor = conn.execute(
        "INSERT INTO scene (lake_id, source, acquired_at, cloud_fraction, file_path, downloaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (lake_id, source, acquired_at, cloud_fraction, file_path, downloaded_at or utc_now_iso()),
    )
    conn.commit()
    return cursor.lastrowid


def insert_measurement(conn: sqlite3.Connection, scene_id: int, lake_id: int, sensor: str,
                       extent_ha: float | None, status: str, measured_at: str | None = None) -> int:
    """Insert one lake-extent measurement.

    extent_ha must be None exactly when status is 'insufficient_observation':
    a failed measurement is recorded as missing, never as an invented zero.
    """
    if sensor not in SENSORS:
        raise ValueError(f"sensor must be one of {SENSORS}, got {sensor!r}")
    if status not in MEASUREMENT_STATUSES:
        raise ValueError(f"measurement status must be one of {MEASUREMENT_STATUSES}, got {status!r}")
    if status == "ok" and extent_ha is None:
        raise ValueError("status 'ok' needs an extent_ha value")
    if status in NO_AREA_STATUSES and extent_ha is not None:
        raise ValueError(f"status {status!r} must have extent_ha = None, not a number")
    if status == "no_lake_detected" and sensor != "optical":
        raise ValueError("'no_lake_detected' is an optical result only")
    cursor = conn.execute(
        "INSERT INTO measurement (scene_id, lake_id, sensor, extent_ha, status, measured_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (scene_id, lake_id, sensor, extent_ha, status, measured_at or utc_now_iso()),
    )
    conn.commit()
    return cursor.lastrowid


def insert_risk_score(conn: sqlite3.Connection, lake_id: int, measurement_id: int, method: str, status: str,
                      baseline_ha: float | None, deviation_score: float | None,
                      scored_at: str | None = None) -> int:
    if method not in RISK_METHODS:
        raise ValueError(f"risk method must be one of {RISK_METHODS}, got {method!r}")
    if status not in RISK_STATUSES:
        raise ValueError(f"risk status must be one of {RISK_STATUSES}, got {status!r}")
    cursor = conn.execute(
        "INSERT INTO risk_score (lake_id, measurement_id, method, status, baseline_ha, deviation_score, scored_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (lake_id, measurement_id, method, status, baseline_ha, deviation_score, scored_at or utc_now_iso()),
    )
    conn.commit()
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
def get_extent_history(conn: sqlite3.Connection, lake_id: int,
                       exclude_measurement_id: int | None = None, sensor: str | None = None) -> list[ExtentRecord]:
    """Every usable past extent of a lake, oldest first, ready for score_against_seasonal_baseline().

    - observed_on is the satellite pass date (scene.acquired_at), not when the
      pipeline happened to process it, since the seasonal baseline is about
      what month the lake was seen in.
    - Measurements with status 'insufficient_observation' are left out: they
      have no extent, and treating them as zero would drag the baseline down.
    - exclude_measurement_id lets the caller leave out the measurement it is
      about to score, so a new value is never compared against itself.
    - sensor ('optical' or 'radar') keeps the two sensors' baselines apart: they measure the same
      lake slightly differently, and mixing them would create false "change" scores.
    """
    rows = conn.execute(
        "SELECT m.id, s.acquired_at, m.extent_ha FROM measurement m JOIN scene s ON s.id = m.scene_id "
        "WHERE m.lake_id = ? AND m.status = 'ok' AND (? IS NULL OR m.sensor = ?) ORDER BY s.acquired_at, m.id",
        (lake_id, sensor, sensor),
    ).fetchall()
    return [
        ExtentRecord(observed_on=date.fromisoformat(row["acquired_at"][:10]), extent_ha=row["extent_ha"])
        for row in rows
        if row["id"] != exclude_measurement_id
    ]


def get_lakes(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM lake ORDER BY id").fetchall()


# ---------------------------------------------------------------------------
# Run log
# ---------------------------------------------------------------------------
def start_run_log(conn: sqlite3.Connection, started_at: str | None = None) -> int:
    cursor = conn.execute("INSERT INTO run_log (started_at) VALUES (?)", (started_at or utc_now_iso(),))
    conn.commit()
    return cursor.lastrowid


def finish_run_log(conn: sqlite3.Connection, run_id: int, lakes_processed: int, scenes_downloaded: int,
                   errors: str | None = None, finished_at: str | None = None) -> None:
    """Close a run. errors is the real error text (None only for a genuinely clean run)."""
    cursor = conn.execute(
        "UPDATE run_log SET finished_at = ?, lakes_processed = ?, scenes_downloaded = ?, errors = ? "
        "WHERE id = ? AND finished_at IS NULL",
        (finished_at or utc_now_iso(), lakes_processed, scenes_downloaded, errors, run_id),
    )
    conn.commit()
    if cursor.rowcount != 1:
        raise ValueError(f"run_log {run_id} does not exist or was already finished")


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------
def seed_lakes(conn: sqlite3.Connection) -> list[int]:
    """Insert the seed lakes if missing. Safe to run every time.

    If a lake with the same code already exists with different values, this
    raises rather than silently keeping either version, because a changed
    coordinate would make new measurements incomparable with old ones.
    """
    ids: list[int] = []
    for lake in SEED_LAKES:
        existing = conn.execute("SELECT * FROM lake WHERE code = ?", (lake["code"],)).fetchone()
        if existing is None:
            ids.append(insert_lake(conn, **lake))
            continue
        mismatched = {key: (existing[key], value) for key, value in lake.items() if existing[key] != value}
        if mismatched:
            raise ValueError(f"lake {lake['code']} already stored with different values (stored, seed): {mismatched}")
        ids.append(existing["id"])
    return ids
