"""ShinGhar pages (/shinghar, /shinghar/villages|forest|lakes|alerts|method), with their OWN layout and stylesheet
(templates/sg/, static/shinghar.css), separate from the SailAb GLOF (FYP) pages. They read ONLY the cached files in data/shinghar/ (built by
shinghar/build_valley.py) and the read-only SailAb working copy (lake area charts). Works offline.

The only thing this page writes is the alert review state (data/shinghar/alerts.json). Nothing is ever sent.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sailab import queries
from shinghar import alerts as A
from shinghar import forest as F
from shinghar import glacier as G
from shinghar import risk as R
from webapp import charts

ALLOWED_FILES = {"forest_patches.geojson": "application/geo+json", "lake_paths.geojson": "application/geo+json",
                 "forest_overview.png": "image/png", "forest_patches.csv": "text/csv",
                 "forest_visual_check.png": "image/png", "site_risk.json": "application/json"}
COMPONENT_LABELS = {"lake_growth": "Lake growth", "lake_anomaly": "Lake anomaly", "flood_path": "Near lake outflow path",
                    "forest_loss_upslope": "Vegetation loss upslope (forest areas)", "loss_slope": "Slope of that loss",
                    "site_area": "Size of the loss site", "village_below": "Village below the site",
                    "near_water": "Near surface water"}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


PAGES = {"villages": "sg/villages.html", "forest": "sg/forest.html", "lakes": "sg/lakes.html",
         "alerts": "sg/alerts.html", "method": "sg/method.html"}


def _slug(name: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-")


def headline(r: dict) -> str:
    """Short summary of what adds most to a village's score, from the same numbers as its reasons."""
    n = len(r.get("upstream_lakes") or [])
    short = {
        "flood_path": lambda v: f"on the outflow path of {n} monitored lake{'s' if n != 1 else ''}",
        "forest_loss_upslope": lambda v: f"{v:.1f} ha vegetation loss upslope",
        "loss_slope": lambda v: f"loss on {v:.0f}° slopes",
        "lake_growth": lambda v: f"upstream lake {v:+.1f} %/yr",
        "lake_anomaly": lambda v: f"upstream lake z {v:+.1f}",
    }
    parts = [short[c["name"]](c["raw"]) for c in sorted(r["components"], key=lambda c: -c["points"])
             if c["points"] > 0 and c["raw"] is not None][:3]
    return " · ".join(parts) if parts else "no measured factor adds to the score"


def page_data(data_dir: Path, conn, today: date, with_charts: bool = True) -> dict[str, Any]:
    valley = _load(data_dir / "valley.json")
    d: dict[str, Any] = {"valley": valley, "built": (data_dir / "build_log.json").exists()}
    if valley is None or not d["built"]:
        return d
    d["build_log"] = _load(data_dir / "build_log.json")
    d["forest"] = _load(data_dir / "forest_agreement.json")
    patches = (_load(data_dir / "forest_patches.geojson") or {"features": []})["features"]
    d["patches"] = sorted((f["properties"] for f in patches), key=lambda p: p["rank"])
    d["patch_count"] = len(d["patches"])
    d["glacier"] = _load(data_dir / "glacier.json") or {}
    d["visual_check"] = _load(data_dir / "forest_visual_check.json")
    d["risk"] = _load(data_dir / "risk.json")
    d["site_risk"] = _load(data_dir / "site_risk.json")
    d["site_by_patch"] = {s["patch_id"]: s for s in (d["site_risk"] or {}).get("results", [])}
    d["alerts"] = sorted(A.AlertStore(data_dir / "alerts.json").load().values(), key=lambda a: -a.score)
    d["settings"] = {"ndvi": F.NDVI_DROP_THRESHOLD, "min_patch": F.MIN_PATCH_HA, "rank_weights": F.RANK_WEIGHTS,
                     "fast": R.FAST_EXPANSION_PCT_PER_YR, "summer_months": G.SUMMER_MONTHS,
                     "min_values": G.MIN_VALUES_PER_YEAR, "min_years": G.MIN_YEARS}
    d["component_labels"] = COMPONENT_LABELS
    d["units"] = R.UNITS
    for r in d["risk"]["results"]:
        r["slug"] = _slug(r["village"]["name"])
        r["headline"] = headline(r)
    results = d["risk"]["results"]
    trends = [g["trend"] for g in d["glacier"].values()]
    d["summary"] = {
        "villages": len(results), "lakes": len(d["glacier"]),
        "bands": {b: sum(1 for r in results if r["band"] == b) for b in ("high", "watch", "low")},
        "lakes_with_trend": sum(1 for t in trends if t["fast_expansion"] is not None),
        "lakes_fast": sum(1 for t in trends if t["fast_expansion"]),
        "site_bands": {b: sum(1 for s in d["site_by_patch"].values() if s["band"] == b) for b in ("high", "watch", "low")},
        "alerts_total": len(d["alerts"]), "alerts_draft": sum(1 for a in d["alerts"] if a.state == "draft"),
    }
    d["alerts_open"] = d["summary"]["alerts_draft"]
    charts_ = {}
    for code in (d["glacier"] if with_charts else []):
        lake = queries.get_lake(conn, code)
        if lake is None:
            charts_[code] = None
            continue
        history = queries.lake_history(conn, lake["id"])
        charts_[code] = charts.extent_chart(history, date(2019, 1, 1), today) if history else None
    d["charts"] = charts_
    d["lang_note"] = A.LANG_NOTE
    return d


def register(app: FastAPI, render: Callable[..., HTMLResponse], read_only, today: Callable[[], date],
             data_dir: Path) -> None:
    """render (the SailAb page renderer) is not used: ShinGhar pages have their own layout."""
    store = A.AlertStore(data_dir / "alerts.json")
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    css = Path(__file__).parent / "static" / "shinghar.css"

    def show(request: Request, name: str, nav: str, with_charts: bool = False) -> HTMLResponse:
        with read_only() as conn:
            d = page_data(data_dir, conn, today(), with_charts=with_charts)
        return templates.TemplateResponse(request, name, {"d": d, "nav": nav, "css_version": int(css.stat().st_mtime)})

    @app.get("/shinghar", response_class=HTMLResponse)
    def shinghar_overview(request: Request) -> HTMLResponse:
        return show(request, "sg/overview.html", "overview")

    @app.get("/shinghar/{page}", response_class=HTMLResponse)
    def shinghar_page(request: Request, page: str) -> HTMLResponse:
        if page not in PAGES:
            raise HTTPException(404, f"no ShinGhar page {page!r}")
        return show(request, PAGES[page], page, with_charts=(page == "lakes"))

    @app.get("/shinghar/files/{name}")
    def shinghar_file(name: str) -> FileResponse:
        if name not in ALLOWED_FILES or not (data_dir / name).exists():
            raise HTTPException(404, f"{name} not built")
        return FileResponse(data_dir / name, media_type=ALLOWED_FILES[name])

    @app.get("/shinghar/audio/{name}")
    def shinghar_audio(name: str) -> FileResponse:
        path = data_dir / "audio" / name
        if "/" in name or not name.endswith(".mp3") or not path.exists():
            raise HTTPException(404, "no such audio file")
        return FileResponse(path, media_type="audio/mpeg")

    def _update(alert_id: str, fn) -> RedirectResponse:
        alerts = store.load()
        if alert_id not in alerts:
            raise HTTPException(404, f"no alert {alert_id!r}")
        try:
            fn(alerts[alert_id])
        except A.ReviewError as exc:
            raise HTTPException(409, str(exc)) from exc
        store.save(alerts)
        return RedirectResponse(f"/shinghar/alerts#alert-{alert_id}", status_code=303)

    @app.post("/shinghar/alerts/{alert_id}/review")
    async def review(alert_id: str, request: Request) -> RedirectResponse:
        form = parse_qs((await request.body()).decode("utf-8"))
        reviewer = (form.get("reviewer") or [""])[0]
        return _update(alert_id, lambda a: A.mark_reviewed(a, reviewer))

    @app.post("/shinghar/alerts/{alert_id}/ready")
    def ready(alert_id: str) -> RedirectResponse:
        return _update(alert_id, A.mark_ready)
