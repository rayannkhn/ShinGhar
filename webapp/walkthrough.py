"""The live check, step by step: turns what the pipeline reports while it runs into cards a viewer can follow.

Each card says what came into the step, what happened (with the formula and the real numbers), and the result
handed on, plus pictures where a picture shows something. Cards appear the moment their step finishes.

Where the numbers come from:
  - sign-in, search, cloud, download, measurement, score and save: the pipeline's own values, reported by
    run_pipeline_once(on_step=...) as each step happens (sailab/pipeline.py, _emit);
  - pictures and intermediate values (NDWI at the centre, the Otsu histogram, the growth order): the scene page's
    code (webapp/scene_view.py), which re-runs the pipeline's unchanged measurement functions on the same file.
    If that recomputation disagrees with what the pipeline stored, the card says so;
  - the ESA check: ESA's own Copernicus Data Space catalogue, asked live (no account needed). If it does not
    answer, the card says so and the check carries on.

Replay: when a check finds no new scene for a sensor, the latest stored usable scene of that sensor is walked
through the same steps, every card marked as a replay. A replay never writes to the database.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from datetime import date
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
from PIL import Image

S2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"
S1_COLLECTION = "COPERNICUS/S1_GRD"
ESA_CATALOGUE = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
ESA_TIMEOUT_S = 10
PICTURE_PX = 480          # longest side of a saved picture
GROWTH_FRAMES = 24


# ---------------------------------------------------------------------------
# ESA Copernicus catalogue
# ---------------------------------------------------------------------------
def esa_filter(scene_id: str, sensor: str) -> str:
    """OData filter that finds this Earth Engine scene's original product in ESA's catalogue.

    Earth Engine's Sentinel-2 id is <datatake start>_<granule start>_<tile>; ESA's product name holds the datatake
    start and the tile. Earth Engine's Sentinel-1 id is ESA's product name without '.SAFE'. A two-minute time window
    around the pass is added because a name-only search is slow (20.2 s against 0.6 s, measured 2026-11-13)."""
    from datetime import datetime, timedelta

    stamp = scene_id.split("_")[0] if sensor == "optical" else scene_id.split("_")[4]
    t = datetime.strptime(stamp, "%Y%m%dT%H%M%S")
    window = (f"ContentDate/Start gt {(t - timedelta(minutes=2)):%Y-%m-%dT%H:%M:%S}.000Z and "
              f"ContentDate/Start lt {(t + timedelta(minutes=2)):%Y-%m-%dT%H:%M:%S}.000Z")
    if sensor == "optical":
        tile = scene_id.split("_")[-1]
        return (f"Collection/Name eq 'SENTINEL-2' and {window} and contains(Name,'MSIL2A_{stamp}') "
                f"and contains(Name,'_{tile}_')")
    return f"Collection/Name eq 'SENTINEL-1' and {window} and startswith(Name,'{scene_id}')"


def esa_lookup(scene_id: str, sensor: str) -> dict[str, Any]:
    """Ask ESA's catalogue for the scene. Never raises: a failure comes back as {'error': ...}."""
    import requests

    started = time.monotonic()
    try:
        query = esa_filter(scene_id, sensor)
        r = requests.get(ESA_CATALOGUE, timeout=ESA_TIMEOUT_S, params={
            "$filter": query, "$select": "Id,Name,ContentDate,Online", "$top": "5"})
        if r.status_code != 200:
            return {"error": f"ESA answered HTTP {r.status_code}", "seconds": time.monotonic() - started}
        products = r.json().get("value", [])
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "seconds": time.monotonic() - started}
    return {"products": [{"id": p.get("Id") or p.get("@odata.id", ""), "name": p.get("Name"),
                          "start": (p.get("ContentDate") or {}).get("Start"), "online": p.get("Online")}
                         for p in products], "seconds": time.monotonic() - started}


def satellite_of(name: str | None, sensor: str) -> str:
    if name and len(name) >= 3 and name[:2] in ("S1", "S2"):
        return f"Sentinel-{name[1]}{name[2]}"
    return "Sentinel-2" if sensor == "optical" else "Sentinel-1"


# ---------------------------------------------------------------------------
# Pictures
# ---------------------------------------------------------------------------
def _scaled(rgb: np.ndarray) -> Image.Image:
    rows, cols = rgb.shape[:2]
    scale = max(1, PICTURE_PX // max(rows, cols))
    return Image.fromarray(rgb.astype(np.uint8)).resize((cols * scale, rows * scale), Image.NEAREST)


def growth_order(mask: np.ndarray, seed: tuple[int, int]) -> np.ndarray:
    """Steps from the seed to each lake pixel, walking 4-connected inside the lake (-1 outside).
    Only for drawing: the lake itself is the region the pipeline's region_grow() returned."""
    order = np.full(mask.shape, -1, dtype=int)
    if not mask[seed]:
        return order
    order[seed] = 0
    queue = deque([seed])
    rows, cols = mask.shape
    while queue:
        r, c = queue.popleft()
        for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if 0 <= nr < rows and 0 <= nc < cols and mask[nr, nc] and order[nr, nc] < 0:
                order[nr, nc] = order[r, c] + 1
                queue.append((nr, nc))
    return order


def growth_gif(background: np.ndarray, mask: np.ndarray, seed: tuple[int, int], out: Path) -> int:
    """Animated GIF of the lake filling outward from the centre. Returns the number of frames."""
    order = growth_order(mask, seed)
    last = int(order.max())
    base = (background.astype(float) * 0.55 + 30).astype(np.uint8)
    frames = []
    for i in range(1, GROWTH_FRAMES + 1):
        reach = round(last * i / GROWTH_FRAMES)
        frame = base.copy()
        grown = (order >= 0) & (order <= reach)
        frame[grown] = (30, 144, 255)
        front = (order >= 0) & (order > reach - max(1, last // GROWTH_FRAMES)) & (order <= reach)
        frame[front] = (255, 196, 0)
        sr, sc = seed
        frame[max(sr - 1, 0):sr + 2, max(sc - 1, 0):sc + 2] = (220, 30, 30)
        frames.append(_scaled(frame).convert("P", palette=Image.ADAPTIVE, colors=64))
    durations = [110] * (len(frames) - 1) + [1800]
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0)
    return len(frames)


def histogram_svg(counts: list[int], edges: list[float], threshold: float | None, centre: float | None) -> str:
    """Bars of the flat-ground VV values Otsu was given, with Otsu's threshold drawn between the two groups."""
    w, h, pad_l, pad_b, pad_t = 560, 250, 40, 34, 50     # pad_t keeps the labels above the tallest bar
    top = max(counts) or 1
    lo, hi = edges[0], edges[-1]
    x = lambda v: pad_l + (v - lo) / (hi - lo or 1) * (w - pad_l - 10)
    bars = []
    for i, n in enumerate(counts):
        x0, x1 = x(edges[i]), x(edges[i + 1])
        bh = n / top * (h - pad_b - pad_t)
        water = threshold is not None and edges[i + 1] <= threshold
        bars.append(f'<rect x="{x0:.1f}" y="{h - pad_b - bh:.1f}" width="{max(x1 - x0 - 1, 1):.1f}" height="{bh:.1f}" '
                    f'class="{"hb-water" if water else "hb-land"}"/>')
    ticks = []
    for v in range(int(np.ceil(lo / 5) * 5), int(hi) + 1, 5):
        ticks.append(f'<line x1="{x(v):.1f}" x2="{x(v):.1f}" y1="{h - pad_b}" y2="{h - pad_b + 4}" class="hb-axis"/>'
                     f'<text x="{x(v):.1f}" y="{h - pad_b + 16}" text-anchor="middle" class="hb-text">{v}</text>')
    marks = ""
    if threshold is not None:
        tx = x(threshold)
        marks += (f'<line x1="{tx:.1f}" x2="{tx:.1f}" y1="18" y2="{h - pad_b}" class="hb-threshold"/>'
                  f'<text x="{tx + 5:.1f}" y="14" class="hb-text hb-strong">Otsu threshold {threshold:.2f} dB</text>'
                  f'<text x="{tx - 6:.1f}" y="32" text-anchor="end" class="hb-text">◂ darker: water candidates</text>'
                  f'<text x="{tx + 6:.1f}" y="32" class="hb-text">brighter: land ▸</text>')
    if centre is not None and lo <= centre <= hi:
        cx = x(centre)
        marks += (f'<path d="M{cx - 6:.1f},{h - pad_b + 2} L{cx + 6:.1f},{h - pad_b + 2} L{cx:.1f},{h - pad_b - 8} Z" class="hb-centre"/>')
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Histogram of flat-ground radar values with the Otsu threshold">'
            f'<line x1="{pad_l}" x2="{w - 10}" y1="{h - pad_b}" y2="{h - pad_b}" class="hb-axis"/>{"".join(bars)}{"".join(ticks)}{marks}'
            f'<text x="{(w + pad_l) / 2:.0f}" y="{h - 2}" text-anchor="middle" class="hb-text">VV backscatter (dB)</text>'
            f'<text x="12" y="{(h - pad_b) / 2:.0f}" transform="rotate(-90 12 {(h - pad_b) / 2:.0f})" text-anchor="middle" class="hb-text">pixels</text></svg>')


def _fmt(v: Any, digits: int = 2) -> str:
    return "—" if v is None else f"{v:,.{digits}f}"


# ---------------------------------------------------------------------------
# The walkthrough
# ---------------------------------------------------------------------------
class Walkthrough:
    """Collects step cards for one live check. on_step() is called from the pipeline's thread; steps() from the
    web page's thread, so the list is guarded by a lock and handed out as copies."""

    def __init__(self, out_dir: Path, url_prefix: str, lake: Mapping[str, Any], repo_root: Path,
                 find_file: Callable[[str], Path | None], esa: Callable[[str, str], dict] = esa_lookup) -> None:
        self.out_dir, self.url_prefix, self.lake, self.repo_root = out_dir, url_prefix, dict(lake), repo_root
        self.find_file, self.esa = find_file, esa
        self._lock = threading.Lock()
        self._steps: list[dict[str, Any]] = []
        self._started = time.monotonic()
        self._last = self._started
        self._analysis: dict[str, Any] = {}       # scene_id -> SceneAnalysis (computed once, at download)
        self._esa_done: set[str] = set()
        self.measured = {"optical": False, "radar": False}   # did this run itself measure a scene of the sensor?

    # -- access ---------------------------------------------------------------------------
    def steps(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(s) for s in self._steps]

    def _add(self, key: str, title: str, *, sensor: str | None = None, scene: str | None = None, came_in: str = "",
             happened: list[str] | None = None, formulas: list[str] | None = None, result: str = "",
             tone: str = "ok", pictures: list[dict] | None = None, svg: str | None = None,
             table: dict | None = None, replay: bool = False) -> None:
        now = time.monotonic()
        with self._lock:
            self._steps.append({"n": len(self._steps) + 1, "key": key, "title": title, "sensor": sensor,
                                "scene": scene, "came_in": came_in, "happened": happened or [],
                                "formulas": formulas or [], "result": result, "tone": tone,
                                "pictures": pictures or [], "svg": svg, "table": table, "replay": replay,
                                "at_s": round(now - self._started, 1), "took_s": round(now - self._last, 1)})
            self._last = now

    def _picture(self, name: str, rgb: np.ndarray, caption: str) -> dict:
        path = self.out_dir / f"{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        _scaled(rgb).save(path)
        return {"src": f"{self.url_prefix}/{path.name}", "caption": caption}

    def _gif(self, name: str, a: Any, caption: str) -> dict | None:
        if a.region_mask is None or a.seed is None or a.background is None:
            return None
        path = self.out_dir / f"{name}.gif"
        growth_gif(a.background, a.region_mask, a.seed, path)
        return {"src": f"{self.url_prefix}/{path.name}", "caption": caption, "animated": True}

    # -- the pipeline's events --------------------------------------------------------------
    def on_step(self, kind: str, data: dict) -> None:
        handler = getattr(self, f"_on_{kind}", None)
        if handler is not None:
            handler(data)

    def _on_signed_in(self, d: dict) -> None:
        self._add("sign_in", "Sign in to Google Earth Engine",
                  came_in="The service-account key stored on this laptop (never shown).",
                  happened=["The pipeline signed in with ee.ServiceAccountCredentials and ee.Initialize: no browser, "
                            "no person, the same way the nightly GitHub Actions run signs in."],
                  result=f"Signed in as {d['account']}")

    def _on_searched(self, d: dict) -> None:
        sensor, lake, scenes = d["sensor"], d["lake"], d["scenes"]
        optical = sensor == "optical"
        happened = [f"Collection: {S2_COLLECTION if optical else S1_COLLECTION} "
                    f"({'Sentinel-2 surface reflectance' if optical else 'Sentinel-1 radar, ground range detected'}).",
                    f"Area: a circle of {lake['boundary_radius_m']:,.0f} m around the lake centre "
                    f"({lake['centre_lat']:.5f}° N, {lake['centre_lon']:.5f}° E).",
                    f"Dates: after {d['since']} (a day before the newest stored {sensor} scene) up to {d['until']}."]
        if optical:
            happened.append("For each scene, Earth Engine also sent the scene-classification (SCL) pixels of the lake "
                            "window; our code counts the cloud over the lake from them.")
        else:
            happened.append("Filters: instrument mode IW, VV polarisation. Radar sees through cloud, so there is no cloud check.")
        rows = [[s["scene_id"], s["acquired_at"][:16].replace("T", " ") + " UTC"]
                + ([_fmt(s["lake_cloud_percent"], 1) + " %", _fmt(s["tile_cloud_percent"], 1) + " %"] if optical else [])
                for s in scenes]
        table = {"head": ["Earth Engine scene id", "Acquired"] + (["Cloud over lake", "Cloud over tile"] if optical else []),
                 "rows": rows} if rows else None
        n = len(scenes)
        self._add(f"search_{sensor}", f"Search for new {'optical (Sentinel-2)' if optical else 'radar (Sentinel-1)'} images",
                  sensor=sensor, came_in=f"Lake {lake['name']} ({lake['code']}); newest stored {sensor} scene date.",
                  happened=happened, table=table, tone="ok" if n else "info",
                  result=(f"{n} scene{'s' if n != 1 else ''} listed by Earth Engine" if n else
                          f"No {sensor} scene newer than {d['since']}: Earth Engine answered normally, with none."))

    def _on_already_recorded(self, d: dict) -> None:
        with self._lock:
            for s in reversed(self._steps):
                if s["key"] == f"search_{d['sensor']}":
                    s["result"] += f" · {d['scene']['scene_id']} is already stored, so it is skipped"
                    break

    def _esa_step(self, scene: dict, sensor: str, replay: bool = False) -> None:
        sid = scene["scene_id"]
        if (sid, replay) in self._esa_done:
            return
        self._esa_done.add((sid, replay))
        found = self.esa(sid, sensor)
        coll = S2_COLLECTION if sensor == "optical" else S1_COLLECTION
        products = found.get("products") or []
        if "error" in found:
            tone, result = "warn", f"ESA's catalogue did not answer ({found['error']}). The check carries on with Earth Engine's copy."
            name = None
        elif not products:
            tone, result, name = "warn", "ESA's catalogue answered but listed no matching product.", None
        else:
            p = products[0]
            name = p["name"]
            tone, result = "ok", f"Found in ESA's catalogue: {name}"
        chain = (f"{satellite_of(name, sensor)} (ESA) → Copernicus product {name or '(not confirmed)'} → "
                 f"Earth Engine asset {coll}/{sid} → our download")
        self._add("esa", "Where the image comes from: ESA Copernicus → Earth Engine", sensor=sensor, scene=sid,
                  came_in=f"Earth Engine scene id {sid}",
                  happened=["Sentinel satellites belong to the EU's Copernicus programme, run by ESA. Earth Engine keeps a "
                            "copy of each Copernicus product; the pipeline downloads from that copy.",
                            "To show it is the same image, ESA's own catalogue (Copernicus Data Space) was asked live for "
                            f"this scene ({found.get('seconds', 0):.1f} s, no account needed).",
                            f"Chain: {chain}"],
                  result=result, tone=tone, replay=replay)

    def _on_cloud_checked(self, d: dict) -> None:
        scene = d["scene"]
        self._esa_step(scene, "optical")
        self._cloud_card(scene, d["limit"], d["decision"] == "measure")

    def _cloud_card(self, scene: dict, limit: float, measure: bool, replay: bool = False) -> None:
        cloud = scene.get("lake_cloud_percent")
        self._add("cloud", "Cloud over the lake", sensor="optical", scene=scene["scene_id"],
                  came_in=f"Scene {scene['scene_id']} and its SCL (scene classification) pixels over the lake window.",
                  happened=["Cloud over lake = pixels classed as cloud, cloud shadow or thin cirrus ÷ valid pixels inside the "
                            "lake circle × 100 (not the whole 100 km tile's figure)."],
                  formulas=[f"cloud over lake = {_fmt(cloud, 1)} %   (limit {limit:.0f} %"
                            + (f", whole tile {scene['tile_cloud_percent']:.1f} %)" if scene.get("tile_cloud_percent") is not None
                               else "; the whole-tile figure is not stored)")],
                  result=("Clear enough: download and measure" if measure else
                          "Too cloudy over the lake: recorded, not downloaded. Optical steps stop here for this scene."),
                  tone="ok" if measure else "stop", replay=replay)

    def _on_downloaded(self, d: dict) -> None:
        scene, sensor = d["scene"], d["sensor"]
        if sensor == "radar":
            self._esa_step(scene, "radar")
        self._download_card(scene, sensor, Path(d["path"]), d["stored_path"], d["sha256"], d["size_bytes"])

    def _analyse(self, scene: dict, sensor: str, path: Path) -> Any:
        from webapp import scene_view
        key = (scene["scene_id"], str(path))
        if key not in self._analysis:
            if sensor == "optical":
                self._analysis[key] = scene_view.analyse_optical(path, self.lake, date.fromisoformat(scene["acquired_at"][:10]))
            else:
                self._analysis[key] = scene_view.analyse_radar(path, self.lake,
                                                               self.repo_root / "data" / "dem" / f"{self.lake['code']}_dem.tif")
        return self._analysis[key]

    def _download_card(self, scene: dict, sensor: str, path: Path, stored_path: str, sha: str, size: int,
                       replay: bool = False) -> None:
        a = self._analyse(scene, sensor, path)
        tag = f"{'r' if replay else 'n'}_{scene['scene_id']}"
        if sensor == "optical":
            pic = self._picture(f"{tag}_truecolour", a.pictures["truecolour"],
                                "True colour (red, green, blue bands) of the lake window")
            bands = "B2, B3, B4, B8, B11 and SCL at 10 m"
        else:
            pic = self._picture(f"{tag}_vv", a.pictures["vv"], "VV radar backscatter: dark = smooth surface such as calm water")
            bands = "VV and VH backscatter in dB at 10 m"
        cols, rows = a.window_px
        self._add("download", "Download the lake window" if not replay else "Open the stored lake window", sensor=sensor,
                  scene=scene["scene_id"], replay=replay,
                  came_in=f"Scene {scene['scene_id']} ({scene['acquired_at'][:10]}).",
                  happened=[f"Only a {cols} × {rows} pixel window ({cols * a.pixel_size_m / 1000:.1f} × {rows * a.pixel_size_m / 1000:.1f} km) "
                            f"around the lake was {'downloaded from Earth Engine' if not replay else 'read from the stored file'}, never the whole tile: {bands}.",
                            "The SHA-256 fingerprint lets anyone re-download the scene and confirm it is the same file."],
                  formulas=[f"file  {stored_path}", f"size  {size / 1024:,.0f} KB", f"sha256  {sha}"],
                  pictures=[pic], result="Image ready for measurement")

    def _on_measured(self, d: dict) -> None:
        self.measured[d["sensor"]] = True
        self._measure_cards(d["scene"], d["sensor"], Path(d["path"]), d["status"], d["extent_ha"], d["reason"])

    def _measure_cards(self, scene: dict, sensor: str, path: Path, status: str, extent_ha: float | None, reason: str,
                       replay: bool = False) -> None:
        a = self._analyse(scene, sensor, path)
        tag = f"{'r' if replay else 'n'}_{scene['scene_id']}"
        sid = scene["scene_id"]
        if sensor == "optical":
            g, nir = a.stats.get("green_at_centre"), a.stats.get("nir_at_centre")
            formulas = ["NDWI = (Green − NIR) ÷ (Green + NIR)      water when NDWI > 0.2"]
            if g is not None and nir is not None and g + nir:
                formulas.append(f"at the lake centre: ({g:,.0f} − {nir:,.0f}) ÷ ({g:,.0f} + {nir:,.0f}) = {(g - nir) / (g + nir):.3f}"
                                f"  →  {'water' if (g - nir) / (g + nir) > 0.2 else 'not water'}")
            pics = [self._picture(f"{tag}_ndwi", a.pictures["ndwi"], "NDWI map: blue = water (NDWI > 0.2), brown = land")]
            if "checks" in a.pictures:
                pics.append(self._picture(f"{tag}_checks", a.pictures["checks"],
                                          "Checks C and D: pink = cloud or shadow, cyan = snow or ice"))
            self._add("detect", "Detect water: NDWI", sensor=sensor, scene=sid, replay=replay,
                      came_in="Green (B3) and near-infrared (B8) reflectance of every pixel.",
                      happened=["Water reflects green light but absorbs near-infrared, so water pixels have a high NDWI.",
                                f"{a.stats.get('water_px_in_window', 0):,} of {a.window_px[0] * a.window_px[1]:,} pixels in the window are water."],
                      formulas=formulas, pictures=pics, result="Water map ready")
        else:
            h = a.stats.get("otsu_histogram")
            svg = histogram_svg(h["counts"], h["edges"], a.threshold_db, a.stats.get("vv_at_centre_db")) if h else None
            pics = [self._picture(f"{tag}_threshold", a.pictures["threshold"],
                                  "Brown: steeper than 10°, removed · Blue: darker than the threshold · Pale: brighter")]
            centre = a.stats.get("vv_at_centre_db")
            self._add("detect", "Detect water: slope mask + Otsu threshold", sensor=sensor, scene=sid, replay=replay,
                      came_in="VV backscatter (dB) of every pixel, and the slope from the stored elevation model (DEM).",
                      happened=[f"Slope mask: {a.masked_steep_px or 0:,} pixels steeper than {a.slope_limit_deg:.0f}° removed (lake water is flat; "
                                "bright mountain faces would otherwise spoil the threshold).",
                                f"Otsu's method: over the {a.stats.get('otsu_input_px', 0):,} flat pixels left, it picks the cut-off "
                                "that best separates two groups, dark (water) and bright (land).",
                                "The red triangle under the histogram marks the lake centre's value."],
                      formulas=[f"Otsu threshold = {_fmt(a.threshold_db)} dB",
                                f"lake centre VV = {_fmt(centre)} dB  →  "
                                + ("water candidate" if centre is not None and a.threshold_db is not None and centre < a.threshold_db else "not a water candidate")],
                      svg=svg, pictures=pics, result="Water candidates ready")

        same = abs((a.extent_ha or 0) - (extent_ha or 0)) < 0.005 and a.status == status
        if not same:
            self._add("check", "Recomputation differs", sensor=sensor, scene=sid, tone="warn", replay=replay,
                      came_in="The pipeline's result and this page's recomputation from the same file.",
                      happened=[f"Pipeline: {status} {extent_ha}. Recomputed here: {a.status} {a.extent_ha}."],
                      result="Shown as found: the pipeline's value is the one stored.")
        gif = self._gif(f"{tag}_growth", a, "The lake grows outward from the centre (red), pixel by pixel, while it stays water")
        rule = (f"Start at the lake centre pixel; add each 4-connected neighbour that is water and within "
                f"{self.lake['growth_distance_limit_m']:,.0f} m of the centre; repeat until no pixel can be added.")
        if status == "ok":
            px = round(extent_ha * 10_000 / a.pixel_size_m ** 2)
            self._add("grow", "Grow the lake from its centre", sensor=sensor, scene=sid, replay=replay,
                      came_in="The water map and the lake centre from the database.",
                      happened=[rule, "The distance limit stops the region leaking along a river; then the checks for "
                                "no-data, cloud and snow touching the lake all passed."],
                      pictures=[gif] if gif else [], result=f"{px:,} lake pixels, connected to the centre")
            self._add("area", "Calculate the area", sensor=sensor, scene=sid, replay=replay,
                      came_in=f"{px:,} lake pixels of {a.pixel_size_m:.0f} m × {a.pixel_size_m:.0f} m.",
                      happened=["Area = number of lake pixels × area of one pixel."],
                      formulas=[f"{px:,} px × {a.pixel_size_m ** 2:,.0f} m² = {px * a.pixel_size_m ** 2:,.0f} m² = {extent_ha:.2f} ha"],
                      result=f"Lake area: {extent_ha:.2f} ha")
        else:
            label = "No lake found" if status == "no_lake_detected" else "Measurement refused"
            self._add("grow", label, sensor=sensor, scene=sid, replay=replay, tone="stop",
                      came_in="The water map and the lake centre from the database.",
                      happened=[rule, f"Reason: {reason}"], pictures=[gif] if gif else [],
                      result=("No area is stored for this scene (nothing is filled in), so there is no score."
                              if status != "no_lake_detected" else
                              "A clear summer image with no water at the centre: recorded as 'no lake found', with no area."))

    def _on_scored(self, d: dict) -> None:
        self._score_card(d["scene"], d["sensor"], d["extent_ha"], d["status"], d["same_month"], d["years"],
                         d["baseline_ha"], d["score"])

    def _score_card(self, scene: dict, sensor: str, extent: float, status: str, same_month: list[dict], years: int,
                    baseline: float | None, score: float | None, replay: bool = False, stored: str | None = None) -> None:
        from sailab.pipeline import MIN_SAME_MONTH_VALUES, MIN_SAME_MONTH_YEARS
        month = date.fromisoformat(scene["acquired_at"][:10]).strftime("%B")
        rows = [[v["date"], f"{v['extent_ha']:.2f} ha"] for v in same_month]
        happened = [f"History: this lake's earlier {sensor} areas from {month} of earlier years only (never later data, never the other sensor).",
                    f"Check F: at least {MIN_SAME_MONTH_VALUES} values from at least {MIN_SAME_MONTH_YEARS} different years, "
                    f"else 'insufficient history'. Here: {len(same_month)} values from {years} year{'s' if years != 1 else ''}."]
        if status == "ok" and baseline is not None:
            values = [v["extent_ha"] for v in same_month]
            spread = float(np.std(values, ddof=1)) if len(values) > 1 else None
            formulas = ["score = (area − baseline) ÷ spread      baseline = mean, spread = standard deviation (n − 1)",
                        f"baseline = {baseline:.2f} ha    spread = {_fmt(spread)} ha",
                        f"score = ({extent:.2f} − {baseline:.2f}) ÷ {_fmt(spread)} = {_fmt(score)}"]
            result = f"Score {_fmt(score)}: " + ("within the usual range for " + month if score is not None and abs(score) < 2
                                                 else "2 or more spreads from the usual " + month + " area")
        else:
            formulas = []
            result = "Insufficient history: no score (a score from too few values would be noise)"
        if stored:
            happened.append(stored)
        self._add("score", f"Risk score ({'optical' if sensor == 'optical' else 'radar'})", sensor=sensor,
                  scene=scene["scene_id"], replay=replay, came_in=f"Lake area {extent:.2f} ha on {scene['acquired_at'][:10]}.",
                  happened=happened, formulas=formulas, result=result,
                  table={"head": [f"Earlier {month} dates", "Area"], "rows": rows} if rows else None,
                  tone="ok" if status == "ok" else "info")

    def _on_not_scored(self, d: dict) -> None:
        self._not_scored_card(d["scene"], d["extent_ha"])

    def _not_scored_card(self, scene: dict, extent: float, replay: bool = False) -> None:
        self._add("score", "Risk score (radar): switched off", sensor="radar", scene=scene["scene_id"], replay=replay,
                  came_in=f"Radar lake area {extent:.2f} ha.", tone="info",
                  happened=["Radar areas are measured and stored every night, but not scored yet (SCORE_RADAR = False).",
                            "Reason: on the lakes with trustworthy optical, about 1 radar value in 6 is clearly wrong from "
                            "December to May (wet snow and frozen ground look like water), against 1.6% from June to November.",
                            "Planned: score radar for June–November with its own baseline per orbit direction, after a backtest."],
                  result="Stored, not scored")

    def _on_saved(self, d: dict) -> None:
        parts = [f"scene #{d['scene_row']}"]
        if d.get("measurement_id"):
            parts.append(f"measurement #{d['measurement_id']}")
        if d.get("risk_id"):
            parts.append(f"risk score #{d['risk_id']}")
        self._add("saved", "Saved to the database", sensor=d["sensor"], scene=d["scene"]["scene_id"],
                  came_in="Everything this scene produced.",
                  happened=["Written to this laptop's working copy of the database (never the published copy the nightly "
                            "run commits). The lake page, chart and observation log now show it."]
                  + ([f"Note: {d['note']}."] if d.get("note") else []),
                  result="Saved: " + ", ".join(parts))

    # -- replay -----------------------------------------------------------------------------
    def replay_failed(self, sensor: str, error: str) -> None:
        self._add("replay", f"The {sensor} replay could not finish", sensor=sensor, replay=True, tone="warn",
                  came_in="The latest stored scene.", happened=[f"Error: {error}"],
                  result="The live part of the check above is unaffected.")

    def replay(self, conn, sensor: str) -> None:
        """Walk the lake's latest stored usable scene of `sensor` through the same steps. Writes nothing."""
        from sailab import db
        from sailab.pipeline import (MIN_SAME_MONTH_VALUES, MIN_SAME_MONTH_YEARS, OPTICAL_CLOUD_LIMIT_PERCENT, sha256_of)
        from sailab.risk import score_against_seasonal_baseline

        source = "sentinel-2" if sensor == "optical" else "sentinel-1"
        rows = conn.execute(
            """SELECT s.id AS scene_row, s.acquired_at, s.cloud_fraction, s.file_path, m.id AS mid, m.status, m.extent_ha,
                      r.id AS rid, r.status AS rstatus, r.deviation_score
               FROM scene s JOIN measurement m ON m.scene_id = s.id
               LEFT JOIN risk_score r ON r.measurement_id = m.id
               WHERE s.lake_id = ? AND s.source = ? AND m.status = 'ok' ORDER BY s.acquired_at DESC""",
            (self.lake["id"], source)).fetchall()
        row = next((r for r in rows if self.find_file(r["file_path"]) is not None), None)
        if row is None:
            self._add("replay", f"No stored {sensor} measurement to replay", sensor=sensor, replay=True, tone="info",
                      came_in=f"Every stored {sensor} scene of {self.lake['name']}.",
                      happened=[f"This lake has no usable {sensor} measurement with its file on this laptop"
                                + (" (radar has never measured this lake)." if sensor == "radar" and not rows else ".")],
                      result="Nothing to replay")
            return
        path = self.find_file(row["file_path"])
        scene_id = Path(row["file_path"]).stem
        scene = {"scene_id": scene_id, "acquired_at": row["acquired_at"], "lake_cloud_percent": row["cloud_fraction"],
                 "tile_cloud_percent": None}
        self._add("replay", f"Replay: the latest stored {sensor} scene, {row['acquired_at'][:10]}", sensor=sensor,
                  replay=True, tone="info", came_in="No new scene from this check to measure.",
                  happened=["To show every step anyway, the newest stored scene with a usable measurement is walked through "
                            "the same code. Its image is the stored file; nothing below is new data and nothing is written."],
                  result=f"Replaying scene {scene_id}")
        self._esa_step(scene, sensor, replay=True)
        if sensor == "optical":
            self._cloud_card(scene, OPTICAL_CLOUD_LIMIT_PERCENT, True, replay=True)
        self._download_card(scene, sensor, path, row["file_path"], sha256_of(path), path.stat().st_size, replay=True)
        self._measure_cards(scene, sensor, path, row["status"], row["extent_ha"], "", replay=True)
        acquired_on = date.fromisoformat(row["acquired_at"][:10])
        if sensor == "optical":
            history = [h for h in db.get_extent_history(conn, self.lake["id"], exclude_measurement_id=row["mid"], sensor=sensor)
                       if h.observed_on < acquired_on]
            same = [h for h in history if h.observed_on.month == acquired_on.month]
            years = len({h.observed_on.year for h in same})
            values = [{"date": h.observed_on.isoformat(), "extent_ha": h.extent_ha} for h in same]
            stored = (f"Stored with this scene: risk score #{row['rid']}, {row['rstatus']}"
                      + (f" {row['deviation_score']:+.2f}" if row["deviation_score"] is not None else "") + "."
                      if row["rid"] else "No risk score is stored with this scene.")
            if len(same) < MIN_SAME_MONTH_VALUES or years < MIN_SAME_MONTH_YEARS:
                self._score_card(scene, sensor, row["extent_ha"], "insufficient_history", values, years, None, None,
                                 replay=True, stored=stored)
            else:
                s = score_against_seasonal_baseline(history, acquired_on, row["extent_ha"])
                self._score_card(scene, sensor, row["extent_ha"], "ok", values, years, s.baseline_ha, s.deviation_score,
                                 replay=True, stored=stored)
        else:
            self._not_scored_card(scene, row["extent_ha"], replay=True)
        self._add("saved", "Nothing saved: this was a replay", sensor=sensor, scene=scene_id, replay=True, tone="info",
                  came_in="The replayed results.",
                  happened=["A replay never writes to the database, so it cannot be mistaken for new data."],
                  result=f"Already stored as scene #{row['scene_row']}, measurement #{row['mid']}")
