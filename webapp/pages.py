"""Builds what each page shows, entirely from sailab.queries over the read-only working copy.

Kept separate from the templates so that every number on a screen can be traced (and tested) to a
query result. Nothing here supplies a default value for missing data: missing stays None, and the
template says so in words.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sailab import queries
from webapp import charts, lake_info

STALE_AFTER_DAYS = 7          # the reference design's "data gap": no usable observation in 7 days
PKT = timezone(timedelta(hours=5))
HISTORY_PAGE_SIZE = 25
RANGES = {"12m": 365, "24m": 730, "all": None}


def _d(iso: str | date) -> date:
    if isinstance(iso, datetime):
        return iso.date()
    if isinstance(iso, date):
        return iso
    return datetime.fromisoformat(iso).date()


def lake_card(conn, lake: dict, today: date) -> dict[str, Any]:
    s = queries.lake_summary(conn, lake["id"], today)
    days = [d for d in (s["days_since_last_ok"], s["radar"]["days_since_last_ok"]) if d is not None]
    # Data gap: no usable measurement from EITHER sensor in the last STALE_AFTER_DAYS days.
    gap = not days or min(days) > STALE_AFTER_DAYS
    return {**lake, "summary": s, "data_gap": gap, "days_since_any_ok": min(days) if days else None,
            "sparkline": charts.sparkline(queries.recent_ok_extents(conn, lake["id"])),
            "radar_sparkline": charts.sparkline(queries.recent_ok_extents(conn, lake["id"], sensor="radar"))}


def dashboard(conn, today: date) -> dict[str, Any]:
    lakes = [lake_card(conn, l, today) for l in queries.list_lakes(conn)]
    totals = queries.database_totals(conn)
    first = conn.execute("SELECT MIN(acquired_at), MAX(acquired_at) FROM scene").fetchone()
    with_ok = [l for l in lakes if l["days_since_any_ok"] is not None]
    freshest = min(with_ok, key=lambda l: l["days_since_any_ok"]) if with_ok else None
    return {
        "lakes": lakes,
        "totals": totals,
        "first_scene": first[0],
        "last_scene": first[1],
        # share of OPTICAL scenes too cloudy (radar scenes have no cloud and must not dilute this)
        "too_cloudy_pct": (100.0 * totals["too_cloudy"] / totals["optical_scenes"]) if totals["optical_scenes"] else None,
        "measured_ok": totals["optical_ok"],
        "freshest": freshest,
        "stale_lakes": [l for l in lakes if l["data_gap"]],
        "latest_run": queries.latest_run(conn),
        "runs": queries.run_log(conn, 6),
        # One map per country: lakes 1,000 km apart on one grid would be dots in an empty frame.
        "maps": [(country, charts.location_map([{**l, "link": f"/lakes/{l['code']}"} for l in lakes if l.get("country", "Pakistan") == country]))
                 for country in dict.fromkeys(l.get("country", "Pakistan") for l in lakes)],
    }


def lake_detail(conn, lake: dict, today: date, range_key: str, page: int, repo: Path,
                work_dir: Path | None = None) -> dict[str, Any]:
    card = lake_card(conn, lake, today)
    history = queries.lake_history(conn, lake["id"])
    days = RANGES.get(range_key, None) if range_key in RANGES else None
    range_key = range_key if range_key in RANGES else "all"
    end = today
    start = (end - timedelta(days=days)) if days else (_d(history[0]["acquired_at"]) if history else end)
    chart = charts.extent_chart(history, start, end) if history else None

    sensors = {}
    for sensor, summary in (("optical", card["summary"]), ("radar", card["summary"]["radar"])):
        score = summary["latest_risk_score"]
        inputs = None
        if score is not None:
            inputs = queries.same_month_inputs(conn, lake["id"], _d(score["acquired_at"]), score["measurement_id"], sensor)
        latest_ok = summary["latest_ok_measurement"]
        image = None
        if latest_ok is not None:
            on_disk = (repo / latest_ok["file_path"]).is_file() or (work_dir is not None and (work_dir / latest_ok["file_path"]).is_file())
            image = {"available": on_disk, "file_path": latest_ok["file_path"],
                     "acquired_at": latest_ok["acquired_at"], "extent_ha": latest_ok["extent_ha"]}
        sensors[sensor] = {"score": score, "score_inputs": inputs, "image": image, "summary": summary}

    newest_first = list(reversed(history))
    pages = max(1, -(-len(newest_first) // HISTORY_PAGE_SIZE))
    page = min(max(page, 1), pages)
    rows = newest_first[(page - 1) * HISTORY_PAGE_SIZE: page * HISTORY_PAGE_SIZE]
    return {"lake": card, "chart": chart, "range_key": range_key, "chart_start": start, "chart_end": end,
            "sensors": sensors, "score": sensors["optical"]["score"], "score_inputs": sensors["optical"]["score_inputs"],
            "image": sensors["optical"]["image"], "log_rows": rows,
            "info": lake_info.build(lake, history, card["summary"]["latest_risk_score"], card["summary"]["latest_judged"],
                                    repo / "data" / "dem"),
            "page": page, "pages": pages, "scene_count": len(history),
            "ok_in_range": sum(1 for r in history if r["measurement_status"] == "ok" and r["sensor"] == "optical"
                               and start <= _d(r["acquired_at"]) <= end),
            "radar_ok_in_range": sum(1 for r in history if r["measurement_status"] == "ok" and r["sensor"] == "radar"
                                     and start <= _d(r["acquired_at"]) <= end)}


def scene_record(conn, scene_id: int) -> dict[str, Any] | None:
    """One scene with its lake, its stored measurement and its risk score (None if there is no such scene)."""
    row = conn.execute(
        f"""SELECT s.id AS scene_id, s.lake_id, s.source, s.acquired_at, s.cloud_fraction, s.file_path, s.downloaded_at,
                   s.file_path LIKE '{queries.NOT_DOWNLOADED_PREFIX}%' AS too_cloudy,
                   m.id AS measurement_id, m.sensor, m.status AS measurement_status, m.extent_ha, m.measured_at,
                   r.status AS risk_status, r.baseline_ha, r.deviation_score
            FROM scene s LEFT JOIN measurement m ON m.scene_id = s.id
            LEFT JOIN risk_score r ON r.measurement_id = m.id WHERE s.id = ?""", (scene_id,)).fetchone()
    if row is None:
        return None
    rec = dict(row)
    rec["lake"] = next(l for l in queries.list_lakes(conn) if l["id"] == rec["lake_id"])
    # neighbours in this lake's log (oldest first, same order as lake_history), for previous/next links
    ids = [r[0] for r in conn.execute("SELECT id FROM scene WHERE lake_id = ? ORDER BY acquired_at, id", (rec["lake_id"],))]
    i = ids.index(scene_id)
    rec["older_id"] = ids[i - 1] if i > 0 else None
    rec["newer_id"] = ids[i + 1] if i + 1 < len(ids) else None
    return rec


def scene_quality(row: dict) -> tuple[str, str]:
    """(chip style, words) for one observation-log row, from its stored status only."""
    if row["too_cloudy"]:
        return "muted", "Not downloaded: cloud over lake"
    if row["measurement_status"] == "ok":
        return "ok", "Usable"
    if row["measurement_status"] == "no_lake_detected":
        return "error", "No lake found at the centre"
    if row["measurement_status"] == "insufficient_observation":
        return "warn", ("Refused by radar checks" if row.get("source") == "sentinel-1" else "Refused by quality checks")
    return "muted", "No measurement recorded"


# --- template filters ------------------------------------------------------------------------
def fmt_date(iso: str | None) -> str:
    return "—" if not iso else _d(iso).strftime("%d %b %Y")


def fmt_utc_time(iso: str | None) -> str:
    if not iso:
        return "—"
    t = datetime.fromisoformat(iso).astimezone(timezone.utc)
    return t.strftime("%d %b %Y, %H:%M UTC")


def fmt_pkt(iso: str | None) -> str:
    if not iso:
        return "—"
    return datetime.fromisoformat(iso).astimezone(PKT).strftime("%d %b %Y, %H:%M PKT")


def fmt_ha(v: float | None) -> str:
    return "—" if v is None else f"{v:.2f} ha"


def fmt_score(v: float | None) -> str:
    return "—" if v is None else f"{v:+.2f}".replace("-", "−")
