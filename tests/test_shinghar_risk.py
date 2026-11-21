"""Tests for the ShinGhar risk-fusion formula (shinghar.risk)."""
import pytest

from shinghar import risk as r


def test_weights_sum_to_one_and_every_component_has_a_scale():
    assert sum(r.WEIGHTS.values()) == pytest.approx(1.0)
    assert set(r.WEIGHTS) | set(r.SITE_WEIGHTS) == set(r.SCALES) == set(r.UNITS)


@pytest.mark.parametrize("name,value,expected", [
    ("lake_growth", -3.0, 0.0), ("lake_growth", 5.0, 0.5), ("lake_growth", 25.0, 1.0),
    ("flood_path", 60.0, 0.0), ("flood_path", 5.0, 1.0), ("flood_path", 27.5, 0.5), ("flood_path", 2.0, 1.0),
    ("loss_slope", 25.0, 0.5), ("lake_anomaly", None, None),
])
def test_scale(name, value, expected):
    assert r.scale(name, value) == (None if expected is None else pytest.approx(expected))


def test_bands():
    assert [r.band(s) for s in (0, 29.9, 30, 59.9, 60, 100)] == ["low", "low", "watch", "watch", "high", "high"]


def test_all_maximal_gives_100_high():
    res = r.fuse("v", {"lake_growth": 50, "lake_anomaly": 5, "flood_path": 0, "forest_loss_upslope": 100, "loss_slope": 45})
    assert res.score == 100.0 and res.band == "high" and res.coverage == 1.0 and res.missing == []


def test_hand_computed_score_and_contributions():
    res = r.fuse("v", {"lake_growth": 5.0, "lake_anomaly": None, "flood_path": 27.5,
                       "forest_loss_upslope": 10.0, "loss_slope": 15.0})
    pts = {c.name: c.points for c in res.components}
    # 25*0.5 + 0 (missing) + 20*0.5 + 25*0.5 + 15*0
    assert pts == {"lake_growth": 12.5, "lake_anomaly": 0.0, "flood_path": 10.0, "forest_loss_upslope": 12.5, "loss_slope": 0.0}
    assert res.score == 35.0 and res.band == "watch"
    assert res.missing == ["lake_anomaly"] and res.coverage == 0.85


def test_reasons_come_from_numbers_and_name_missing_data():
    res = r.fuse("v", {"lake_growth": 7.2, "lake_anomaly": None, "flood_path": 8.0,
                       "forest_loss_upslope": 4.0, "loss_slope": 31.0},
                 details={"lake_growth": "Lake X", "flood_path": "Lake X"})
    text = " ".join(res.reasons)
    assert "+7.2 %/yr" in text and "fast-expansion flag" in text
    assert "on the downhill path of water from Lake X, 8 km below the lake" in text
    assert len(res.reasons) == 4          # 3 top reasons + the missing-data note
    assert res.reasons[-1].startswith("No data for: lake anomaly")


def test_nothing_measured():
    res = r.fuse("v", {})
    assert res.score == 0.0 and res.coverage == 0.0 and res.band == "low"
    assert res.reasons[0].startswith("None of the measured factors")


def test_not_applicable_is_known_zero_not_missing():
    res = r.fuse("v", {"flood_path": 20_000.0, "forest_loss_upslope": 0.0},
                 not_applicable={"lake_growth": "no monitored lake upstream", "lake_anomaly": "no monitored lake upstream",
                                 "loss_slope": "no loss upslope"})
    assert res.score == 0.0 and res.coverage == 1.0 and res.missing == []
    assert res.not_applicable == ["lake_growth", "lake_anomaly", "loss_slope"]
    assert "Does not apply: lake growth, lake anomaly (no monitored lake upstream); loss slope (no loss upslope)." in res.reasons
    assert not any(t.startswith("No data for") for t in res.reasons)


def test_site_weights_sum_to_one_and_have_scales():
    assert sum(r.SITE_WEIGHTS.values()) == pytest.approx(1.0)
    assert all(k in r.SCALES and k in r.UNITS for k in r.SITE_WEIGHTS)


def test_site_risk_formula_and_reasons():
    # 5 ha (0.5) x 30 + 35 deg (1.0) x 30 + 250 m below (1.0) x 30 + 1 km to water (0.0) x 10 = 75
    res = r.fuse("site 1", {"site_area": 5.0, "loss_slope": 35.0, "village_below": 250.0, "near_water": 1000.0},
                 {"village_below": "Testkot", "loss_slope": "at this site"}, weights=r.SITE_WEIGHTS)
    assert res.score == 75.0 and res.band == "high" and res.coverage == 1.0
    text = " ".join(res.reasons)
    assert "Testkot, is 250 m away" in text and "loss at this site is on steep ground" in text


def test_site_without_a_village_below_is_not_applicable_not_missing():
    res = r.fuse("site 2", {"site_area": 2.0, "loss_slope": 20.0, "near_water": 500.0}, weights=r.SITE_WEIGHTS,
                 not_applicable={"village_below": "no listed village is lower than this site"})
    assert res.not_applicable == ["village_below"] and res.missing == [] and res.coverage == 1.0
    assert any(r.startswith("Does not apply: village below") for r in res.reasons)


def test_outflow_path_points_fall_with_distance_along_the_path():
    # the reason for the 2026-11-21 change: 24 km and 38 km down the path must not score the same
    near = r.fuse("v", {"flood_path": 24.0}).components
    far = r.fuse("v", {"flood_path": 38.0}).components
    pn = next(c.points for c in near if c.name == "flood_path")
    pf = next(c.points for c in far if c.name == "flood_path")
    assert pn > pf > 0 and pn == round(20 * (50 - 24) / 45, 1) and pf == round(20 * (50 - 38) / 45, 1)
