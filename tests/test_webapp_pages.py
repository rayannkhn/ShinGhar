"""Tests for the Dashboard and Lake Detail pages and the offline charts.

Uses the temporary database from conftest.py (KRB: 5 scenes, 2 usable at 240.0 and 250.0 ha, one
score +1.50; ATS: no scenes; run 2 failed with "EarthEngineError: quota"). Every expected value below
comes from those rows, so a page that showed anything else would fail.
"""
import re
from datetime import date
from math import floor

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin
from rasterio.warp import transform as warp_transform

from sailab import db
from webapp import charts, images, pages
from webapp.main import create_app

TODAY = date(2026, 11, 9)


def visible_text(html: str) -> str:
    """What a person reading the page sees: tags removed, whitespace collapsed (SVG coordinates are not text)."""
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


@pytest.fixture
def client(source_db, tmp_path):
    return TestClient(create_app(source_db=source_db, work_dir=tmp_path / "work", today=lambda: TODAY,
                                 repo=tmp_path / "repo"))


def write_lake_window(path, lon, lat, rows=30, cols=30):
    """6-band window with a 5x5 water block (25 px) around the lake centre, as in test_pipeline.py."""
    xs, ys = warp_transform("EPSG:4326", "EPSG:32643", [lon], [lat])
    x0, y0 = floor(xs[0] / 10) * 10 - 150, floor(ys[0] / 10) * 10 + 160
    green = np.full((rows, cols), 100, np.uint16); nir = np.full((rows, cols), 300, np.uint16)
    green[13:18, 13:18], nir[13:18, 13:18] = 300, 50
    scl = np.full((rows, cols), 5, np.uint16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=cols, height=rows, count=6, dtype="uint16",
                       crs="EPSG:32643", transform=from_origin(x0, y0, 10, 10)) as dst:
        dst.write(np.stack([green, green, green, nir, nir, scl]))


# --- dashboard --------------------------------------------------------------------------------
def test_dashboard_shows_the_real_counts(client):
    html = client.get("/").text
    text = visible_text(html)
    assert "Lakes monitored 8 " in text
    assert "Scenes recorded 5 5 optical, 0 radar" in text
    assert "40% 2 of 5 optical scenes" in text                       # too cloudy: 2 of 5 OPTICAL scenes
    assert "Usable measurements 2 2 of 3 measurement attempts passed every check (optical 2 of 3, radar 0 of 0)." in text
    assert 'title="Not a scene count: the 2 too-cloudy optical scenes were never measured."' in html   # behind the ⓘ tip
    assert "Days since a usable measurement 120 Karambar Lake, optical, 12 Jul 2026" in text
    assert "Optical: 250.00 ha on 12 Jul 2026, 120 days ago" in text
    assert "Radar: No usable measurement yet" in text                # no radar rows: said in words
    assert "No usable measurement yet" in text                        # ATS has none


def test_dashboard_banners_come_from_the_data(client):
    text = visible_text(client.get("/").text)
    assert ("for 8 of 8 lakes (Karambar Lake, Atro Sar, Shishper glacier lake, Darkut glacial lake, Borith Lake, "
            "Passu glacier lake, Tsho Rolpa, Thulagi lake)") in text                               # no lake has a usable image in 7 days
    assert "The latest pipeline run (run 2) recorded an error." in text
    assert "EarthEngineError: quota" in text


def test_dashboard_never_shows_the_reference_designs_sample_values(client):
    """The reference screens use sample data (33 lakes, Critical 0.86, advisories). None of it may appear."""
    text = visible_text(client.get("/").text)
    for sample in ("0.86", "Critical", "GL-014", "Hunza", "Advisor", "Sample data"):
        assert sample not in text, sample
    assert not re.search(r"\b33\b", text)


# --- lake detail --------------------------------------------------------------------------------
def test_lake_page_score_and_its_inputs(client):
    html = client.get("/lakes/KRB").text
    assert "Optical deviation <span class=\"num\">+1.50</span>" in html
    assert "245.00 ha" in html                                     # stored baseline
    assert "Earlier July optical values</dt><dd>1 from 1 year</dd>" in html   # only 2025-07-10 is an earlier July value
    assert "Radar not scored" in html and "not risk-scored" in html       # radar scoring is off (2026-11-09)


def test_lake_page_observation_log_has_every_scene_newest_first(client):
    html = client.get("/lakes/KRB").text
    html = html[html.index("<h2>Observation log</h2>"):]          # only the log table, not the header or chart
    order = [html.index(d) for d in ("21 Oct 2026", "12 Jul 2026", "15 Aug 2025", "01 Aug 2025", "10 Jul 2025")]
    assert order == sorted(order)
    assert html.count(">Not downloaded: cloud over lake</span>") == 2
    assert html.count(">Refused by quality checks</span>") == 1
    assert html.count(">Usable</span>") == 2


def test_lake_page_marks_unbuilt_panels(client):
    html = client.get("/lakes/KRB").text
    for title in ("Dam and glacier", "Terrain above the lake", "Recent weather"):
        assert f"<h2>{title}</h2>\n  <p>No data: not part of this build.</p>" in html
    # radar IS part of the build since 2026-11-09: it must not be labelled as missing any more
    assert "<h2>Sentinel-1 radar</h2>" not in html and "Latest usable radar image" in html


def test_a_lake_with_no_data_says_so(client):
    html = client.get("/lakes/ATS").text
    assert "None yet" in html and "No scenes recorded for this lake yet." in html
    assert "No optical risk score has been computed for this lake yet." in html
    assert "No usable radar measurement yet." in html
    assert client.get("/lakes/ATS/latest-image.png").status_code == 404


def test_unknown_lake_is_404(client):
    assert client.get("/lakes/XYZ").status_code == 404


def test_missing_image_file_is_reported_not_faked(client):
    html = client.get("/lakes/KRB").text
    assert "is not on this machine" in html and "data/scenes/KRB/2026-07-12.tif" in html
    r = client.get("/lakes/KRB/latest-image.png")
    assert r.status_code == 404 and "not on this machine" in r.json()["detail"]


def test_image_is_rendered_from_the_stored_file(client, tmp_path):
    write_lake_window(tmp_path / "repo" / "data/scenes/KRB/2026-07-12.tif", 73.7053229, 36.880833)
    r = client.get("/lakes/KRB/latest-image.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert "/lakes/KRB/latest-image.png" in client.get("/lakes/KRB").text


def test_recomputed_region_has_the_same_pixel_count_as_the_measurement(tmp_path):
    write_lake_window(tmp_path / "w.tif", 73.7053229, 36.880833)
    lake = {"centre_lon": 73.7053229, "centre_lat": 36.880833, "growth_distance_limit_m": 2500.0}
    assert images.render_scene_png(tmp_path / "w.tif", lake, tmp_path / "w.png") == 25
    assert (tmp_path / "w.png").is_file()


# --- charts ---------------------------------------------------------------------------------------
def test_sparkline_needs_two_values():
    assert "polyline" not in charts.sparkline([250.0])
    assert "polyline" in charts.sparkline([240.0, 250.0])


def test_extent_chart_draws_only_real_points_and_every_scene(conn):
    from sailab import queries
    history = queries.lake_history(conn, 1)
    svg = charts.extent_chart(history, date(2025, 1, 1), TODAY)
    assert svg.count('class="pt"') == 2                    # the two usable measurements
    assert svg.count('class="baseline"') == 1              # one scored measurement
    assert svg.count('class="tick ') == 5                  # every scene
    # 2025-07-10 and 2026-07-12 are a year apart: not joined by a line
    assert svg.count(f'stroke="{charts.OPTICAL}" stroke-width="1.5"') == 0


def test_extent_chart_with_nothing_usable_says_so():
    svg = charts.extent_chart([], date(2026, 1, 1), TODAY)
    assert "No usable measurement in this period" in svg


def _ok(day: str, ha: float, sensor: str) -> dict:
    return {"acquired_at": day, "measurement_status": "ok", "extent_ha": ha, "baseline_ha": None,
            "deviation_score": None, "sensor": sensor, "too_cloudy": False,
            "source": "sentinel-1" if sensor == "radar" else "sentinel-2"}


def _axis_labels(svg: str) -> list[float]:
    return [float(v) for v in re.findall(r'text-anchor="end" class="axis">(-?\d+)</text>', svg)]


def test_far_off_radar_values_do_not_stretch_the_axis_but_are_still_shown():
    """Karambar case: optical ~255 ha, two radar errors (0.2 and 404 ha). The axis follows the optical
    values and the near radar values; the two errors are hollow markers at the edges, counted on the chart."""
    hist = [_ok("2026-07-01", 250.0, "optical"), _ok("2026-07-10", 257.0, "optical"),
            _ok("2026-07-05", 262.0, "radar"), _ok("2026-07-15", 0.2, "radar"), _ok("2026-07-20", 404.0, "radar")]
    svg = charts.extent_chart(hist, date(2026, 6, 1), date(2026, 8, 31))
    labels = _axis_labels(svg)
    assert min(labels) > 200 and max(labels) < 300, labels
    assert svg.count('class="pt"') == 2                              # both optical dots, drawn normally
    assert svg.count('class="pt-radar"') == 1                        # the near radar value, drawn normally
    assert svg.count('off-scale"') == 2                              # the two errors: not hidden
    assert "0.20 ha (off the scale, below the axis)" in svg and "404.00 ha (off the scale, above the axis)" in svg
    assert "2 radar values off the scale" in svg


def test_optical_values_always_set_the_axis():
    """An optical value is never pinned to an edge, however far it is from the others."""
    hist = [_ok("2026-07-01", 250.0, "optical"), _ok("2026-07-10", 60.0, "optical"), _ok("2026-07-05", 255.0, "radar")]
    svg = charts.extent_chart(hist, date(2026, 6, 1), date(2026, 8, 31))
    assert "off-scale" not in svg and min(_axis_labels(svg)) < 60


def test_radar_only_period_uses_all_radar_values():
    """With no optical value in the period there is nothing to compare against, so nothing is pinned."""
    hist = [_ok("2026-03-01", 255.0, "radar"), _ok("2026-03-13", 20.0, "radar")]
    svg = charts.extent_chart(hist, date(2026, 2, 1), date(2026, 4, 30))
    assert "off-scale" not in svg and svg.count('class="pt-radar"') == 2


def test_location_map_places_both_lakes():
    svg = charts.location_map([
        {"code": "KRB", "name": "Karambar Lake", "centre_lon": 73.7053229, "centre_lat": 36.880833, "data_gap": True, "link": "/lakes/KRB"},
        {"code": "ATS", "name": "Atro Sar", "centre_lon": 73.65037, "centre_lat": 36.64458, "data_gap": False, "link": "/lakes/ATS"}])
    assert "KRB" in svg and "ATS" in svg and 'stroke-dasharray="3 2"' in svg


def test_score_formatting_uses_a_real_minus_sign():
    assert pages.fmt_score(-0.9645) == "−0.96" and pages.fmt_score(1.5) == "+1.50" and pages.fmt_score(None) == "—"


# --- offline: no page may load anything from the internet ---------------------------------------------
@pytest.mark.parametrize("url", ["/", "/lakes/KRB", "/lakes/ATS", "/live", "/preview/confirm-advisory",
                                 "/preview/delivery-status", "/preview/risk-threshold", "/static/style.css"])
def test_pages_load_nothing_from_the_internet(client, url):
    """Only the live check needs a network connection; every page, style and image is served locally.
    Loads are src=, CSS url(...) and <link href>. A plain <a href> to an outside page (a cited source, Copernicus
    Browser) loads nothing until clicked, so it is allowed, but it must open in a new tab."""
    body = client.get(url).text
    refs = re.findall(r"""(?:src|url)\s*[=(]\s*["']?([^"' )>]+)""", body)
    refs += re.findall(r"""<link\b[^>]*\bhref\s*=\s*["']?([^"' >]+)""", body)
    external = [r for r in refs if re.match(r"(https?:)?//", r)]
    assert external == [], external
    for tag in re.findall(r"""<a\b[^>]*\bhref\s*=\s*["']?(?:https?:)?//[^>]*>""", body):
        assert 'target="_blank"' in tag and "noopener" in tag, tag


# --- with radar rows (added 2026-11-09) -------------------------------------------------------------
@pytest.fixture
def radar_client(source_db, tmp_path):
    """The conftest database plus one usable KRB radar pass on 2026-10-30 (260.00 ha, insufficient history)
    and one refused radar pass on 2026-11-01."""
    conn = db.connect(source_db)
    sid = db.insert_scene(conn, 1, "sentinel-1", "2026-10-30T13:05:17+00:00", None, "data/scenes/KRB/S1A_X_1.tif")
    mid = db.insert_measurement(conn, sid, 1, "radar", 260.0, "ok")
    db.insert_risk_score(conn, 1, mid, "anomaly_detector", "insufficient_history", None, None)
    sid2 = db.insert_scene(conn, 1, "sentinel-1", "2026-11-01T01:05:40+00:00", None, "data/scenes/KRB/S1A_X_2.tif")
    db.insert_measurement(conn, sid2, 1, "radar", None, "insufficient_observation")
    conn.close()
    return TestClient(create_app(source_db=source_db, work_dir=tmp_path / "work", today=lambda: TODAY,
                                 repo=tmp_path / "repo"))


def test_dashboard_shows_radar_separately_and_cloud_share_is_optical_only(radar_client):
    text = visible_text(radar_client.get("/").text)
    assert "Scenes recorded 7 5 optical, 2 radar" in text
    assert "40% 2 of 5 optical scenes" in text                      # unchanged by the radar scenes
    assert "Usable measurements 3 3 of 5 measurement attempts passed every check (optical 2 of 3, radar 1 of 2)." in text
    assert "Days since a usable measurement 10 Karambar Lake, radar, 30 Oct 2026" in text
    assert "Radar: 260.00 ha on 30 Oct 2026, 10 days ago" in text
    assert "Optical: 250.00 ha on 12 Jul 2026, 120 days ago" in text  # optical value not replaced by radar


def test_lake_page_draws_radar_as_triangles_and_labels_its_rows(radar_client):
    html = radar_client.get("/lakes/KRB").text
    assert html.count('class="pt-radar"') == 1 and html.count('class="pt"') == 2
    log = html[html.index("<h2>Observation log</h2>"):]
    assert log.count("Sentinel-1 radar") == 2 and log.count(">Refused by radar checks</span>") == 1
    assert "Radar not scored" in html and "Optical deviation" in html


def test_radar_image_outline_matches_the_measurement(tmp_path):
    """Synthetic radar + DEM from test_pipeline_radar: the drawn region must be the same 36 pixels the
    radar measurement counts."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("tpr", "tests/test_pipeline_radar.py")
    tpr = importlib.util.module_from_spec(spec); spec.loader.exec_module(tpr)
    lake = {"centre_lon": 73.7053229, "centre_lat": 36.880833, "growth_distance_limit_m": 2500.0}
    tpr.write_radar(tmp_path / "r.tif", lake)
    tpr.write_dem(tmp_path / "dem.tif", lake)
    assert images.render_radar_png(tmp_path / "r.tif", lake, tmp_path / "dem.tif", tmp_path / "r.png") == 36
    assert (tmp_path / "r.png").is_file()


# --- page structure (added 2026-11-09 after a stray </div> pushed the observation log out of the layout) ---
from html_check import unbalanced_tags  # noqa: E402  (also applied to every HTML response by conftest.py)


PAGE_URLS = ["/", "/lakes/KRB", "/lakes/ATS", "/lakes/KRB?range=12m", "/lakes/KRB?range=24m", "/lakes/KRB?page=2",
             "/lakes/XXX", "/live", "/preview/confirm-advisory", "/preview/delivery-status", "/preview/risk-threshold",
             "/preview/nope", "/scenes/1", "/scenes/2", "/scenes/3", "/scenes/6", "/scenes/7", "/scenes/9999"]


@pytest.mark.parametrize("url", PAGE_URLS)
def test_every_page_has_balanced_html(radar_client, url):
    assert unbalanced_tags(radar_client.get(url).text) == []


def test_every_html_route_is_in_the_page_list(radar_client):
    """A new HTML page must be added to PAGE_URLS, or this fails: no page can escape the structure check."""
    import re as _re
    html_routes = {r.path for r in radar_client.app.routes
                   if "GET" in getattr(r, "methods", set()) and getattr(r, "response_class", None) is not None
                   and getattr(r.response_class, "__name__", "") == "HTMLResponse"}
    covered = {p for p in html_routes for u in PAGE_URLS
               if _re.fullmatch(_re.sub(r"\{[^}]+\}", "[^/?]+", p), u.split("?")[0])}
    assert html_routes and covered == html_routes, html_routes - covered


def test_the_structure_check_runs_on_real_pages(radar_client):
    """Guards the guard: the conftest wrapper must actually see the pages, and must reject a broken one."""
    from conftest import HTML_PAGES_CHECKED
    before = len(HTML_PAGES_CHECKED)
    radar_client.get("/lakes/KRB")
    assert len(HTML_PAGES_CHECKED) == before + 1
    assert unbalanced_tags("<main><div></div></div><h2>x</h2></main>") != []


def test_observation_log_is_inside_the_main_layout(radar_client):
    html = radar_client.get("/lakes/KRB").text
    assert html.index("<h2>Observation log</h2>") < html.index("</main>")


# --- part 1 of the supervisor's fixes (2026-11-18): flowchart, one step per screen, less text -----------------
def test_dashboard_has_the_flowchart_of_every_step(client):
    html = client.get("/").text
    assert 'class="flowchart"' in html and "How a check works" in html
    from webapp.flowchart import STEPS
    assert [n for n, *_ in STEPS] == list(range(1, 11))
    for _, title, _ in STEPS:                                   # every step is drawn, in order
        assert f'class="fc-title">{title}</text>' in html
    assert html.index(">Sign in</text>") < html.index(">Detect water</text>") < html.index(">Save</text>")
    assert "no new image → replay newest stored one" in html and "radar: measured, not scored" in html


def test_live_page_shows_one_step_at_a_time_with_previous_and_next(client):
    html = client.get("/live").text
    for marker in ('id="stepper"', 'id="stage"', 'id="prev"', 'id="next"', "ArrowRight", "ArrowLeft"):
        assert marker in html, marker


def test_long_explanations_sit_behind_a_toggle_not_on_the_page(client):
    lake = client.get("/lakes/KRB").text
    assert '<details class="more"><summary>How to read this chart</summary>' in lake
    assert '<details class="more"><summary>Why radar is not scored</summary>' in lake
    assert lake.count('<details class="more">') >= 3     # chart, radar, quality labels (no image files in the test database)


# --- part 4 (2026-11-18): Nepal test lakes ---------------------------------------------------------------
def test_nepal_lakes_are_grouped_apart_everywhere(client):
    dash = client.get("/").text
    assert '<h3 class="map-country">Nepal (test lakes)</h3>' in dash and '<h3 class="map-country">Pakistan</h3>' in dash
    assert dash.count('class="map-country"') == 2                    # one map per country, not one stretched map
    assert '<div class="section">Nepal (test lakes)</div>' in dash   # sidebar
    assert dash.index('<div class="section">Lakes</div>') < dash.index('<div class="section">Nepal (test lakes)</div>')
    live = client.get("/live").text
    assert '<optgroup label="Nepal (test lakes)">' in live and '<optgroup label="Pakistan">' in live
    assert live.index('value="THU"') > live.index('<optgroup label="Nepal (test lakes)">')
