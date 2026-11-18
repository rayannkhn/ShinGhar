"""Lake information: cited facts are complete and well-formed, and the plain-language reading follows the data."""
from __future__ import annotations

from pathlib import Path

import pytest

from sailab.db import SEED_LAKES
from webapp import lake_info as L

REPO = Path(__file__).resolve().parent.parent


def row(date, area, source="sentinel-2", status="ok"):
    return {"acquired_at": date, "extent_ha": area, "source": source,
            "sensor": "optical" if source == "sentinel-2" else "radar", "measurement_status": status}


# --- the cited facts --------------------------------------------------------------------------------
def test_every_seed_lake_has_an_entry():
    assert {l["code"] for l in SEED_LAKES} == set(L.FACTS)


def test_every_fact_cites_a_known_https_source():
    for code, f in L.FACTS.items():
        for fact in f.about + f.history:
            assert fact.sources, (code, fact.text)
            for key in fact.sources:
                assert key in L.SOURCES, (code, key)
    for key, (label, url) in L.SOURCES.items():
        assert url.startswith("https://") and label, key


def test_every_source_is_used():
    used = {k for f in L.FACTS.values() for fact in f.about + f.history for k in fact.sources}
    assert used == set(L.SOURCES)


def test_a_lake_without_published_facts_says_so():
    ats = L.FACTS["ATS"]
    assert ats.about == [] and ats.history == [] and "No published source" in ats.gaps


# --- the plain-language reading ----------------------------------------------------------------------
def test_steady_lake():
    hist = [row("2020-08-01T05:00:00", 100.0), row("2020-09-01T05:00:00", 101.0),
            row("2025-08-01T05:00:00", 101.5), row("2025-09-01T05:00:00", 102.0)]
    texts = [r.text for r in L.read_our_data(hist, None, None)]
    assert any("steady" in t and "2020" in t and "2025" in t for t in texts)


def test_growing_lake_is_flagged_above_ten_percent():
    hist = [row("2020-08-01T05:00:00", 10.0), row("2020-09-01T05:00:00", 10.0),
            row("2025-08-01T05:00:00", 12.0), row("2025-09-01T05:00:00", 12.0)]
    grown = [r for r in L.read_our_data(hist, None, None) if "grown" in r.text]
    assert len(grown) == 1 and grown[0].tone == "warn" and "+20.0%" in grown[0].text


def test_years_with_one_image_do_not_make_a_trend():
    hist = [row("2020-08-01T05:00:00", 10.0), row("2025-08-01T05:00:00", 20.0)]
    texts = [r.text for r in L.read_our_data(hist, None, None)]
    assert any("Too few clear photos" in t for t in texts) and not any("grown" in t for t in texts)


def test_thin_data_is_called_thin():
    hist = [row("2024-08-01T05:00:00", 10.0), row("2024-09-01T05:00:00", None, status="insufficient_observation")]
    first = L.read_our_data(hist, None, None)[0]
    assert first.tone == "warn" and "1 of 2" in first.text and "thin" in first.text


@pytest.mark.parametrize("z, words, tone", [(0.4, "within the usual range", "ok"), (-1.5, "a little smaller", "ok"),
                                            (2.3, "clearly larger", "warn")])
def test_score_wording(z, words, tone):
    score = {"status": "ok", "deviation_score": z, "acquired_at": "2026-10-23T05:00:00"}
    got = [r for r in L.read_our_data([row("2026-10-23T05:00:00", 1.0)], score, None) if "score" in r.text]
    assert len(got) == 1 and words in got[0].text and got[0].tone == tone and f"{z:+.2f}" in got[0].text


def test_insufficient_history_score_is_explained():
    score = {"status": "insufficient_history", "deviation_score": None, "acquired_at": "2026-10-23T05:00:00"}
    texts = [r.text for r in L.read_our_data([row("2026-10-23T05:00:00", 1.0)], score, None)]
    assert any("no score yet" in t for t in texts)


def test_drained_lake_is_reported():
    judged = {"status": "no_lake_detected", "acquired_at": "2025-07-01T05:00:00"}
    texts = [r.text for r in L.read_our_data([row("2022-04-30T05:00:00", 8.8)], None, judged)]
    assert any("drained" in t and "2025-07-01" in t for t in texts)


def test_a_drained_lake_shows_no_older_score():
    judged = {"status": "no_lake_detected", "acquired_at": "2025-07-01T05:00:00"}
    score = {"status": "ok", "deviation_score": 0.3, "acquired_at": "2022-04-30T05:00:00"}
    texts = [r.text for r in L.read_our_data([row("2022-04-30T05:00:00", 8.8)], score, judged)]
    assert not any("score" in t for t in texts)


def test_a_bad_radar_pass_is_called_out_and_a_good_one_is_not():
    hist = [row(f"2024-{m:02d}-01T05:00:00", 100.0) for m in range(1, 11)]
    hist += [row(f"2024-01-{d:02d}T00:10:00", 98.0, source="sentinel-1") for d in range(1, 13)]
    hist += [row(f"2024-02-{d:02d}T12:13:00", 40.0, source="sentinel-1") for d in range(1, 13)]
    radar = [r.text for r in L.read_our_data(hist, None, None) if "Radar" in r.text]
    assert len(radar) == 1 and "~12:00 UTC orbit 60% low" in radar[0] and "~00:00 UTC orbit agrees" in radar[0]


def test_radar_agreeing_everywhere():
    hist = [row(f"2024-{m:02d}-01T05:00:00", 100.0) for m in range(1, 11)]
    hist += [row(f"2024-01-{d:02d}T00:10:00", 95.0, source="sentinel-1") for d in range(1, 13)]
    radar = [r for r in L.read_our_data(hist, None, None) if "Radar" in r.text]
    assert len(radar) == 1 and radar[0].tone == "ok" and "every orbit (12 images)" in radar[0].text


def test_radar_is_not_judged_against_too_few_clear_photos():
    hist = [row("2023-09-17T05:00:00", 0.68)]   # Passu: the one-off optical value is no reference
    hist += [row(f"2024-01-{d:02d}T00:10:00", 11.0, source="sentinel-1") for d in range(1, 13)]
    radar = [r for r in L.read_our_data(hist, None, None) if "radar" in r.text.lower()]
    assert len(radar) == 1 and radar[0].tone == "muted" and "too few clear photos" in radar[0].text


def test_no_images_at_all():
    assert [r.text for r in L.read_our_data([], None, None)] == ["No images are stored for this lake yet."]


# --- elevation from the stored DEM -------------------------------------------------------------------
def test_elevation_missing_dem_is_none(tmp_path):
    assert L.centre_elevation(tmp_path / "none.tif", 86.47656, 27.86090) is None


@pytest.mark.skipif(not (REPO / "data/dem/TRL_dem.tif").is_file(), reason="TRL DEM not on this machine")
def test_tsho_rolpa_elevation_matches_the_published_height():
    # JRC Global Surface Water / ICIMOD give about 4,546 m for the lake surface.
    assert abs(L.centre_elevation(REPO / "data/dem/TRL_dem.tif", 86.47656, 27.86090) - 4546) < 15
