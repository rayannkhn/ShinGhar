# Scheduled run 3 (GitHub run 42916975176, pipeline run 12), checked 2026-11-11 08:58 UTC

Source: `gh run list`, `gh run view --json jobs`, job log via `gh api .../actions/jobs/130181817081/logs`,
bot commit 20ffbfc (already on this laptop through the hourly `git pull --ff-only` cron job).

| Item | Value |
|---|---|
| Event | `schedule`: the third scheduled run, and the first over six lakes |
| Cron slot | 2026-11-10 18:00 UTC; GitHub started it 22:42:13 UTC (about 4.7 h late) |
| Job | success; every step success |
| Test step | `265 passed, 1 warning in 10.80s` |
| Pipeline | run 12, 22:42:52 to 22:43:03 UTC (11 s): 6 lakes, 4 scenes recorded, 2 downloaded, 2 measurements, 0 risk scores, no error |
| run_log row | `12 \| 2026-11-10T22:42:52+00:00 \| 2026-11-10T22:43:03+00:00 \| 6 \| 2 \| (no error)` |
| Bot commit | 20ffbfc "Automated run: 2026-11-10T22:43:03Z (success)": sailab_glof.db, 2 radar GeoTIFFs, logs/runs/2026-11-10T224252Z.log |

## What it found
- Optical: one new Sentinel-2 pass on 2026-11-10 over Karambar and Atro Sar, both too cloudy (92.1 % and 70.7 % over
  the lake): recorded, not downloaded. For the four new lakes the same pass was already stored by the backfill.
- Radar: the 2026-11-10 01:05 UTC Sentinel-1D pass for Karambar (261.14 ha, threshold −17.32 dB) and Atro Sar
  (98.05 ha, −15.05 dB). Not scored. For the four new lakes it was already stored by the backfill.
- **These are the same areas the GUI live check measured from the same pass on 2026-11-10 07:49 UTC (261.14 and
  98.05 ha, `logs/2026-11-10_gui_live_check_found_new_pass.md`), and the files have the same SHA-256:**
  KRB 5c899ab15164059f3cc4d35845fce8d0b52f27ecf868d41c61786986ddcddcaf, ATS 3281926f2dec40b880647ecfccb0cba6e009abbd4bf9e69efcd47e17d28ef47b.
  The live check and the nightly run give identical results on the same scene.

## Scheduled runs so far: 3
| Run | Slot (UTC) | Started (UTC) | Started (PKT) |
|---|---|---|---|
| 6 | 8 Nov 18:00 | 8 Nov 21:31 | 9 Nov 02:31 |
| 9 | 9 Nov 18:00 | 10 Nov 01:01 | 10 Nov 06:01 |
| 12 | 10 Nov 18:00 | 10 Nov 22:42 | 11 Nov 03:42 |
Three different daily slots. Note: by UTC start time, runs 9 and 12 both started on 10 November (GitHub's delays);
by slot and by Pakistan time they are three different days.

## Job log, pipeline section (verbatim, timestamps stripped)
2026-11-10 22:42:52,636 INFO run_once: mode: scheduled/normal, data dir: /home/runner/work/sailab-glof-live/sailab-glof-live/data/scenes
2026-11-10 22:42:52,784 INFO sailab.pipeline: run 12 started
2026-11-10 22:42:53,462 INFO sailab.pipeline: signed in to Earth Engine as sailab-glof-bot@kaarigar-507118.iam.gserviceaccount.com
2026-11-10 22:42:54,833 INFO sailab.pipeline: KRB: 2 scenes listed after 2026-11-04
2026-11-10 22:42:54,833 INFO sailab.pipeline: KRB 20261105T055021_20261105T055015_T43SCA: already recorded, skipped
2026-11-10 22:42:54,836 INFO sailab.pipeline: KRB 20261110T055049_20261110T055844_T43SCA: lake cloud 92.1259521772781% > 10.0% limit: too cloudy for optical, recorded but not downloaded (radar passes are listed separately)
2026-11-10 22:42:55,130 INFO sailab.pipeline: KRB: 2 radar scenes listed after 2026-11-08
2026-11-10 22:42:55,341 INFO sailab.pipeline: KRB S1D_IW_GRDH_1SDV_20261109T130519_20261109T130544_005391_00A47E_3D25: already recorded, skipped
2026-11-10 22:42:56,958 INFO sailab.pipeline: KRB S1D_IW_GRDH_1SDV_20261110T010541_20261110T010606_005398_00A4C0_EE4D: downloaded data/scenes/KRB/S1D_IW_GRDH_1SDV_20261110T010541_20261110T010606_005398_00A4C0_EE4D.tif sha256=5c899ab15164059f3cc4d35845fce8d0b52f27ecf868d41c61786986ddcddcaf
2026-11-10 22:42:57,232 INFO sailab.pipeline: KRB S1D_IW_GRDH_1SDV_20261110T010541_20261110T010606_005398_00A4C0_EE4D: radar ok 261.14 (26114 px below -17.32 dB connected to the centre)
2026-11-10 22:42:57,232 INFO sailab.pipeline: KRB S1D_IW_GRDH_1SDV_20261110T010541_20261110T010606_005398_00A4C0_EE4D: radar not risk-scored (SCORE_RADAR is off: snowmelt errors, see pipeline.py)
2026-11-10 22:42:58,198 INFO sailab.pipeline: ATS: 2 scenes listed after 2026-11-04
2026-11-10 22:42:58,198 INFO sailab.pipeline: ATS 20261105T055021_20261105T055015_T43SCA: already recorded, skipped
2026-11-10 22:42:58,199 INFO sailab.pipeline: ATS 20261110T055049_20261110T055844_T43SCA: lake cloud 70.70438472418671% > 10.0% limit: too cloudy for optical, recorded but not downloaded (radar passes are listed separately)
2026-11-10 22:42:58,377 INFO sailab.pipeline: ATS: 2 radar scenes listed after 2026-11-08
2026-11-10 22:42:58,435 INFO sailab.pipeline: ATS S1D_IW_GRDH_1SDV_20261109T130454_20261109T130519_005391_00A47E_443A: already recorded, skipped
2026-11-10 22:42:58,954 INFO sailab.pipeline: ATS S1D_IW_GRDH_1SDV_20261110T010541_20261110T010606_005398_00A4C0_EE4D: downloaded data/scenes/ATS/S1D_IW_GRDH_1SDV_20261110T010541_20261110T010606_005398_00A4C0_EE4D.tif sha256=3281926f2dec40b880647ecfccb0cba6e009abbd4bf9e69efcd47e17d28ef47b
2026-11-10 22:42:59,061 INFO sailab.pipeline: ATS S1D_IW_GRDH_1SDV_20261110T010541_20261110T010606_005398_00A4C0_EE4D: radar ok 98.05 (9805 px below -15.05 dB connected to the centre)
2026-11-10 22:42:59,061 INFO sailab.pipeline: ATS S1D_IW_GRDH_1SDV_20261110T010541_20261110T010606_005398_00A4C0_EE4D: radar not risk-scored (SCORE_RADAR is off: snowmelt errors, see pipeline.py)
2026-11-10 22:42:59,857 INFO sailab.pipeline: SHP: 1 scenes listed after 2026-11-09
2026-11-10 22:42:59,858 INFO sailab.pipeline: SHP 20261110T055049_20261110T055844_T43SDA: already recorded, skipped
2026-11-10 22:43:00,159 INFO sailab.pipeline: SHP: 2 radar scenes listed after 2026-11-09
2026-11-10 22:43:00,218 INFO sailab.pipeline: SHP S1D_IW_GRDH_1SDV_20261110T010541_20261110T010606_005398_00A4C0_EE4D: already recorded, skipped
2026-11-10 22:43:00,218 INFO sailab.pipeline: SHP S1D_IW_GRDH_1SDV_20261110T010606_20261110T010631_005398_00A4C0_FF67: already recorded, skipped
2026-11-10 22:43:01,182 INFO sailab.pipeline: DKT: 1 scenes listed after 2026-11-09
2026-11-10 22:43:01,183 INFO sailab.pipeline: DKT 20261110T055049_20261110T055844_T43SCA: already recorded, skipped
2026-11-10 22:43:01,446 INFO sailab.pipeline: DKT: 1 radar scenes listed after 2026-11-09
2026-11-10 22:43:01,472 INFO sailab.pipeline: DKT S1D_IW_GRDH_1SDV_20261110T010541_20261110T010606_005398_00A4C0_EE4D: already recorded, skipped
2026-11-10 22:43:02,137 INFO sailab.pipeline: BRT: 1 scenes listed after 2026-11-09
2026-11-10 22:43:02,138 INFO sailab.pipeline: BRT 20261110T055049_20261110T055844_T43SDA: already recorded, skipped
2026-11-10 22:43:02,435 INFO sailab.pipeline: BRT: 1 radar scenes listed after 2026-11-09
2026-11-10 22:43:02,463 INFO sailab.pipeline: BRT S1D_IW_GRDH_1SDV_20261110T010541_20261110T010606_005398_00A4C0_EE4D: already recorded, skipped
2026-11-10 22:43:03,097 INFO sailab.pipeline: PSU: 1 scenes listed after 2026-11-09
2026-11-10 22:43:03,097 INFO sailab.pipeline: PSU 20261110T055049_20261110T055844_T43SDA: already recorded, skipped
2026-11-10 22:43:03,329 INFO sailab.pipeline: PSU: 1 radar scenes listed after 2026-11-09
2026-11-10 22:43:03,356 INFO sailab.pipeline: PSU S1D_IW_GRDH_1SDV_20261110T010541_20261110T010606_005398_00A4C0_EE4D: already recorded, skipped
2026-11-10 22:43:03,359 INFO sailab.pipeline: run 12 finished: RunResult(run_id=12, lakes_processed=6, scenes_recorded=4, scenes_downloaded=2, measurements=2, risk_scores=0, errors=None, notes=[])
2026-11-10 22:43:03,359 INFO run_once: summary: run_id=12 lakes=6 scenes_recorded=4 downloaded=2 measurements=2 risk_scores=0
2026-11-10 22:43:03,359 INFO run_once: run OK
