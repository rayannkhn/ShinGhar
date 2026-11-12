# SailAb GLOF — automated lake monitoring (live build)

Final-year project. SailAb GLOF is designed as a five-stage early-warning system for glacial lake
outburst floods (GLOFs) in Pakistan: **Acquisition → Measurement → Risk Scoring → Downstream Analysis
→ Alerting**. This repository is the **live build of the first three stages** for **six lakes**
(Karambar and Atro Sar from the start; Shishper, Darkut, Borith and Passu added on 2026-11-10),
running automatically on real Sentinel-2 (optical) and Sentinel-1 (radar) satellite data.

> **What this is not.** This is a working, automated **monitoring prototype**. It is **not** a
> validated early-warning system and it sends **no alerts**. It has **never detected an outburst as it
> happened**. One monitored lake, Shishper, burst several times before it was added; looking back at
> its stored record, 2 of its 3 confirmed outbursts are visible (see [The six lakes](#the-six-lakes)).
> Please read [Limitations](#limitations) before quoting any number from it.

*Status as of 2026-11-11. Sections marked ⏳ change as the scheduled runs accumulate.*

---

## What runs automatically

Every night at **23:00 Pakistan time (18:00 UTC)**, GitHub Actions
([`.github/workflows/daily_run.yml`](.github/workflows/daily_run.yml)) does the following with no
human involved:

1. Installs the pinned packages and runs the **full test suite** (265 tests). If any test fails, the
   pipeline does not run, so broken code can never write to the database.
2. Signs in to Google Earth Engine with a **service-account key** stored as an encrypted GitHub
   secret (no browser, no person).
3. For each lake, lists new Sentinel-2 scenes since the newest one already stored, and measures the
   **cloud over the lake itself** (not over the whole 100 km tile), using Sentinel-2's own scene
   classification band and our own counting code.
4. Scenes with more than **10 % cloud over the lake** are **recorded but not downloaded**.
5. Clear scenes: downloads **only the small lake window** (bands B2, B3, B4, B8, B11 + SCL, 10 m,
   UTM 43N), measures the lake, and stores the measurement.
6. Scores each usable **optical** measurement against the lake's own optical **seasonal baseline**.
7. **Radar (Sentinel-1, since 2026-11-09):** lists every new radar pass (radar sees through cloud),
   downloads the lake window (VV, VH), measures the lake, and stores it as a `radar` measurement.
   Radar is **not risk-scored** (see [Radar](#radar-sentinel-1)).
8. Writes a `run_log` row (start, finish, counts, and the **real error text** if anything failed),
   writes a timestamped log file to `logs/runs/`, and **commits the database and logs back to this
   repository** — also after a failed run, so failures stay visible.

The run history is public: open the **Actions** tab of this repository. Each bot commit
("Automated run: <UTC time> (success|failure)") contains that run's log.

**Scheduled runs so far: 3**, one for each daily slot (8, 9 and 10 November). In Pakistan time they started on
three different days; by UTC start time runs 9 and 12 both started on 10 November, because of GitHub's delays.

| Date (UTC) | Trigger | Result |
|---|---|---|
| 2026-11-08 12:00 | manual (setup test) | success, no new scene |
| 2026-11-08 19:01 | manual (after pinning Ubuntu 24.04) | success, no new scene |
| **2026-11-08 21:31** | **schedule** (the 18:00 UTC slot, started 3.5 h late by GitHub) | **success**, 171 tests passed in 6.13 s (`logs/2026-11-08_scheduled_run_6_github_test_step.log`, from GitHub's job log), no new scene since 2026-11-05; bot commit `5872d48`, `run_log` row 6 |
| 2026-11-09 12:09 | manual (checking radar on GitHub) | success, no new scene; bot commit `21ad8a6`, `run_log` row 8 |
| **2026-11-10 01:01** | **schedule** (the 2026-11-09 18:00 UTC slot, started about 7 h late by GitHub) | **success**, 216 tests passed in 8.51 s; **new Sentinel-1 pass for both lakes** (2026-11-09 13:05 UTC): Karambar 257.55 ha, Atro Sar 97.14 ha, both within the 15 % rule, not scored; first images committed to `data/scenes/`; bot commit `69378dc`, `run_log` row 9 (`logs/2026-11-10_scheduled_run_2_report.md`) |
| **2026-11-10 22:42** | **schedule** (the 2026-11-10 18:00 UTC slot, about 4.7 h late) | **success**, 265 tests passed in 10.80 s; first run over **six lakes**, 11 s: new Sentinel-1 pass (2026-11-10 01:05 UTC) for Karambar 261.14 ha and Atro Sar 98.05 ha, **identical to the GUI live check of the same pass** (same areas, same file SHA-256); new optical pass too cloudy; the four new lakes already had both passes from the backfill; bot commit `20ffbfc`, `run_log` row 12 (`logs/2026-11-11_scheduled_run_3_report.md`) |

Manual runs do not count as automatic. GitHub can start scheduled runs late or skip them, so the
Actions tab is the record of which ones actually happened.

## What still needs a human

- **Adding a lake** (coordinates, window size, growth limit): `sailab/db.py`, `SEED_LAKES`.
  Changing a stored lake's values is deliberately refused unless done on purpose (see
  `logs/2026-11-08_atro_sar_window_change.log` for the one time this was done, and why).
- **Renewing the Earth Engine key** if it is revoked or expires (the run will fail visibly with the
  error in `run_log`).
- **The historical backfills** were **started by hand** with the same pipeline code; they are not
  automatic runs. Karambar and Atro Sar: optical 2023-01-01 → 2026-11-05 (run 3, 2026-11-08) and radar
  (run 7, 2026-11-09). The four lakes added on 2026-11-10: `run_once.py --backfill --lakes SHP,DKT,BRT,PSU`
  (runs 10 and 11, 2026-11-10; Shishper from 2019, the others from 2023).
- **Interpreting the results.** Nothing in this repository decides that a lake is dangerous.

## Explicitly out of scope for this build

- **Downstream Analysis** (flood path, road network) and **Alerting**. The tested code for flood
  path tracing and bridge finding is in `sailab/terrain.py`, `flood_path.py` and `network.py`, but it
  is **not connected** to this pipeline.
- **The trained risk model.** Only the seasonal-baseline fallback (FR-14/FR-18) is used.
- **Radar risk scores.** Radar is measured and shown, but not scored (see [Radar](#radar-sentinel-1)).

---

## The six lakes

| Code | Lake | Centre (lon, lat) | Window / growth limit | History from | "No lake" check | What measures it reliably |
|---|---|---|---|---|---|---|
| KRB | Karambar Lake | 73.7053229, 36.880833 | 2500 / 2500 m | 2023 | no | optical and radar |
| ATS | Atro Sar | 73.65037, 36.64458 | 1500 / 1500 m | 2023 | no | optical and radar |
| SHP | Shishper glacier lake | 74.5650, 36.3590 | 1500 / 1500 m | **2019** | **yes** | optical while the lake exists; radar never (0 of 881) |
| DKT | Darkut glacial lake | 73.40701, 36.64219 | 1000 / 1000 m | 2023 | **yes** | optical and radar |
| BRT | Borith Lake | 74.86214, 36.43053 | 1000 / 1000 m | 2023 | no | radar; optical only partly |
| PSU | Passu glacier lake | 74.87979, 36.45744 | 1000 / 1000 m | 2023 | no | radar only (silty water) |

Karambar and Atro Sar use the exact values the project's earlier real results were computed from.
**Atro Sar's window was changed from 800 m to 1500 m on 2026-11-08** because the 800 m export cut the
lake off at the window's edge: the earlier reported **76.51 ha was only the part inside the window**.
On the same 2026-07-18 scene the whole lake measures **105.82 ha** (identical at 1500, 2000 and
2500 m). Evidence: `logs/2026-11-08_step5_atro_sar_radius_check.log`.

**The four lakes added on 2026-11-10** were chosen with the project owner from lakes with a recorded
outburst or a published outburst risk. Before any was added, each candidate was tested with the
pipeline's own download and measurement on real scenes (`logs/2026-11-10_new_lake_candidates/README.md`).
Khurdopin and Ghulkin were tested and **left out**: neither has a lake to measure now (a dry river plain;
ponds on the glacier surface). Pakistan's official list of 33 hazardous lakes could not be found by name.

- **Shishper (Hassanabad, Hunza):** an ice-dammed lake beside the surging Shishper glacier; outbursts on
  22–23 June 2019, 29 May 2020 and 7 May 2022 (the KKH bridge). Centre: inside both the 2019 and the 2022
  lake outlines on Sentinel-2. History starts in **2019** so its own outbursts are in the record. Looking
  back, **2 of the 3 are visible** (`scripts/check_shishper_outbursts.py` →
  `logs/2026-11-11_shishper_outburst_check.log`): 2019 (11.77 ha on 31 May → 0.09 ha on 5 July → no lake
  from 4 August) and 2022 (17.05 ha on 10 April, 5.83 ha on 30 April → no lake on 14 June). **2020 is not:**
  the lake was there (1,048 pixels, 10.48 ha, on 25 May) but cloud touched it, so check D refused it. Every
  "no lake" scene was checked on the image: none shows water at the lake site
  (`logs/2026-11-11_shishper_timeline_truecolour.png`). Radar refuses every Shishper pass (narrow, steep,
  debris-covered valley).
- **Darkut (Yasin):** at the Darkut glacier tongue; grown from 4.5 to 15.4 ha (Amin et al. 2020,
  Meteorological Applications, doi 10.1002/met.1877). Centre: the published position (PMD study). The
  most consistent new lake: all 86 usable optical values are 14.74–17.80 ha; radar agrees except in winter.
- **Borith (Hunza):** near the Passu and Ghulkin glaciers; named a possible future GLOF source (Iqbal et
  al. 2023). Radar is steady (about 11 ha in summer). **Optical is unreliable:** NDWI often catches only
  part of the lake (19 of 81 usable values are under 9 ha), which produced false scores such as −8.81.
- **Passu (Hunza):** at the Passu glacier snout; past outbursts (e.g. January 2008) and a May 2022 meltwater
  release. **Its silty water is invisible to NDWI:** only 3 of 156 optical measurements were "usable",
  and those are wrong (0.48–4.17 ha against about 19 ha on the JRC water map and about 11 ha by radar).
  Radar measures it in 277 of 335 passes.

## Data source

All imagery is ESA Copernicus data: **Sentinel-2 Level-2A** surface reflectance
(`COPERNICUS/S2_SR_HARMONIZED`), **Sentinel-1 GRD** radar (`COPERNICUS/S1_GRD`) and the **Copernicus 30 m
DEM** for the radar slope mask, accessed through **Google Earth Engine** with a service account
registered for noncommercial use. Every stored scene is identified by its Earth Engine scene id
(e.g. `20260718T054641_20260718T055712_T43SCA`) and can be re-downloaded by anyone with Earth Engine
access. The SHA-256 of every downloaded file is written to the run log.

The water detection, region growing, area, cloud and snow checks and risk scores are all computed
by this repository's own code, not by Earth Engine.

---

## How a measurement is made (and when it is refused)

Code: `sailab/pipeline.py` → `measure_scene`, using the unchanged, earlier-tested functions in
`sailab/measurement.py`.

1. NDWI per pixel from B3 (green) and B8 (near-infrared); water if NDWI > **0.2**.
2. The lake centre is located from the file's own georeferencing.
3. Water is grown outward from the centre (4-connected), within the lake's growth limit.
4. Area = pixel count × 100 m².

A measurement is recorded as **`insufficient_observation` (never as a zero)** when:

- the centre pixel is not water (e.g. frozen lake);
- the lake touches missing data at the window edge (it may be cut off);
- **cloud or cloud shadow touches the lake** (check D);
- **snow or ice touches the lake, or covers more than half of the lake circle** (check C).

Checks C and D were added after the first backfill showed real errors: a snowfield counted as lake
(462.88 ha for a ~250 ha lake), a frozen lake measured as 0.14 ha, and cloud hiding part of a lake
(87.42 ha instead of ~106). See `logs/2026-11-08_backfill_outliers_true_colour_vs_detected.png`.
They are deliberately **strict**: they also rejected 43 measurements that looked correct (often for
only a few noisy edge pixels). We chose fewer measurements over wrong ones.

**"No lake detected"** (added 2026-11-10, status `no_lake_detected`, **no area stored**): an ice-dammed lake
that bursts can vanish, and "centre not water" then looks like any bad image. For lakes whose water NDWI
sees reliably (Shishper and Darkut, `lake.detects_drainage = 1`), a "centre not water" scene is recorded as
"no lake" only if it is from **May–October** (outside it a frozen lake also shows no water), there is **no
cloud, cloud shadow, snow/ice or missing data within 150 m of the centre**, and **under 10 %** of the pixels
there are water. Judgement-call limits, not calibrated. Silty lakes (Passu) must never use it: NDWI misses
their water even when the lake is full. Tests: `tests/test_pipeline.py` (winter, snow, cloud, shadow, a
data gap and lakes without the setting all stay refusals).

## How a risk score is made

Code: `sailab/risk.py` (unchanged) via `sailab/pipeline.py`.

- **Baseline** = mean of the lake's earlier usable measurements in the **same calendar month**;
  **spread** = their sample standard deviation; **score** = (new extent − baseline) / spread.
- Only measurements from **before** the scene's date are used.
- **Check F:** no score unless that month has **at least 5 earlier values from at least 2 different
  years**; otherwise the score is `insufficient_history`. With only 2–3 values the spread is tiny and
  modest changes produced meaningless scores (e.g. −49.6) in the first backfill.
- A score is a **statistical deviation**, not a danger level or a probability.

## Radar (Sentinel-1)

Code: `sailab/radar.py` (using the unchanged `otsu_threshold` and `region_grow`), wired in
`sailab/pipeline.py`. Sentinel-1 passes each lake about every 6 days (ascending and descending orbits).
The validation and error counts below are for **Karambar and Atro Sar**, where radar was first built; for
the four new lakes see [The six lakes](#the-six-lakes) (Darkut, Borith, Passu measure well by radar;
Shishper never does).

- **The known failure, reproduced:** on the original Karambar SAR file, the original method gives
  **975.88 ha** (the documented 975.9 ha). The picture (`logs/2026-11-09_radar_leak_where.png`) shows
  why: Otsu over the whole window splits bright mountain faces from everything else (cut-off −9.5 dB),
  so the flat valley floor counts as water. A slope mask on its own did not fix it.
- **The mitigation:** drop pixels steeper than **10°** (from the Copernicus 30 m DEM, slope computed by
  our own code), **then** run Otsu over the remaining flat ground, where it separates lake (median −20.1 dB)
  from the rest of the flat ground (median −11.3 dB) at −15.3 dB (`logs/2026-11-09_radar_backscatter_levels.log`). On the original file the leak is gone: **267.52 ha**
  (`logs/2026-11-09_radar_slope_mask_original_karambar.log`). Unmasked, the leak still reaches the
  window edge and is refused (a test keeps this visible).
- **How 10° was chosen (honestly):** 5°, 10°, 15° and 20° were tried on the **one** original radar file
  (Karambar; there was no original Atro Sar radar file) and gave 258.7–281.6 ha; 10° was picked as the
  middle of that stable range. So it is **not independent of that file**. It was not fitted to optical
  (5° would have been closer to optical) and it was fixed before any comparison with optical.
- **The original SAR file's date is not recorded**, so its 267.52 ha cannot be compared with any
  dated optical value (e.g. 237.2 ha on 18 July): the lake varies about 237–257 ha across a summer.
- **Validation against optical, on scenes the 10° limit was not chosen on:** radar and optical of the
  same lake within 3 days (`logs/2026-11-09_radar_validation.log`,
  `logs/2026-11-09_radar_validation_independence.log`). 30 radar passes, but only **16 independent
  optical scenes** (Karambar 7, Atro Sar 9), from **2 lakes, summer only (June–September), 2023–2026**.
  One value per optical scene: Karambar radar **+5.2 %**, Atro Sar radar **−6.4 %**.
- **What this does and does not show:** a mitigation that worked on these two lakes in summer, **not a
  validated general fix**. The offsets are lake-specific and of opposite sign, so two lakes say nothing
  about a third.
- **Slope code checked against two references** (`scripts/check_slope_reference.py` →
  `logs/2026-11-09_slope_reference_check.log`): identical to `numpy.gradient` on both DEM windows (max
  difference 0.0000°); against Earth Engine's own `ee.Terrain.slope` (computed on the native 30 m DEM),
  97.8 % (Karambar) and 98.9 % (Atro Sar) of pixels fall on the same side of 10°. **But the area is
  sensitive to the slope source near the shore:** with Earth Engine's slope, Karambar summer areas change
  by under 0.4 %, Atro Sar summer areas by about −3 to −4 % (one summer pass becomes a refusal), and winter
  values by up to −14 %. Whether 10° is the *right* limit cannot be checked without a dated, surveyed
  shoreline, which this project does not have.
- **Open question:** why Karambar radar reads high and Atro Sar radar reads low is **unexplained**. A
  plausible cause is shoreline terrain (how the 30 m DEM and the 10° mask cut the shore) or water
  turbidity/surface roughness; **untested**.
- **Why radar is not risk-scored:** **29 of 363** usable radar values (8.0 %) are clearly wrong by a
  stated rule: more than 15 % away from that lake's median optical area (just beyond the largest summer
  radar–optical difference, +13.0 %; a judgement, not calibrated; 20 % gives 23, 25 % gives 15).
  `scripts/count_radar_errors.py` → `logs/2026-11-10_radar_error_count.log` (29 of 361 on 9 November,
  `logs/2026-11-09_radar_error_count.log`; the two passes since are within the rule). (An earlier count with
  hand-set summer ranges, Karambar 230–300 ha and Atro Sar 90–110 ha, gave 18 + 10 = 28:
  `logs/2026-11-09_radar_validation.log`. The two rules agree on 8 %.) **16 of the 29 are in
  April–June**, where wet snow during melt is as dark as water on radar, so the lake seems to vanish
  (Karambar 0.2 ha) or flood outward (403.9 ha). Those errors produced the largest radar "anomalies"
  (e.g. +50.3, −7.4). A melt-season check needs ground truth we do not have (optical is also blind in
  spring), so radar scoring stays off (`pipeline.SCORE_RADAR = False`); the 361 radar scores written by
  the first radar backfill were removed (`logs/2026-11-09_radar_scores_removed.log`; archived copy kept).
- **Winter radar values** (≈ 255–260 ha at Karambar in January–March) probably measure the frozen
  lake surface; they cannot be checked against optical and are **unvalidated**.

---

## Current contents of the database (`sailab_glof.db`)

⏳ As of 2026-11-11, after the backfill of the four new lakes (runs 10 and 11). Newest scene: 2026-11-10.
Scheduled run 12 then added 4 scenes for Karambar and Atro Sar (4,458 in total); the tables below are from before it.

| | KRB | ATS | SHP | DKT | BRT | PSU |
|---|---|---|---|---|---|---|
| Optical scenes | 307 | 304 | 594 | 305 | 306 | 306 |
| … too cloudy (recorded, not downloaded) | 178 | 179 | 385 | 165 | 165 | 150 |
| … usable / refused / no lake | 20 / 109 / 0 | 25 / 100 / 0 | 6 / 108 / **95** | 86 / 54 / 0 | 81 / 60 / 0 | 3 / 153 / 0 |
| … usable area range (ha) | 198.31–257.83 | 105.16–107.17 | 0.09–19.49 | 14.74–17.80 | 0.01–13.75 | 0.48–4.17 |
| Optical risk scores `ok` / `insufficient_history` | 8 / 12 | 11 / 14 | 0 / 6 | 45 / 41 | 25 / 56 | 0 / 3 |
| Radar passes | 221 | 221 | 881 | 339 | 335 | 335 |
| … usable / refused | 191 / 30 | 172 / 49 | 0 / 881 | 327 / 12 | 304 / 31 | 277 / 58 |
| First scene | 2023-01-05 | 2023-01-05 | 2019-01-01 | 2023-01-04 | 2023-01-05 | 2023-01-05 |

Optical dates for KRB and ATS run to 2026-11-05 (their newest optical scene), the others to 2026-11-10.
Borith and Passu optical values are shown but not trustworthy (see [The six lakes](#the-six-lakes)).

**Measurement counts, defined side by side** (both numbers are correct; they count different things):

| | Optical | Radar | Total |
|---|---|---|---|
| Scenes recorded (`scene` rows) | 2,122 | 2,332 | **4,454** |
| Too cloudy: recorded, not downloaded, **no measurement row** | 1,222 | 0 | 1,222 |
| **Measurement rows written** (`measurement` rows, every status) | 900 | 2,332 | **3,232** |
| of which refused (`insufficient_observation`) | 584 | 1,061 | 1,645 |
| of which **no lake found** (`no_lake_detected`, no area) | 95 | 0 | 95 |
| of which **usable** (`ok`, passed every check) | 221 | 1,271 | **1,492** |

So "3,232" is every measurement attempt stored, and "1,492" is the usable subset
(1,492 + 1,645 + 95 = 3,232). Only usable optical values are risk-scored (89 `ok`, 132
`insufficient_history`); radar is not scored. (With two lakes, on 10 November: 1,053 / 696 / 408.)

So **58 % of optical scenes (1,222 of 2,122) were too cloudy over the lake** for optical measurement —
the cloud problem the project's radar fallback is meant to solve, measured with our own data.

**`run_log` history:**

| Row | What | Result |
|---|---|---|
| 1 | First backfill attempt (by hand) | **Failed** at sign-in: `run_once.py` never signed in to Earth Engine. Bug fixed, test added. Kept as a real failure record. |
| 2 | First backfill (by hand), before checks C/D/F | Completed. Its rows were replaced (see below); the row is kept as history. |
| 3 | Backfill re-run (by hand) with checks C/D/F | Completed: 611 scenes, 254 downloads. **These are the rows in the database now.** |
| 4 | First GitHub Actions run (triggered by hand) | Completed: no new scenes since 2026-11-05. |
| 5 | Second GitHub Actions run (triggered by hand, after pinning the runner to Ubuntu 24.04) | Completed: no new scenes. |
| 6 | **First scheduled run** (GitHub's scheduler, 2026-11-08 21:31 UTC) | Completed: no new scenes. |
| 7 | Radar backfill (by hand, 2026-11-09) | Completed: 440 radar passes downloaded and measured. Its 361 radar risk scores were later removed (radar scoring off). |
| 8 | GitHub Actions run (triggered by hand, 2026-11-09 12:09 UTC) to check radar on GitHub | Completed: no new scenes. |
| 9 | **Second scheduled run** (GitHub's scheduler, 2026-11-10 01:02 UTC) | Completed: 2 new radar passes recorded, downloaded and measured (Karambar 257.55 ha, Atro Sar 97.14 ha); no new optical scene. |
| 10 | Backfill of the four new lakes (by hand, 2026-11-10 17:40 UTC) | **Failed** at Passu after Shishper, Darkut and Borith: Earth Engine returned HTTP 503 "memory capacity exceeded". 2,998 scenes recorded before it. Kept as a real failure record. |
| 11 | Same backfill, resumed (2026-11-10 20:04 UTC) | Completed: resumed after the last finished lake (Borith); Passu, 403 scenes. |
| 12 | **Third scheduled run** (GitHub's scheduler, 2026-11-10 22:42 UTC), first over six lakes | Completed in 11 s: 4 scenes recorded (2 too cloudy optical, 2 radar), Karambar 261.14 ha, Atro Sar 98.05 ha. |

The pre-C/D/F database and its 5-band images are archived locally (`data/archive_v1/`, not in this
repository); the comparison is in `logs/2026-11-08_cdf_before_after.md`.

**Downloaded images:** backfill images (about 1.9 GB, optical and radar, six lakes) are kept on the developer's machine, **not** in this
repository (`data/backfill/` is git-ignored). Each can be re-downloaded by its scene id and checked
against the SHA-256 in its backfill run log (`logs/runs/*_backfill.log`). Images downloaded by the
scheduled runs are committed to `data/scenes/`. **First used by run 9** (2026-11-10): two Sentinel-1 windows,
whose SHA-256 values match the run log (`logs/2026-11-10_scheduled_run_2_report.md`).

---

## Evidence that the pieces work on real data

| Claim | Evidence |
|---|---|
| Automated downloads match the project's original manual Earth Engine exports **pixel for pixel** (0 differing values: Karambar 1,280,175, Atro Sar 132,845; bands 1-5) | `logs/2026-11-08_item2_live_download_vs_original_final.log`, `logs/2026-11-08_cdf_live_6band_vs_original.log` |
| The original Karambar file still gives **237.22 ha** (reported as 237.2) with the unchanged code | `tests/test_pipeline.py::test_real_karambar_original_file_reproduces_237_2_ha` |
| The original Atro Sar file (76.51 ha) is **cut off** by its window | `tests/test_pipeline.py::test_real_atro_sar_original_file_is_flagged_as_cut_off_by_the_window` |
| Cloud measured over the lake differs from the tile value in many scenes (Atro Sar: 7 of 17 decisions differ) | `logs/2026-11-08_step4_live_find_new_scenes.log` |
| A failed run is recorded, not hidden | `run_log` row 1; `logs/runs/2026-11-08T103538Z_backfill.log` |
| The radar failure reproduces (975.88 ha), and with the slope mask the leak is gone (267.52 ha) on the same original file | `tests/test_radar.py`, `logs/2026-11-09_radar_slope_mask_original_karambar.log` |
| 29 of 363 usable radar values are clearly wrong (more than 15 % from the lake's optical median), 16 of them April–June | `scripts/count_radar_errors.py`, `logs/2026-11-10_radar_error_count.log` |
| Every stored measurement can be reproduced from its file: all 696 (two lakes, 10 Nov) and all 2,536 of the four new lakes recomputed by the scene-page code give the stored status and area | `scripts/check_scene_recompute.py`, `logs/2026-11-10_scene_page_recompute_check.log`, `logs/2026-11-11_scene_recompute_check_new_lakes.log` |
| Each new lake was tested on real scenes before it was added; Khurdopin and Ghulkin were left out because they have no lake to measure | `logs/2026-11-10_new_lake_candidates/README.md` |
| Shishper's stored record shows 2 of its 3 confirmed outbursts (2019, 2022), and every "no lake" scene shows no water on the image | `scripts/check_shishper_outbursts.py`, `logs/2026-11-11_shishper_outburst_check.log`, `logs/2026-11-11_shishper_timeline_truecolour.png` |
| Swapping NDWI for MNDWI does not fix the water test: it finds Passu (10 of 12 scenes) but over-measures Darkut (22 vs 15.4 ha) and lets Karambar leak (up to 394 ha) | `scripts/compare_water_index.py`, `logs/2026-11-11_ndwi_vs_mndwi.log` |
| The tests catch deliberate bugs in the new modules: 35 one-line mutations in `db.py`, `pipeline.py`, `radar.py`, `earth_engine_client.py`, **all caught**; 2 survived the first run (same-day value in the baseline; latitude limit) and tests were added for both | `scripts/mutation_check.py`, `logs/2026-11-09_mutation_check_new_modules_run1.log` (what survived), `..._run4_final.log` (35 of 35) |
| Every HTML page any test renders is checked for unbalanced tags; the original stray `</div>` now fails 17 tests (2 before), and a bug planted in the live page's failed state fails 3 | `tests/conftest.py`, `tests/html_check.py`, `logs/2026-11-09_html_balance_check_proof.log` |
| Our slope code equals `numpy.gradient`; 98–99 % of pixels agree with Earth Engine's slope on the 10° mask | `logs/2026-11-09_slope_reference_check.log` |
| Radar vs optical within 3 days: Karambar +5.2 %, Atro Sar −6.4 %, on 16 independent summer optical scenes from 2 lakes | `logs/2026-11-09_radar_validation.log`, `logs/2026-11-09_radar_validation_independence.log` |

**About the tests (265, all passing):** most use small synthetic grids with hand-calculated expected
answers — they prove the algorithms compute correctly, **not** real-world accuracy. Four use the
project's three original real GeoTIFFs in `tests/data/` (Karambar and Atro Sar Sentinel-2, Karambar SAR). The Earth Engine tests replace Earth Engine with a
mock (stated in the test file); the real connection is proven only by the live-run logs. The 20
tests inherited from the earlier project pass unchanged.

---

## Limitations

1. **No outburst has been detected as it happened.** Shishper's past outbursts are in its stored record
   (2 of 3 visible, looking back); the risk score was not designed for them and gave no score there
   (check F: too little same-month history). Nothing has been tested on a live event.
2. **Newly formed lakes cannot be scored** (check F needs earlier same-month years). These are often
   the dangerous ones: Shishper (formed 2018) has 6 usable values and no score.
3. **Cloud:** 58 % of optical scenes were too cloudy over the lake. Radar fills those dates with
   measurements, but radar is **not risk-scored**, so risk scores still come from clear optical days only.
4. **Blind in winter:** frozen or snow-covered lakes are refused (correctly), so there are few or no
   measurements from roughly November to May. Scheduled runs before spring may produce no `ok` area.
5. **Under-detection:** the NDWI cut-off of 0.2 misses real water on some days. Known and **not
   fixed**. Karambar 2025-08-12 (198.31 ha, score −2.96) is very likely this, not a real change.
6. **Strict checks lose good data:** 43 plausible measurements were rejected.
7. **Judgement-call settings:** the 10 % cloud limit was chosen from one month of data; the
   thresholds in checks C, D, F are reasoned choices, not calibrated values.
8. **Sentinel-2's classification can mistake snow for cloud** (seen in real scenes). This only makes
   the pipeline refuse a measurement, never invent one.
9. **The growth limit can cut a lake short without a warning** (seen with Atro Sar at 1200 m before
   the window change).
10. **Measurement accuracy is only roughly known:** Karambar measured about 10 % below its published
    area in the earlier project tests (from that project's own results; not re-checked in this repository).
11. **GitHub scheduling:** scheduled runs can start late or occasionally be skipped by GitHub.
12. **Radar:** a mitigation validated on only 2 lakes in summer (16 independent scenes), with
    unexplained lake-specific offsets (+5.2 %, −6.4 %); 29 of 363 usable radar values (8.0 %; 16 in
    April–June snowmelt, 10 in February–March) are clearly wrong; winter radar values are unvalidated; radar is not scored.
13. **The NDWI water test fails on silty or murky glacial water.** Passu: almost never seen (3 of 156, all
    wrong). Borith: often only part of the lake, giving false scores (−8.81, −7.94). Shishper: only part of
    its murky lake. **Borith and Passu optical values are still risk-scored** (not yet changed). Swapping the
    index for MNDWI did not fix it (`logs/2026-11-11_ndwi_vs_mndwi.log`).
14. **"No lake detected" uses judgement-call limits** (May–October, 150 m, 10 %), checked by eye on Shishper
    only; it is switched on only for the two lakes with clear water.
15. **Repository growth:** each nightly run commits its new images; with six lakes about 3 GB a year, so
    images must move out of git within the year.

---

## The web app (local, for demonstration)

`.venv/bin/uvicorn app:app`, then open http://127.0.0.1:8000. It needs no internet connection except for
the Live check button.

- **Dashboard** and **Lake Detail** (six lakes): every number is read from the database (a test checks that the
  reference designs' sample values never appear). `scripts/verify_gui_numbers.py` re-checks every number
  on both screens against independent SQL (77 of 77 with six lakes); the cold run-through result is in
  `logs/2026-11-08_gui_cold_runthrough_numbers.md`.
- **"No lake found":** when a lake's latest clear optical scene found no lake, its page shows a red banner
  (worded as a measurement result, not an alert), the chart marks each such scene with a red ×, the log
  shows "No lake found at the centre", and the dashboard says so under the lake. Screenshots:
  `docs/screenshots/2026-11-11/`.
- **Scene pages** (`/scenes/<id>`, the "View image" link on every observation-log row): the measurement is
  **recomputed from the stored file** when the page opens, with the pipeline's own unchanged functions,
  and shown next to what the run stored ("Same as stored" / "Differs from stored"). Optical: true colour,
  the **NDWI** map (water above 0.2) and the cloud/snow map that checks C and D use, with the NDWI at the
  lake centre and pixels × 10 m × 10 m = area. Radar: VV backscatter and the threshold map (ground steeper
  than 10° removed, pixels darker than that pass's Otsu threshold, the grown lake), with the threshold in dB.
  Too-cloudy scenes say "not downloaded"; a missing file says so. All 696 stored measurements recompute the
  same (`logs/2026-11-10_scene_page_recompute_check.log`). Screenshots: `docs/screenshots/2026-11-10/`.
- **Working copy:** at start-up the app copies `sailab_glof.db` to `.webapp/` and shows which commit it
  came from. It never writes to the published file, so it cannot collide with the nightly bot's commits.
- **Automatic reload:** after a `git pull` changes `sailab_glof.db`, the app notices within a minute and
  copies it again, but only if the file is unchanged on two checks in a row and passes SQLite's integrity
  check, and never while a live check is running. Open pages then refresh themselves (new numbers on screen
  about 1.5–2.5 minutes after the pull). A banner also offers **Load the newer data now** (`POST /reload`).
  Reloading discards this laptop's live-check results. `SAILAB_AUTO_RELOAD_SECONDS=0` turns it off.
  Real-server check: `logs/2026-11-10_gui_auto_reload_check.md`. To pull automatically, add to `crontab -e`:
  `0 * * * * cd ~/Documents/SAILAB_FYP1_FINAL && git pull --ff-only -q`
- **Live check:** one button runs the real pipeline for every lake (six now), writing to the working copy only.
  The timings below were measured with two lakes; with six it takes longer (not yet measured).
  Tested for real: no new scene (about 10 s), network cut (fails after about 20-35 s, 32 s and 23 s in two real tests, with a plain-language
  error), and a copy rewound to 2026-08-15 (42 scenes found, 12 measured; every row and every file
  identical to the backfill: `logs/2026-11-08_gui_live_check_new_scenes_vs_backfill.log`). On 2026-11-10 a
  live check found a **real new radar pass** 3 minutes after the nightly run had looked (Karambar 261.14 ha,
  Atro Sar 98.05 ha, 21 s): `logs/2026-11-10_gui_live_check_found_new_pass.md`.
- **Design previews** (Confirm advisory, Delivery status, Risk threshold): the design's own sample data,
  watermarked, every control disabled, no script. The only routes that change anything are `POST /live/check`
  and `POST /reload`, and both write only to `.webapp/` (a test checks the route list).
- The screens next to the reference designs, and why they differ: `docs/comparison/`.
- What to click and say in a demo: `docs/DEMO_SCRIPT.md`; if the live check fails: `docs/LIVE_CHECK_FALLBACK.md`.
- Odds of a usable optical scene in a November demo: none for Karambar or Atro Sar in any year on record
  (`logs/2026-11-09_live_demo_lake_odds.md`; not yet counted for the new lakes).
- `docs/DEMO_SCRIPT.md` and `docs/LIVE_CHECK_FALLBACK.md` still describe two lakes.

## Repository layout

```
sailab/
  measurement.py  acquisition.py  risk.py     earlier-tested core modules (unchanged)
  terrain.py  flood_path.py  network.py       downstream analysis modules (unchanged, not wired in)
  db.py                    SQLite schema, inserts, history, seed lakes
  earth_engine_client.py   Earth Engine sign-in, scene listing, lake-window cloud, download
  pipeline.py              the run: stages wired together, checks C/D/F, radar, resume, run log
  radar.py                 Sentinel-1 measurement: slope mask, Otsu over flat ground, region growing
  queries.py               read-only queries behind every number the web app shows
webapp/                    FastAPI + Jinja2 app: pages, offline SVG charts, live check, design previews
app.py                     web app entry point (uvicorn app:app)
scripts/
  run_once.py              entry point (GitHub Actions); --backfill [--lakes CODES] for historical runs
  init_db.py               create the database and seed the lakes
  verify_gui_numbers.py    check every number on the two real screens against the database
  validate_radar.py        compare radar with optical measured within 3 days
  count_radar_errors.py    count clearly wrong radar values with a stated rule
  mutation_check.py        break one line at a time in the new modules and check the tests fail
  check_slope_reference.py compare our slope code with two independent references
  check_scene_recompute.py re-measure every stored scene from its file and compare with the database
  check_shishper_outbursts.py  compare Shishper's stored record with its published outburst dates
  compare_water_index.py   NDWI vs MNDWI with the same region growing, on stored summer scenes
docs/                      reference designs, side-by-side comparison, demo script
tests/                     265 tests; tests/data/ holds the original real optical and SAR GeoTIFFs
data/dem/                  Copernicus DEM windows for the radar slope mask
logs/                      verification logs; logs/runs/ has one log per pipeline run
sailab_glof.db             the database (open with DB Browser for SQLite)
```

## Running it yourself

```bash
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests/ -q          # no credentials needed
```

A live run needs an Earth Engine service-account key, either in the `EE_SERVICE_ACCOUNT_KEY`
environment variable (the key's JSON text) or at `~/.config/sailab/ee-key.json`:

```bash
.venv/bin/python scripts/run_once.py
```

Never commit the key. The GitHub workflow reads it from the repository secret
`EE_SERVICE_ACCOUNT_KEY`.
