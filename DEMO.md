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

## The 3-minute script (story page, 1920x1080 projector)

Open <http://127.0.0.1:8100/>, click **Start demo**, then use the arrow keys (or the bar at the bottom); Esc leaves demo
mode. Each step fills one screen. The banner "Hazard screening, not a forecast ... not sent" stays on screen.

**0:00 - Start (15 s).** The question: which mountain villages should be checked first, and why? Four real numbers:
39 slope sites flagged for ranger visits, 467 clear satellite photos of 3 glacial lakes since 2019, 11 villages
screened, 152 ha of forest ground that lost its green 2019-2025.

**0:15 - 1 The place (25 s).** Sentinel-2 true colour, summer 2025 (118 photos combined, clouds and snow removed). Point at
the 3 lakes (blue), 11 villages (yellow), 39 sites (pink). Context line: the August 2022 flash floods (Dawn, linked).

**0:40 - 2 Forest (40 s).** Drag the three sliders 2019 -> 2025. Site 2: "2.9 ha of forest lost its green ... 38° slope,
3.1 km from Asharopatoi and 530 m above it"; you can see a wide bare channel where trees were. Say: losing green can
also be a debris flow or construction, so a ranger checks every site.

**1:20 - 2 Lake (30 s).** Kalam north lake, 2019 vs 2025, with the outline our pipeline measured (29.2 ha and 30.0 ha,
the same numbers as in the database). Chart: about 30 ha every summer. "Stable: good news, and we keep watching."
Finding: none of the 3 lakes grows fast (at most 0.2 %/yr; flag at 5 %/yr).

**1:50 - 3 Who first (30 s).** No village reaches "watch" today; the five to check first, each with one reason. The bars
show what adds up to each score. One sentence: being on a lake's water path counts more the closer the lake is (full
points within 5 km, none beyond 50 km).

**2:20 - 4 What happens next (40 s).** Labelled EXAMPLE for Asharopatoi (it is "low"): briefing for the Forest Department,
the village's own reasons and numbers in Urdu (and Pashto), play the voice (37 s / 34 s), type a name, click
"Reviewed by expert", then "Mark ready": "ready (not sent)". After the demo, click "reset demo" (the history keeps
every step).

Expert view (tabs at the top): Overview, Villages, Forest, Glacial lakes, Alerts, Method & limits, with all the numbers.

## Honest-limits slide

- **Screening, not forecasting.** Weights and thresholds are judgement calls (shown on screen), not calibrated on past
  events. No field validation.
- **Clouds and snow.** Optical lake areas need clear, snow-free days: most winter and many spring scenes are refused,
  so the lake record is mostly June-October. Radar is measured by the FYP pipeline but not used here.
- **10 m resolution.** Small clearings (< 0.5 ha) are not reported; GHSL built-up areas are 100 m cells; the DEM is 30 m.
- **Vegetation loss is not deforestation.** Our NDVI drop also catches debris flows, river erosion, construction, crops
  and a dry summer. Hansen counts fire, landslides and disease too. Agreement with Hansen is only 0.6 % of our loss
  (Hansen finds very little in this valley at 30 m) and 21 % is also in Dynamic World; the three products measure
  different things. The visual check of 8 patches is by eye, not a field visit.
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
| Lake areas, seasonal score | Real (FYP pipeline on Sentinel-2) | `sailab_glof.db`, backfill runs 25 (UTA, UTB, KLN to 30 Aug 2026), 27 (KLN optical to 20 Nov 2026) and 28 (KLN radar) |
| Lake trend, fast-expansion flag | Real, computed from those areas | `data/shinghar/glacier.json` |
| Forest loss (NDVI), agreement with Hansen | Real, computed | `data/shinghar/forest_*` |
| Dynamic World check (third product) | Real, computed | `forest_agreement.json` -> `dynamic_world`; per site in `forest_patches.*` |
| Risk per forest site, reasons | Real, computed | `data/shinghar/site_risk.json` |
| Visual check of 8 patches | Real images, judged by eye | `data/shinghar/forest_visual_check.*` |
| Flow paths, village risk, reasons | Real, computed | `data/shinghar/lake_paths.geojson`, `risk.json` |
| Alert texts, MP3s | Generated from templates with each village's own reasons and numbers; machine Urdu/Pashto; one labelled example | `data/shinghar/alerts.json`, `audio/` |
| Story images (valley, 3 sites, lake) | Real Sentinel-2 composites / the pipeline's own scene and outline | `data/shinghar/story/` (`story_images.json` lists every input) |
| "What you can see" lines | By-eye reading of those images, not a field visit | `data/shinghar/story/site_notes.json` |
| Everything on the page | Cached files; works offline | `data/shinghar/` |
| AI-written (Claude API) alert text | **Not built** (your choice: templates; no API key) | |
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

Village bands: until 2026-11-21 the outflow-path part gave every village on a lake's path the same 20 points (10 km and
38 km scored alike). With the owner's approval it now falls with the distance along the path (full within 5 km, none
beyond 50 km). Before: 5 watch (Asharopatoi 42.8, Boyun 38.0, Kuz Laikot 36.8, Pishmal 36.6, Shahu 30.2). After: 0 high,
0 watch, 11 low (Asharopatoi 29.8, Boyun 29.5, Kuz Laikot 26.7, Pishmal 26.5, Gall 25.5, Kass 25.4, Shahu 23.3, four at 0).
So no real alert is drafted; one alert for the top village is drafted and labelled EXAMPLE to show the flow.

Known gaps from the backfill:
- **Earth Engine errors:** runs 25 and 27 stopped on "memory capacity exceeded" (HTTP 503), a temporary server error.
  Run 28 (2026-11-21) completed KLN with 0 errors, so all three lakes are now complete for optical and radar (radar is
  measured by the FYP pipeline but not used by ShinGhar).
- The latest scene anomalies are negative (UTA z -0.2, UTB z -1.3, KLN z -4.5 in October/November): these are autumn
  scenes (shrinking or partly frozen lakes) and only positive anomalies add points, so they score 0.
- Pipeline bug found (in the code copied from the FYP): resuming a failed run with `--lakes` set to a subset that does
  not contain the last finished lake failed with `ValueError: 10 is not in list` (run 26). Fixed in this copy
  (`sailab/acquisition.py`, regression test in `tests/test_acquisition.py`); the FYP folder itself is untouched.

## 5. Evidence

- Screenshots (2026-11-21, 1400 px wide): `docs/screenshots/2026-11-21/shinghar_*.png`, one per page.
- Offline check: the app was started inside a network namespace with no internet (`unshare -rn`); every ShinGhar page,
  the cached files, an MP3 and `/sailab` returned 200, and the overview switched to the static map by itself
  (`docs/screenshots/2026-11-21/shinghar_overview_OFFLINE.png`).
- Tests: `.venv/bin/python -m pytest -q`: 372 passed on 2026-11-21.
- Story screenshots at 1920x1080: `docs/screenshots/2026-11-21/story/` (one per demo step, plus the flow after review).
- MP3 proof: in the browser both files load (37.5 s and 33.9 s) and play (1.4 s played after 1.5 s); offline they are served from `data/shinghar/audio/`.
- Story images: `.venv/bin/python -m shinghar.story_images --fetch` (Earth Engine, then cached; `rgb_stack.tif`, 102 MB, is gitignored).
- Rebuild from scratch: `shinghar.forest_ee.fetch_stack(...)` and `fetch_dw(...)` (Earth Engine, about 10 min), then
  `.venv/bin/python -m shinghar.build_valley`. Both GeoTIFFs are gitignored (64 MB and 33 MB).
