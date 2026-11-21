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


PAGES = {"overview": "sg/overview.html", "villages": "sg/villages.html", "forest": "sg/forest.html", "lakes": "sg/lakes.html",
         "alerts": "sg/alerts.html", "method": "sg/method.html"}


def _slug(name: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-")


def headline(r: dict) -> str:
    """Short summary of what adds most to a village's score, from the same numbers as its reasons."""
    n = len(r.get("upstream_lakes") or [])
    short = {
        "flood_path": lambda v: f"{v:.0f} km down a lake's outflow path",
        "forest_loss_upslope": lambda v: f"{v:.1f} ha vegetation loss upslope",
        "loss_slope": lambda v: f"loss on {v:.0f}° slopes",
        "lake_growth": lambda v: f"upstream lake {v:+.1f} %/yr",
        "lake_anomaly": lambda v: f"upstream lake z {v:+.1f}",
    }
    parts = [short[c["name"]](c["raw"]) for c in sorted(r["components"], key=lambda c: -c["points"])
             if c["points"] > 0 and c["raw"] is not None][:3]
    return " · ".join(parts) if parts else "no measured factor adds to the score"


FLOOD_SOURCE = {"text": "Flash floods destroy 54 bridges, 50 hotels in Hazara and Malakand", "by": "Dawn, August 2022",
                "url": "https://dawn.com/news/1707167/flash-floods-destroy-54-bridges-50-hotels-in-hazara-and-malakand"}


def plain_village_reason(r: dict) -> str:
    """ONE plain-English sentence from the village's strongest score part (no jargon, numbers from the result)."""
    comps = {c["name"]: c for c in r["components"]}
    ranked = [c for c in sorted(r["components"], key=lambda c: -c["points"]) if c["points"] > 0 and c["raw"] is not None]
    if not ranked:
        return "Nothing we measure adds to the score here: no forest loss above it and no monitored lake upstream."
    top = ranked[0]["name"]
    if top in ("forest_loss_upslope", "loss_slope"):
        ha = comps["forest_loss_upslope"]["raw"]
        steep = comps["loss_slope"]["raw"]
        return (f"{ha:.1f} ha of forest on the slopes above the village lost its green since 2019"
                + (f", on ground about {steep:.0f}° steep." if steep is not None else "."))
    if top == "flood_path":
        return f"It lies {comps['flood_path']['raw']:.0f} km downstream of a glacial lake, on the path its water would take."
    if top == "lake_growth":
        return f"The glacial lake above it is growing by {comps['lake_growth']['raw']:.1f} % a year."
    return "The glacial lake above it was bigger than usual in its latest clear photo."


def site_sentence(p: dict, villages: dict[str, dict]) -> str:
    v = villages.get(p["nearest_settlement"] or "")
    above = (p["mean_elev_m"] - v["elev_m"]) if (v and p.get("mean_elev_m") is not None) else None
    where = f"{p['dist_settlement_m'] / 1000:.1f} km from {p['nearest_settlement']}"
    if above is not None and above >= 50:
        where += f" and {round(above, -1):.0f} m above it"
    return (f"{p['area_ha']:.1f} ha of forest lost its green between {{b}} and {{a}}, on a {p['mean_slope_deg']:.0f}° slope, "
            f"{where}.")


def lake_line_svg(yearly: list[dict], width: int = 640, height: int = 300) -> str:
    """Summer median area per year (optical only), y axis from 0 so a stable lake looks stable."""
    if not yearly:
        return ""
    left, right, top, bottom = 56, 20, 24, 44
    hi = max(y["median_ha"] for y in yearly) * 1.25
    n = len(yearly)
    X = lambda i: left + (width - left - right) * (i / max(1, n - 1))
    Y = lambda v: top + (height - top - bottom) * (1 - v / hi)
    grid = []
    step = 10 if hi > 30 else 5
    v = 0
    while v <= hi:
        grid.append(f'<line x1="{left}" x2="{width - right}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="grid"/>'
                    f'<text x="{left - 10}" y="{Y(v) + 6:.1f}" text-anchor="end" class="ax">{v}</text>')
        v += step
    pts = " ".join(f"{X(i):.1f},{Y(y['median_ha']):.1f}" for i, y in enumerate(yearly))
    marks = "".join(f'<circle cx="{X(i):.1f}" cy="{Y(y["median_ha"]):.1f}" r="6" class="pt"><title>{y["year"]}: '
                    f'{y["median_ha"]} ha (median of {y["n"]} clear photos)</title></circle>'
                    f'<text x="{X(i):.1f}" y="{height - 14}" text-anchor="middle" class="ax">{y["year"]}</text>'
                    for i, y in enumerate(yearly))
    return (f'<svg viewBox="0 0 {width} {height}" class="linechart" role="img" aria-label="Summer lake area per year">'
            f'{"".join(grid)}<text x="{left}" y="14" class="ax">hectares</text>'
            f'<polyline points="{pts}" class="line"/>{marks}</svg>')


def story_data(d: dict, data_dir: Path) -> dict | None:
    imgs = _load(data_dir / "story" / "story_images.json")
    f, g, risk = d["forest"], d["glacier"], d["risk"]["results"]
    villages = {v["name"]: v for v in d["valley"]["villages"]}
    by_id = {p["patch_id"]: p for p in d["patches"]}
    notes_file = _load(data_dir / "story" / "site_notes.json") or {}
    notes = notes_file.get("sites", {})
    st: dict[str, Any] = {"images": imgs, "flood_source": FLOOD_SOURCE, "notes_by": notes_file.get("by")}
    st["tiles"] = [
        {"value": d["patch_count"], "text": "slope sites flagged for ranger visits"},
        {"value": sum(x["optical_ok"] for x in g.values()),
         "text": f"clear satellite photos used to measure {len(g)} glacial lakes since 2019"},
        {"value": len(risk), "text": "villages screened"},
        {"value": f"{f['ours_loss_ha']:.0f} ha", "text": f"of forest ground lost its green, {f['before_year']} to {f['after_year']}"},
    ]
    sites = []
    for s_ in (imgs or {}).get("sites", []):
        p = by_id.get(s_["patch_id"])
        if p is None:
            continue
        sites.append({**s_, "p": p, "sentence": site_sentence(p, villages).format(b=f["before_year"], a=f["after_year"]),
                      "seen": notes.get(str(s_["patch_id"]))})
    st["sites"] = sites
    growth = [x["trend"]["growth_pct_per_yr"] for x in g.values() if x["trend"]["growth_pct_per_yr"] is not None]
    st["lakes_fast"] = sum(1 for x in g.values() if x["trend"]["fast_expansion"])
    st["lakes_max_change"] = max((abs(v) for v in growth), default=None)
    lk = (imgs or {}).get("lake")
    if lk:
        t = g[lk["code"]]["trend"]
        meds = [y["median_ha"] for y in t["yearly"]]
        typical = round(sum(meds) / len(meds)) if meds else None
        stable = t["fast_expansion"] is False and abs(t["growth_pct_per_yr"]) < 1
        st["lake"] = {**lk, "name": g[lk["code"]]["name"], "trend": t, "typical_ha": typical, "stable": stable,
                      "chart": lake_line_svg(t["yearly"]), "first": t["yearly"][0]["year"] if t["yearly"] else None}
    st["villages"] = [{"name": r["village"]["name"], "area": r["village"]["area"], "band": r["band"], "score": r["score"],
                       "reason": plain_village_reason(r)} for r in risk[:5]]
    st["bands"] = {b: sum(1 for r in risk if r["band"] == b) for b in ("high", "watch", "low")}
    # score breakdown per village, plain labels
    plain = {"forest_loss_upslope": "forest loss above", "loss_slope": "steep ground", "flood_path": "on a lake's water path",
             "lake_growth": "lake growing", "lake_anomaly": "lake bigger than usual"}
    st["breakdown"] = [{"name": r["village"]["name"], "score": r["score"],
                        "parts": [{"key": c["name"], "label": plain[c["name"]], "points": c["points"]}
                                  for c in r["components"] if c["points"] > 0]} for r in risk]
    st["plain_parts"] = plain
    st["path_rule"] = R.SCALES["flood_path"]
    # village labels: put a label on the right when another village sits just to its left (e.g. Gall and Kass)
    if imgs:
        vs = imgs["valley"]["villages"]
        gap = imgs["valley"]["width"] / 9
        for v in vs:
            v["side"] = "right" if any(o is not v and 0 < v["xy"][0] - o["xy"][0] < gap and abs(v["xy"][1] - o["xy"][1]) < gap / 3
                                       for o in vs) else "left"
        lake_m = [int(n.split(", ")[-1].rstrip(" m)").replace(",", "")) for n in (x["name"] for x in g.values()) if n.endswith(" m)")]
        elev = [v["elev_m"] for v in d["valley"]["villages"]]
        st["facts"] = [
            ("Forest", f"{f['forest_ha']:,.0f} ha, from global satellite forest maps"),
            ("Glacial lakes", f"{len(g)} measured, at {min(lake_m):,}–{max(lake_m):,} m" if lake_m else f"{len(g)} measured"),
            ("Villages", f"{len(elev)}, at {min(elev):,}–{max(elev):,} m above sea level" if elev else f"{len(risk)}"),
            ("Box shown", f"about {imgs['valley']['width'] * imgs['valley']['scale_m_per_px'] / 1000:.0f} × "
                          f"{imgs['valley']['height'] * imgs['valley']['scale_m_per_px'] / 1000:.0f} km"),
        ]
    st["alert"] = d["alerts"][0] if d["alerts"] else None
    if st["alert"]:
        r0 = next((r for r in risk if r["village"]["name"] == st["alert"].village), None)
        st["alert_reasons"] = [x.split(" (+")[0] for x in (r0["reasons"] if r0 else [])
                               if not x.startswith(("Does not apply", "No data"))][:2]
        st["alert_to"] = A.DEPARTMENTS[st["alert"].band]
    return st


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
        charts_[code] = None   # filled below: optical by default, radar behind a toggle
    d["charts"] = charts_
    d["lang_note"] = A.LANG_NOTE
    d["radar"] = {}
    for code in (d["glacier"] if with_charts else []):
        lake = queries.get_lake(conn, code)
        history = queries.lake_history(conn, lake["id"]) if lake else []
        optical_rows = [r for r in history if r.get("source") != "sentinel-1" and (r.get("sensor") or "optical") != "radar"]
        opt_ok = [r["extent_ha"] for r in optical_rows if r.get("measurement_status") == "ok" and r.get("extent_ha") is not None]
        rad_ok = [r["extent_ha"] for r in history if (r.get("sensor") == "radar" or r.get("source") == "sentinel-1")
                  and r.get("measurement_status") == "ok" and r.get("extent_ha") is not None]
        med = sorted(opt_ok)[len(opt_ok) // 2] if opt_ok else None
        off = sum(1 for v in rad_ok if med and abs(v - med) > charts.RADAR_AXIS_FRACTION * med)
        keep = bool(rad_ok) and off <= len(rad_ok) / 2
        d["radar"][code] = {"ok": len(rad_ok), "off": off, "shown": keep, "optical_median": med,
                            "fraction": charts.RADAR_AXIS_FRACTION}
        if history:
            d["charts"][code] = {"optical": charts.extent_chart(optical_rows, date(2019, 1, 1), today) if optical_rows else None,
                                 "with_radar": charts.extent_chart(history, date(2019, 1, 1), today) if keep else None}
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
    def shinghar_story(request: Request) -> HTMLResponse:
        with read_only() as conn:
            d = page_data(data_dir, conn, today(), with_charts=False)
        st = story_data(d, data_dir) if d.get("built") else None
        return templates.TemplateResponse(request, "sg/story.html",
                                          {"d": d, "st": st, "nav": "story", "css_version": int(css.stat().st_mtime)})

    @app.get("/shinghar/img/{name}")
    def shinghar_img(name: str) -> FileResponse:
        path = data_dir / "story" / name
        if "/" in name or not name.endswith((".jpg", ".png")) or not path.exists():
            raise HTTPException(404, "no such image")
        return FileResponse(path, media_type="image/jpeg" if name.endswith(".jpg") else "image/png")

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

    @app.api_route("/shinghar/audio/{name}", methods=["GET", "HEAD"])
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

    @app.post("/shinghar/alerts/{alert_id}/reset")
    def reset(alert_id: str) -> RedirectResponse:
        return _update(alert_id, A.reset_to_draft)
