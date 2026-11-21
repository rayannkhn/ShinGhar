"""The /shinghar page: honest banners, 'not built' when there are no cached files, the review gate over HTTP."""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from shinghar import alerts as A
from shinghar import risk as R
from webapp.main import create_app

TODAY = date(2026, 11, 20)


def make_client(source_db, tmp_path, monkeypatch, data_dir):
    monkeypatch.setenv("SHINGHAR_DATA_DIR", str(data_dir))
    return TestClient(create_app(source_db=source_db, work_dir=tmp_path / "work", today=lambda: TODAY,
                                 repo=tmp_path / "repo"))


def write_cache(d):
    d.mkdir(parents=True, exist_ok=True)
    (d / "valley.json").write_text(json.dumps({"valley": "Test valley", "tehsil": "T", "district": "D", "province": "P",
                                               "lakes": ["KRB"], "villages": []}))
    (d / "build_log.json").write_text(json.dumps({"finished": "2026-11-20T00:00:00+00:00"}))
    (d / "forest_agreement.json").write_text(json.dumps({
        "forest_ha": 100.0, "before_year": "2019", "after_year": "2025", "s2_images_before": 5, "s2_images_after": 6,
        "hansen_asset": "UMD/hansen/global_forest_change_2025_v1_13", "hansen_years": [2020, 2025],
        "ours_loss_ha": 3.0, "hansen_loss_ha": 1.0, "both_loss_ha": 0.5,
        "agreement": {"ours_confirmed_by_hansen": 0.1667, "hansen_found_by_ours": 0.5, "iou": 0.1429}}))
    (d / "forest_patches.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": None, "properties": {
            "patch_id": 7, "rank": 1, "rank_score": 88.0, "area_ha": 1.23, "source": "both", "hansen_main_year": 2023,
            "mean_slope_deg": 31.0, "nearest_settlement": "Testkot", "dist_settlement_m": 1500, "dist_water_m": 200,
            "lat": 35.5, "lon": 72.5}}]}))
    (d / "glacier.json").write_text(json.dumps({"KRB": {"name": "Karambar Lake", "lon": 73.7, "lat": 36.9,
        "trend": {"fast_expansion": None, "growth_pct_per_yr": None, "note": "Not enough summer data: 0 year(s).", "yearly": []},
        "anomaly": None, "optical_ok": 0, "optical_scenes": 0, "newest_scene": None}}))
    res = R.fuse("Testkot", {"flood_path": 100.0, "forest_loss_upslope": 25.0, "loss_slope": 40.0, "lake_growth": 12.0},
                 details={"lake_growth": "Karambar Lake", "flood_path": "Karambar Lake (5 km upstream)"})
    (d / "risk.json").write_text(json.dumps({"weights": R.WEIGHTS, "scales": R.SCALES, "bands": R.BANDS,
        "forest_radius_m": 3000, "upstream_path_max_m": 1500, "path_max_height_above_m": 50,
        "risk_loss_sources": ["both", "ndvi_only", "hansen_only"],
        "results": [{"village": {"name": "Testkot", "area": "T", "elev_m": 2000, "lat": 35.5, "lon": 72.5},
                     "score": res.score, "band": res.band, "coverage": res.coverage, "reasons": res.reasons,
                     "components": [c.__dict__ for c in res.components]}]}))
    al = A.Alert("testkot-high", "Testkot", res.band, res.score, "briefing text", A.community_message("ur", "high", "ٹیسٹ"),
                 A.community_message("ps", "high", "ٹیسٹ"))
    A.AlertStore(d / "alerts.json").save({al.alert_id: al})
    return res


def test_page_says_not_built_without_cached_files(source_db, tmp_path, monkeypatch):
    c = make_client(source_db, tmp_path, monkeypatch, tmp_path / "empty")
    for url in ("/shinghar", "/shinghar/overview", "/shinghar/villages", "/shinghar/forest", "/shinghar/lakes", "/shinghar/alerts", "/shinghar/method"):
        html = c.get(url).text
        assert "Hazard screening, not a forecast." in html and "not sent to anyone" in html, url
        assert "Not built" in html, url
    assert c.get("/shinghar/nope").status_code == 404


def test_page_shows_cached_numbers_and_review_gate(source_db, tmp_path, monkeypatch):
    d = tmp_path / "sg"
    res = write_cache(d)
    assert res.band == "high"
    c = make_client(source_db, tmp_path, monkeypatch, d)
    over = c.get("/shinghar/overview").text
    assert "Testkot" in over and "/static/shinghar.css" in over and "SailAb GLOF</a>" not in over   # own layout
    assert "1 / 0" in over                                  # villages high / watch
    vill = c.get("/shinghar/villages").text
    assert f"{res.score:.0f}" in vill and "fast-expansion flag" in vill    # reason from the numbers
    forest = c.get("/shinghar/forest").text
    assert "16.7 %" in forest                               # share of our loss also in Hansen
    assert "Third check: Google Dynamic World" in forest and "No Dynamic World result" in forest   # honest "not built"
    assert "Not enough summer data" in c.get("/shinghar/lakes").text
    html = c.get("/shinghar/alerts").text
    assert '<span class="now">draft</span>' in html and "sent: no" in html
    # a HIGH alert cannot be marked ready before review
    r = c.post("/shinghar/alerts/testkot-high/ready", follow_redirects=False)
    assert r.status_code == 409
    r = c.post("/shinghar/alerts/testkot-high/review", content="reviewer=", headers={"content-type": "application/x-www-form-urlencoded"},
               follow_redirects=False)
    assert r.status_code == 409                             # a name is required
    r = c.post("/shinghar/alerts/testkot-high/review", content="reviewer=Dr+Test",
               headers={"content-type": "application/x-www-form-urlencoded"}, follow_redirects=False)
    assert r.status_code == 303
    assert c.post("/shinghar/alerts/testkot-high/ready", follow_redirects=False).status_code == 303
    stored = A.AlertStore(d / "alerts.json").load()["testkot-high"]
    assert stored.state == "ready" and stored.sent is False and stored.history[0]["by"] == "Dr Test"
    assert '<span class="now">ready</span>' in c.get("/shinghar/alerts").text


def test_file_routes_only_serve_known_files(source_db, tmp_path, monkeypatch):
    d = tmp_path / "sg"
    write_cache(d)
    c = make_client(source_db, tmp_path, monkeypatch, d)
    assert c.get("/shinghar/files/forest_patches.geojson").status_code == 200
    assert c.get("/shinghar/files/valley.json").status_code == 404
    assert c.get("/shinghar/audio/../alerts.json").status_code == 404



def write_story(d):
    """Minimal story images metadata (the images themselves are not needed to render the page)."""
    st = d / "story"
    st.mkdir(parents=True, exist_ok=True)
    (st / "story_images.json").write_text(json.dumps({
        "source": {"before_year": "2019", "after_year": "2025", "images_before": 5, "images_after": 6},
        "valley": {"files": {"before": "valley_2019.jpg", "after": "valley_2025.jpg"}, "width": 100, "height": 100,
                   "scale_m_per_px": 10.0, "lakes": [], "villages": [{"name": "Testkot", "xy": [50, 50]}],
                   "sites": [{"rank": 1, "area_ha": 1.23, "xy": [40, 40]}]},
        "sites": [{"rank": 1, "patch_id": 7, "files": {"before": "s_2019.jpg", "after": "s_2025.jpg"}, "chip_m": 1200}],
        "lake": None}))
    (st / "valley_2025.jpg").write_bytes(b"\xff\xd8\xff")


def test_story_page_plain_language_and_demo(source_db, tmp_path, monkeypatch):
    d = tmp_path / "sg"
    write_cache(d)
    c = make_client(source_db, tmp_path, monkeypatch, d)
    assert "Not built" in c.get("/shinghar").text           # no story images yet: says so
    write_story(d)
    html = c.get("/shinghar").text
    assert "Start demo" in html and "Which mountain villages should be checked first" in html
    assert "slope sites flagged for ranger visits" in html and "villages screened" in html
    assert 'id="place"' in html and 'id="sees"' in html and 'id="who"' in html and 'id="next"' in html
    # plain language: no jargon on the landing page (it lives in the Expert view)
    import re
    text = re.sub(r"<script.*?</script>|<[^>]+>", " ", html, flags=re.S)
    for jargon in ("NDVI", "GHSL", "Dynamic World", "z-score", "NDWI", "Hansen"):
        assert jargon not in text, jargon
    assert "1.2 ha of forest lost its green between 2019 and 2025" in html          # site sentence from the numbers
    assert c.get("/shinghar/img/valley_2025.jpg").status_code == 200
    assert c.get("/shinghar/img/../alerts.json").status_code == 404


def test_reset_puts_an_alert_back_to_draft_and_keeps_history(source_db, tmp_path, monkeypatch):
    d = tmp_path / "sg"
    write_cache(d)
    c = make_client(source_db, tmp_path, monkeypatch, d)
    c.post("/shinghar/alerts/testkot-high/review", content="reviewer=Dr+Test",
           headers={"content-type": "application/x-www-form-urlencoded"}, follow_redirects=False)
    assert c.post("/shinghar/alerts/testkot-high/reset", follow_redirects=False).status_code == 303
    stored = A.AlertStore(d / "alerts.json").load()["testkot-high"]
    assert stored.state == "draft" and [h["event"] for h in stored.history] == ["reviewed by expert", "reset to draft (demo)"]


def test_plain_sentences_use_the_villages_own_numbers():
    from webapp.shinghar_page import plain_village_reason, site_sentence
    comp = lambda n, raw, pts: {"name": n, "raw": raw, "points": pts, "weight": .2}
    r = {"components": [comp("forest_loss_upslope", 5.76, 7.2), comp("loss_slope", 35.7, 15.0), comp("flood_path", 34.2, 7.0)]}
    assert plain_village_reason(r) == "5.8 ha of forest on the slopes above the village lost its green since 2019, on ground about 36° steep."
    r = {"components": [comp("flood_path", 9.9, 17.8), comp("forest_loss_upslope", 3.73, 4.7)]}
    assert plain_village_reason(r) == "It lies 10 km downstream of a glacial lake, on the path its water would take."
    assert plain_village_reason({"components": []}).startswith("Nothing we measure adds to the score")
    p = {"area_ha": 2.94, "mean_slope_deg": 38.5, "nearest_settlement": "Asharopatoi", "dist_settlement_m": 3133, "mean_elev_m": 2385}
    s = site_sentence(p, {"Asharopatoi": {"elev_m": 1851}}).format(b=2019, a=2025)
    assert s == "2.9 ha of forest lost its green between 2019 and 2025, on a 38° slope, 3.1 km from Asharopatoi and 530 m above it."
