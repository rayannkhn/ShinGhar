"""ShinGhar glacier layer: lake area trend and the "fast expansion" flag, from the SailAb pipeline's own measurements.

Method (stated on screen):
  1. Take every usable OPTICAL area ('ok' status; radar is not used, as in the SailAb risk score) from summer months
     SUMMER_MONTHS (Jul-Sep: lakes are ice-free and the pipeline's snow check passes most often).
  2. Per year with at least MIN_VALUES_PER_YEAR values: the median area (robust to the occasional partial detection).
  3. Trend: ordinary least-squares slope of the yearly medians against the year (ha/yr), needs MIN_YEARS years.
     Growth %/yr = slope / mean of the yearly medians x 100.
  4. Flag "fast expansion" when growth > FAST_EXPANSION_PCT_PER_YR.
Missing data is reported as missing, never as 0 % growth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import median

from shinghar.risk import FAST_EXPANSION_PCT_PER_YR

SUMMER_MONTHS = (7, 8, 9)
MIN_VALUES_PER_YEAR = 2
MIN_YEARS = 3


@dataclass
class Trend:
    yearly: list[dict] = field(default_factory=list)   # [{"year", "median_ha", "n"}], years that qualify
    skipped_years: list[dict] = field(default_factory=list)  # [{"year", "n"}] with too few values
    slope_ha_per_yr: float | None = None
    growth_pct_per_yr: float | None = None
    fast_expansion: bool | None = None                 # None = not enough data to say
    first_ha: float | None = None
    last_ha: float | None = None
    note: str = ""


def summer_trend(values: list[tuple[date, float]]) -> Trend:
    """values: (observed date, area ha) of usable optical measurements, any order."""
    by_year: dict[int, list[float]] = {}
    for d, ha in values:
        if d.month in SUMMER_MONTHS and ha is not None:
            by_year.setdefault(d.year, []).append(ha)
    t = Trend()
    for y in sorted(by_year):
        n = len(by_year[y])
        if n >= MIN_VALUES_PER_YEAR:
            t.yearly.append({"year": y, "median_ha": round(median(by_year[y]), 2), "n": n})
        else:
            t.skipped_years.append({"year": y, "n": n})
    if len(t.yearly) < MIN_YEARS:
        t.note = (f"Not enough summer data: {len(t.yearly)} year(s) with at least {MIN_VALUES_PER_YEAR} clear summer "
                  f"values, {MIN_YEARS} needed.")
        return t
    xs = [r["year"] for r in t.yearly]
    ys = [r["median_ha"] for r in t.yearly]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    t.slope_ha_per_yr = round(slope, 3)
    t.growth_pct_per_yr = round(100.0 * slope / my, 2) if my else None
    t.fast_expansion = None if t.growth_pct_per_yr is None else t.growth_pct_per_yr > FAST_EXPANSION_PCT_PER_YR
    t.first_ha, t.last_ha = ys[0], ys[-1]
    t.note = (f"{len(t.yearly)} summers ({xs[0]}-{xs[-1]}), median {ys[0]:.1f} -> {ys[-1]:.1f} ha; "
              f"trend {t.slope_ha_per_yr:+.2f} ha/yr = {t.growth_pct_per_yr:+.1f} %/yr "
              f"({'above' if t.fast_expansion else 'not above'} the {FAST_EXPANSION_PCT_PER_YR:.0f} %/yr flag).")
    return t


def lake_values(conn, lake_id: int) -> list[tuple[date, float]]:
    """Usable optical areas of one lake from the SailAb database (same rows the SailAb risk score uses)."""
    rows = conn.execute(
        "SELECT s.acquired_at, m.extent_ha FROM measurement m JOIN scene s ON s.id = m.scene_id "
        "WHERE m.lake_id = ? AND m.status = 'ok' AND m.sensor = 'optical' ORDER BY s.acquired_at", (lake_id,)).fetchall()
    return [(date.fromisoformat(r[0][:10]), r[1]) for r in rows]


def latest_anomaly(conn, lake_id: int) -> dict | None:
    """The newest SailAb seasonal z-score for the lake ('ok' optical risk score), or None if there is none."""
    r = conn.execute(
        "SELECT r.deviation_score, r.baseline_ha, s.acquired_at, m.extent_ha FROM risk_score r "
        "JOIN measurement m ON m.id = r.measurement_id JOIN scene s ON s.id = m.scene_id "
        "WHERE r.lake_id = ? AND r.status = 'ok' AND m.sensor = 'optical' ORDER BY s.acquired_at DESC LIMIT 1",
        (lake_id,)).fetchone()
    if r is None:
        return None
    return {"z": r[0], "baseline_ha": r[1], "date": r[2][:10], "extent_ha": r[3]}
