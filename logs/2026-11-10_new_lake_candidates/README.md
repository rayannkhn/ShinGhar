# New lake candidates: can the system measure them? (2026-11-10)

Nothing here is in the database. Scratch downloads only; scripts in this folder.

## 1. Where the water is (JRC Global Surface Water v1.4, 1984-2021, max extent; `find_water.py`)
| Candidate | Water body found | Note |
|---|---|---|
| Borith Lake | 13.2 ha, water in 90 % of observations, 36.4305 N 74.8621 E, ~2,630 m | persistent lake |
| Passu glacier lake | 19.1 ha, 90.7 %, 36.4574 N 74.8798 E, ~2,560 m | at the Passu glacier snout |
| Ghulkin | only ponds of ~10 ha on the glacier surface (36.4233 N 74.8246 E) | not a lake basin |
| Shishper | not in JRC (ends 2021; lake was ephemeral) | found on Sentinel-2 instead |
| Khurdopin | a 116 ha patch with water in only 47 % of observations at the old lake site (36.3378 N 75.4889 E) | ephemeral |

Shishper lake on Sentinel-2 (`locate.py`): 19.1 ha centred 36.3578 N 74.5680 E (Apr-May 2022, before the 7 May
2022 outburst); 20.4 ha centred 36.3607 N 74.5627 E (May-Jun 2019). Gone in summer 2025 (`shishper_2025.png`).

## 2. The pipeline's own measurement on real scenes (`smoke.py`: list, lake cloud, download, measure_scene)
| Lake | Period | Clear scenes measured | Result |
|---|---|---|---|
| Shishper | May-Jun 2019 | 2 | ok 19.49 and 11.77 ha |
| Shishper | Apr-May 2022 | 3 | ok 17.05, ok 5.83, refused (centre not water) |
| Shishper | Jul 2025 | 4 | all refused: centre not water (lake drained: correct) |
| Khurdopin | Jun-Sep 2019 and Jul 2025 | 8 | all refused: centre not water (no lake: dry river plain) |
| Passu | Jul 2025 | 4 | all refused: centre not water, **although the lake is there**: silty grey water, NDWI at the centre −0.03 |
| Borith | Jul 2025 | 4 | ok 10.08, ok 3.75, 2 refused; NDWI at the centre 0.87 on the good day |
| Ghulkin | Jul 2025 | 4 | all refused: centre on glacier ice |

Pictures of these scenes (true colour and NDWI, centre marked): `test_scenes_truecolour_ndwi.png`.

## 3. What this means
- NDWI > 0.2 (the project's unchanged water test) does **not** see silt-laden glacial water (Passu), and sees
  Shishper's murky lake only in part. Only clear water (Borith) measures well, and even Borith varies day to day.
- "Centre not water" therefore does **not** reliably mean "the lake has drained": at Passu it happens with the lake
  full. A drained-lake status based on NDWI alone would give false outburst signals on silty lakes.
- Khurdopin and Ghulkin have no lake to measure now; Shishper has had none since the 2022 outburst.
