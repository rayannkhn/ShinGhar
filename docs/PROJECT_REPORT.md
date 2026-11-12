# SailAb GLOF — complete project report

*Status: 11 November 2026, about 21:00 UTC on 10 Nov (02:00 PKT). Repository: `rayannkhn/sailab-glof-live`, data as of commit `f5c2101` (six lakes, after backfill runs 10 and 11). First written 9 November; updated for scheduled run 2, the scene pages, automatic reload, and the four new lakes.*

This file explains everything built so far: what the system is, how each part works, every problem met on the way
and how it was solved, the web app screen by screen with every number on it explained, the tests and how far they
can be trusted, and what is still open. Every number here comes from the database (`sailab_glof.db`), a log file in
`logs/`, or a test run, and the source is named next to it. Times are UTC unless marked PKT (UTC+5).

---

## Contents

1. [The project in one page](#1-the-project-in-one-page)
2. [Where this build started from](#2-where-this-build-started-from)
3. [The system, piece by piece](#3-the-system-piece-by-piece)
4. [How one nightly run works, step by step](#4-how-one-nightly-run-works-step-by-step)
5. [The data in the database right now](#5-the-data-in-the-database-right-now)
6. [Timeline: what was done, in order](#6-timeline-what-was-done-in-order)
7. [Every problem we hit, and how it was solved](#7-every-problem-we-hit-and-how-it-was-solved)
8. [Radar (Sentinel-1) in detail](#8-radar-sentinel-1-in-detail); 8b. [The four new lakes, in detail](#8b-the-four-new-lakes-in-detail)
9. [The web app (GUI), screen by screen](#9-the-web-app-gui-screen-by-screen)
10. [Every number on the GUI, explained](#10-every-number-on-the-gui-explained)
11. [The tests: what they prove, and whether they are legit](#11-the-tests-what-they-prove-and-whether-they-are-legit)
12. [Independent checks beyond the tests](#12-independent-checks-beyond-the-tests)
13. [Automation on GitHub](#13-automation-on-github)
14. [Security and safety](#14-security-and-safety)
15. [Known limitations (honest list)](#15-known-limitations-honest-list)
16. [What is still open](#16-what-is-still-open)
17. [For the defence: likely questions and true answers](#17-for-the-defence-likely-questions-and-true-answers)
18. [Glossary](#18-glossary)
19. [Where to find everything](#19-where-to-find-everything)

---

## 1. The project in one page

**What it is.** SailAb GLOF is designed as a five-stage early-warning system for glacial lake outburst floods
(GLOFs) in northern Pakistan:

> **Acquisition → Measurement → Risk Scoring →** Downstream Analysis → Alerting

**This build covers the first three stages**, for **six lakes** (two from the start, four added on 10 November), running **automatically every night** on real
satellite data. Downstream Analysis (flood path, roads, bridges) and Alerting were **out of scope by agreement**.

| | |
|---|---|
| Lakes | **Karambar (KRB)**, **Atro Sar (ATS)**, and from 10 Nov **Shishper (SHP)**, **Darkut (DKT)**, **Borith (BRT)**, **Passu (PSU)**, Gilgit-Baltistan |
| Satellites | **Sentinel-2** (optical, cloud-blocked) and **Sentinel-1** (radar, sees through cloud) |
| Data source | ESA Copernicus data through **Google Earth Engine**, signed in with a service account (no person needed) |
| Runs | **GitHub Actions**, every night at **23:00 PKT (18:00 UTC)**, commits its results back to the repository |
| Stores | One SQLite database, `sailab_glof.db` (5 tables) |
| Shows | A local web app (FastAPI + Jinja2): Dashboard, Lake Detail, a page per scene (NDWI / radar threshold views), Live check, three inert design previews; reloads itself after a `git pull` |
| Code | **4,298 lines** of new code (new `sailab/` modules, `webapp/` Python, templates and CSS, `scripts/`, `app.py`; tests not counted), **265 tests**, all passing |
| History | **4,454 scenes** from 1 Jan 2019 (Shishper; the others from 2023) to 10 Nov 2026 (2,122 optical, 2,332 radar) |

**What it is not.** It is a working, automated **monitoring prototype**. It sends **no alerts**, it has **never
detected an outburst as it happened** (Shishper's past outbursts are in its stored record, and 2 of 3 are visible
looking back, section 8b), and its risk score is a **statistical deviation**, not a danger level or a probability.

**The rules this build followed** (from the build brief): never claim something works without logs or evidence; never
show placeholder data as real; reuse the earlier, already-tested modules unchanged; hand-write the algorithms; ask
before architectural decisions; show failures honestly.

---

## 2. Where this build started from

Before this build, the project (FYP-1 proof package) had **6 small hand-written modules (about 310 lines)**, tested
against 8 test cases from the project's Test Plan, with 6 deliberate mutations to check the tests were not hollow, and
one real-image check (a flood scene in Spain from the Sen1Floods11 dataset, not a glacial lake). Earlier real results:
**Karambar 237.2 ha** (Sentinel-2, 18 July 2026), **Atro Sar 76.51 ha**, and a radar attempt for Karambar that gave a
wrong **975.9 ha**.

Those 6 modules were reused **byte-for-byte unchanged** in this build:

| Module | What it does | Key functions |
|---|---|---|
| `sailab/measurement.py` | Water detection and lake area | `ndwi`, `classify_water_ndwi`, `otsu_threshold`, `region_grow`, `extent_area_m2` |
| `sailab/acquisition.py` | Sensor choice, resumable downloads | `choose_sensor`, `ResumableRun` |
| `sailab/risk.py` | Seasonal-baseline score | `score_against_seasonal_baseline` |
| `sailab/terrain.py`, `flood_path.py`, `network.py` | Downstream analysis | flood path tracing, bridge finding (**not wired in**: out of scope) |

The 20 tests that came with them still pass unchanged (`logs/2026-11-07_step1_pytest_baseline.log`: 20 passed).

---

## 3. The system, piece by piece

```
 Google Earth Engine (Sentinel-2, Sentinel-1, Copernicus DEM)
          │  service-account sign-in, list scenes, measure cloud over the lake, download a small window
          ▼
 sailab/earth_engine_client.py ──► sailab/pipeline.py ──► sailab/db.py ──► sailab_glof.db
                                     │   uses (unchanged): measurement.py, acquisition.py, risk.py
                                     │   uses (new): radar.py (slope mask + Otsu over flat ground)
                                     ▼
                          logs/runs/<time>.log  (every step, every file's SHA-256)

 GitHub Actions (.github/workflows/daily_run.yml): tests → scripts/run_once.py → commit DB + logs

 webapp/ (FastAPI) ── reads a COPY of sailab_glof.db, read-only ──► Dashboard, Lake Detail, scene pages, Live check, previews
                     └─ re-copies it by itself when sailab_glof.db changes (after a git pull)
```

### 3.1 New code written in this build

| File | Lines | Purpose |
|---|---|---|
| `sailab/db.py` | 345 | SQLite schema (5 tables), inserts with validation, history queries, the six seed lakes with a guard that refuses silently changing a stored lake; adds new lake columns to an older file in place |
| `sailab/earth_engine_client.py` | 431 | Sign-in; list Sentinel-2 and Sentinel-1 scenes; count cloud over the lake from Sentinel-2's own SCL band; download the lake window; download the DEM; check every downloaded file (projection, pixel size, band count) |
| `sailab/pipeline.py` | 496 | The run: for each lake, list new scenes, decide (too cloudy / download), measure, apply checks C, D, F, "no lake detected", score, log; per-lake history start; resume after a crash; radar path; run log |
| `sailab/radar.py` | 110 | Radar measurement: slope from the DEM (hand-written), drop steep pixels, Otsu over flat ground, region growing from the lake centre |
| `sailab/queries.py` | 135 | Read-only queries behind every number the web app shows |
| `webapp/main.py` | 382 | The web app: routes, working copy of the DB, provenance, live check, previews, scene pages, reload and automatic reload |
| `webapp/pages.py` | 157 | Builds the data for each page, including one scene's record |
| `webapp/scene_view.py` | 187 | One scene re-measured from its file with the pipeline's own functions, and its pictures: true colour, NDWI, cloud/snow; VV backscatter, threshold map |
| `webapp/charts.py` | 212 | Charts drawn as SVG on the server (no internet, no chart library) |
| `webapp/images.py` | 73 | True-colour and radar images with the measured outline, recomputed from the stored file |
| `webapp/live.py` | 133 | The Live check button: one real pipeline run, plain-language error messages |
| `webapp/templates/*.html`, `static/style.css` | 819 | Page layouts and styling, matched to the 18 reference designs |
| `scripts/` | 814 | `run_once.py` (nightly entry point; `--backfill --lakes`), `init_db.py`, `verify_gui_numbers.py`, `validate_radar.py`, `count_radar_errors.py`, `mutation_check.py`, `check_slope_reference.py`, `check_scene_recompute.py`, `check_shishper_outbursts.py`, `compare_water_index.py` |

### 3.2 The database (`sailab_glof.db`)

| Table | One row per | Main columns |
|---|---|---|
| `lake` | monitored lake | code, name, centre lon/lat, window radius, growth limit |
| `scene` | satellite pass over a lake | source (sentinel-2 / sentinel-1), acquired_at, cloud over the lake, file path (or `not_downloaded/…`) |
| `measurement` | measurement attempt on a downloaded scene | sensor (optical/radar), status (`ok` or `insufficient_observation`), extent_ha |
| `risk_score` | scored usable optical measurement | status (`ok` / `insufficient_history`), baseline_ha, deviation_score |
| `run_log` | pipeline run | started, finished, lakes processed, scenes downloaded, the real error text if it failed |

A refused measurement is stored as `insufficient_observation` with **no number**, never as a zero.

### 3.3 The six lakes (fixed values)

| Code | Lake | Centre (lon, lat) | Window radius | Growth limit | History from | "No lake" check |
|---|---|---|---|---|---|---|
| KRB | Karambar Lake | 73.7053229, 36.880833 | 2500 m | 2500 m | 2023 | no |
| ATS | Atro Sar | 73.65037, 36.64458 | 1500 m (was 800 m, see problem P3) | 1500 m | 2023 | no |
| SHP | Shishper glacier lake | 74.5650, 36.3590 | 1500 m | 1500 m | **2019** | yes |
| DKT | Darkut glacial lake | 73.40701, 36.64219 (published position) | 1000 m | 1000 m | 2023 | yes |
| BRT | Borith Lake | 74.86214, 36.43053 | 1000 m | 1000 m | 2023 | no |
| PSU | Passu glacier lake | 74.87979, 36.45744 | 1000 m | 1000 m | 2023 | no |

Why these four, and how each was tested before it was added: section 8b.

---

## 4. How one nightly run works, step by step

1. **GitHub starts the job** at 18:00 UTC (it can be late) on a fresh Ubuntu 24.04 machine with Python 3.13.
2. **Install** the exact pinned package versions (`requirements.txt`).
3. **Run the full test suite.** If any test fails, the pipeline does **not** run, so broken code can never write data.
4. **Sign in** to Earth Engine with the service-account key from an encrypted GitHub secret.
5. **For each lake, optical (Sentinel-2):**
   1. List scenes newer than the newest stored one (starting one day earlier, so a late-arriving scene is not missed;
      duplicates are skipped by scene id).
   2. For each scene, fetch only its SCL (scene-classification) band over the lake window and **count cloud and cloud
      shadow inside the lake circle ourselves** (classes 3, 8, 9, 10).
   3. **More than 10 % cloud over the lake → recorded, not downloaded** (file path `not_downloaded/…`).
   4. Otherwise **download the lake window** (bands B2, B3, B4, B8, B11 + SCL, 10 m, UTM zone 43N) and check the file.
   5. **Measure:** NDWI = (green − NIR) / (green + NIR) per pixel; water if NDWI > 0.2; grow the water region outward
      from the lake centre (4-connected, within the growth limit); area = pixels × 100 m².
   6. **Refuse** (`insufficient_observation`) if: the centre pixel is not water (frozen lake); the lake touches missing
      data at the window edge; **check D** cloud or shadow touches the lake; **check C** snow/ice touches the lake or
      covers more than half the lake circle.
   7. **Score** a usable value against the same lake's earlier optical values from the **same calendar month**, strictly
      before this date: score = (area − mean) ÷ standard deviation. **Check F:** no score unless there are at least 5
      earlier values from at least 2 different years (`insufficient_history` instead).
6. **For each lake, radar (Sentinel-1):** list new passes, download VV+VH, measure with the slope mask (section 8),
   store as a `radar` measurement. **Radar is not risk-scored.**
7. **Write the run log** (database row + text file with every decision and every file's SHA-256).
8. **Commit** the database and logs back to the repository, **also after a failed run**, so failures stay visible.

---

## 5. The data in the database right now

*(as of commit `f5c2101`; last pipeline run: run 11, the resumed backfill of the new lakes, 10 Nov 20:21 UTC)*

### 5.1 Scenes and measurements

| | KRB | ATS | SHP | DKT | BRT | PSU | Total |
|---|---|---|---|---|---|---|---|
| Optical scenes | 307 | 304 | 594 | 305 | 306 | 306 | 2,122 |
| … too cloudy (recorded, not downloaded) | 178 | 179 | 385 | 165 | 165 | 150 | 1,222 (58 %) |
| … usable (`ok`) | 20 | 25 | 6 | 86 | 81 | 3 | 221 |
| … refused (`insufficient_observation`) | 109 | 100 | 108 | 54 | 60 | 153 | 584 |
| … no lake found (`no_lake_detected`) | 0 | 0 | 95 | 0 | 0 | 0 | 95 |
| Optical usable area range (ha) | 198.31–257.83 | 105.16–107.17 | 0.09–19.49 | 14.74–17.80 | 0.01–13.75 | 0.48–4.17 | |
| Radar passes | 221 | 221 | 881 | 339 | 335 | 335 | 2,332 |
| … usable / refused | 191 / 30 | 172 / 49 | 0 / 881 | 327 / 12 | 304 / 31 | 277 / 58 | 1,271 / 1,061 |
| Optical risk scores `ok` / `insufficient_history` | 8 / 12 | 11 / 14 | 0 / 6 | 45 / 41 | 25 / 56 | 0 / 3 | 89 / 132 |
| First scene | 2023-01-05 | 2023-01-05 | 2019-01-01 | 2023-01-04 | 2023-01-05 | 2023-01-05 | |

Borith's and Passu's optical values are shown but **not trustworthy** (section 8b); they are still risk-scored.

### 5.2 The two measurement counts people mix up

| | Optical | Radar | Total |
|---|---|---|---|
| Scenes recorded | 2,122 | 2,332 | **4,454** |
| Too cloudy: no measurement row at all | 1,222 | 0 | 1,222 |
| **Measurement rows written** (every attempt) | 900 | 2,332 | **3,232** |
| of which refused | 584 | 1,061 | 1,645 |
| of which no lake found (no area) | 95 | 0 | 95 |
| of which **usable** | 221 | 1,271 | **1,492** |

So **3,232** is every measurement attempt stored and **1,492** is the usable subset (1,492 + 1,645 + 95 = 3,232).
Neither is a scene count. (Two lakes, before run 9 on 9 Nov: 1,051 / 694 / 406; after run 9: 1,053 / 696 / 408.)

### 5.3 The run log

| Row | When (UTC) | What | Result |
|---|---|---|---|
| 1 | 8 Nov 10:35 | First backfill attempt (by hand) | **Failed**: the script never signed in to Earth Engine. Kept as a real failure record |
| 2 | 8 Nov 10:36 | First backfill (before checks C/D/F) | Completed, 254 downloads; its rows were later replaced |
| 3 | 8 Nov 11:23 | Backfill re-run with checks C/D/F | Completed: 611 scenes, 254 downloads. **These are the optical rows in the DB now** |
| 4 | 8 Nov 12:01 | First GitHub Actions run (started by hand) | Completed, no new scene |
| 5 | 8 Nov 19:01 | GitHub run after pinning Ubuntu 24.04 (by hand) | Completed, no new scene |
| 6 | 8 Nov 21:32 | **First scheduled run** (GitHub's scheduler) | Completed, no new scene; 171 tests passed in 6.13 s |
| 7 | 9 Nov 06:50 | Radar backfill (by hand) | Completed: 440 radar passes downloaded and measured |
| 8 | 9 Nov 12:09 | GitHub run (by hand) to check radar on GitHub | Completed, no new scene |
| 9 | 10 Nov 01:02 | **Second scheduled run** (the 9 Nov 18:00 slot, started about 7 h late by GitHub) | Completed; 216 tests passed in 8.51 s; **2 new radar passes** (9 Nov 13:05): Karambar 257.55 ha, Atro Sar 97.14 ha; first images committed to `data/scenes/` (`logs/2026-11-10_scheduled_run_2_report.md`) |
| 10 | 10 Nov 17:40 | Backfill of the four new lakes (by hand) | **Failed** at Passu, after Shishper, Darkut and Borith: Earth Engine HTTP 503 "memory capacity exceeded" (2,998 scenes recorded before it). Kept as a real failure record |
| 11 | 10 Nov 20:04 | Same backfill, resumed | Completed: resumed after the last finished lake; Passu, 403 scenes |
| 12 | 10 Nov 22:42 | **Third scheduled run**, first over six lakes (10 Nov 18:00 slot, about 4.7 h late) | Completed in 11 s; 265 tests passed; Karambar 261.14 ha and Atro Sar 98.05 ha from the 10 Nov 01:05 radar pass, identical to the live check of the same pass (same SHA-256); 2 too-cloudy optical scenes (`logs/2026-11-11_scheduled_run_3_report.md`) |

---

## 6. Timeline: what was done, in order

**7 November (evening)**
- Moved the original files into `sailab/` and `tests/`; 20 inherited tests pass.
- Set up the Google Cloud project and the Earth Engine service account; key stored at `~/.config/sailab/ee-key.json`
  (permissions 600, never committed).
- First live Earth Engine call: 17 Karambar scenes found for Sep-Nov 2026 (`logs/2026-11-08_step3_first_live_ee_call.log`).
- Proved our automated download is **identical, pixel for pixel**, to the project's original manual exports
  (0 differing values out of 1,280,175 for Karambar and 132,845 for Atro Sar).
- Reproduced the original results with the unchanged code: Karambar **237.22 ha** (reported 237.2), Atro Sar 76.51 ha.

**8 November**
- Measured cloud over the lake instead of over the whole 100 km tile (7 of 17 decisions differ at Atro Sar).
- Found Atro Sar was cut off by its 800 m window; changed to 1500 m: **105.82 ha** (problem P3).
- Two smoke tests on August 2026; set the optical cloud limit to 10 % (problem P6).
- Full historical backfill (2023-01-01 → 2026-11-05); found snow, cloud and frozen-lake errors; added checks C, D, F;
  re-ran the backfill (problem P5).
- Wrote the README; published the repository; set up GitHub Actions with the key as a secret.
- Fixed GitHub's deprecation warnings (Ubuntu and Node versions) and concurrent-commit safety.
- Built the web app (data layer and API; Dashboard and Lake Detail; three design previews; Live check; design
  comparison, demo script). Tested the Live check for real three ways.
- **21:31: the first scheduled run** (GitHub's scheduler).

**9 November**
- Added Sentinel-1 radar: reproduced the 975.9 ha failure, found the cause, fixed it on that file with a slope mask
  plus Otsu over flat ground (267.52 ha), validated against near-same-day optical, backfilled 440 passes.
- Found that wet snow in spring makes radar look like water; **turned radar scoring off** and deleted the 361 radar
  scores (archived copy kept).
- An external reviewer challenged several claims; each challenge was answered with evidence, and several claims were
  corrected (radar validation wording, GUI layout bug, chart scale, missing evidence files, 28 vs 29).
- Defence preparation: mutation testing of the new modules (35 of 35 caught after 2 test fixes), systematic HTML
  checks, an independent slope check, a full claims sweep, a live-check fallback plan, and lake odds for the demo.

**10 November**
- **01:02: the second scheduled run** (run 9): new Sentinel-1 pass for both lakes, measured and committed with its images.
- A live check from the GUI found **another real pass** (10 Nov 01:05 UTC), 3 minutes after the bot had looked: Karambar
  261.14 ha, Atro Sar 98.05 ha (`logs/2026-11-10_gui_live_check_found_new_pass.md`).
- Built **scene pages** (each pass re-measured from its file and drawn: NDWI for optical, threshold map for radar);
  checked all 696 stored measurements reproduce exactly.
- Built the newer-data banner and **automatic reload** after a `git pull` (problem P12 solved).
- **Four lakes added** with the project owner (section 8b). Searched the literature and Earth Engine's surface-water
  map for lakes with recorded outbursts; tested six candidates with the pipeline's own download and measurement on
  real scenes; left out Khurdopin and Ghulkin (no lake to measure); added Shishper, Darkut, Borith, Passu.
- Added the **"no lake detected"** status for clear-water lakes, and a per-lake history start (Shishper from 2019).
- Backfilled the four lakes (runs 10 and 11, about 2 h 40 min; run 10 failed on an Earth Engine 503 and run 11
  resumed). Re-checked all 2,536 new measurements against their files (0 differ).
- Checked Shishper against its published outburst dates: 2 of 3 visible. Tested MNDWI against NDWI (no single
  index fixes every lake). Pushed as commit `f5c2101` before the nightly run.

---

## 7. Every problem we hit, and how it was solved

Each entry: **what happened → why → what we did → evidence.**

### Pipeline and data

**P1. The service account could not download.** With the *Viewer* role, Earth Engine refused to create download URLs.
→ The role only allows reading metadata. → The project owner gave the account *Earth Engine Resource Editor* (plus
*Service Usage Consumer*). → Downloads work (step 3 and item 2 logs).

**P2. The "missing data" rule refused everything.** Earth Engine exports have a border of zero pixels around the
window. → Refusing any scene with zeros refused good scenes. → Now a scene is refused only if **the lake region itself
touches** missing data (meaning the lake might be cut off). → `tests/test_pipeline.py`.

**P3. Atro Sar's earlier 76.51 ha was wrong.** The 800 m export window cut the lake off at its edge. → Measured the
same 18 July scene at several window sizes: 105.82 ha at 1500, 2000 and 2500 m alike. → Window and growth limit
changed to 1500 m, logged with the before/after values and proof that no stored data was affected.
**The report, slides and proof package outside this repository still need 76.51 → 105.82 ha.**
→ `logs/2026-11-08_step5_atro_sar_radius_check.log`, `logs/2026-11-08_atro_sar_window_change.log`, and a test that
flags the original file as cut off.

**P4. The first backfill failed at sign-in** (run_log row 1). → `run_once.py` never signed in. → Sign-in moved inside
the pipeline's error handling, with a test. The failed row was **kept**, on purpose, as a real failure record.

**P5. The first backfill accepted impossible values.** A snowfield counted as lake (**462.88 ha** for a ~250 ha lake),
a frozen lake measured as **0.14 ha**, cloud hiding part of a lake (**87.42 ha** instead of ~106), and scores like
**−49.6** from only 2-3 earlier values. → Three checks added: **C** (snow/ice), **D** (cloud touching the lake), **F**
(enough history). → Before vs after: Karambar usable range 167.82–462.88 → **198.31–257.83 ha**, Atro Sar 0.14–110.55
→ **105.16–107.17 ha**; largest score 49.57 → **2.96**. **Cost:** 43 plausible values were also rejected (12 + 31),
often for a few noisy edge pixels. We chose fewer measurements over wrong ones.
→ `logs/2026-11-08_cdf_before_after.md`, `logs/2026-11-08_backfill_outliers_true_colour_vs_detected.png`.

**P6. Scenes with some cloud under-measured the lakes.** In the August 2026 smoke test, scenes with 28.8 % and 34.7 %
lake cloud gave too-small areas. → The optical cloud limit was set to **10 %** (a judgement from one month of data, not
calibrated). → `logs/2026-11-08_step5_smoke_test_aug2026_10pct.log`.

**P7. Tile cloud ≠ lake cloud.** Sentinel-2's cloud percentage is for the whole 100 km tile. → We count cloud inside the
lake circle ourselves from the SCL band. At Atro Sar, 7 of 17 decisions differ.
→ `logs/2026-11-08_step4_live_find_new_scenes.log`.

**P8. An empty date range crashed Earth Engine.** When the period was already fully covered, Earth Engine rejected the
query ("Empty date ranges not supported"). → Return "nothing new" without asking. → Mutation E6 checks this.

### GitHub automation

**P9. GitHub deprecation warnings** (Ubuntu image and Node 20 actions). → Pinned `ubuntu-24.04`, moved to
`actions/checkout@v5` and `actions/setup-python@v6`. No OS reinstall needed on the laptop.

**P10. Two bot commits could collide.** → The commit step runs `git pull --rebase` before pushing, and a concurrency
group stops two runs at once.

**P11. Claude was listed as a co-author/collaborator.** → Removed at the project owner's request; commits carry only
the owner's name.

### Web app

**P12. "The GUI shows an old last run."** The app copies the database **when it starts**, so it did not see later
nightly runs until restarted. → First: working as designed (it never touches the published file). Then (10 Nov, the
owner asked for it to be automatic): the app now notices when `sailab_glof.db` changes after a `git pull` and copies it
again by itself, only once the file is unchanged on two checks and passes SQLite's integrity check, never during a live
check; open pages refresh themselves. The pull itself is an hourly cron job on the laptop, outside the app. →
`logs/2026-11-10_gui_auto_reload_check.md`.

**P13. "Internal server error" after an update.** New templates were loaded but the old Python code was still running.
→ Restart the server after code changes.

**P14. The observation log fell outside the page layout** (a stray `</div>` in `lake.html`). Found on the screenshots
made for the reviewer. → Fixed; then made the check **systematic**: every HTML page any test renders is now checked
for unbalanced tags. The original bug now fails 17 tests (2 before); a bug planted in the live page's failed state
fails 3. → `tests/conftest.py`, `logs/2026-11-09_html_balance_check_proof.log`.

**P15. The Karambar chart's scale ran from −60 to 464 ha** because a few radar errors (0.2 ha, 404 ha) set it,
flattening the real ~257 ha line. → The scale now follows the optical values (plus radar values within 25 % of the
optical median); far-off radar values are **not hidden**: they are hollow triangles at the edge, real value on hover,
counted on the chart (6 at Karambar, 3 at Atro Sar). Now 180–337 ha.

**P16. "406" could be read as a scene count** next to "1,051 scenes". → The tile now says "406 of 694 measurement
attempts passed every check … Not a scene count" (408 of 696 after run 9).

**P16b. "Why are the 9 and 10 Nov radar values different?"** (257.55 vs 261.14 ha at Karambar). Two passes 12 h apart,
from opposite orbit directions, each with its own Otsu threshold. A 1.4 % change is below the median 1.6 % difference
between earlier opposite-direction passes less than 24 h apart: measurement noise, not a lake change.

**P16c. "Can I see the image and NDWI for each pass?"** → Scene pages (section 9.4), with the measurement recomputed
from the file and compared with what was stored.

### Radar

**P17. Radar measured 975.9 ha for a ~250 ha lake.** → Explained and fixed on that file (section 8): 267.52 ha.

### New lakes (10-11 November)

**P19. "Add renowned lakes with past outbursts" — but which, and where exactly?** Pakistan's official list of 33
hazardous lakes could not be found by name. → Lakes were picked from published events and studies, located on
Earth Engine's JRC surface-water map and on Sentinel-2, and **tested with the pipeline's own download and
measurement** before being added (`logs/2026-11-10_new_lake_candidates/README.md`). Darkut uses its published position.

**P20. Two of the requested lakes have nothing to measure.** Khurdopin's surge-dammed lake drained (dry river
plain in 2019 and 2025); Ghulkin's "lakes" are ponds on the moving glacier surface. → Left out, with the owner's
agreement; the evidence is kept.

**P21. NDWI does not see silty glacial water.** Passu: 0 of 4 test scenes, then 3 of 156 in the backfill, all wrong
(0.48–4.17 ha against about 19 ha). Borith: often only part of the lake. → Radar measures both; NDWI left
unchanged (an original module). Tried MNDWI (shortwave infrared): finds Passu but over-measures Darkut and leaks at
Karambar (`logs/2026-11-11_ndwi_vs_mndwi.log`). **Not solved;** Borith and Passu optical values are still
risk-scored, which gave false scores such as −8.81 and −7.94 at Borith.

**P22. An outburst looked like a bad image.** When Shishper drained, every scene said "centre not water", the same as
a frozen or cloudy day. → New status `no_lake_detected` with no area, only for clear-water lakes, May–October, with
no cloud, snow/ice or missing data within 150 m of the centre and under 10 % water there. Tested on synthetic files
(winter, snow, cloud, shadow and a data gap all stay refusals) and checked by eye on Shishper's real scenes.

**P23. Earth Engine refused a download mid-backfill** ("memory capacity exceeded", HTTP 503) at the sixth lake. →
The run recorded the failure (run 10); the existing resume logic restarted after the last finished lake (run 11).

**P24. Radar never measures Shishper** (0 of 881 passes: narrow, steep, debris-covered valley). → Documented;
Shishper is an optical-only lake.

**P18. Wet snow in spring looks like water on radar.** 29 of 361 usable radar values (now 29 of 363) are clearly wrong, 16 of them in
April-June; they produced the largest false anomalies (+50.3, −7.4). → Radar scoring turned off; the 361 radar scores
deleted (archived copy kept). → `logs/2026-11-09_radar_scores_removed.log`, `logs/2026-11-09_radar_error_count.log`.

### Honesty corrections (claims that were overstated and then fixed)

| Claim as first made | Correction | Evidence |
|---|---|---|
| Radar validated on "30 pairs", "a fix" | **16 independent optical scenes** from 2 lakes, summer only; a **mitigation**, not a general fix; lake offsets unexplained | `logs/2026-11-09_radar_validation_independence.log` |
| GUI "finished" | It had a layout bug and an outcome with no saved evidence; both fixed | `logs/2026-11-09_gui_live_check_outcomes_evidence.md` |
| "28 of 361 radar values wrong, no evidence file" | The 28 did have a source (hand-set ranges); a stated, reproducible rule gives **29**; both are now documented | `logs/2026-11-09_radar_error_count.log`, `logs/2026-11-09_radar_validation.log` |
| "Mostly April-June" | 16 of 29 in April-June, 10 in February-March | same |
| Comparison doc: "Radar is not built" | Rewritten for the current screens | `docs/comparison/README.md` |
| "Valley floor ≈ −15 dB" | The flat ground's median is −11.3 dB; −15.3 dB is the cut-off (found while checking this report) | `logs/2026-11-09_radar_backscatter_levels.log` |
| Network-cut failure "about 33 s" | Varies: 32 s and 23 s in two real tests, now "20-35 s" | evidence file above |
| Shishper check, first version: "3 of 3 outbursts seen" | The script let a usable value from up to a year earlier count as "before"; for 2020 it used July 2019. With both sides limited to 45 days: **2 of 3** | `logs/2026-11-11_shishper_outburst_check.log` (header notes the fix) |
| This report: "about 3,900 lines" of code (9 Nov) | Not reproducible: counting the same files at commit `6e94e09` gives **3,437**; now 3,958 after the scene pages and reload, counted the same way | `wc -l` over the files listed in section 3.1 |

---

## 8. Radar (Sentinel-1) in detail

**Why radar.** 58 % of optical scenes are too cloudy over the lake. Radar sees through cloud: Sentinel-1 passes both
lakes about every 6 days (221 passes each, 2023 → 9 Nov 2026).

**How radar measures water.** Calm water reflects the radar beam away, so it looks **dark** (low backscatter, in dB).
The classic method: find a threshold that splits dark from bright (**Otsu's method**), then grow the dark region from
the lake centre.

**Why the old method gave 975.9 ha.** Otsu over the whole window split **bright mountain faces** from everything else
(cut-off −9.5 dB, shown in `logs/2026-11-09_radar_leak_where.png`), so the flat **valley floor** counted as water and the region leaked down the valley.

**The fix (a mitigation).**
1. Compute slope from the Copernicus 30 m DEM (hand-written code, central differences).
2. **Drop pixels steeper than 10°** *before* thresholding.
3. Run Otsu **over the remaining flat ground only**, where it separates the lake (median −20.1 dB) from the rest of
   the flat ground (median −11.3 dB), at a cut-off of −15.3 dB (`logs/2026-11-09_radar_backscatter_levels.log`).
4. Grow the region from the lake centre; refuse if it reaches missing data.
On the original file: **267.52 ha**, no leak. (A slope mask *alone*, with Otsu over the whole window, did not fix it.)

**How 10° was chosen.** 5°, 10°, 15°, 20° gave 258.65, 267.52, 275.39, 281.62 ha on the one original file; 10° is the
middle of that stable range. It was **not** fitted to optical and was fixed before any comparison.

**Validation against optical** (radar within 3 days of a clear optical scene): **16 independent optical scenes**
(Karambar 7, Atro Sar 9), June-September 2023-2026. Karambar radar reads **+5.2 %**, Atro Sar **−6.4 %**. Opposite
signs, unexplained.

**Independent slope check (new today).** Our slope code is **identical to numpy's** gradient (max difference
0.0000°). Against Google Earth Engine's own slope algorithm, **97.8 % / 98.9 %** of pixels fall on the same side of
10°. **But the area is sensitive to the slope source near the shore:** with Earth Engine's slope, Karambar summer areas
change by under 0.4 %, Atro Sar summer areas by about −3 to −4 % (one summer pass becomes a refusal), winter values by
up to −14 %. Whether 10° is the *right* limit cannot be checked without a dated, surveyed shoreline.

**Why radar is not scored.** 29 of 363 usable radar values (8 %; `logs/2026-11-10_radar_error_count.log`) are more than 15 % away from the lake's optical
median; 16 are in April-June (wet snow during melt is as dark as water). Winter radar values (Karambar ~255-260 ha in
January-March) probably measure the frozen surface and are unvalidated. Scoring stays off until a melt-season check
exists, which needs ground truth we do not have.

**Status of radar data.** On 9 Nov, Earth Engine had no Sentinel-1 pass newer than 28 Oct 2026
(`logs/2026-11-09_radar_s1_coverage_check.log`). **The gap is closed:** run 9 recorded the 9 Nov 13:05 pass, and a live
check found the 10 Nov 01:05 pass (opposite orbit direction).

**Radar on the four new lakes** (not validated against optical like Karambar and Atro Sar): Darkut 327 of 339 passes
usable (about 14.7 ha against 16.1 ha optical; outliers only in winter and spring); Borith 304 of 335 (about 11–12 ha,
steadier than its optical); Passu 277 of 335 (about 11 ha; the only usable measure of this silty lake);
Shishper 0 of 881.

## 8b. The four new lakes, in detail

**How they were chosen.** The project owner asked for well-known lakes with past outbursts, 6–7 in total, "with rich
data and very sure results". Candidates: Shishper, Khurdopin, Passu, Ghulkin, plus two of our choice from the
dangerous ones. Each was located from published sources and the JRC surface-water map, then tested on real
Sentinel-2 (and later Sentinel-1) scenes with the pipeline's own code. Evidence: `logs/2026-11-10_new_lake_candidates/`.

| Lake | Why | Test result | Decision |
|---|---|---|---|
| Shishper (Hassanabad) | Ice-dammed lake beside a surging glacier; outbursts 22–23 Jun 2019, 29 May 2020, 7 May 2022 (KKH bridge) | Lake measured in 2019 and Apr 2022; gone since; radar never | **Added**, history from 2019, "no lake" check on |
| Darkut (Yasin) | Grew 4.5 → 15.4 ha; risk to Darkut village (Amin et al. 2020) | 6 of 6 optical, 6 of 6 radar, 15.3–16.7 ha | **Added**, "no lake" check on |
| Borith (Hunza) | Named a possible GLOF source (Iqbal et al. 2023) | Radar 6 of 6 (10.7–11.3 ha); optical 2 of 4 | **Added** |
| Passu (Hunza) | Past outbursts (Jan 2008); May 2022 release | Optical 0 of 4 (silty); radar 3 of 6 | **Added** (radar only) |
| Khurdopin (Shimshal) | 2017 outburst; 20-year surge cycle | No lake at the site in 2019 or 2025 | Left out |
| Ghulkin | 2008–2009 outbursts | Only ponds on the glacier surface | Left out |

**Shishper's outbursts in the stored record** (`scripts/check_shishper_outbursts.py`, 45 days either side):

| Outburst | Before | After | Verdict |
|---|---|---|---|
| 22–23 Jun 2019 | 11.77 ha, 31 May | 0.09 ha, 5 Jul; no lake from 4 Aug | **Seen** |
| 29 May 2020 | the lake was there (10.48 ha, 25 May) but **refused by check D** (cloud touching it) | no usable or no-lake scene within 45 days | **Not seen** |
| 18 May 2021 (one thesis only; uncertain) | no usable value | no lake, 9 Jun | cannot tell |
| 7 May 2022 | 17.05 ha 10 Apr; 5.83 ha 30 Apr | no lake, 14 Jun | **Seen** |

Every "no lake" scene was checked on the image (`logs/2026-11-11_shishper_timeline_truecolour.png`): none shows
water at the lake site. Note what this is: the record **shows** the outbursts looking back. The system did not
detect them as they happened, and the risk score gave nothing (check F: too little same-month history).
A further check is possible against Lovell & Muhammad (2024), who date six fill-and-drain phases.

**Methods: what the panel's criticism means here.** At the FYP-1 mid review the panel said the methods are old.
For water detection that is confirmed by our own data: a fixed NDWI cut-off (from 1996) fails on silty or murky
glacial water, and swapping it for another fixed index (MNDWI) helps one lake and hurts three. The newer approaches
listed in the team's paper review are a Sentinel-1 + Sentinel-2 random-forest classifier (Wangchuk & Bolch 2020) and
improved, terrain-corrected radar thresholds (Markert et al. 2020; Khan et al. 2025). Neither is built yet.

---

## 9. The web app (GUI), screen by screen

**Start it:** `.venv/bin/uvicorn app:app`, open <http://127.0.0.1:8000>. It runs only on this laptop
(127.0.0.1), needs **no internet** except for the Live check button, and has **no sign-in** (agreed: no real accounts
exist, so a login would only look like security).

**How it gets its data.** At start-up it **copies** `sailab_glof.db` into `.webapp/` and reads only that copy,
read-only. The header chip shows **which git commit** the data came from and when it was copied. The Live check and the
reload are the only things that write, and only to `.webapp/`. So the app can never collide with the nightly bot.

**How fresh data arrives.** The bot commits to GitHub; a `git pull` (by hand, or an hourly cron job:
`0 * * * * cd ~/Documents/SAILAB_FYP1_FINAL && git pull --ff-only -q`) updates `sailab_glof.db` on the laptop. The app
checks the file every 60 s; when it has changed and is unchanged on the next check and passes SQLite's integrity check,
it copies it again (never during a live check), and every open page refreshes itself within 30 s. Meanwhile a blue
banner says **"Newer data available"** with a **Load the newer data now** button. A reload discards this laptop's
live-check results. `SAILAB_AUTO_RELOAD_SECONDS=0` turns automatic reload off (e.g. on the morning of the defence).

**Design.** The layout follows the **18 reference designs** the project owner provided (`docs/design_reference/`):
colours measured from the images, top bar, yellow banner, left navigation, KPI row, map + lake list, cards, tables.
Where the real data differs, the screen follows the data, not the design (table in `docs/comparison/README.md`): e.g.
no "Critical 0.86" risk tiers (the trained model is not built), no basemap (needs internet), lakes not ranked by risk
(deviation is not danger).

### 9.1 Every page has
- **Top bar:** logo, "SailAb GLOF", and the **Data chip** ("Data: commit 69378dc, copied …", plus "+ N live checks on
  this laptop" if any).
- **Yellow banner:** "Prototype. Monitoring and measurement only: Downstream Analysis and Alerting are not built, so
  this system sends no alerts."
- **Left navigation:** Dashboard, Live check, the six lakes, and the three design previews (marked "preview").

### 9.2 Dashboard (`/`)
- **"Last pipeline run"** at the top right (from the newest `run_log` row, in PKT).
- **Warning banner** if no lake has a usable measurement (optical or radar) in the last 7 days.
- **Error banner** if the latest run recorded an error.
- **Five KPI tiles** (explained in section 10).
- **Monitored lakes map:** the real lake centres on a plain latitude/longitude grid. Solid marker = usable measurement
  in the last 7 days; dashed = data gap.
- **Lakes list:** each lake's latest usable optical and radar area and age, its optical score chip, a "Radar not
  scored" chip, and two small lines of its last usable extents (optical above, radar below).
- **Pipeline runs table:** every `run_log` row: start, finish, lakes, downloads, result (Completed / Error with the
  real error text). Run 1's failure is visible.

### 9.3 Lake Detail (`/lakes/KRB`, `/lakes/ATS`)
- **Header card:** score chips; latest usable optical area and date; latest usable radar area and date; scenes recorded
  with the breakdown; settings (centre, window, growth limit).
- **Lake extent chart:** blue dots = optical usable values, green triangles = radar usable values (never joined to
  each other); points more than 45 days apart are not joined ("a gap is a gap, not a trend"); grey dashes = seasonal
  baseline where a score exists; hollow triangles at the edge = radar values far off the scale; **two tick strips**
  underneath showing **every scene** (optical: blue measured, ochre refused, grey too cloudy; radar: green measured,
  ochre refused), so every gap is explained by real scenes. Range buttons: 12 months, 24 months, All.
- **"How the latest score was made":** the scene, measured area, how many earlier same-month values from how many
  years, the baseline and the score, with the formula in words; and why radar is not scored.
- **Latest usable optical image:** the real Sentinel-2 true-colour window with the lake outline **recomputed from the
  stored file by the same code**; its pixel count equals the stored area (checked by a script).
- **Latest usable radar image:** the VV backscatter with its outline, same idea.
- **Three dashed panels:** Dam and glacier, Terrain above the lake, Recent weather: "No data: not part of this build".
- **Observation log:** every scene, newest first, 25 per page: date, sensor, cloud over the lake, extent, quality
  (Usable / Refused by quality checks / Refused by radar checks / Not downloaded: cloud over lake), risk, and a
  **View image** link (**Details** for too-cloudy scenes) to that scene's page.

### 9.4 Scene page (`/scenes/<id>`)
One satellite pass. Newer / older links step through the lake's log.
- **Stored by the run:** pass time (UTC and PKT), cloud over the lake (optical), the stored result and area, when it
  was measured, the risk score (or "not scored (radar)"), the file.
- **Recomputed now from the stored file:** when the page opens, the pipeline's **own unchanged function**
  (`sailab.pipeline.measure_scene` for optical, `sailab.radar.measure_radar_scene` for radar) runs on the file. The
  page shows its result and reason, and **"Same as stored"** or **"Differs from stored"**; the lake region as pixels ×
  10 m × 10 m = area (also for a refused scene, so you can see what was grown before it was refused).
  - Optical: the NDWI formula, NDWI at the lake centre and the median inside the lake, water pixels in the whole window
    (only those connected to the centre count), cloud and snow pixels in the window.
  - Radar: pixels removed as steeper than 10°, **that pass's Otsu threshold in dB**, the median backscatter of the lake,
    of the other flat ground and of the whole window.
- **Pictures, with the grown lake outlined in yellow:**
  - Optical: **true colour**; **NDWI** (blue above 0.2 = water, darker = higher; brown/pale below); **cloud and snow**
    (pink cloud/shadow, cyan snow/ice: what checks C and D look at).
  - Radar: **VV backscatter** (dark = calm water); **threshold map** (brown = removed as steep, blue = flat ground darker
    than the threshold, pale = brighter; yellow dots inside the lake are brighter pixels that are not counted).
- **Too cloudy:** "Not downloaded: X % of the lake was under cloud", no picture. **File missing:** says so, nothing drawn.
  **Recomputation error:** shown as it is, nothing in its place.
- **Check:** all **696** stored measurements recompute to the stored status and area, 0 differ, 0 errors
  (`scripts/check_scene_recompute.py`, `logs/2026-11-10_scene_page_recompute_check.log`, 608 s). Example: Atro Sar
  21 Oct 2026 was refused because snow touches the lake, which the cloud-and-snow picture shows.

### 9.5 Live check (`/live`)
One button, **"Check both lakes now"** (the label predates the new lakes), runs the **real pipeline** for every lake against Earth Engine, writing only to
the laptop's copy. The page refreshes every 3 s while it runs, then shows one of:
- **Blue: "No new scene for either lake"** (about 10-20 s; tested for real: 11 s on 9 Nov).
- **Blue/ochre: "N new scenes recorded"**, with the pipeline's own log (tested on a copy rewound to 15 Aug: 42 scenes
  found, 12 measured, every row and every file identical to the nightly pipeline's).
- **Red: "The check could not complete"** with a plain-language reason (no internet, usage limit, key refused, other)
  and the exact error underneath (tested for real with the network cut: 32 s and 23 s).
- **Real result on 10 Nov 07:49 UTC (21 s):** a new Sentinel-1 pass, Karambar 261.14 ha, Atro Sar 98.05 ha; a second
  check 5 minutes later correctly found nothing new (9 s) (`logs/2026-11-10_gui_live_check_found_new_pass.md`).
Fallback plan for the defence: `docs/LIVE_CHECK_FALLBACK.md`.

### 9.6 Design previews (`/preview/…`)
Confirm advisory, Delivery status, Risk threshold: the designs for the stages **not built**, with the design's own
sample data, a "Design preview" watermark, **every control disabled**, and no script. A test checks the app has only two
routes that change anything (`POST /live/check`, `POST /reload`), both writing only to `.webapp/`.

### 9.7 The read-only API (`/api/…`)
`/api/provenance` (also shows the automatic reload's last check and result), `/api/lakes`, `/api/lakes/{code}`, `/api/lakes/{code}/history`, `/api/run-log`,
`/api/run-log/latest`, `/api/totals`: the same numbers as JSON.

---

## 10. Every number on the GUI, explained

*(values on the current data; `scripts/verify_gui_numbers.py` re-computes each with its own SQL and finds it on the
rendered page: **30 of 30 checks passed**)*

### Dashboard tiles

| Tile | Shows | What it means | Computed from |
|---|---|---|---|
| Lakes monitored | **6** | Karambar, Atro Sar, Shishper, Darkut, Borith, Passu | `lake` rows |
| Scenes recorded | **4454** | 2,122 optical + 2,332 radar passes, 1 Jan 2019 to 10 Nov 2026 | `scene` rows |
| Too cloudy for optical | **58 %** | 1,222 of 2,122 optical scenes had over 10 % cloud on the lake, so were not downloaded | `scene.file_path` starting `not_downloaded/` |
| Usable measurements | **1492** | 1,492 of 3,232 measurement attempts passed every check (optical 221 of 900, radar 1,271 of 2,332). Not a scene count | `measurement` rows by status |
| Days since a usable measurement | **0** (on 10 Nov) | The freshest usable value of any lake and sensor: Darkut radar, 10 Nov 2026 | newest `ok` measurement |

The dashboard's lake list also shows, in red, a lake whose latest clear optical scene found **no lake** (Shishper:
28 Oct 2026). The warning banner names the lakes with no usable measurement in 7 days (on 10 Nov: Shishper only).

### Lake list and Lake Detail header

| Number | Karambar | Atro Sar | Meaning |
|---|---|---|---|
| Latest usable optical area | **257.02 ha**, 6 Sep 2026 | **105.90 ha**, 27 Aug 2026 | Newest optical value that passed every check |
| Latest usable radar area | **257.55 ha**, 9 Nov 2026 | **97.14 ha**, 9 Nov 2026 | Newest radar value (not scored) |
| Optical score chip | **Optical insufficient history** | **Optical deviation −0.96** | See below |
| Scenes recorded | **528** (optical 307: 20 usable, 109 refused, 178 too cloudy; radar 221: 191 usable, 30 refused) | **525** (optical 304: 25 / 100 / 179; radar 221: 172 / 49) | Per lake |
| Settings | window 2500 m, growth limit 2500 m | window 1500 m, growth limit 1500 m | From the `lake` row |

**The four new lakes** (on 10 Nov):

| Number | Shishper | Darkut | Borith | Passu |
|---|---|---|---|---|
| Latest usable optical area | 5.83 ha, 30 Apr 2022 | 16.45 ha, 21 Sep 2026 | 4.26 ha, 31 Oct 2026 (**partial**) | 4.17 ha, 17 Sep 2023 (**wrong**: silty water) |
| Optical score chip | insufficient history | **deviation +1.08** | deviation −7.94 (**false**: from the partial area) | insufficient history |
| Latest radar area | none usable | 14.34 ha, 10 Nov 2026 | 12.66 ha, 10 Nov 2026 | 12.03 ha, 10 Nov 2026 |
| Special | red banner: "No lake found in the latest clear optical scene (28 Oct 2026)" | | | |

### The scores

- **Atro Sar −0.96:** the 27 Aug 2026 area (105.90 ha) against **11 earlier August optical values from 4 years**
  (mean **106.35 ha**). −0.96 means about one standard deviation **below** the usual August size, which is ordinary
  variation (one standard deviation is about 0.47 ha). It is **not** a danger level.
- **Karambar "insufficient history":** its latest usable optical value (6 Sep 2026, 257.02 ha) has only **3 earlier
  September values from 3 years**; check F needs 5 from 2 years, so no score is given rather than a meaningless one.
- **Darkut +1.08:** the 21 Sep 2026 area (16.45 ha), about one standard deviation above its earlier September values.
- **Borith −7.94 is not real:** NDWI saw only 4.26 ha (31 Oct) of a lake radar measures at about 11 ha in summer (12.66 ha on 10 Nov). See P21.
- **All scores so far:** 89 `ok`, 132 `insufficient_history` (Karambar and Atro Sar alone: 19 / 26). Largest |score|: Karambar **−2.96** (12 Aug 2025,
  198.31 ha; very likely NDWI under-detection, not a real change), Atro Sar **1.74**.

### Why the numbers can look "odd"

- **Optical and radar differ** (Karambar 257.02 vs 257.55 ha; Atro Sar 105.90 vs 97.14 ha): the two sensors measure the lake
  slightly differently (summer offsets +5.2 % and −6.4 %), so they are never averaged or joined on the chart.
- **Many rows show no score:** too-cloudy scenes are not measured, refused scenes have no area, radar is not scored,
  and most months lack 5 earlier values.
- **Two radar values a day apart differ by 1-2 %** (Karambar 257.55 ha on 9 Nov, 261.14 ha on 10 Nov in a live check):
  opposite orbit directions and a new threshold per pass; the usual difference is 1.6 % (problem P16b).
- **"Data gap" for Karambar and Atro Sar in November:** from October to December, in every year on record, neither has a
  single usable optical value: clear scenes are refused because the lake is frozen or snow-covered
  (`logs/2026-11-09_live_demo_lake_odds.md`). The last usable optical value of each year is in late August or
  September.

---

## 11. The tests: what they prove, and whether they are legit

### 11.1 The numbers

**265 tests, all passing** (`.venv/bin/python -m pytest tests -q`, about 18 s).

| Test file | Tests | Covers |
|---|---|---|
| `test_measurement.py`, `test_acquisition.py`, `test_risk.py`, `test_terrain.py`, `test_flood_path.py`, `test_network.py` | 20 | The inherited modules (unchanged) |
| `test_db.py` | 28 | Schema, validation, history queries, seed guard, coordinate limits, the no-lake status, new lake columns added to an old file |
| `test_earth_engine_client.py` | 34 | UTM grid, lake-cloud counting, date ranges, file checks, sign-in errors (Earth Engine **mocked**) |
| `test_pipeline.py` | 45 | The run end to end on synthetic files; checks C, D, F; "no lake" and its safeguards; per-lake history start; resume; duplicates; failures recorded; 2 real files |
| `test_radar.py`, `test_pipeline_radar.py` | 18 | Slope, mask, Otsu-over-flat, refusals, radar not scored; 2 tests on the real original SAR file |
| `test_webapp_api.py`, `_pages.py`, `_live.py`, `_previews.py` | 92 | Every page and number, live-check outcomes, previews inert, offline, HTML structure |
| `test_webapp_scenes.py` | 28 | "No lake found" banner, chart marker, chip and recomputation; scene pages (recomputed area agrees, a planted mismatch shows "Differs", too cloudy, missing file, radar threshold), reload, automatic reload (waits one check, never copies a changing or broken file, waits for a live check, the watcher thread works) |

On GitHub, the first scheduled run passed **171 tests in 6.13 s** and the second **216 in 8.51 s** (the suite was
smaller then; `logs/2026-11-08_scheduled_run_6_github_test_step.log`, `logs/2026-11-10_scheduled_run_2_report.md`).

### 11.2 What the tests do prove

- **The algorithms compute what they should.** Most tests use small synthetic grids with expected answers worked out
  by hand (e.g. a 5×5 water block must measure 0.25 ha; a plane rising 1 m per 10 m must have slope 5.71°).
- **The rules are enforced:** a frozen centre is refused; cloud touching the lake is refused; a score needs 5 values
  from 2 years; a same-day value is not in the baseline; radar is never scored; a refused measurement can never carry
  a number; a failed run is recorded with its real error.
- **The GUI shows only real data:** a test checks the reference designs' sample values never appear on real pages;
  every page loads nothing from the internet; the only changing routes are `POST /live/check` and `POST /reload`.
- **The scene page cannot hide a disagreement:** a test stores 250 ha for a file that holds a 0.25 ha lake and checks
  the page says "Differs from stored".
- **Real files:** 4 tests use the project's 3 original real GeoTIFFs: Karambar reproduces **237.22 ha**; the original
  Atro Sar file is flagged as cut off; the original SAR file still shows the 975.9 ha leak without the mask and gives
  267.52 ha with it.

### 11.3 Are the tests hollow? Mutation testing

A test suite that always passes proves nothing. So, like the original 6 modules, each new module was **deliberately
broken one line at a time** and the suite re-run (`scripts/mutation_check.py`, 35 mutations in `db.py`,
`pipeline.py`, `radar.py`, `earth_engine_client.py`; examples: invert the slope mask, let same-day values into the
baseline, swap the UTM hemisphere, stop downloading the SCL band, switch radar scoring back on).

- **First run: 2 survived** (the suite still passed with the bug in):
  - **P1:** a value from the **same day** allowed into the baseline (`<` changed to `<=`). Real case: Karambar has two
    scenes on 26 Oct 2025. → New test `test_a_value_from_the_same_day_is_not_part_of_the_baseline`.
  - **D7:** the latitude limit widened from ±90° to ±180°. → New test `test_out_of_range_coordinates_are_refused`.
- **Final run: 35 of 35 caught.** All four logs are kept, including two runs that stopped early because two of the
  mutation texts matched twice (the script now validates every mutation before running any).
  → `logs/2026-11-09_mutation_check_new_modules_run1.log` (survivors), `…_run4_final.log` (35 of 35).

### 11.4 What the tests do NOT prove (so the claims stay honest)

- **Real-world accuracy.** Synthetic tests prove the code is correct, not that the lake area is right. The only
  accuracy evidence is the comparisons in section 12, and the earlier project's note that Karambar measured about 10 %
  below its published area (from that project, not re-checked here).
- **The live Earth Engine connection.** Earth Engine is replaced by a mock in the tests (stated in the test file);
  the real connection is proven only by the run logs and the nightly runs.
- **That a GLOF would be detected.** No real outburst has happened on either lake; the score has never been tested on a
  real event.
- **That the thresholds are right.** 10 % cloud, 0.2 NDWI, 10° slope, checks C/D/F limits are reasoned choices,
  documented as such, not calibrated values.

**Verdict: the tests are legitimate for what they claim** (the code does what it is written to do, the safety rules
hold, the GUI shows only real data, and deliberately planted bugs are caught). They are **not** evidence of measurement
accuracy or of flood detection, and this report never uses them that way.

---

## 12. Independent checks beyond the tests

| Check | Result | Evidence |
|---|---|---|
| Our download vs the original manual Earth Engine export | **0 differing pixels** (1,280,175 Karambar; 132,845 Atro Sar) | `logs/2026-11-08_item2_live_download_vs_original_final.log` |
| Original results reproduced with unchanged code | Karambar 237.22 ha (reported 237.2); Atro Sar 76.51 ha (and shown to be cut off) | `logs/2026-11-08_item2_reproduce_original_results.log` |
| Atro Sar whole lake | 105.82 ha at 1500, 2000 and 2500 m windows | `logs/2026-11-08_step5_atro_sar_radius_check.log` |
| Checks C/D/F before vs after | Impossible values removed (KRB 6 of 9, ATS 10 of 10); 43 plausible values lost | `logs/2026-11-08_cdf_before_after.md` |
| Live check vs the nightly pipeline | 42 scenes, 12 measured, every row and all 12 file checksums identical | `logs/2026-11-08_gui_live_check_new_scenes_vs_backfill.log` |
| Every GUI number vs independent SQL | 30 of 30 (two lakes); **77 of 77** with six lakes | `scripts/verify_gui_numbers.py` |
| Image outline vs stored area | Recomputed pixel count equals the stored area exactly (e.g. Atro Sar 10,590 px = 105.90 ha) | same script |
| Every stored measurement vs its file | All 696 (two lakes) and all **2,536 of the new lakes** recompute to the stored status and area (0 differ, 0 errors) | `logs/2026-11-10_scene_page_recompute_check.log`, `logs/2026-11-11_scene_recompute_check_new_lakes.log` |
| New lakes before they were added | 6 candidates tested on real scenes; 4 added, 2 left out | `logs/2026-11-10_new_lake_candidates/README.md` |
| Shishper record vs published outbursts | 2 of 3 visible; every "no lake" scene shows no water on the image | `logs/2026-11-11_shishper_outburst_check.log` |
| NDWI vs MNDWI | MNDWI finds Passu (10 of 12) but over-measures Darkut and leaks at Karambar | `logs/2026-11-11_ndwi_vs_mndwi.log` |
| Automatic reload on a real server | Changed file seen, copied on the next check (18 s), open page refreshed itself to the new count | `logs/2026-11-10_gui_auto_reload_check.md` |
| Radar vs optical, within 3 days | Karambar +5.2 %, Atro Sar −6.4 % (16 independent scenes, summer) | `logs/2026-11-09_radar_validation*.log` |
| Slope code vs numpy and Earth Engine | Identical to numpy; 97.8 % / 98.9 % same 10° decision as Earth Engine; area sensitive near the shore | `logs/2026-11-09_slope_reference_check.log` |
| Clearly wrong radar values | 29 of 363 (15 % rule; 29 of 361 on 9 Nov); 28 with the earlier hand-set ranges | `logs/2026-11-10_radar_error_count.log` |
| Every claim in the docs | Two sweeps; the second found and fixed 6 problems | `logs/2026-11-09_claims_sweep_2.md` |
| Radar backscatter levels quoted in the docs | Lake −20.1 dB, flat ground −11.3 dB, cut-off −15.3 dB (corrected: the docs had said the valley floor was ≈ −15 dB) | `logs/2026-11-09_radar_backscatter_levels.log` |

---

## 13. Automation on GitHub

- **Workflow:** `.github/workflows/daily_run.yml`, cron `0 18 * * *` (23:00 PKT), plus a manual "Run workflow" button.
  Ubuntu 24.04, Python 3.13, `contents: write` permission, one run at a time.
- **Steps:** checkout → Python → install pinned packages → **tests first** → pipeline → commit DB + logs (always, also
  after a failure) with `git pull --rebase` before pushing.
- **Runs so far (GitHub's record):** 5 runs, all successful: 3 started by hand (8 Nov 12:00 and 19:01, 9 Nov 12:08)
  and **2 started by the scheduler**: 8 Nov 21:31 (3.5 h after the 18:00 slot) and 10 Nov 01:01 (the 9 Nov slot,
  about 7 h late). GitHub can start late or skip.
- **The requirement is 3 scheduled runs on 3 different days.** 2 done; the next slot is 10 Nov 18:00 UTC (at recent
  delays, it may start after midnight UTC). Manual runs do not count. The README's run table is updated only from
  GitHub's own run list.
- **Committing a downloaded scene to `data/scenes/`** was first exercised by run 9: two Sentinel-1 windows, SHA-256
  matching the run log.
- **Limits:** public repository, so minutes are free; each run takes about 1 minute (limit 6 h). Schedules in public
  repositories are switched off after 60 days without repository activity. Every committed image adds to the
  repository: about 1 GB a year with two lakes, about 3 GB with six, so images must move out of git within the year.
- **Tonight (10–11 Nov) is the first scheduled run over six lakes.** It continues each lake from its newest stored
  scene; its duration with six lakes is not yet known.

---

## 14. Security and safety

- **The Earth Engine key** is never in the repository: locally at `~/.config/sailab/ee-key.json` (permissions 600),
  on GitHub as an encrypted secret. The saved GitHub log excerpt contains only the test step.
- **The web app** binds to 127.0.0.1 (this laptop only), reads a copy of the database read-only, has exactly two
  routes that change anything (`POST /live/check` and `POST /reload`, both writing only to `.webapp/`), loads nothing
  from the internet (its only script asks this same app for `/api/provenance`), and the design previews cannot act.
  It never runs `git` itself to pull; the pull is the owner's own cron job.
- **No fake data:** design sample values are confined to the three watermarked previews, and a test checks they never
  appear on real pages. Missing images say so ("not on this machine"), never show a placeholder.
- **Commits** carry only the project owner's name.

---

## 15. Known limitations (honest list)

1. No outburst has been detected as it happened; Shishper's past outbursts are visible in its record (2 of 3) only
   looking back, and the risk score gave nothing there.
2. Newly formed lakes cannot be scored (check F needs earlier years); these are often the dangerous ones (Shishper:
   6 usable values, no score).
3. 58 % of optical scenes are too cloudy; radar fills dates but is not scored.
4. Blind in winter: frozen or snow-covered lakes are refused (correctly); no usable optical value from October to
   December in any year.
5. NDWI 0.2 under-detects water on some days (e.g. Karambar 12 Aug 2025, 198.31 ha, score −2.96). Known, not fixed.
6. Strict checks lose good data: 43 plausible values rejected.
7. Judgement-call settings (10 % cloud, check limits, 10° slope), documented, not calibrated.
8. Sentinel-2's classification can mistake snow for cloud (only causes refusals, never invented values).
9. The growth limit can cut a lake short without a warning.
10. Measurement accuracy is only roughly known.
11. GitHub can start scheduled runs late or skip them.
12. Radar: a mitigation on 2 lakes in summer; unexplained offsets; 8 % clearly wrong values; winter unvalidated;
    sensitive to the slope source near the shore; not scored; never works at Shishper.
13. NDWI fails on silty or murky glacial water (Passu, Borith, Shishper); Borith and Passu optical values are still
    risk-scored, with false scores (−8.81, −7.94). MNDWI is not a fix.
14. "No lake detected" uses judgement-call limits (May–October, 150 m, 10 %), checked by eye on Shishper only.
15. Repository growth: about 3 GB of images a year with six lakes.

---

## 16. What is still open

| Item | Status |
|---|---|
| Scheduled run 3 | **Done** (run 12, 10 Nov 22:42 UTC, success, six lakes). Three daily slots covered; by UTC start time two runs began on 10 Nov |
| Borith and Passu optical scoring | Decision for the project owner: switch it off (like radar) until a better water method is tested |
| A modern water method | Sentinel-1 + Sentinel-2 random-forest classifier, built next to NDWI and compared on all six lakes; improved radar thresholds |
| Shishper vs Lovell & Muhammad (2024) | Compare the stored record with their six dated fill-and-drain phases |
| Demo script and live-check fallback | `docs/DEMO_SCRIPT.md`, `docs/LIVE_CHECK_FALLBACK.md` still describe two lakes; live-check time with six lakes not yet measured |
| The 10 Nov 01:05 radar pass | **Recorded** by run 12 with exactly the live check's values |
| Hourly `git pull` cron job | Added by the owner on 10 Nov (`crontab -l` shows it); the app's automatic reload is built |
| Repository size | Images committed nightly (about 3 GB a year with six lakes): move them out of git within the year |
| Report, slides and proof package outside the repo | Change Atro Sar **76.51 → 105.82 ha**; use the corrected radar wording (16 independent scenes, mitigation, not a general fix) |
| Why the radar offsets differ by lake | Open question; shoreline slope is one plausible contributor (untested as an explanation) |
| Whether 10° is the right slope limit | Cannot be checked without a dated, surveyed shoreline |
| "Karambar ~10 % below published area" | From the earlier project; not re-checked here |
| Downstream Analysis, Alerting, trained risk model | Not built (out of scope) |

---

## 17. For the defence: likely questions and true answers

- **"Has it ever caught a GLOF?"** Not as it happened. But Shishper, which burst in 2019, 2020 and 2022, is now
  monitored with history from 2019, and its stored record shows 2 of those 3: the lake area, then "no lake found".
  2020 was missed because cloud touched the lake on the one clear day before it.
- **"Why these six lakes?"** Each has a recorded outburst or a published outburst risk, and each was tested on real
  scenes before it was added. Two requested lakes were left out because there is no lake there to measure now.
- **"Your methods are old."** Agreed for water detection, and we measured it: the fixed NDWI cut-off fails on silty
  glacial water (Passu), and swapping to MNDWI does not fix it. The next step is a Sentinel-1 + Sentinel-2
  random-forest classifier, as in the newer literature.
- **"Can I see what the satellite saw?"** Yes: every row of the observation log opens that pass, re-measured from its
  file, with true colour, NDWI and cloud/snow (optical) or backscatter and the threshold map (radar), and whether it
  matches what was stored (all 696 do).
- **"Does it run by itself?"** Yes, every night on GitHub with no person involved; the run history is GitHub's own,
  timestamped record. (Say the number of scheduled runs counted from the Actions tab the evening before.)
- **"Why so few scores?"** A score needs 5 earlier values from 2 years for that month; winter months rarely have any.
- **"What about cloud?"** 58 % of optical scenes are too cloudy. Radar measures through cloud but is not scored
  because of spring snowmelt errors.
- **"Is the radar problem solved?"** For these two lakes in summer the leak is gone; not validated for other lakes or
  seasons.
- **"Are the tests real?"** 35 deliberate bugs in the new code were all caught; the first time 2 slipped through and
  tests were added for both.
- **"Is the slope mask verified?"** The code matches numpy exactly and agrees with Earth Engine on 98-99 % of pixels,
  but the area is sensitive to slope near the shore, and 10° itself cannot be verified without a surveyed shoreline.
- **"Why did Atro Sar change from 76.51 to 105.82 ha?"** The old window cut the lake off; we found and corrected it.
- **"What if the live check fails?"** See `docs/LIVE_CHECK_FALLBACK.md`: it says so plainly, records the failure, and
  the logged real run is shown instead. In November the expected honest result is "no new scene" or "refused: frozen".

The full demo script is `docs/DEMO_SCRIPT.md`.

---

## 18. Glossary

| Term | Meaning |
|---|---|
| GLOF | Glacial lake outburst flood: sudden release of water from a glacier-dammed or moraine-dammed lake |
| Sentinel-2 | ESA optical satellites (visible and infrared light); blocked by cloud |
| Sentinel-1 | ESA radar satellites; see through cloud and at night |
| Scene / pass | One satellite image over a lake |
| SCL | Sentinel-2's scene classification band (cloud, shadow, snow, water…), used to count cloud over the lake |
| NDWI | Normalised Difference Water Index, (green − NIR)/(green + NIR); water is high |
| VV backscatter | The radar signal returned (dB); calm water is dark |
| Otsu's method | Picks the threshold that best splits pixel values into two groups |
| Region growing | Starts at the lake centre and adds connected water pixels |
| DEM | Digital elevation model (Copernicus 30 m), used for slope |
| Check C / D / F | Snow-ice refusal / cloud-touching-lake refusal / enough-history rule for scoring |
| Seasonal baseline | Mean of the lake's earlier usable values in the same calendar month |
| Deviation score | (area − baseline) ÷ standard deviation; how unusual, not how dangerous |
| `insufficient_observation` | The scene could not be measured reliably; no number stored |
| `insufficient_history` | Too few earlier values to score |
| Backfill | The one-off historical run (2023 → Nov 2026), started by hand, using the same pipeline code |
| Mutation testing | Deliberately breaking code to check the tests notice |
| Working copy | The web app's private copy of the database |

---

## 19. Where to find everything

| What | Where |
|---|---|
| Overview and status | `README.md` |
| This report | `docs/PROJECT_REPORT.md` |
| Demo script / live-check fallback | `docs/DEMO_SCRIPT.md`, `docs/LIVE_CHECK_FALLBACK.md` |
| Reference designs / comparison | `docs/design_reference/`, `docs/comparison/` |
| Current screenshots | `docs/screenshots/2026-11-09/` (Dashboard, Lake Detail, live check); `docs/screenshots/2026-11-10/` (scene pages, log links, newer-data banner) |
| Evidence logs | `logs/` (dated); one log per pipeline run in `logs/runs/` |
| Database | `sailab_glof.db` (open with DB Browser for SQLite) |
| Run the tests | `.venv/bin/python -m pytest tests -q` |
| Check the GUI numbers | `.venv/bin/python scripts/verify_gui_numbers.py` |
| Re-check every stored measurement against its file | `.venv/bin/python scripts/check_scene_recompute.py` (about 10 minutes) |
| Re-run the mutation check | `.venv/bin/python scripts/mutation_check.py` (about 3 minutes) |
| Start the web app | `.venv/bin/uvicorn app:app`, then <http://127.0.0.1:8000> |
