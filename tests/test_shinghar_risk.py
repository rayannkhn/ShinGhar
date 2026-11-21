"""Tests for the ShinGhar risk-fusion formula (shinghar.risk)."""
import pytest

from shinghar import risk as r


def test_weights_sum_to_one_and_every_component_has_a_scale():
    assert sum(r.WEIGHTS.values()) == pytest.approx(1.0)
    assert set(r.WEIGHTS) == set(r.SCALES) == set(r.UNITS)


@pytest.mark.parametrize("name,value,expected", [
    ("lake_growth", -3.0, 0.0), ("lake_growth", 5.0, 0.5), ("lake_growth", 25.0, 1.0),
    ("flood_path", 20_000.0, 0.0), ("flood_path", 500.0, 1.0), ("flood_path", 5250.0, 0.5),
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
    res = r.fuse("v", {"lake_growth": 5.0, "lake_anomaly": None, "flood_path": 5250.0,
                       "forest_loss_upslope": 10.0, "loss_slope": 15.0})
    pts = {c.name: c.points for c in res.components}
    # 25*0.5 + 0 (missing) + 20*0.5 + 25*0.5 + 15*0
    assert pts == {"lake_growth": 12.5, "lake_anomaly": 0.0, "flood_path": 10.0, "forest_loss_upslope": 12.5, "loss_slope": 0.0}
    assert res.score == 35.0 and res.band == "watch"
    assert res.missing == ["lake_anomaly"] and res.coverage == 0.85


def test_reasons_come_from_numbers_and_name_missing_data():
    res = r.fuse("v", {"lake_growth": 7.2, "lake_anomaly": None, "flood_path": 800.0,
                       "forest_loss_upslope": 4.0, "loss_slope": 31.0},
                 details={"lake_growth": "Lake X", "flood_path": "Lake X"})
    text = " ".join(res.reasons)
    assert "+7.2 %/yr" in text and "fast-expansion flag" in text
    assert "Houses of the village are 800 m from the downhill path water would take out of Lake X." in text
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
