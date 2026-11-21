"""Tests for the ShinGhar fast-expansion trend (shinghar.glacier)."""
from datetime import date

import pytest

from sailab import db
from shinghar import glacier as g


def test_trend_on_hand_computed_series():
    vals = []
    for y, ha in [(2021, 10.0), (2022, 11.0), (2023, 12.0)]:
        vals += [(date(y, 7, 10), ha), (date(y, 8, 10), ha), (date(y, 8, 20), ha + 100)]  # median ignores the outlier... (3 values)
    t = g.summer_trend(vals)
    # medians of (ha, ha, ha+100) = ha; slope 1 ha/yr; mean 11 -> 9.09 %/yr > 5
    assert [r["median_ha"] for r in t.yearly] == [10.0, 11.0, 12.0]
    assert t.slope_ha_per_yr == pytest.approx(1.0)
    assert t.growth_pct_per_yr == pytest.approx(9.09)
    assert t.fast_expansion is True


def test_non_summer_and_thin_years_are_left_out_and_reported():
    vals = [(date(2021, 5, 1), 50.0), (date(2021, 7, 1), 10.0), (date(2021, 7, 9), 10.0),
            (date(2022, 8, 1), 10.0),                                  # one value: skipped
            (date(2023, 9, 1), 10.0), (date(2023, 9, 5), 10.0)]
    t = g.summer_trend(vals)
    assert [r["year"] for r in t.yearly] == [2021, 2023]
    assert t.skipped_years == [{"year": 2022, "n": 1}]
    assert t.growth_pct_per_yr is None and t.fast_expansion is None   # 2 years < MIN_YEARS: not "0 % growth"
    assert t.note.startswith("Not enough summer data")


def test_stable_lake_not_flagged():
    vals = [(date(y, m, 1), 40.0) for y in (2020, 2021, 2022, 2023) for m in (7, 8)]
    t = g.summer_trend(vals)
    assert t.growth_pct_per_yr == 0.0 and t.fast_expansion is False


def test_lake_values_and_latest_anomaly_read_the_sailab_tables(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    lid = db.insert_lake(conn, "TST", "T", 72.4, 35.4, 1000.0, 1000.0)
    s1 = db.insert_scene(conn, lid, "sentinel-2", "2024-07-01T05:00:00+00:00", 0.0, "a.tif")
    s2 = db.insert_scene(conn, lid, "sentinel-1", "2024-07-02T05:00:00+00:00", None, "b.tif")
    s3 = db.insert_scene(conn, lid, "sentinel-2", "2024-07-03T05:00:00+00:00", 0.0, "c.tif")
    m1 = db.insert_measurement(conn, s1, lid, "optical", 40.0, "ok")
    db.insert_measurement(conn, s2, lid, "radar", 41.0, "ok")
    db.insert_measurement(conn, s3, lid, "optical", None, "insufficient_observation")
    db.insert_risk_score(conn, lid, m1, "anomaly_detector", "ok", 39.0, 0.8)
    assert g.lake_values(conn, lid) == [(date(2024, 7, 1), 40.0)]
    assert g.latest_anomaly(conn, lid) == {"z": 0.8, "baseline_ha": 39.0, "date": "2024-07-01", "extent_ha": 40.0}
    assert g.latest_anomaly(conn, 999) is None
