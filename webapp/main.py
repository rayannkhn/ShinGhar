"""SailAb GLOF web app: read-only views over a working copy of sailab_glof.db.

Why a copy (decided with the project owner, 2026-11-09): the nightly GitHub Actions run commits its
own sailab_glof.db. If this laptop also wrote to that file (the live-trigger button does write), the two
binary copies could never be merged. So at start-up the app copies the repository's database to
.webapp/ and works only on that copy. The copy's origin (file checksum, git commit, time) is recorded
and shown on every page, so a viewer can tell exactly which published state they are looking at.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sailab import queries
from webapp import images, pages, scene_view
from webapp import run_note
from webapp.live import LiveChecker, explain_error

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DB = REPO / "sailab_glof.db"
DEFAULT_WORK_DIR = REPO / ".webapp"
WORKING_COPY_NAME = "sailab_glof_working_copy.db"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def make_working_copy(source_db: Path, work_dir: Path) -> dict[str, Any]:
    """Copy the source database and describe exactly where the copy came from."""
    if not source_db.is_file():
        raise FileNotFoundError(f"source database not found: {source_db}")
    work_dir.mkdir(parents=True, exist_ok=True)
    copy = work_dir / WORKING_COPY_NAME
    # Copy to a temporary name, then rename: a page reading the old copy at that moment keeps reading it whole.
    tmp = work_dir / (WORKING_COPY_NAME + ".tmp")
    shutil.copy2(source_db, tmp)
    os.replace(tmp, copy)
    rel = os.path.relpath(source_db, REPO)
    committed_db_status = _git("status", "--porcelain", "--", rel)
    return {
        "source_db": str(source_db),
        "source_sha256": _sha256(source_db),
        "working_copy": str(copy),
        "copied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git("rev-parse", "--short", "HEAD"),
        "git_commit_time": _git("log", "-1", "--format=%cI"),
        "git_commit_subject": _git("log", "-1", "--format=%s"),
        # True if the source file differs from what is committed (e.g. a local run wrote to it):
        "source_differs_from_commit": None if committed_db_status is None else committed_db_status != "",
    }


def create_app(source_db: Path | None = None, work_dir: Path | None = None,
               today: Callable[[], Any] | None = None, repo: Path | None = None,
               live_runner: Callable[..., Any] | None = None, auto_reload_seconds: float | None = None,
               esa_lookup: Callable[[str, str], dict] | None = None) -> FastAPI:
    source_db = Path(source_db or os.environ.get("SAILAB_SOURCE_DB", DEFAULT_SOURCE_DB))
    work_dir = Path(work_dir or os.environ.get("SAILAB_WORK_DIR", DEFAULT_WORK_DIR))
    today = today or (lambda: datetime.now(timezone.utc).date())

    app = FastAPI(title="SailAb GLOF", docs_url="/api/docs", redoc_url=None)
    repo_root = Path(repo or os.environ.get("SAILAB_REPO", REPO))   # where scene file paths are resolved

    def fresh_copy() -> None:
        """(Re)make the working copy from the source database. Used at start-up and by POST /reload."""
        app.state.provenance = make_working_copy(source_db, work_dir)
        copy = Path(app.state.provenance["working_copy"])
        # A fresh copy means earlier live checks (and any half-finished one's resume file) no longer apply.
        for stale in (work_dir / "live_checks.json", copy.with_suffix(".resume.json")):
            stale.unlink(missing_ok=True)
        app.state.live = LiveChecker(copy, work_dir / "live_scenes", work_dir / "live_checks.json", runner=live_runner,
                                     repo_root=repo_root, find_file=lambda rel: scene_file(rel), esa=esa_lookup)

    fresh_copy()
    working_copy = Path(app.state.provenance["working_copy"])     # same path after every reload
    reload_lock = threading.Lock()      # a reload and the start of a live check never overlap

    def source_is_newer() -> bool:
        """True when sailab_glof.db on disk (e.g. after git pull) is not the file these pages copied."""
        try:
            return _sha256(source_db) != app.state.provenance["source_sha256"]
        except OSError:
            return False

    @contextmanager
    def read_only() -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(f"file:{working_copy}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    app.state.read_only = read_only

    def lake_or_404(conn: sqlite3.Connection, code: str) -> dict[str, Any]:
        lake = queries.get_lake(conn, code)
        if lake is None:
            raise HTTPException(status_code=404, detail=f"no lake with code {code!r} in the database")
        return lake

    @app.get("/api/provenance")
    def provenance() -> dict[str, Any]:
        return {**app.state.provenance, "auto_reload": app.state.auto_reload}

    @app.get("/api/lakes")
    def lakes() -> list[dict[str, Any]]:
        with read_only() as conn:
            return [{**lake, "summary": queries.lake_summary(conn, lake["id"], today())}
                    for lake in queries.list_lakes(conn)]

    @app.get("/api/lakes/{code}")
    def lake(code: str) -> dict[str, Any]:
        with read_only() as conn:
            found = lake_or_404(conn, code)
            return {**found, "summary": queries.lake_summary(conn, found["id"], today())}

    @app.get("/api/lakes/{code}/history")
    def lake_history(code: str) -> list[dict[str, Any]]:
        with read_only() as conn:
            return queries.lake_history(conn, lake_or_404(conn, code)["id"])

    @app.get("/api/run-log")
    def run_log(limit: int = 20) -> list[dict[str, Any]]:
        with read_only() as conn:
            return queries.run_log(conn, limit)

    @app.get("/api/run-log/latest")
    def run_log_latest() -> dict[str, Any]:
        with read_only() as conn:
            row = queries.latest_run(conn)
        if row is None:
            raise HTTPException(status_code=404, detail="run_log is empty")
        return row

    @app.get("/api/totals")
    def totals() -> dict[str, int]:
        with read_only() as conn:
            return queries.database_totals(conn)

    # --- HTML pages -------------------------------------------------------------------------
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    templates.env.filters.update({"date": pages.fmt_date, "utc_time": pages.fmt_utc_time, "pkt": pages.fmt_pkt,
                                  "ha": pages.fmt_ha, "score": pages.fmt_score,
                                  "month": lambda iso: datetime.fromisoformat(iso).strftime("%B")})
    templates.env.globals.update({"quality": pages.scene_quality, "stale_days": pages.STALE_AFTER_DAYS})
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

    def render(request: Request, name: str, nav: str, d: dict[str, Any]) -> HTMLResponse:
        with read_only() as conn:
            nav_lakes = queries.list_lakes(conn)
        return templates.TemplateResponse(request, name, {"d": d, "nav": nav, "nav_lakes": nav_lakes,
                                                          "provenance": app.state.provenance,
                                                          "live_run_ids": app.state.live.live_run_ids(),
                                                          "source_is_newer": source_is_newer() and _valid_sqlite(source_db),
                                                          "auto_reload_on": app.state.auto_reload["interval_s"] > 0,
                                                          "auto_reload_s": app.state.auto_reload["interval_s"]})

    @app.get("/", response_class=HTMLResponse)
    def dashboard_page(request: Request) -> HTMLResponse:
        with read_only() as conn:
            d = pages.dashboard(conn, today())
            d["run_note"] = run_note.build(conn, repo_root, explain_error)
        return render(request, "dashboard.html", "dashboard", d)

    @app.get("/lakes/{code}", response_class=HTMLResponse)
    def lake_page(request: Request, code: str, range: str = "all", page: int = 1) -> HTMLResponse:
        with read_only() as conn:
            d = pages.lake_detail(conn, lake_or_404(conn, code), today(), range, page, repo_root, work_dir)
        return render(request, "lake.html", code, d)

    # Design previews: static templates with the design's own sample data. They read nothing from the
    # database. The app's only non-GET routes are POST /live/check and POST /reload; both write to the
    # working copy in .webapp/ only (a test checks this), so nothing on the previews can act.
    previews = {"confirm-advisory": ("preview_confirm_advisory.html", "p-confirm"),
                "delivery-status": ("preview_delivery_status.html", "p-delivery"),
                "risk-threshold": ("preview_risk_threshold.html", "p-threshold")}

    @app.get("/preview/{name}", response_class=HTMLResponse)
    def preview_page(request: Request, name: str) -> HTMLResponse:
        if name not in previews:
            raise HTTPException(status_code=404, detail=f"no design preview called {name!r}")
        template, nav = previews[name]
        return render(request, template, nav, {})

    @app.get("/lakes/{code}/latest-radar.png")
    def lake_latest_radar(code: str) -> FileResponse:
        with read_only() as conn:
            found = lake_or_404(conn, code)
            latest = queries.lake_summary(conn, found["id"], today())["radar"]["latest_ok_measurement"]
        if latest is None:
            raise HTTPException(status_code=404, detail=f"{code} has no usable radar measurement yet")
        tif = repo_root / latest["file_path"]
        if not tif.is_file() and (work_dir / latest["file_path"]).is_file():
            tif = work_dir / latest["file_path"]
        dem = repo_root / "data" / "dem" / f"{code}_dem.tif"
        if not tif.is_file() or not dem.is_file():
            raise HTTPException(status_code=404, detail=f"radar or DEM file not on this machine: {latest['file_path']}")
        png = work_dir / "images" / f"{code}_{tif.stem}_radar.png"
        if not png.is_file():
            images.render_radar_png(tif, found, dem, png)
        return FileResponse(png, media_type="image/png")

    # --- live check and reload: the only routes that change anything, and only in .webapp/ -------
    @app.get("/live", response_class=HTMLResponse)
    def live_page(request: Request) -> HTMLResponse:
        live = app.state.live
        return render(request, "live.html", "live", {"state": live.snapshot(), "history": list(reversed(live.history))})

    @app.get("/live/state.json")
    def live_state() -> JSONResponse:
        """What the Live check page polls while a check runs: status and the step cards so far."""
        st = app.state.live.snapshot()
        return JSONResponse({k: st.get(k) for k in ("status", "started_at", "finished_at", "seconds", "lake_code",
                                                     "lake_name", "steps", "explanation", "errors")})

    @app.get("/live/steps/{folder}/{name}")
    def live_step_file(folder: str, name: str) -> FileResponse:
        base = (work_dir / "live_steps").resolve()
        path = (base / folder / name).resolve()
        if base not in path.parents or not path.is_file() or path.suffix not in (".png", ".gif"):
            raise HTTPException(status_code=404, detail="no such picture")
        return FileResponse(path, media_type="image/gif" if path.suffix == ".gif" else "image/png")

    @app.post("/live/check")
    async def live_check(request: Request) -> RedirectResponse:
        fields = parse_qs((await request.body()).decode("utf-8", "replace"))
        code = (fields.get("lake") or [request.query_params.get("lake", "")])[0].strip().upper()
        with reload_lock:
            try:
                app.state.live.start(code)       # does nothing if a check is already running
            except ValueError:
                raise HTTPException(status_code=400, detail=f"unknown lake {code!r}")
        return RedirectResponse("/live", status_code=303)

    def reload_now() -> bool:
        """Copy sailab_glof.db again. False (nothing done) while a live check is writing to the working copy."""
        with reload_lock:
            if app.state.live.snapshot().get("status") == "running":
                return False
            fresh_copy()
            analyses.clear()
            return True

    @app.post("/reload")
    def reload_data() -> RedirectResponse:
        """Copy sailab_glof.db again (after a git pull). Reads the source file only; writes only .webapp/."""
        if not reload_now():
            raise HTTPException(status_code=409, detail="a live check is running; reload when it has finished")
        return RedirectResponse("/", status_code=303)

    # --- automatic reload (decided with the project owner, 2026-11-10) ------------------------------
    # An hourly `git pull --ff-only` (the owner's cron job, outside this app) updates sailab_glof.db; this
    # notices and reloads by itself. Safety: the new file must be unchanged for two checks in a row (so a
    # half-written file is never copied) and must pass SQLite's own integrity check; never during a live check.
    # Every decision is kept in app.state.auto_reload and shown at /api/provenance.
    auto = {"interval_s": float(auto_reload_seconds if auto_reload_seconds is not None
                                else os.environ.get("SAILAB_AUTO_RELOAD_SECONDS", 60)),
            "pending_sha256": None, "last_check": None, "last_result": None, "last_reload": None}
    app.state.auto_reload = auto

    def _valid_sqlite(path: Path) -> bool:
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                return conn.execute("PRAGMA quick_check").fetchone()[0] == "ok" and \
                    conn.execute("SELECT COUNT(*) FROM scene").fetchone() is not None
            finally:
                conn.close()
        except sqlite3.Error:
            return False

    def auto_reload_tick() -> str:
        """One check. Returns what it did: current / waiting / skipped: ... / reloaded."""
        auto["last_check"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            sha = _sha256(source_db)
        except OSError as exc:
            result = f"skipped: source unreadable ({exc})"
        else:
            if sha == app.state.provenance["source_sha256"]:
                auto["pending_sha256"], result = None, "current"
            elif auto["pending_sha256"] != sha:
                auto["pending_sha256"], result = sha, "waiting"          # changed: confirm on the next check
            elif not _valid_sqlite(source_db):
                result = "skipped: source is not a valid database"
            elif not reload_now():
                result = "skipped: a live check is running"
            else:
                auto["pending_sha256"], auto["last_reload"], result = None, auto["last_check"], "reloaded"
        auto["last_result"] = result
        return result

    app.state.auto_reload_tick = auto_reload_tick

    if auto["interval_s"] > 0:
        def _watch() -> None:
            while not stop.wait(auto["interval_s"]):
                try:
                    auto_reload_tick()
                except Exception as exc:  # never let the watcher die silently
                    auto["last_result"] = f"error: {type(exc).__name__}: {exc}"
        stop = threading.Event()
        app.state.auto_reload_stop = stop
        threading.Thread(target=_watch, name="auto-reload", daemon=True).start()

    # --- one scene, re-measured from its own file ---------------------------------------------
    analyses: dict[tuple, Any] = {}

    def scene_file(file_path: str) -> Path | None:
        for base in (repo_root, work_dir):             # repository, or downloaded by a live check here
            if (base / file_path).is_file():
                return base / file_path
        return None

    def scene_or_404(conn: sqlite3.Connection, scene_id: int) -> dict[str, Any]:
        row = pages.scene_record(conn, scene_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"no scene with id {scene_id} in the database")
        return row

    def analysis_for(rec: dict[str, Any]) -> tuple[Any, str | None]:
        """(SceneAnalysis or None, why not). Cached per file and modification time."""
        if rec["too_cloudy"]:
            return None, "not_downloaded"
        tif = scene_file(rec["file_path"])
        if tif is None:
            return None, "file_missing"
        dem = repo_root / "data" / "dem" / f"{rec['lake']['code']}_dem.tif"
        if rec["source"] == "sentinel-1" and not dem.is_file():
            return None, "dem_missing"
        key = (rec["lake"]["code"], str(tif), tif.stat().st_mtime_ns)
        if key not in analyses:
            try:
                analyses[key] = (scene_view.analyse_radar(tif, rec["lake"], dem) if rec["source"] == "sentinel-1"
                                 else scene_view.analyse_optical(tif, rec["lake"], date.fromisoformat(rec["acquired_at"][:10])), None)
            except Exception as exc:     # shown on the page as it is; nothing is filled in
                analyses[key] = (None, f"error: {type(exc).__name__}: {exc}")
        return analyses[key]

    @app.get("/scenes/{scene_id}", response_class=HTMLResponse)
    def scene_page(request: Request, scene_id: int) -> HTMLResponse:
        with read_only() as conn:
            rec = scene_or_404(conn, scene_id)
        a, why_not = analysis_for(rec)
        d = {"s": rec, "a": a, "why_not": why_not, "cloud_limit": scene_view.CLOUD_LIMIT_PERCENT,
             "pictures": scene_view.PICTURES.get(rec["source"], ()),
             "agreement": scene_view.compare(rec["measurement_status"], rec["extent_ha"], a) if a else None,
             "from_live_check": scene_file(rec["file_path"]) is not None and not (repo_root / rec["file_path"]).is_file()}
        return render(request, "scene.html", rec["lake"]["code"], d)

    @app.get("/scenes/{scene_id}/{kind}.png")
    def scene_picture(scene_id: int, kind: str) -> FileResponse:
        with read_only() as conn:
            rec = scene_or_404(conn, scene_id)
        if kind not in scene_view.PICTURES.get(rec["source"], ()):
            raise HTTPException(status_code=404, detail=f"no {kind!r} picture for a {rec['source']} scene")
        a, why_not = analysis_for(rec)
        if a is None or kind not in a.pictures:
            raise HTTPException(status_code=404, detail=f"picture not available: {why_not or 'no SCL band in this file'}")
        tif = scene_file(rec["file_path"])
        png = work_dir / "images" / "scenes" / f"{rec['lake']['code']}_{tif.stem}_{tif.stat().st_mtime_ns}_{kind}.png"
        if not png.is_file():
            scene_view.save_png(a.pictures[kind], png)
        return FileResponse(png, media_type="image/png")

    @app.get("/lakes/{code}/latest-image.png")
    def lake_latest_image(code: str) -> FileResponse:
        with read_only() as conn:
            found = lake_or_404(conn, code)
            latest = queries.lake_summary(conn, found["id"], today())["latest_ok_measurement"]
        if latest is None:
            raise HTTPException(status_code=404, detail=f"{code} has no usable measurement yet")
        tif = repo_root / latest["file_path"]
        if not tif.is_file() and (work_dir / latest["file_path"]).is_file():
            tif = work_dir / latest["file_path"]          # downloaded by a live check on this laptop
        if not tif.is_file():
            raise HTTPException(status_code=404, detail=f"image file not on this machine: {latest['file_path']}")
        png = work_dir / "images" / f"{code}_{tif.stem}.png"
        if not png.is_file():
            images.render_scene_png(tif, found, png)
        return FileResponse(png, media_type="image/png")

    return app
