"""Our stored Nepal lake areas against published survey figures, from sailab_glof.db (read-only).

Optical: every stored 'ok' Sentinel-2 measurement, per year. Radar: every stored 'ok' Sentinel-1 measurement, split by
pass time (about 00 UTC and about 12 UTC are different orbits, so different viewing geometry over steep valleys).
Published figures (sources in README.md): Tsho Rolpa about 1.55-1.6 km2 (ICIMOD; 1999 survey 1.55 km2); Thulagi
0.94 km2 (ICIMOD 2009) and 0.89 km2 (2017 bathymetric survey, Remote Sensing 10(5) 798).
Usage: .venv/bin/python logs/2026-11-18_nepal_lake_candidates/compare_published.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from statistics import median

REPO = Path(__file__).resolve().parents[2]
PUBLISHED_HA = {"TRL": (155.0, 160.0), "THU": (89.0, 94.0)}


def main() -> None:
    conn = sqlite3.connect(f"file:{REPO / 'sailab_glof.db'}?mode=ro", uri=True)
    for code, (lo, hi) in PUBLISHED_HA.items():
        name = conn.execute("SELECT name FROM lake WHERE code = ?", (code,)).fetchone()[0]
        print(f"\n{code} {name}: published {lo:.0f}-{hi:.0f} ha")
        rows = conn.execute("""SELECT s.source, s.acquired_at, m.status, m.extent_ha FROM scene s
                               JOIN measurement m ON m.scene_id = s.id JOIN lake l ON l.id = s.lake_id
                               WHERE l.code = ? ORDER BY s.acquired_at""", (code,)).fetchall()
        for source in ("sentinel-2", "sentinel-1"):
            got = [r for r in rows if r[0] == source]
            ok = [r for r in got if r[2] == "ok"]
            print(f"  {source}: {len(got)} images stored, {len(ok)} measured, {len(got) - len(ok)} refused by the checks")
            if not ok:
                continue
            if source == "sentinel-2":
                med = median(r[3] for r in ok)
                print(f"    median {med:.1f} ha, range {min(r[3] for r in ok):.1f}-{max(r[3] for r in ok):.1f}; "
                      f"vs published: {(med - hi) / hi * 100:+.1f}% to {(med - lo) / lo * 100:+.1f}%")
                for year in sorted({r[1][:4] for r in ok}):
                    a = [r[3] for r in ok if r[1][:4] == year]
                    print(f"    {year}: {len(a):3d} images, median {median(a):6.1f} ha")
            else:
                for hour in sorted({r[1][11:13] for r in ok}):
                    a = [r[3] for r in ok if r[1][11:13] == hour]
                    near = sum(1 for x in a if x >= 0.8 * lo)
                    print(f"    pass ~{hour} UTC: {len(a):3d} images, median {median(a):6.1f} ha, "
                          f"{near} of {len(a)} ({near / len(a) * 100:.0f}%) within 20% of the published low figure or above")


if __name__ == "__main__":
    main()
