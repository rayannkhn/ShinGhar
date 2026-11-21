# ShinGhar Step 1: choosing the pilot valley (2026-11-20)

Requirement: a KP valley (Chitral or Upper Swat) with 2-3 glacial lakes AND forest on the slopes above villages.
All numbers below come from the scripts in this folder (Earth Engine, service account; outputs `*.log` / `*.json`).
Scratch downloads were kept outside the repository; the database was not touched.

## 1. Search areas (`find_candidates.py` → `find_candidates.log`)
JRC GSW v1.4 water bodies > 5 ha; Hansen GFC **2025 v1.13** (newest in the EE catalog); ESA WorldCover v200; GHSL 2020
built surface; GLIMS glacier outlines.

| Search box | Glacier (GLIMS) | Hansen tree cover ≥30 % | WorldCover trees | Hansen loss 2001-25 | Built-up | High lakes near ice |
|---|---|---|---|---|---|---|
| Chitral: Golen | 0 km² | 84 ha | 1,713 ha | 0.0 ha | 138 ha | 1 (6.5 ha) |
| Chitral: Reshun-Booni | 48 km² | 43 ha | 3,359 ha | 0.1 ha | 363 ha | 2 (7.7, 11.2 ha; water 34-48 % of the time) |
| Chitral: Brep (Yarkhun) | 37 km² | 63 ha | 1,374 ha | 0.0 ha | 112 ha | 0 (water bodies are river reaches) |
| Chitral: Laspur | 56 km² | 78 ha | 594 ha | 0.0 ha | 77 ha | several near Shandur, none within 1.5 km of a glacier |
| **Upper Swat: Utror-Gabral** | 40 km² | **17,101 ha** | **29,157 ha** | 47.2 ha | 77 ha | 5 |
| **Upper Swat: Kalam-Ushu-Mahodand** | 125 km² | **8,057 ha** | **14,257 ha** | 22.2 ha | 50 ha | 5 |

Chitral fails the forest requirement (Hansen forest ≤ 84 ha per box), so its lakes were not smoke-tested.

## 2. District check and villages (`settlements.py`, names: OpenStreetMap Nominatim → `settlements_named.json`)
FAO GAUL 2015 level 2: SB, SC, SD, SE, SF, SI in Swat District; SA in Upper Dir; SH, SJ in Kohistan; SG unassigned
(those four were not smoke-tested). All lakes tested are in Kalam Tehsil except SA (Kalkot Tehsil, Upper Dir).
Villages (GHSL 2020 built-up clusters) have 36-75 % tree cover within 3 km; Hansen loss 2001-25 within 3 km of
Kalam (Boyun cluster) is 21.6 ha, Pishmal 14.7 ha.

## 3. Pipeline smoke test (`smoke.py` → `smoke_1.log`, `smoke_2.log`, `smoke_*.json`; partial first run: `smoke_partial_SA_SB.log`)
Same method as `logs/2026-11-18_nepal_lake_candidates/`: summer (Jul-Sep) 2024 and 2025, the 4 clearest scenes per
season (ties broken by date, so early July, snowiest, comes first), radius = growth limit = 1000 m, `measure_scene` unchanged.

| Lake | Centre (JRC) | Elev | Usable / tested | Areas (ha) | Refused because |
|---|---|---|---|---|---|
| **SE** | 35.41921 N 72.43293 E | 3,028 m | **7 / 8** | 42.0-45.4 (+ 11.57 on 2025-07-01) | 1 snow touching |
| **SD** | 35.43385 N 72.45197 E | 3,183 m | **6 / 8** | 17.1-17.9 (+ 11.39 on 2025-07-01) | 2 snow touching |
| SA (Upper Dir) | 35.36737 N 72.34591 E | 3,535 m | 4 / 8 | 73.9-74.6 | snow, centre not water (2024) |
| SF | 35.64618 N 72.51194 E | 3,345 m | 3 / 8 | 29.6-30.5 | snow touching (5) |
| SI | 35.60281 N 72.59834 E | 3,887 m | 3 / 8 | 17.6-17.8 | snow, centre not water |
| SB | 35.63584 N 72.29714 E | 4,077 m | 2 / 8 | 20.3, 25.9 | snow (4), centre not water |
| SC | 35.60824 N 72.23468 E | 3,865 m | 1 / 8 | 11.9 | window edge, snow |

SD and SE both gave a partial area (about 11.5 ha) on 2025-07-01: probably part of the lake still frozen or
snow-covered and not flagged by check C. This is the known under-detection limit, not a real change.
None of the lakes has a name in OpenStreetMap at its centre; local names must be confirmed.

## 4. Downhill paths (`flow_paths.py` → `flow_paths.log`): GLO-30 DEM, the FYP's `fill_sinks` + `trace_flood_path_2d`
SD and SE drain north past **Kass (Utror)** at 9.8 / 11.6 km (800-930 m lower), then to the Swat river past
Shahu, Pishmal, Asharopatoi and Zarhinal. SB and SC route via Gall (Utror). SF and SI join the same river further down.
Kalam town (Boyun cluster) was not within 500 m of any traced path at its cluster centre; the river runs through the town.

## 5. Recommendation
Pilot valley **Utror-Kalam, Kalam Tehsil, Swat District (Upper Swat, KP)**: lakes **SE and SD** (best measured) plus
**SF** (third lake, 3/8), villages Kass/Utror, Kalam, Pishmal, Matiltan, ...; dense forest on the slopes.
