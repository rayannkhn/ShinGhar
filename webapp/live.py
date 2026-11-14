"""The live-check button: one real pipeline run for one chosen lake, started from the web page, shown step by step.

It calls the same run_pipeline_once() the nightly GitHub Actions run uses, with the real Earth Engine
connection, against the app's WORKING COPY of the database (never the published sailab_glof.db).
Whatever happens is shown as it happened: each step as a card (webapp/walkthrough.py), the run's own result
object and its own log lines. There is no fallback or canned result: if the run fails, the page shows the real
error. When the run finds no new scene for a sensor, the lake's latest stored scene is replayed through the same
steps, every card marked as a replay; a replay writes nothing.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import traceback
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Same start date as scripts/run_once.py. Only used for a lake with no stored scene (every seeded lake has some).
INITIAL_SINCE_DATE = date(2022, 12, 31)


def explain_error(error: str | None) -> str | None:
    """One plain sentence for the top of a failed check, chosen from the REAL error text. The full error is
    always shown underneath; this only says, in words, which kind of failure it was."""
    if not error:
        return None
    e = error.lower()
    if any(s in e for s in ("connectionerror", "max retries", "failed to establish", "nameresolution",
                            "name or service not known", "temporary failure in name resolution", "timed out",
                            "network is unreachable", "proxyerror")):
        return "Could not reach Google's servers: this laptop has no internet connection, or the network is blocking it."
    if any(s in e for s in ("quota", "too many", "capacity exceeded", "429", "rate limit")):
        return "Earth Engine declined the request because of a usage limit. Trying again later usually works."
    if any(s in e for s in ("invalid_grant", "invalid jwt", "unauthorized", "401")):
        return "Earth Engine refused the sign-in: the service-account key may have been revoked or replaced."
    if any(s in e for s in ("permission", "403", "denied")):
        return "Earth Engine denied permission for part of the check."
    if "no service-account key" in e:
        return "No Earth Engine key was found on this laptop."
    return "The pipeline reported an error."


class _Capture(logging.Handler):
    """Collects the pipeline's own log lines for display."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        stamp = datetime.fromtimestamp(record.created, timezone.utc).strftime("%H:%M:%S")
        self.lines.append(f"{stamp} {record.levelname} {record.getMessage()}")


class LiveChecker:
    """Runs one check at a time in a background thread and keeps its state for the page to show."""

    def __init__(self, db_path: Path, data_dir: Path, state_file: Path,
                 runner: Callable[..., Any] | None = None, repo_root: Path | None = None,
                 find_file: Callable[[str], Path | None] | None = None,
                 esa: Callable[[str, str], dict] | None = None) -> None:
        self.db_path, self.data_dir, self.state_file = db_path, data_dir, state_file
        self.steps_dir = state_file.parent / "live_steps"
        self.repo_root = repo_root or Path(__file__).resolve().parent.parent
        self.find_file = find_file or (lambda rel: (self.repo_root / rel) if (self.repo_root / rel).is_file() else None)
        self.esa = esa
        self.walkthrough: Any = None
        self._runner = runner
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.state: dict[str, Any] = {"status": "idle"}
        self.history: list[dict[str, Any]] = self._load_history()

    # -- state ------------------------------------------------------------------------------
    def _load_history(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.state_file.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def live_run_ids(self) -> set[int]:
        return {h["run_id"] for h in self.history if h.get("run_id") is not None}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self.state)
            walk = self.walkthrough
        state["steps"] = walk.steps() if walk is not None else []
        return state

    # -- running ----------------------------------------------------------------------------
    def lake(self, code: str) -> dict[str, Any] | None:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM lake WHERE code = ?", (code,)).fetchone()
        finally:
            conn.close()
        return dict(row) if row else None

    def start(self, lake_code: str) -> bool:
        """Start a check of one lake unless one is already running. Returns False if one was already running.
        Raises ValueError for an unknown lake code."""
        from webapp.walkthrough import Walkthrough, esa_lookup

        lake = self.lake(lake_code)
        if lake is None:
            raise ValueError(f"unknown lake {lake_code!r}")
        with self._lock:
            if self.state.get("status") == "running":
                return False
            check_no = len(self.history) + 1
            started = datetime.now(timezone.utc)
            folder = f"{started:%Y%m%dT%H%M%S}_{lake['code']}"
            self.walkthrough = Walkthrough(self.steps_dir / folder, f"/live/steps/{folder}", lake, self.repo_root,
                                           self.find_file, self.esa or esa_lookup)
            self.state = {"status": "running", "started_at": started.isoformat(timespec="seconds"),
                          "lake_code": lake["code"], "lake_name": lake["name"], "check_no": check_no, "log": []}
            self._thread = threading.Thread(target=self._run, name="live-check", daemon=True)
            self._thread.start()
            return True

    def wait(self, timeout: float | None = None) -> None:
        """For tests and scripts: block until the current check has finished."""
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        capture = _Capture()
        pipeline_log = logging.getLogger("sailab.pipeline")
        pipeline_log.addHandler(capture)
        previous_level = pipeline_log.level
        pipeline_log.setLevel(logging.INFO)
        result, crash = None, None
        try:
            runner = self._runner
            if runner is None:
                from sailab.pipeline import run_pipeline_once as runner
            walk = self.walkthrough
            result = runner(self.db_path, self.data_dir, INITIAL_SINCE_DATE,
                            lakes=[walk.lake["id"]], on_step=walk.on_step)
            if not (result is not None and result.errors):
                # No new scene measured for a sensor: replay the latest stored one (read-only), clearly marked.
                conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
                conn.row_factory = sqlite3.Row
                try:
                    for sensor in ("optical", "radar"):
                        if not walk.measured[sensor]:
                            try:
                                walk.replay(conn, sensor)
                            except Exception as exc:  # a replay failing is shown, but is not a pipeline failure
                                walk.replay_failed(sensor, f"{type(exc).__name__}: {exc}")
                finally:
                    conn.close()
        except Exception as exc:  # run_pipeline_once records its own errors; this is for anything outside it
            crash = f"{type(exc).__name__}: {exc}\n" + "".join(traceback.format_exception(exc)[-4:])
        finally:
            pipeline_log.removeHandler(capture)
            pipeline_log.setLevel(previous_level)
        finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
        outcome = asdict(result) if result is not None else None
        errors = crash or (outcome or {}).get("errors")
        if errors:
            status = "failed"
        elif outcome and outcome["scenes_recorded"] == 0:
            status = "no_new_scene"
        else:
            status = "new_scenes"
        with self._lock:
            seconds = int((datetime.fromisoformat(finished) - datetime.fromisoformat(self.state["started_at"])).total_seconds())
            self.state = {**self.state, "status": status, "finished_at": finished, "result": outcome,
                          "errors": errors, "explanation": explain_error(errors), "seconds": seconds,
                          "log": capture.lines}
            self.history.append({"run_id": (outcome or {}).get("run_id"), "status": status,
                                 "lake_code": self.state.get("lake_code"),
                                 "started_at": self.state["started_at"], "finished_at": finished})
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(self.history, indent=1))
