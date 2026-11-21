"""Tests for shinghar.forest (pure numpy logic; no Earth Engine)."""
import numpy as np
import pytest

from shinghar import forest as f


def test_ndvi_values_and_zero_denominator():
    out = f.ndvi(np.array([0.5, 0.3, 0.0]), np.array([0.1, 0.3, 0.0]))
    assert out[0] == pytest.approx(0.4 / 0.6)
    assert out[1] == 0.0
    assert np.isnan(out[2])


def test_forest_mask_is_worldcover_trees_or_hansen_30():
    wc = np.array([10, 30, 30, 10])
    tc = np.array([0, 30, 29, 80])
    assert f.forest_mask(wc, tc).tolist() == [True, True, False, True]


def test_ndvi_loss_needs_forest_and_drop_above_threshold_and_never_counts_nan():
    before = np.array([0.8, 0.8, 0.8, 0.8, np.nan])
    after = np.array([0.5, 0.65, 0.5, 0.79, 0.1])
    forest = np.array([True, True, False, True, True])
    # drops: 0.3 (loss), 0.15 (below 0.2), 0.3 but not forest, 0.01, NaN
    assert f.ndvi_loss(before, after, forest).tolist() == [True, False, False, False, False]


def test_hansen_loss_window_and_forest():
    ly = np.array([0, 18, 19, 25, 26, 22])
    tc = np.array([90, 90, 90, 90, 90, 10])
    assert f.hansen_loss(ly, 2019, 2025, tc).tolist() == [False, False, True, True, False, False]


def test_agreement_counts_and_none_when_empty():
    ours = np.array([1, 1, 0, 0, 1], dtype=bool)
    hans = np.array([1, 0, 1, 0, 1], dtype=bool)
    valid = np.array([1, 1, 1, 1, 0], dtype=bool)
    a = f.agreement(ours, hans, valid)
    assert (a["ours_px"], a["hansen_px"], a["both_px"], a["either_px"]) == (2, 2, 1, 3)
    assert a["ours_confirmed_by_hansen"] == 0.5 and a["hansen_found_by_ours"] == 0.5
    assert a["iou"] == pytest.approx(1 / 3)
    empty = f.agreement(np.zeros(3, bool), np.zeros(3, bool), np.ones(3, bool))
    assert empty["iou"] is None and empty["ours_confirmed_by_hansen"] is None


def test_label_patches_min_area_source_year_slope():
    loss = np.zeros((20, 20), bool)
    loss[0:8, 0:8] = True          # 64 px = 0.64 ha -> kept
    loss[15:17, 15:17] = True      # 4 px = 0.04 ha -> dropped
    ours = np.zeros_like(loss); ours[0:4, 0:8] = True
    hans = np.zeros_like(loss); hans[4:8, 0:8] = True
    ly = np.zeros((20, 20), int); ly[4:8, 0:8] = 22
    slope = np.full((20, 20), 30.0)
    labels, patches = f.label_patches(loss, ours, hans, ly, slope)
    assert len(patches) == 1
    p = patches[0]
    assert p.area_ha == pytest.approx(0.64)
    assert p.source == "both" and p.ndvi_share == 0.5 and p.hansen_share == 0.5
    assert p.hansen_main_year == 2022 and p.mean_slope_deg == 30.0
    assert labels[16, 16] == 0 and labels[0, 0] == p.patch_id


def test_label_patches_empty():
    labels, patches = f.label_patches(np.zeros((5, 5), bool), np.zeros((5, 5), bool), np.zeros((5, 5), bool))
    assert patches == [] and labels.sum() == 0


def test_nearest():
    assert f.nearest([("a", 0, 0), ("b", 10, 0)], 8, 0) == ("b", 2.0)
    assert f.nearest([], 0, 0) == (None, None)


def test_rank_patches_weights_and_order():
    ps = [f.Patch(1, 1.0, 0, 0, mean_slope_deg=10, dist_settlement_m=6000),
          f.Patch(2, 3.0, 0, 0, mean_slope_deg=30, dist_settlement_m=0),
          f.Patch(3, 2.0, 0, 0, mean_slope_deg=None, dist_settlement_m=2500)]
    out = f.rank_patches(ps)
    # p2: 40*1 + 30*1 + 30*1 = 100; p3: 40*0.5 + 0 + 30*0.5 = 35; p1: 0 + 0 + 0 = 0
    assert [(p.patch_id, p.rank_score, p.rank) for p in out] == [(2, 100.0, 1), (3, 35.0, 2), (1, 0.0, 3)]
    assert f.rank_patches([]) == []
