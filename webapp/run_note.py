"""The dashboard's note on the latest nightly run: what the run did, in plain words, lake by lake.

Two sources, both written by the run itself, nothing inferred:
  - the database: the run_log row (times, errors) and the scenes stored during the run (scene.downloaded_at falls
    between the run's start and finish), with their measurement and risk score;
  - the run's own log file, logs/runs/<start>Z.log, committed by the nightly job: how many images Earth Engine
    listed for each lake, which were already stored, and the measurement's reason (the database keeps no reason).
A run without a log file gets no note (the pipeline-runs table still lists it).

Only runs with a log file in logs/runs/ (not *_backfill.log) count as nightly runs here: a live check on this laptop
writes a run_log row to the working copy but no log file, so it never replaces the note.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

_LINE = re.compile(r"^\S+ \S+ (\w+) [\w.]+: (.*)$")
_STARTED = re.compile(r"^run (\d+) started$")
_LISTED = re.compile(r"^(\w+): (\d+) (radar )?scenes listed after (\S+)$")
_ALREADY = re.compile(r"^(\w+) (\S+): already recorded, skipped$")
_OPTICAL = re.compile(r"^(\w+) (\S+): (ok|insufficient_observation|no_lake_detected) (\S+) \((.*)\)$")
_RADAR = re.compile(r"^(\w+) (\S+): radar (ok|insufficient_observation) (\S+) \((.*)\)$")
_CLOUDY = re.compile(r"^(\w+) (\S+): lake cloud ([\d.]+)% > ([\d.]+)% limit")
_MODE = re.compile(r"^mode: (\S+)")


def nightly_logs(repo_root: Path) -> list[Path]:
    """Run logs, newest first (file names start with the run's UTC start time; *_backfill.log excluded)."""
    return sorted((repo_root / "logs" / "runs").glob("*Z.log"), reverse=True)


def parse_log(path: Path) -> dict[str, Any]:
    """What the run's own log says, keyed by lake code and scene id."""
    out: dict[str, Any] = {"run_id": None, "mode": None, "listed": {}, "already": {}, "reasons": {}, "cloud": {},
                           "errors": []}
    for raw in path.read_text(errors="replace").splitlines():
        m = _LINE.match(raw)
        if not m:
            continue
        level, msg = m.groups()
        if level == "ERROR":
            out["errors"].append(msg)
        if (s := _STARTED.match(msg)) and out["run_id"] is None:
            out["run_id"] = int(s.group(1))
        elif s := _MODE.match(msg):
            out["mode"] = s.group(1).rstrip(",")
        elif s := _LISTED.match(msg):
            code, n, radar, since = s.groups()
            out["listed"][(code, "radar" if radar else "optical")] = (int(n), since)
        elif s := _ALREADY.match(msg):
            out["already"].setdefault(s.group(1), []).append(s.group(2))
        elif s := _RADAR.match(msg):
            out["reasons"][s.group(2)] = s.group(5)
        elif s := _OPTICAL.match(msg):
            out["reasons"][s.group(2)] = s.group(5)
        elif s := _CLOUDY.match(msg):
            out["cloud"][s.group(2)] = float(s.group(3))
    return out


def _d(iso: str | None) -> str:
    """'2026-11-10' -> '10 Nov'."""
    if not iso:
        return "none"
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {d:%b}"


def _month(iso: str) -> str:
    return date.fromisoformat(iso[:10]).strftime("%B")


def _scene_line(r: sqlite3.Row, reasons: dict[str, str]) -> dict[str, Any]:
    """One stored scene, as one sentence."""
    sensor = "radar" if r["source"] == "sentinel-1" else "optical"
    sid = Path(r["file_path"]).name.removesuffix(".tif")
    day = _d(r["acquired_at"])
    item = {"sensor": sensor, "day": day, "scene_id": r["id"], "tone": "ok"}
    if sensor == "optical" and r["file_path"].startswith("not_downloaded/"):
        cloud = r["cloud_fraction"]
        item.update(tone="muted", scene_id=None,
                    text=f"new optical image ({day}): too cloudy over the lake"
                         + (f" ({cloud:.0f}%)" if cloud is not None else "") + ", recorded but not measured")
        return item
    status, ha = r["status"], r["extent_ha"]
    why = reasons.get(sid)
    if status == "ok":
        text = f"new {sensor} image ({day}): measured {ha:.2f} ha"
        if sensor == "radar":
            text += " (radar is not risk-scored yet)"
        elif r["rstatus"] == "ok" and r["deviation_score"] is not None:
            s = r["deviation_score"]
            m = _month(r["acquired_at"])
            text += (f", score {s:+.2f} " + (f"(within the usual range for {m})" if abs(s) < 2
                                              else f"(2 or more spreads from the usual {m} area)"))
            item["tone"] = "ok" if abs(s) < 2 else "warn"
        elif r["rstatus"] == "insufficient_history":
            text += f", no score yet (too few earlier {_month(r['acquired_at'])} values)"
    elif status == "no_lake_detected":
        item["tone"] = "error"
        text = f"new {sensor} image ({day}): clear, but no lake found at the centre"
    elif status == "insufficient_observation":
        item["tone"] = "muted"
        text = f"new {sensor} image ({day}): not measured" + (f" ({why})" if why else "")
    else:
        text = f"new {sensor} image ({day}): {status}"
    item["text"] = text
    return item


def build(conn: sqlite3.Connection, repo_root: Path, explain: Any = None) -> dict[str, Any] | None:
    """The note for the newest run that has a log file AND is in this database, or None when there is none.
    (A log pulled from GitHub before the GUI reloaded its database copy is skipped until the reload.)"""
    path = log = run = None
    for path in nightly_logs(repo_root):
        log = parse_log(path)
        if log["run_id"] is not None:
            run = conn.execute("SELECT * FROM run_log WHERE id = ?", (log["run_id"],)).fetchone()
        if run is not None:
            break
    if run is None:
        return None
    started, finished = run["started_at"], run["finished_at"] or run["started_at"]
    seconds = int((datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds())
    added = conn.execute(
        """SELECT s.id, s.lake_id, s.source, s.acquired_at, s.cloud_fraction, s.file_path,
                  m.status, m.extent_ha, r.status AS rstatus, r.deviation_score
           FROM scene s LEFT JOIN measurement m ON m.scene_id = s.id
           LEFT JOIN risk_score r ON r.measurement_id = m.id
           WHERE s.downloaded_at >= ? AND s.downloaded_at <= ? ORDER BY s.lake_id, s.source DESC, s.acquired_at""",
        (started, finished)).fetchall()
    # Newest image of each lake and sensor as the run left it (not as the database is today).
    newest = {(row["lake_id"], row["source"]): row["d"] for row in conn.execute(
        "SELECT lake_id, source, MAX(acquired_at) AS d FROM scene WHERE downloaded_at <= ? GROUP BY lake_id, source",
        (finished,))}

    def stored_outcome(lake_id: int, source: str) -> str:
        """What the newest stored image of this lake and sensor gave, e.g. 'too cloudy (71%)'."""
        r = conn.execute(
            """SELECT s.file_path, s.cloud_fraction, m.status, m.extent_ha FROM scene s
               LEFT JOIN measurement m ON m.scene_id = s.id
               WHERE s.lake_id = ? AND s.source = ? AND s.downloaded_at <= ?
               ORDER BY s.acquired_at DESC, s.id DESC LIMIT 1""", (lake_id, source, finished)).fetchone()
        if r is None:
            return "none stored"
        if r["file_path"].startswith("not_downloaded/"):
            return "too cloudy" + (f", {r['cloud_fraction']:.0f}% cloud" if r["cloud_fraction"] is not None else "")
        return {"ok": f"measured {r['extent_ha']:.2f} ha" if r["extent_ha"] is not None else "measured",
                "no_lake_detected": "no lake found",
                "insufficient_observation": "not measured"}.get(r["status"], r["status"] or "not measured")

    lakes = []
    for lake in conn.execute("SELECT id, code, name FROM lake ORDER BY id"):
        items = [_scene_line(r, log["reasons"]) for r in added if r["lake_id"] == lake["id"]]
        checked = any(k[0] == lake["code"] for k in log["listed"])
        if not items:
            opt = (newest.get((lake["id"], "sentinel-2")) or "")[:10]
            rad = (newest.get((lake["id"], "sentinel-1")) or "")[:10]
            if checked:
                parts = []
                for sensor, key in (("optical", "sentinel-2"), ("radar", "sentinel-1")):
                    n, since = log["listed"].get((lake["code"], sensor), (0, None))
                    day = newest.get((lake["id"], key))
                    stored = f"{_d(day)}: {stored_outcome(lake['id'], key)}" if day else "none stored"
                    parts.append(f"{sensor}: Earth Engine listed {n} after {_d(since)}, already stored (newest {stored})"
                                 if n else f"{sensor}: Earth Engine had no image after {_d(since)} "
                                 + (f"(newest stored {stored})" if day else "(none stored yet)"))
                text = "nothing new · " + " · ".join(parts)
            else:
                text = "not checked in this run" if log["listed"] else "nothing new"
            items = [{"text": text, "tone": "muted", "scene_id": None}]
        lakes.append({"code": lake["code"], "name": lake["name"], "items": items})

    new = len(added)
    measured = sum(1 for r in added if r["status"] == "ok")
    if run["errors"]:
        headline, tone = "The run stopped with an error", "error"
    elif new == 0:
        headline, tone = "Completed, nothing new", "info"
    else:
        headline, tone = (f"Completed: {new} new image{'s' if new != 1 else ''}, "
                          f"{measured} measured"), "ok"
    summary = None
    if new == 0 and not run["errors"]:
        opt = max((v for (_, src), v in newest.items() if src == "sentinel-2"), default=None)
        rad = max((v for (_, src), v in newest.items() if src == "sentinel-1"), default=None)
        summary = ("Earth Engine was checked for every lake. Its newest images were already stored"
                   + (f" (optical {_d(opt)}, {opt[11:16]} UTC; radar {_d(rad)}, {rad[11:16]} UTC)" if opt and rad else "")
                   + ", so no new satellite pass has arrived since then.")
    error_line = error_plain = None
    if run["errors"]:
        error_line = run["errors"].splitlines()[0]
        error_plain = explain(run["errors"]) if explain else None
    return {"run_id": run["id"], "started_at": started, "finished_at": run["finished_at"], "seconds": seconds,
            "mode": log["mode"], "scheduled": (log["mode"] or "").startswith("scheduled"),
            "headline": headline, "tone": tone, "summary": summary, "lakes": lakes,
            "new_scenes": new, "error_line": error_line, "error_plain": error_plain,
            "log_file": str(path.relative_to(repo_root)) if path else None}
