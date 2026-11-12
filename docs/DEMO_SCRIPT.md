# SailAb GLOF: demo script

About 8 minutes. Every number on screen comes from `sailab_glof.db`; the one network-dependent step is
the live check, and its three possible outcomes are planned below.

## The evening before
1. `git pull` (gets the nightly bot's latest database and logs).
2. `.venv/bin/python -m pytest tests/ -q`: all tests must pass.
3. `.venv/bin/python scripts/verify_gui_numbers.py`: must end with "N of N checks passed".
4. Open the repository's **Actions** tab and note how many **scheduled** runs have succeeded and on which days.
5. Note the newest scene date for each lake (Dashboard, "Scenes recorded") so a "no new scene" result is expected.

## On the day, before the jury arrives
1. Connect to the internet and check it works (open any website).
2. `cd ~/Documents/SAILAB_FYP1_FINAL && .venv/bin/uvicorn app:app`, then open http://127.0.0.1:8000.
3. Keep these ready in separate tabs, as fallbacks:
   - `logs/2026-11-08_gui_live_check_new_scenes_vs_backfill.log` (the real "new scenes" run)
   - `docs/comparison/` (screens next to the designs)
   - the GitHub repository's Actions tab.

## 1. Dashboard (1.5 min)
- "This is a monitoring prototype for two lakes, Karambar and Atro Sar. Alerting is not built, and the banner says so."
- Point at the **Data: commit …** chip: "These pages read a copy of the database the nightly GitHub run publishes. This is the exact commit."
- KPI row: "611 scenes since January 2023, **58% too cloudy** over the lake to measure optically. That is the cloud
  problem from our problem statement, measured with our own data."
- Warning banner: "Neither lake has had a usable image for over 7 days. In winter they are frozen, snowed in or clouded over."
- Pipeline runs table: "Run 1 failed. We kept it: it was a real bug, recorded honestly, then fixed."

## 2. Lake Detail: Atro Sar (2 min)
- Latest usable image: "A real Sentinel-2 image. The yellow outline is recomputed from the stored file by the same
  measurement code, and it contains exactly the stored 10,590 pixels, 105.90 ha."
- "Our earlier report said 76.51 ha. That window was too small and cut the lake off. The whole lake is about 106 ha.
  We found that ourselves and corrected it."
- Chart: "Each dot is a usable measurement. Each tick underneath is a real scene: blue measured, ochre refused by our
  quality checks, grey too cloudy. Points separated by winter are not joined: a gap is a gap."
- "How the latest score was made": "The score is a deviation from the same month in earlier years, here −0.96.
  It is not a danger level or a probability."
- Radar triangles and the radar image: "Sentinel-1 radar sees through cloud. Our first radar method leaked
  into the valley and measured 975.9 ha. Removing steep ground before thresholding removed the leak on that file.
  The 10-degree limit was chosen on that one file, so we then checked it on scenes it was not chosen on: against
  near-same-day optical, radar reads 5% high at Karambar and 6% low at Atro Sar, on 16 summer scenes from 2 lakes.
  That is a mitigation for these two lakes in summer, not a general fix, and why the two lakes differ is still
  open. In snowmelt season wet snow looks like water, so radar is measured and shown but not risk-scored."
- Dashed panels: "Dam, terrain and weather are part of the design but not of this build, so they say so."

## 3. Live check (1 to 2 min): the one real-time step
Click **Live check**, then **Check both lakes now**. Say while it runs:
"This calls Google Earth Engine now, with the same pipeline the nightly run uses. It writes only to this laptop's copy,
never to the published record."

### Outcome A: "No new scene for either lake" (most likely; about 10 to 20 s)
"Earth Engine answered, and there is no Sentinel-2 pass newer than the last stored one. The satellite passes about every
2 to 5 days and new images take some hours to appear. The log underneath shows each request it made."

### Outcome B: new scenes recorded (possible)
"It found a new pass." Point at the log line for each scene: too cloudy, refused by a check (it names which), or
measured with its area. If one was measured, open that lake's page: the new point is on the chart.
In November to May a measured area is unlikely; a refusal is the honest, expected result.

### Outcome C: "The check could not complete" (no internet, a usage limit, or a key problem)
**It takes about 20 to 35 seconds to fail with no internet** (32 s and 23 s in two real tests), because Google's libraries retry. Do not click again.
Say during the wait: "If the network is down, the client retries for up to about half a minute before giving up."
When the red box appears, read its first sentence aloud, then:
"Nothing was invented: the pages still show the last stored data, and the failure is itself recorded in the run log.
Here is the same button run successfully on 8 November." Open
`logs/2026-11-08_gui_live_check_new_scenes_vs_backfill.log`: "We rewound a copy of the database to 15 August and pressed
the button. It found 42 real scenes, measured 12, and every row and every downloaded file was identical to what the nightly
pipeline had stored."

## 4. Design previews (1 min)
Open **Confirm advisory**. "These three screens are the design for the stages we have not built. They carry the
design's sample data, every button is disabled, and the app has no route that could send anything."

## 5. GitHub Actions (1 min)
Open the repository's **Actions** tab. "These are the nightly runs, started by GitHub's scheduler at 11 pm, on different
days, each committing its database and log. The run history is public and timestamped by GitHub, not by us."
Only say "N scheduled runs" with the number you counted the evening before.

## Questions to expect, and honest answers
- **"Has it ever caught a GLOF?"** No. Neither lake has a recorded outburst; the detector has not been tested on a real event.
- **"Why are scores so few?"** A score needs 5 earlier values for that month from 2 years; winter months rarely have any.
- **"What happens in the monsoon?"** Optical is blind under cloud (58% of scenes). Radar measures through cloud
  (within about 6% of optical), but is not risk-scored because of snowmelt errors.
- **"Is the radar problem solved?"** For these two lakes in summer the leak is gone; it is not validated for other
  lakes or seasons, and the 10-degree limit was chosen on the one original radar file.
- **"Why not score radar?"** 29 of 361 usable radar values (8%) are clearly wrong by a stated rule (more than 15% from
  the lake's optical median; `logs/2026-11-09_radar_error_count.log`). 16 of them are in April-June (wet snow), 10 in
  February-March, and they made the largest false anomalies. Fixing that needs spring ground truth we do not have.
- **"Is the slope mask verified?"** The slope code gives exactly the same numbers as numpy, and on 98-99% of pixels
  the same 10-degree decision as Google Earth Engine's own slope. But the radar area is sensitive to the slope near
  the shore: with Earth Engine's slope, Atro Sar summer areas drop about 3-4%. Whether 10 degrees is the right limit
  needs a surveyed shoreline we do not have (`logs/2026-11-09_slope_reference_check.log`).
- **"Are the tests real?"** We broke 35 lines in the new code on purpose; the tests caught all 35. The first time, 2
  slipped through, and we added tests for both (`logs/2026-11-09_mutation_check_new_modules_run1.log`).
- **"Is the 10% cloud limit calibrated?"** No, it is a judgement from one month of data; it is documented as such.
- **"Did the system run since 2023?"** No. Historical images were processed once by hand (the backfill) so the baseline has
  history; the automatic nightly schedule was set up on 8 November 2026. Before the defence, look up the date of the
  first run marked "schedule" in the Actions tab and say that date (on 8 November itself only manual runs had happened).
