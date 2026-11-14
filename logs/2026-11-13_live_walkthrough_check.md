# Live check, step by step: real runs on 2026-11-13

App: `webapp/` with the step-by-step Live check page, port 8003, its own working copy (scratchpad work_8003),
real Earth Engine and real ESA Copernicus Data Space catalogue. Test suite before the runs: 272 passed.

## Darkut (DKT), started 12:18 UTC: status no_new_scene, 20 steps, about 27 s
1. Signed in as sailab-glof-bot@kaarigar-507118.iam.gserviceaccount.com
2. Optical search: 1 scene listed (20261110T055049_20261110T055844_T43SCA, 100.0 % cloud over the lake), already stored, skipped
3. Radar search: 1 scene listed (S1D_IW_GRDH_1SDV_20261110T010541_..._EE4D), already stored, skipped
4-12. Optical replay of 2026-09-21: ESA found S2B_MSIL2A_20260921T054639_N0513_R048_T43SCA_20260921T093437.SAFE;
      NDWI at centre (1,459 - 541) / (1,459 + 541) = 0.459; 1,645 px x 100 m2 = 16.45 ha;
      score (16.45 - 16.05) / 0.37 = 1.08, equal to the stored risk score #137 (+1.08); nothing written
13-20. Radar replay of 2026-11-10: ESA found S1D_IW_GRDH_1SDV_20261110T010541_20261110T010606_005398_00A4C0_EE4D.SAFE;
      32,536 steep pixels removed, Otsu threshold -13.23 dB over 7,618 flat pixels, centre -17.32 dB;
      1,434 px = 14.34 ha; not scored (SCORE_RADAR off); nothing written

## Shishper (SHP): status no_new_scene, 13 steps, 11.5 s
- Optical replay of 2022-04-30 (latest usable): ESA found S2A_MSIL2A_20220430T054641_N0510_R048_T43SDA_20240609T030932.SAFE;
  NDWI at centre 0.297; 583 px = 5.83 ha; insufficient history (check F); nothing written
- Radar: "No stored radar measurement to replay" (radar has never measured this lake)

## Problem found and fixed during the runs
- First Darkut run: ESA's catalogue timed out (10 s) on the optical lookup; the card said so and the check carried on.
  A name-only query took 20.2 s; adding a 2-minute time window around the pass took 0.6 s. Fixed in esa_filter().
