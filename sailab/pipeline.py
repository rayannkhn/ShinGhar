"""Wires Acquisition -> Measurement -> Risk Scoring into one automatic run.

Optical (Sentinel-2): when choose_sensor() says a scene is too cloudy over the lake, it is recorded in
the `scene` table but not downloaded or measured; no number is invented for it.
Radar (Sentinel-1, added 2026-11-09): every radar pass is listed, downloaded and measured with
sailab.radar (slope mask at RADAR_SLOPE_LIMIT_DEG, then Otsu over flat ground, then region growing).
Radar measurements are NOT risk-scored (SCORE_RADAR = False): see the note at SCORE_RADAR.

Every stage uses the already-tested functions unchanged:
  choose_sensor, ResumableRun      (acquisition.py)
  classify_water_ndwi, region_grow, extent_area_m2  (measurement.py)
  score_against_seasonal_baseline  (risk.py)
"""
from __future__ import annotations

import hashlib
import json
import logging
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from math import floor
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np

from sailab import db
from sailab.acquisition import ResumableRun, RunLog, choose_sensor
from sailab.measurement import Pixel, classify_water_ndwi, extent_area_m2, region_grow
from sailab.risk import score_against_seasonal_baseline

log = logging.getLogger("sailab.pipeline")

GREEN_BAND_INDEX = 2   # 1-based rasterio band numbers in B2, B3, B4, B8, B11, SCL order: B3 = green
NIR_BAND_INDEX = 4     # B8 = near-infrared
SCL_BAND_INDEX = 6     # Sentinel-2 scene classification, added to downloads on 2026-11-08

# Checks C and D (added 2026-11-08, agreed with the project owner after the backfill outliers in
# logs/2026-11-08_backfill_outliers_true_colour_vs_detected.png): SCL classes that make a measurement
# untrustworthy when they touch the detected lake. These only ever REJECT a measurement; a wrong SCL
# label can make the pipeline more cautious, never produce a false area.
SCL_SNOW_ICE = 11
SCL_CLOUD_CLASSES = (3, 8, 9, 10)          # cloud shadow, cloud medium/high probability, thin cirrus
SNOW_COVER_LIMIT = 0.5                     # check C: more than half the lake circle snow/ice = frozen/snowed in

# Check F (added 2026-11-08): no risk score unless the scene's calendar month already has at least
# this many earlier usable measurements, from at least this many different years. With 2-3 values the
# spread is tiny and a modest change gave scores like -49 in the first backfill.
MIN_SAME_MONTH_VALUES = 5
MIN_SAME_MONTH_YEARS = 2
NOT_DOWNLOADED_PREFIX = "not_downloaded/"   # scene.file_path for scenes skipped as too cloudy for optical
RISK_STATUS_FROM_RISK_MODULE = {"ok": "ok", "insufficient history": "insufficient_history"}

# Cloud over the lake above this -> not measured optically. Passed to the unchanged choose_sensor(), whose
# own default (50%) is the test limit from TC-ACQ-06. Set to 10% on 2026-11-08, agreed with the project
# owner, after the August 2026 smoke test: scenes with 28.8% and 34.7% lake cloud under-measured the lakes
# (Atro Sar 87.0 ha vs ~106; Karambar 79.65 ha vs ~256), while clear scenes were 0-7%. Based on one month
# of data, so a judgement call, not a calibrated value. Evidence: logs/2026-11-08_step5_smoke_test_aug2026.log
OPTICAL_CLOUD_LIMIT_PERCENT = 10.0

# Radar slope mask: pixels steeper than this are dropped before Otsu. Fixed at 10 degrees on 2026-11-09,
# agreed with the project owner BEFORE validating radar against optical, so the validation is not tuned
# to it. Middle of the stable range on the original Karambar file (5-20 deg gave 258.7-281.6 ha).
# Evidence: logs/2026-11-09_radar_slope_mask_original_karambar.log
RADAR_SLOPE_LIMIT_DEG = 10.0
# Radar risk scoring is OFF (decided with the project owner, 2026-11-09). Validation against optical within
# 3 days: Karambar +5.2%, Atro Sar -6.4% on 16 independent summer optical scenes from 2 lakes
# (logs/2026-11-09_radar_validation.log, ..._independence.log), but 28 of
# 361 usable radar values, mostly April-June (snowmelt: wet snow is as dark as water), are clearly wrong, and
# they produced the largest radar "anomalies" (e.g. +50.3, -7.4). Until a melt-season check is tested on the
# stored data, radar is measured and shown, but never scored. _score() still keeps sensors apart if this is
# ever switched on.
SCORE_RADAR = False

# Drained lake (added 2026-11-10, agreed with the project owner): an ice-dammed lake that bursts can vanish,
# and "centre not water" then looks like any bad image. For lakes where this is trustworthy
# (lake.detects_drainage = 1: their water is seen by NDWI when present), a refused "centre not water" scene is
# recorded as 'no_lake_detected' (still no area) only when ALL hold: the month is May-October (outside it a
# frozen or snow-covered lake also shows no water), and within NO_LAKE_CHECK_RADIUS_M of the centre there is
# no cloud, cloud shadow, snow/ice or missing data, and under NO_LAKE_MAX_WATER_SHARE of the pixels are water.
# Judgement-call limits, not calibrated. Silty lakes (Passu) must NOT use this: NDWI misses their water.
NO_LAKE_MONTHS = range(5, 11)
NO_LAKE_CHECK_RADIUS_M = 150.0
NO_LAKE_MAX_WATER_SHARE = 0.10
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEM_DIR = REPO_ROOT / "data" / "dem"


@dataclass
class MeasurementOutcome:
    status: str                 # 'ok' or 'insufficient_observation'
    extent_ha: float | None
    reason: str                 # human-readable, written to the run log


@dataclass
class RunResult:
    run_id: int
    lakes_processed: int = 0
    scenes_recorded: int = 0
    scenes_downloaded: int = 0
    measurements: int = 0
    risk_scores: int = 0
    errors: str | None = None
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Measurement on a real downloaded GeoTIFF
# ---------------------------------------------------------------------------
def lake_centre_in_pixels(path: str | Path, lon: float, lat: float) -> tuple[float, float]:
    """Fractional (row, col) of a lon/lat inside a GeoTIFF, from the file's own georeferencing.

    This replaces the manual tests' shortcut (centre = rows//2, cols//2), which
    only worked because those exports happened to be centred on the lake.
    """
    import rasterio
    from rasterio.warp import transform as warp_transform

    with rasterio.open(path) as src:
        xs, ys = warp_transform("EPSG:4326", src.crs, [lon], [lat])
        col, row = ~src.transform @ (xs[0], ys[0])
    return row, col


def measure_scene(path: str | Path, lake: Mapping[str, Any], cutoff: float = 0.2,
                  scl_checks: bool = True) -> MeasurementOutcome:
    """NDWI per pixel -> water map -> region grown from the lake centre -> area.

    Returns 'insufficient_observation' (never a zero) when:
      - the lake centre falls outside the downloaded window;
      - the centre pixel itself is not water (or has no data), since growing
        from a non-water seed would report a 1-pixel "lake";
      - the grown lake touches a no-data pixel, since the lake may continue
        into the missing area and would be measured too small without warning;
      - (check D) cloud or cloud shadow touches the grown lake: part of it may be hidden;
      - (check C) snow/ice touches the grown lake (it may have leaked into snow, or the
        lake may be partly frozen), or covers more than half of the lake circle.

    scl_checks=False is only for the project's original 5-band manual exports, which have
    no SCL band; any file the pipeline downloads has it, and a missing band is an error.

    No-data pixels elsewhere are expected and harmless: the export's
    .bounds() rectangle is drawn in lat/lon, so clipping to it leaves a thin
    zero border (up to 6 px, measured on the original Karambar file) along
    the edges of the UTM window.
    """
    import rasterio

    with rasterio.open(path) as src:
        green = src.read(GREEN_BAND_INDEX).astype(float)
        nir = src.read(NIR_BAND_INDEX).astype(float)
        pixel_size_m = float(src.res[0])
        if scl_checks:
            if src.count < SCL_BAND_INDEX:
                raise ValueError(f"{path} has {src.count} bands, no SCL band: cannot run the cloud and snow checks")
            scl = src.read(SCL_BAND_INDEX)
    rows, cols = green.shape
    row_f, col_f = lake_centre_in_pixels(path, lake["centre_lon"], lake["centre_lat"])
    seed = Pixel(floor(row_f), floor(col_f))

    if not (0 <= seed.row < rows and 0 <= seed.col < cols):
        return MeasurementOutcome("insufficient_observation", None, f"lake centre {seed} is outside the {cols}x{rows} window")
    no_data = (green == 0) & (nir == 0)

    is_water = {Pixel(r, c): classify_water_ndwi(green[r, c], nir[r, c], cutoff) for r in range(rows) for c in range(cols)}
    if not is_water[seed]:
        return MeasurementOutcome("insufficient_observation", None, f"centre pixel {seed} is not water (NDWI <= {cutoff})")

    region = region_grow(is_water, seed, (row_f * pixel_size_m, col_f * pixel_size_m), pixel_size_m,
                         float(lake["growth_distance_limit_m"]))
    touching = _pixels_touching(region, no_data)
    if touching:
        return MeasurementOutcome("insufficient_observation", None,
                                  f"lake region ({len(region)} px) borders {touching} no-data pixels; it may be cut off")
    if scl_checks:
        cloud_touching = _pixels_touching(region, np.isin(scl, SCL_CLOUD_CLASSES))
        if cloud_touching:
            return MeasurementOutcome("insufficient_observation", None,
                                      f"check D: lake region ({len(region)} px) borders {cloud_touching} cloud/shadow pixels")
        snow = scl == SCL_SNOW_ICE
        snow_touching = _pixels_touching(region, snow)
        if snow_touching:
            return MeasurementOutcome("insufficient_observation", None,
                                      f"check C: lake region ({len(region)} px) borders {snow_touching} snow/ice pixels")
        circle = _inside_circle(rows, cols, row_f, col_f, float(lake["boundary_radius_m"]) / pixel_size_m) & (scl != 0)
        snow_share = float((snow & circle).sum()) / max(int(circle.sum()), 1)
        if snow_share > SNOW_COVER_LIMIT:
            return MeasurementOutcome("insufficient_observation", None,
                                      f"check C: {snow_share:.0%} of the lake circle is snow/ice (limit {SNOW_COVER_LIMIT:.0%})")
    extent_ha = extent_area_m2(region, pixel_size_m) / 10_000
    return MeasurementOutcome("ok", extent_ha, f"{len(region)} water pixels connected to the centre")


def no_lake_evidence(path: str | Path, lake: Mapping[str, Any], acquired_on: date) -> str | None:
    """Why a refused 'centre not water' scene counts as 'no lake detected', or None if it does not."""
    import rasterio

    if not int(dict(lake).get("detects_drainage") or 0):
        return None
    if acquired_on.month not in NO_LAKE_MONTHS:
        return None
    with rasterio.open(path) as src:
        if src.count < SCL_BAND_INDEX:
            return None
        green = src.read(GREEN_BAND_INDEX).astype(float)
        nir = src.read(NIR_BAND_INDEX).astype(float)
        scl = src.read(SCL_BAND_INDEX)
        pixel_size_m = float(src.res[0])
    row_f, col_f = lake_centre_in_pixels(path, lake["centre_lon"], lake["centre_lat"])
    near = _inside_circle(*green.shape, row_f, col_f, NO_LAKE_CHECK_RADIUS_M / pixel_size_m)
    if not near.any():
        return None
    if ((green == 0) & (nir == 0) & near).any() or (np.isin(scl, SCL_CLOUD_CLASSES) & near).any() \
            or ((scl == SCL_SNOW_ICE) & near).any() or ((scl == 0) & near).any():
        return None
    total = green + nir
    water = np.where(total > 0, (green - nir) / np.where(total > 0, total, 1), -1) > 0.2
    share = float((water & near).sum()) / float(near.sum())
    if share >= NO_LAKE_MAX_WATER_SHARE:
        return None
    return (f"no lake: within {NO_LAKE_CHECK_RADIUS_M:.0f} m of the centre {share:.0%} water, no cloud, snow/ice or "
            f"missing data, month {acquired_on.month:02d}")


def _inside_circle(rows: int, cols: int, centre_row: float, centre_col: float, radius_px: float):
    """True for pixels whose centre lies within radius_px of the (fractional) lake centre."""
    r = np.arange(rows)[:, None] + 0.5
    c = np.arange(cols)[None, :] + 0.5
    return np.hypot(r - centre_row, c - centre_col) <= radius_px


def _pixels_touching(region: set[Pixel], flagged) -> int:
    """How many distinct flagged pixels are 4-connected neighbours of the region (same connectivity as region_grow)."""
    rows, cols = flagged.shape
    touching: set[tuple[int, int]] = set()
    for p in region:
        for r, c in ((p.row - 1, p.col), (p.row + 1, p.col), (p.row, p.col - 1), (p.row, p.col + 1)):
            if 0 <= r < rows and 0 <= c < cols and flagged[r, c]:
                touching.add((r, c))
    return len(touching)


# ---------------------------------------------------------------------------
# Resume state (FR-04): which lake the last unfinished run got through
# ---------------------------------------------------------------------------
def resume_state_path(db_path: str | Path) -> Path:
    return Path(db_path).with_suffix(".resume.json")


def load_resume_state(db_path: str | Path) -> RunLog:
    path = resume_state_path(db_path)
    if not path.exists():
        return RunLog()
    data = json.loads(path.read_text())
    return RunLog(last_completed_lake_id=data["last_completed_lake_id"], download_count=data["download_count"])


def save_resume_state(db_path: str | Path, state: RunLog) -> None:
    resume_state_path(db_path).write_text(json.dumps(
        {"last_completed_lake_id": state.last_completed_lake_id, "download_count": state.download_count}))


def clear_resume_state(db_path: str | Path) -> None:
    resume_state_path(db_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------
def _since_date_for(conn, lake_id: int, initial_since_date: date, source: str = "sentinel-2") -> date:
    """The day before the newest scene of this source already stored (so a same-day second scene is not
    missed; duplicates are skipped by scene id), or initial_since_date if there is none yet."""
    row = conn.execute("SELECT MAX(acquired_at) FROM scene WHERE lake_id = ? AND source = ?",
                       (lake_id, source)).fetchone()
    if row[0] is None:
        return initial_since_date
    return date.fromisoformat(row[0][:10]) - timedelta(days=1)


def _already_recorded(conn, lake_id: int, scene_id: str) -> bool:
    """True if this Earth Engine scene is already stored for this lake, wherever its file was saved
    (data/backfill/..., data/scenes/..., or not_downloaded/...). Matching on the scene id, not the
    whole path, is what stops a scheduled run re-downloading a scene the backfill already has."""
    return conn.execute(
        "SELECT 1 FROM scene WHERE lake_id = ? AND (file_path LIKE ? OR file_path LIKE ?)",
        (lake_id, f"%/{scene_id}.tif", f"{NOT_DOWNLOADED_PREFIX}%/{scene_id}"),
    ).fetchone() is not None


# Optional observer for the web app's step-by-step live check. The nightly run passes none. An observer that
# fails must never change a run's outcome: its error is logged as a warning and the run goes on.
StepObserver = Callable[[str, dict], None]


def _emit(on_step: StepObserver | None, kind: str, **data: Any) -> None:
    if on_step is None:
        return
    try:
        on_step(kind, data)
    except Exception as exc:  # the display failing is not a pipeline failure
        log.warning("step observer failed on %s: %s: %s", kind, type(exc).__name__, exc)


def sha256_of(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_pipeline_once(db_path: str | Path, data_dir: str | Path, initial_since_date: date,
                      lakes: list[int] | None = None, client: Any = None,
                      until_date: date | None = None, dem_dir: str | Path | None = None,
                      on_step: StepObserver | None = None) -> RunResult:
    """One full run over every lake. Never raises for a stage failure: the error is written to
    run_log.errors and returned in RunResult.errors, so the caller can exit non-zero."""
    sign_in_needed = client is None
    if client is None:
        from sailab import earth_engine_client as client  # the real Earth Engine connection
    data_dir = Path(data_dir)
    dem_dir = Path(dem_dir) if dem_dir is not None else DEFAULT_DEM_DIR
    repo_root = Path(db_path).resolve().parent
    conn = db.connect(db_path)
    result = RunResult(run_id=db.start_run_log(conn))
    log.info("run %s started", result.run_id)

    try:
        if sign_in_needed:
            # Inside the try on purpose: a bad or expired key must end up in run_log.errors like any other
            # failure. (The first real backfill on 2026-11-08 failed because this call was missing: run_log 1.)
            account = client.initialize()
            log.info("signed in to Earth Engine as %s", account)
            _emit(on_step, "signed_in", account=account)
        lake_rows = {row["id"]: row for row in db.get_lakes(conn)}
        lake_ids = lakes if lakes is not None else sorted(lake_rows)
        state = load_resume_state(db_path)
        resuming = state.last_completed_lake_id is not None
        if resuming:
            note = f"resuming after lake {state.last_completed_lake_id} (previous run did not finish)"
            log.warning(note)
            result.notes.append(note)

        def process_lake(lake_id: int) -> None:
            if not resuming:
                save_resume_state(db_path, run.log)   # survives even a hard kill part way through this lake
            lake = lake_rows[lake_id]
            # A lake can start its history earlier than the default (Shishper: from 2019, for its outbursts).
            lake_start = dict(lake).get("history_since")
            initial = date.fromisoformat(lake_start) if lake_start else initial_since_date
            since = _since_date_for(conn, lake_id, initial)
            scenes = client.find_new_scenes(lake, since, until_date)
            log.info("%s: %d scenes listed after %s", lake["code"], len(scenes), since)
            _emit(on_step, "searched", lake=dict(lake), sensor="optical", since=since.isoformat(),
                  until=(until_date or datetime.now(timezone.utc).date()).isoformat(), scenes=[_scene_dict(s) for s in scenes])
            for scene in scenes:
                _process_scene(conn, client, lake, scene, data_dir, repo_root, result, on_step)
            if hasattr(client, "find_new_s1_scenes"):
                radar_since = _since_date_for(conn, lake_id, initial, "sentinel-1")
                radar_scenes = client.find_new_s1_scenes(lake, radar_since, until_date)
                log.info("%s: %d radar scenes listed after %s", lake["code"], len(radar_scenes), radar_since)
                _emit(on_step, "searched", lake=dict(lake), sensor="radar", since=radar_since.isoformat(),
                      until=(until_date or datetime.now(timezone.utc).date()).isoformat(),
                      scenes=[_scene_dict(s) for s in radar_scenes])
                slope = _slope_for(client, lake, dem_dir) if radar_scenes else None
                for scene in radar_scenes:
                    _process_radar_scene(conn, client, lake, scene, slope, data_dir, repo_root, result, on_step)
            else:
                log.info("%s: this client has no radar support; radar skipped", lake["code"])
            result.lakes_processed += 1

        run = ResumableRun(lakes=lake_ids, downloader=process_lake, log=state)
        try:
            run.run()
        except Exception:
            # A first failure leaves resume state so the next run picks up after the last finished lake.
            # A resumed run that fails again clears it: otherwise one lake failing every day would stop the
            # lakes before it from ever being checked again. Re-doing a lake is safe: stored scenes are skipped.
            if resuming:
                clear_resume_state(db_path)
            else:
                save_resume_state(db_path, run.log)
            raise
        clear_resume_state(db_path)
    except Exception as exc:  # recorded, never hidden
        result.errors = f"{type(exc).__name__}: {exc}\n" + "".join(traceback.format_exception(exc)[-6:])
        log.error("run %s failed: %s", result.run_id, result.errors)
    finally:
        db.finish_run_log(conn, result.run_id, result.lakes_processed, result.scenes_downloaded, result.errors)
        conn.close()
        log.info("run %s finished: %s", result.run_id, result)
    return result


def _scene_dict(scene) -> dict[str, Any]:
    return {"scene_id": scene.scene_id, "acquired_at": scene.acquired_at,
            "tile_cloud_percent": getattr(scene, "tile_cloud_percent", None),
            "lake_cloud_percent": getattr(scene, "lake_cloud_percent", None)}


def _process_scene(conn, client, lake, scene, data_dir: Path, repo_root: Path, result: RunResult,
                   on_step: StepObserver | None = None) -> None:
    raster = data_dir / lake["code"] / f"{scene.scene_id}.tif"
    try:
        stored_path = str(raster.resolve().relative_to(repo_root))
    except ValueError:
        stored_path = str(raster.resolve())
    skipped_path = f"{NOT_DOWNLOADED_PREFIX}{lake['code']}/{scene.scene_id}"
    if _already_recorded(conn, lake["id"], scene.scene_id):
        log.info("%s %s: already recorded, skipped", lake["code"], scene.scene_id)
        _emit(on_step, "already_recorded", sensor="optical", scene=_scene_dict(scene))
        return

    sensor = choose_sensor(scene.lake_cloud_percent, cloud_limit_percent=OPTICAL_CLOUD_LIMIT_PERCENT)
    _emit(on_step, "cloud_checked", sensor="optical", scene=_scene_dict(scene), limit=OPTICAL_CLOUD_LIMIT_PERCENT,
          decision="measure" if sensor != "radar" else "too_cloudy")
    if sensor == "radar":
        skipped_row = db.insert_scene(conn, lake["id"], "sentinel-2", scene.acquired_at, scene.lake_cloud_percent, skipped_path)
        _emit(on_step, "saved", sensor="optical", scene=_scene_dict(scene), scene_row=skipped_row,
              measurement_id=None, risk_id=None, note="too cloudy: recorded, not downloaded")
        result.scenes_recorded += 1
        log.info("%s %s: lake cloud %s%% > %s%% limit: too cloudy for optical, recorded but not downloaded (radar passes are listed separately)",
                 lake["code"], scene.scene_id, scene.lake_cloud_percent, OPTICAL_CLOUD_LIMIT_PERCENT)
        return

    client.download_scene_window(scene, lake, raster)
    scene_id = db.insert_scene(conn, lake["id"], "sentinel-2", scene.acquired_at, scene.lake_cloud_percent, stored_path)
    result.scenes_recorded += 1
    result.scenes_downloaded += 1
    # The checksum goes into the run log, so anyone can re-download the scene and confirm it is the same file.
    digest = sha256_of(raster)
    log.info("%s %s: downloaded %s sha256=%s", lake["code"], scene.scene_id, stored_path, digest)
    _emit(on_step, "downloaded", sensor="optical", scene=_scene_dict(scene), path=str(raster), stored_path=stored_path,
          sha256=digest, size_bytes=raster.stat().st_size)

    outcome = measure_scene(raster, lake)
    status, reason = outcome.status, outcome.reason
    if status == "insufficient_observation" and reason.startswith("centre pixel") and "is not water" in reason:
        why = no_lake_evidence(raster, lake, date.fromisoformat(scene.acquired_at[:10]))
        if why is not None:
            status, reason = "no_lake_detected", f"{reason}; {why}"
    measurement_id = db.insert_measurement(conn, scene_id, lake["id"], "optical", outcome.extent_ha, status)
    result.measurements += 1
    log.info("%s %s: %s %s (%s)", lake["code"], scene.scene_id, status, outcome.extent_ha, reason)
    _emit(on_step, "measured", sensor="optical", scene=_scene_dict(scene), path=str(raster), status=status,
          extent_ha=outcome.extent_ha, reason=reason, measurement_id=measurement_id)
    risk_id = None
    if status == "ok":   # an unobserved or vanished lake has no extent to compare, so nothing to score
        risk_id = _score(conn, lake, scene, measurement_id, outcome.extent_ha, "optical", result, on_step)
    _emit(on_step, "saved", sensor="optical", scene=_scene_dict(scene), scene_row=scene_id,
          measurement_id=measurement_id, risk_id=risk_id, note=None)


def _score(conn, lake, scene, measurement_id: int, extent_ha: float, sensor: str, result: RunResult,
           on_step: StepObserver | None = None) -> int:
    """Seasonal baseline score against the same lake's earlier values FROM THE SAME SENSOR only."""
    acquired_on = date.fromisoformat(scene.acquired_at[:10])
    # Only scenes from before this one: a backfilled 2024 scene must never be scored against 2025 data.
    history = [record for record in db.get_extent_history(conn, lake["id"], exclude_measurement_id=measurement_id,
                                                          sensor=sensor)
               if record.observed_on < acquired_on]
    same_month = [record for record in history if record.observed_on.month == acquired_on.month]
    same_month_years = {record.observed_on.year for record in same_month}
    scored_on = [{"date": r.observed_on.isoformat(), "extent_ha": r.extent_ha} for r in same_month]
    if len(same_month) < MIN_SAME_MONTH_VALUES or len(same_month_years) < MIN_SAME_MONTH_YEARS:
        # Check F: too little history for this month to say what "normal" is.
        risk_id = db.insert_risk_score(conn, lake["id"], measurement_id, "anomaly_detector", "insufficient_history", None, None)
        _emit(on_step, "scored", sensor=sensor, scene=_scene_dict(scene), extent_ha=extent_ha, status="insufficient_history",
              same_month=scored_on, years=len(same_month_years), baseline_ha=None, score=None, risk_id=risk_id)
        result.risk_scores += 1
        log.info("%s %s: %s risk insufficient_history (check F: %d earlier values for month %02d from %d years; "
                 "need %d from %d)", lake["code"], scene.scene_id, sensor, len(same_month), acquired_on.month,
                 len(same_month_years), MIN_SAME_MONTH_VALUES, MIN_SAME_MONTH_YEARS)
        return risk_id
    score = score_against_seasonal_baseline(history, acquired_on, extent_ha)
    risk_id = db.insert_risk_score(conn, lake["id"], measurement_id, "anomaly_detector",
                                   RISK_STATUS_FROM_RISK_MODULE[score.status], score.baseline_ha, score.deviation_score)
    _emit(on_step, "scored", sensor=sensor, scene=_scene_dict(scene), extent_ha=extent_ha,
          status=RISK_STATUS_FROM_RISK_MODULE[score.status], same_month=scored_on, years=len(same_month_years),
          baseline_ha=score.baseline_ha, score=score.deviation_score, risk_id=risk_id)
    result.risk_scores += 1
    log.info("%s %s: %s risk %s baseline=%s score=%s", lake["code"], scene.scene_id, sensor, score.status,
             score.baseline_ha, score.deviation_score)
    return risk_id


# ---------------------------------------------------------------------------
# Radar (Sentinel-1)
# ---------------------------------------------------------------------------
def _slope_for(client, lake, dem_dir: Path):
    """Slope grid for the lake window from its stored DEM (downloaded once, if missing)."""
    import rasterio

    from sailab.radar import slope_degrees

    dem_path = dem_dir / f"{lake['code']}_dem.tif"
    if not dem_path.is_file():
        client.download_dem_window(lake, dem_path)
        log.info("%s: DEM downloaded to %s sha256=%s", lake["code"], dem_path, sha256_of(dem_path))
    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype(float)
    dem[~np.isfinite(dem)] = np.nan
    return slope_degrees(dem, 10.0)


def _process_radar_scene(conn, client, lake, scene, slope, data_dir: Path, repo_root: Path, result: RunResult,
                         on_step: StepObserver | None = None) -> None:
    from sailab.radar import measure_radar_scene

    if _already_recorded(conn, lake["id"], scene.scene_id):
        log.info("%s %s: already recorded, skipped", lake["code"], scene.scene_id)
        _emit(on_step, "already_recorded", sensor="radar", scene=_scene_dict(scene))
        return
    raster = data_dir / lake["code"] / f"{scene.scene_id}.tif"
    try:
        stored_path = str(raster.resolve().relative_to(repo_root))
    except ValueError:
        stored_path = str(raster.resolve())
    client.download_s1_window(scene, lake, raster)
    scene_row = db.insert_scene(conn, lake["id"], "sentinel-1", scene.acquired_at, None, stored_path)
    result.scenes_recorded += 1
    result.scenes_downloaded += 1
    digest = sha256_of(raster)
    log.info("%s %s: downloaded %s sha256=%s", lake["code"], scene.scene_id, stored_path, digest)
    _emit(on_step, "downloaded", sensor="radar", scene=_scene_dict(scene), path=str(raster), stored_path=stored_path,
          sha256=digest, size_bytes=raster.stat().st_size)

    if slope is None or slope.shape != _raster_shape(raster):
        status, extent, reason = "insufficient_observation", None, "DEM grid does not match the radar window"
    else:
        outcome = measure_radar_scene(raster, lake, slope, RADAR_SLOPE_LIMIT_DEG)
        status, extent, reason = outcome.status, outcome.extent_ha, outcome.reason
    measurement_id = db.insert_measurement(conn, scene_row, lake["id"], "radar", extent, status)
    result.measurements += 1
    log.info("%s %s: radar %s %s (%s)", lake["code"], scene.scene_id, status, extent, reason)
    _emit(on_step, "measured", sensor="radar", scene=_scene_dict(scene), path=str(raster), status=status,
          extent_ha=extent, reason=reason, measurement_id=measurement_id)
    risk_id = None
    if status == "ok" and SCORE_RADAR:
        risk_id = _score(conn, lake, scene, measurement_id, extent, "radar", result, on_step)
    elif status == "ok":
        log.info("%s %s: radar not risk-scored (SCORE_RADAR is off: snowmelt errors, see pipeline.py)",
                 lake["code"], scene.scene_id)
        _emit(on_step, "not_scored", sensor="radar", scene=_scene_dict(scene), extent_ha=extent)
    _emit(on_step, "saved", sensor="radar", scene=_scene_dict(scene), scene_row=scene_row,
          measurement_id=measurement_id, risk_id=risk_id, note=None)


def _raster_shape(path: Path) -> tuple[int, int]:
    import rasterio

    with rasterio.open(path) as src:
        return src.height, src.width
