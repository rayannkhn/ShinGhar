# Nepal test lakes: which two can the system measure? (2026-11-18)

Asked for by the supervisor (international lakes, ideally Nepal). Chosen the same way as the Pakistan lakes:
locate each lake in JRC Global Surface Water v1.4 (1984-2021), then download real Sentinel-2 scenes and measure them
with the pipeline's own unchanged code (`measure_scene`: NDWI 0.2, region growing, checks C and D). Scratch
downloads only; the database was not touched by these tests. Season: October to mid-November 2024 and 2025 (after
the monsoon, the clearest months in Nepal).

## 1. Where the water is (`find_water_*.py`)
| Lake | Centre (JRC centroid) | Max extent | Water in % of observations | Elevation |
|---|---|---|---|---|
| Imja Tsho | 27.89863 N 86.92438 E | 127.7 ha | 90.3 % | 4,990 m |
| Tsho Rolpa | 27.86090 N 86.47656 E | 162.0 ha | 97.3 % | 4,546 m |
| Dig Tsho (burst 1985) | 27.87425 N 86.58595 E | 41.1 ha | 96.9 % | 4,369 m |
| Tam Pokhari (burst 1998) | 27.74260 N 86.84475 E | 32.1 ha | 90.4 % | 4,364 m |
| Thulagi (Dona) | 28.48859 N 84.48544 E | 102.8 ha | 93.7 % | 3,988 m |
| Lower Barun | 27.79819 N 87.09361 E | 165.4 ha | 95.2 % | 4,508 m |

## 2. The pipeline's own measurement on real scenes (`smoke_*.py`; 4 clearest scenes per season)
| Lake | Usable / tested | Areas when usable | Why the others were refused |
|---|---|---|---|
| **Thulagi** | **6 / 8** | 96.91-97.73 ha | 1 cloud touching (check D), 1 snow touching (check C) |
| **Tsho Rolpa** | 2 / 8 | 165.41, 165.25 ha | 1-344 cloud pixels touching (check D) |
| Tam Pokhari | 2 / 8 | 25.00, 24.93 ha | snow touching (check C) |
| Dig Tsho | 1 / 8 | 39.67 ha | window edge (no-data), snow touching |
| Lower Barun | 0 / 8 | — | window edge, cloud, snow/ice touching |
| Imja Tsho | 0 / 8 | — | check C every time: the lake touches its glacier's ice cliff at the east end, which Sentinel-2 classes as snow/ice. The outline itself is right (about 180 ha): `imja_and_tsho_rolpa_oct2024.png` |

## 3. Published areas to compare with
- Tsho Rolpa: 1.55 km2 (1999), about 1.6 km2 (ICIMOD). Measured here 1.65 km2.
- Thulagi: 0.94 km2 (ICIMOD field survey, 2009); 0.89 km2 (October 2017 survey, Remote Sensing 10(5) 798, 2018),
  "almost stable for about two decades". Measured here 0.97 km2.
- Imja Tsho: 1.35 km2 in 2013 (Bolch et al. 2016, Annals of Glaciology); not added (see above).

## 4. Decision (with the project owner)
Tsho Rolpa and Thulagi: both among ICIMOD's highest-risk lakes in Nepal, both measured cleanly, Thulagi on most clear
days. The two that actually burst (Dig Tsho 1985, Tam Pokhari 1998) are measurable but rarely (snow, window edge).
Imja Tsho would need check C relaxed for glacier-contact lakes; the project owner chose to replace it instead.

## Backfill result (2026-11-18, runs 20 and 22)

Run 20 (TRL, THU) finished TRL, then stopped on an Earth Engine HTTP 503 ("memory capacity exceeded") partway through
THU. A rerun with `--lakes THU` crashed at start-up: the resume note said lake 7 (TRL) was done, and
`sailab/acquisition.py` raises `ValueError: 7 is not in list` when the resume note names a lake that is not in this
run's list (a bug in the core module, not changed here). The crash cleared the note; run 22 then completed THU with no errors.

`compare_published.py` → `compare_published.log`:
- Optical: Tsho Rolpa median 165.1 ha (38 clear images, 162–167), +3% to +7% against the published 155–160 ha.
  Thulagi median 96.7 ha (74 clear images, 94–99), +3% to +9% against the published 89–94 ha.
- Radar depends on the orbit pass. Tsho Rolpa: the ~00 UTC pass gives 145 ha (96% of images near the published
  size), and the ~12 UTC pass gives 0% near it. Thulagi is the other way round: ~12 UTC 95% near, ~00 UTC 0%. Most
  likely the steep valley walls hide the lake (radar shadow or layover) from one viewing side. Radar is not scored,
  so no risk score is affected.
- A live check on TRL in the GUI ran end to end (20 steps, nothing new, replayed 2026-10-23 optical: 164.71 ha).
