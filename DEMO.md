# ShinGhar: 3-minute demo script and honest limits

Prototype for the competition proposal "ShinGhar", built on a copy of the SailAb GLOF final-year project.
Pilot valley: **Utror-Kalam, Kalam Tehsil, Swat District, Khyber Pakhtunkhwa** (chosen with the method in
`logs/2026-11-20_shinghar_valley_candidates/README.md`).

Start: `.venv/bin/uvicorn shinghar_app:app --host 127.0.0.1 --port 8100`, open <http://127.0.0.1:8100/> (ShinGhar has its own
look and six pages: Overview, Villages, Forest, Glacial lakes, Alerts, Method & limits). The SailAb (FYP) dashboard of the
same app is at `/sailab`; `app.py` still starts the SailAb app unchanged.
Rebuild the cached results: `.venv/bin/python -m shinghar.build_valley` (needs internet only for the voice MP3s; add
`--skip-voice` offline). The page itself needs no internet: `/shinghar?offline=1` shows the static map.

All numbers below are read from the cached files in `data/shinghar/` at the time of writing; the page always shows
the current ones. LAKE TREND NUMBERS: see section 4 (filled in after the backfill finished).

## The 3-minute script

**0:00 - The problem (20 s).** Villages in KP mountain valleys sit below glacial lakes and below slopes losing their
vegetation. Lakes, forests and warnings are handled by different offices, and warnings rarely reach people in Urdu or
Pashto. Point at the orange banner: *hazard screening, not a forecast; alerts are not sent*.

**0:20 - Overview: map (30 s).** Utror-Kalam: three monitored lakes at 3,000-3,350 m (blue), their downhill paths (dashed),
11 villages (from GHSL built-up areas, names from OpenStreetMap), and vegetation loss 2019-2025 (red/magenta/orange).
Click "static" to show the same map drawn from our own data, offline.
The KPI tiles: villages high / watch, lakes growing fast, vegetation loss, alerts awaiting review.

**0:50 - Forest page (40 s).** 23,683 ha of forest in the box. Our Sentinel-2 NDVI comparison (summer 2019 vs 2025,
98 and 118 images) finds 152 ha of loss; Hansen Global Forest Change (2025 v1.13) maps only 0.93 ha for 2020-2025 here,
and we find 98 % of it. Open the "visual check": of the 8 top-ranked patches, 7 show real change (a slope clearing,
debris-flow and river-bank scars, construction), 1 is unclear. Point at the 39 sites ranked for ranger visits.

**1:30 - Glacial lakes page (30 s).** The lake cards: areas measured by the FYP pipeline since 2019, the summer-median trend
and the fast-expansion flag (> 5 %/yr). (Use the numbers on screen; section 4.)

**2:00 - Villages page (30 s).** The ranking: one transparent score from five parts, weights shown. Open one
village: each part's raw value, scale, weight, points, and 2-3 reasons written from those numbers. "Does not apply" is
different from "no data", and the Data column says how much of the score is backed by data.

**2:30 - Alerts page (30 s).** One drafted alert: English briefing for PDMA / district / Forest Department, Urdu and Pashto
messages, play the MP3. Try "Mark ready": a high alert is blocked until an expert enters a name and clicks
"Reviewed by expert". State: draft -> reviewed -> ready; "sent: no". Nothing is ever sent.

## Honest-limits slide

- **Screening, not forecasting.** Weights and thresholds are judgement calls (shown on screen), not calibrated on past
  events. No field validation.
- **Clouds and snow.** Optical lake areas need clear, snow-free days: most winter and many spring scenes are refused,
  so the lake record is mostly June-October. Radar is measured by the FYP pipeline but not used here.
- **10 m resolution.** Small clearings (< 0.5 ha) are not reported; GHSL built-up areas are 100 m cells; the DEM is 30 m.
- **Vegetation loss is not deforestation.** Our NDVI drop also catches debris flows, river erosion, construction, crops
  and a dry summer. Hansen counts fire, landslides and disease too. Agreement with Hansen is only 0.6 % of our loss
  (Hansen finds very little in this valley at 30 m); the visual check of 8 patches is by eye, not a field visit.
- **Flow paths** are a single steepest-descent line from each lake centre on a 30 m DEM, not a flood model: no depth,
  no volume, no timing.
- **Lakes are unnamed** in OpenStreetMap; local names still need confirming. Village names come from OpenStreetMap.
- **Pashto/Urdu**: text and village-name spellings are machine-written; the Pashto neural voice (ps-AF, an Afghan
  voice) may not match local Swat speech. Must be checked by a native speaker.
- **Glacier layer reused from our FYP** (SailAb GLOF: NDWI > 0.2 + region growing + quality checks), unchanged.
- **Google Earth Engine** was used for all satellite data instead of Microsoft Planetary Computer.
- **Alert text** comes from fixed templates (no AI text in this build). Nothing is sent: there is no sending code.

## What is real, cached, not built

| Part | Status | Source |
|---|---|---|
| Lake areas, seasonal score | Real (FYP pipeline on Sentinel-2) | `sailab_glof.db`, backfill runs 25 (UTA, UTB, KLN to 30 Aug 2026) and 27 (KLN to 20 Nov 2026) |
| Lake trend, fast-expansion flag | Real, computed from those areas | `data/shinghar/glacier.json` |
| Forest loss (NDVI), agreement with Hansen | Real, computed | `data/shinghar/forest_*` |
| Visual check of 8 patches | Real images, judged by eye | `data/shinghar/forest_visual_check.*` |
| Flow paths, village risk, reasons | Real, computed | `data/shinghar/lake_paths.geojson`, `risk.json` |
| Alert texts, MP3s | Generated from templates; machine Urdu/Pashto | `data/shinghar/alerts.json`, `audio/` |
| Everything on the page | Cached files; works offline | `data/shinghar/` |
| Dynamic World layer | **Not built** | |
| AI-written (Claude API) alert text | **Not built** (templates used; no API key) | |
| Sending alerts | **Not built, on purpose** | |
| Field validation | **Not done** | |

## 4. Lake numbers (filled in after the backfill)

Backfill from 2019-01-01 to 2026-11-20 finished for all three lakes (optical). Summer = clear July-September scenes; trend =
least-squares line through the yearly medians (`data/shinghar/glacier.json`).

| Lake | Clear optical scenes | Summer median 2019 -> 2026 | Trend | Fast-expansion flag (> 5 %/yr) |
|---|---|---|---|---|
| UTA, Utror lake A (3,028 m) | 155 | 41.6 -> 41.7 ha | -0.0 %/yr | no |
| UTB, Utror lake B (3,183 m) | 173 | 17.2 -> 16.8 ha | -0.1 %/yr | no |
| KLN, Kalam north lake (3,345 m) | 139 | 29.2 -> 29.8 ha | +0.2 %/yr | no |

**What to say:** none of the three lakes is growing; all are stable within a few percent over 8 summers. The valley's watch
bands come from flow paths, forest loss and steep slopes, not from lake growth. That is a useful screening result, not a gap.

Village bands after the rebuild: 0 high, 5 watch (Asharopatoi 42.8, Boyun 38.0, Kuz Laikot 36.8, Pishmal 36.6, Shahu 30.2),
6 low; 5 draft alerts (all "watch", so none needs the expert review gate; the gate is shown by the tests and on the
Alerts page buttons).

Known gaps from the backfill:
- **KLN radar** stopped at April 2020: Earth Engine answered "memory capacity exceeded" (HTTP 503) twice. Radar is not
  used by ShinGhar; UTA and UTB radar are complete.
- The latest scene anomalies are negative (UTA z -0.2, UTB z -1.3, KLN z -4.5 in October/November): these are autumn
  scenes (shrinking or partly frozen lakes) and only positive anomalies add points, so they score 0.
- Pipeline bug found (copied from the FYP code, not fixed here): resuming a failed run with `--lakes` set to a subset that
  does not contain the last finished lake fails with `ValueError: 10 is not in list` (run 26). A plain re-run works.
