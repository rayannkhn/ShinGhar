"""Lake information for the lake page: published facts with their sources, and a plain-language reading of our own data.

FACTS holds only statements found in a cited source (searched 2026-11-18); each fact names its source keys. Where sources
disagree, or only one news report says it, the text says so. Nothing here is computed. Elevation and the "What our data
shows" sentences are computed from this system's own files (the stored Copernicus 30 m DEM and the database), never typed in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any

SOURCES: dict[str, tuple[str, str]] = {
    "wiki-krb": ("Wikipedia: Karambar Lake", "https://en.wikipedia.org/wiki/Karambar_Lake"),
    "kuhle": ("Kuhle (via SERC Carleton): glacier lake outburst cascades in the Hindukush",
              "https://serc.carleton.edu/31883"),
    "pamir-2018": ("Pamir Times, 19 Jul 2018: GLOF blocks Kurumbar river, forming a lake in Ishkoman valley",
                   "https://pamirtimes.net/2018/07/19/glof-blocks-kurumbar-river-forming-a-lake-in-ishkoman-valley/"),
    "dawn-2022": ("Dawn, 7 May 2022: KKH bridge swept away after Shisper lake outburst", "https://www.dawn.com/news/1688567"),
    "eco-shp": ("Eco-Business / The Third Pole: timely warnings avert loss of life from surging glacier in Pakistan",
                "https://www.eco-business.com/news/timely-warnings-avert-loss-of-life-from-surging-glacier-in-pakistan/"),
    "amin-2020": ("Amin et al. 2020, Meteorological Applications 27, e1877 (Darkut valley GLOF mapping)",
                  "https://doi.org/10.1002/met.1877"),
    "pmd-dkt": ("PMD: Application of remote sensing for temporal mapping of glacier and glacial lake (Darkut)",
                "https://www.pmd.gov.pk/rnd/rndweb/rnd_new/journal/vol13_issue26_files/1_Application_of_Remote_Sensing_for_Temporal_Mapping_of_Glacier_and_Glacial_Lake.pdf"),
    "tribune-2025": ("Express Tribune, 2025: NDMA issues GLOF alert for northern valleys",
                     "https://tribune.com.pk/story/2552659/flash-flood-threat-grows-in-north-as-ndma-issues-glof-alert"),
    "iqbal-2023": ("Iqbal et al. 2023, Proc. Pakistan Academy of Sciences A: GLOF monitoring and risk mapping, Hunza",
                   "https://ppaspk.org/index.php/PPAS-A/article/view/1457"),
    "wiki-brt": ("Wikipedia: Borith Lake", "https://en.wikipedia.org/wiki/Borith_Lake"),
    "pamir-2008": ("Pamir Times, 8 Apr 2008: another GLOF, this time in Ghulkin",
                   "https://pamirtimes.net/2008/04/08/another-glof-this-time-in-ghulkin/"),
    "richardson": ("Richardson & Quincey: the 2008 outburst floods from Ghulkin Glacier (BOKU)",
                   "https://boku.ac.at/fileadmin/data/H03000/H87000/H87200/4Veranstaltungen/4.5_Richardson.pdf"),
    "quincey": ("Quincey (BOKU): Passu glacier outburst, January 2008",
                "https://boku.ac.at/fileadmin/data/H03000/H87000/H87200/4Veranstaltungen/7.5_Quincey.pdf"),
    "icimod-hunza": ("ICIMOD: increasing risk of glacial lake outburst floods in Hunza river basin",
                     "https://www.icimod.org/increasing-risk-of-glacial-lake-outburst-floods-in-hunza-river-basin"),
    "icimod-trl": ("ICIMOD: reassessing Tsho Rolpa glacial lake", "https://www.icimod.org/reassessing-tsho-rolpa-glacial-lake/"),
    "wiki-trl": ("Wikipedia: Tsho Rolpa", "https://en.wikipedia.org/wiki/Tsho_Rolpa"),
    "diplomat-2016": ("The Diplomat, Dec 2016: draining a glacial lake in Nepal",
                      "https://thediplomat.com/2016/12/draining-a-glacial-lake-in-nepal"),
    "ktm-2026": ("Kathmandu Post, 6 Sep 2026: Nepal is draining four glacial lakes; scientists say it is not enough",
                 "https://kathmandupost.com/climate-environment/2026/09/06/nepal-is-draining-four-glacial-lakes-scientists-say-it-is-not-enough"),
    "morung-47": ("The Morung Express: 47 glacial lakes pose outburst threat (ICIMOD list)",
                  "https://morungexpress.com/47-glacial-lakes-pose-glacial-outburst-threat-across-nepals-major-river-corridors"),
    "annapurna-thu": ("The Annapurna Express: guarding Manang, reducing the risk from Thulagi Lake",
                      "https://www.theannapurnaexpress.com/story/67172/"),
    "rs-2018": ("Remote Sensing 10(5) 798, 2018 (Thulagi 2017 survey)", "https://doi.org/10.3390/rs10050798"),
}


@dataclass
class Fact:
    text: str
    sources: tuple[str, ...]


@dataclass
class LakeFacts:
    place: str
    kind: str
    about: list[Fact]
    history: list[Fact]
    gaps: str = ""                       # what we looked for and could not find


FACTS: dict[str, LakeFacts] = {
    "KRB": LakeFacts(
        place="Ishkoman valley, Ghizer district, Gilgit-Baltistan, Pakistan",
        kind="High-altitude glacial lake",
        about=[Fact("Listed at about 4,272 m. Some WWF studies place it in the Broghil valley of Chitral instead, so its "
                    "administrative location is not settled in the sources.", ("wiki-krb",))],
        history=[
            Fact("The Karambar valley had at least six damaging glacial floods in the 19th and 20th centuries "
                 "(sources give 1844, 1861, 1865, 1893, 1895 and 1905). They were long blamed on the Karambar glacier; "
                 "later work points to several lakes draining almost together.", ("kuhle",)),
            Fact("July 2018: an outburst flood from the Badswat side valley blocked the Karambar (Kurumbar) river and "
                 "formed a temporary lake. This was a different source, downstream of this lake.", ("pamir-2018",)),
        ],
        gaps="No published outburst of this lake itself, and no recent hazard rating, was found."),
    "ATS": LakeFacts(
        place="Ishkoman area, Ghizer district, Gilgit-Baltistan, Pakistan (from its coordinates)",
        kind="Glacial lake (from satellite images)",
        about=[],
        history=[],
        gaps="No published source was found under the name \"Atro Sar\". It is one of the project's two original "
             "reference lakes; everything shown for it comes from this system's own measurements."),
    "SHP": LakeFacts(
        place="Hassanabad, Hunza, Gilgit-Baltistan, Pakistan",
        kind="Ice-dammed lake (formed when the surging Shishper glacier blocked a stream)",
        about=[Fact("The Shishper glacier began to surge in May 2018 and blocked the stream from the Muchuhur glacier, "
                    "which formed the lake. An early-warning set-up and continuous monitoring began in 2020.", ("eco-shp",))],
        history=[
            Fact("2019: two major outbursts are reported.", ("eco-shp",)),
            Fact("7 May 2022: an outburst swept away the Hassanabad bridge on the Karakoram Highway and damaged houses, "
                 "farmland and two hydropower projects. Warnings went out beforehand and no one died. Reported peak flows "
                 "differ between outlets (about 5,000 to 8,000 cusecs).", ("dawn-2022", "eco-shp")),
        ],
        gaps="Reports of a 2025 outburst could not be confirmed; our 2025 images show a dry basin."),
    "DKT": LakeFacts(
        place="Darkut village, Yasin valley, Ghizer district, Gilgit-Baltistan, Pakistan",
        kind="Proglacial lake at the tongue of the Darkut glacier (locally Ghamu Bar)",
        about=[Fact("Mapped from 1991 to 2015 with flood modelling of the downstream valley; the lake grew from about "
                    "4.5 to 15.4 ha.", ("amin-2020",)),
               Fact("A PMD study found continuous growth from 1988 to 2015, faster after 2000.", ("pmd-dkt",))],
        history=[Fact("June 2025: Pakistan's NDMA named Darkut among valleys at higher outburst risk during a heat and "
                      "monsoon alert.", ("tribune-2025",))],
        gaps="No dated outburst of this lake was found."),
    "BRT": LakeFacts(
        place="Gojal, upper Hunza, Gilgit-Baltistan, Pakistan, beside the Ghulkin glacier",
        kind="Lake near the Ghulkin and Passu glaciers",
        about=[Fact("Lies beside the Ghulkin glacier; the walking route to the Passu glacier crosses both.", ("wiki-brt",)),
               Fact("Named, with Passu, as one of the area's main lakes to watch for outburst floods.", ("iqbal-2023",))],
        history=[Fact("2008: the neighbouring Ghulkin glacier released several outburst floods (April to June) that "
                      "reached Ghulkin village and the Karakoram Highway. They came from the glacier, not from Borith Lake. "
                      "Sources differ on the exact dates.", ("pamir-2008", "richardson"))],
        gaps="No outburst of Borith Lake itself was found."),
    "PSU": LakeFacts(
        place="Passu, upper Hunza, Gilgit-Baltistan, Pakistan",
        kind="Proglacial lake at the Passu glacier snout",
        about=[Fact("Named, with Borith, as one of the area's main lakes to watch for outburst floods.", ("iqbal-2023",))],
        history=[Fact("6 January 2008: an outburst from the Passu glacier flooded about 2 km of a side stream towards "
                      "the Hunza river.", ("quincey", "icimod-hunza"))],
        gaps="Its water is silty grey, which our optical water test does not see; radar measures it instead."),
    "TRL": LakeFacts(
        place="Rolwaling valley, Dolakha district, Nepal",
        kind="Moraine-dammed lake on the Trakarding glacier",
        about=[Fact("Published area about 1.55 km² (1999) to about 1.6 km² (ICIMOD).", ("wiki-trl", "icimod-trl")),
               Fact("Calving of the glacier front into the lake is growing, and experts say the hazard assessments are "
                    "out of date.", ("ktm-2026",))],
        history=[Fact("1999-2000: an open channel was cut through the end moraine, lowering the lake by 3 m and the water "
                      "that could escape by about 20%. Up to 20 m was planned, but the budget stopped it at 3 m.",
                      ("diplomat-2016", "ktm-2026"))],
        gaps="No outburst of this lake has happened; it is watched because of its size and dam."),
    "THU": LakeFacts(
        place="Below Manaslu, Gorkha/Lamjung, Nepal; drains to the Dona Khola and the Marsyangdi river",
        kind="Moraine-dammed lake with an ice-cored moraine dam",
        about=[Fact("Published area 0.94 km² (2009) and 0.89 km² (October 2017 survey).", ("morung-47", "rs-2018")),
               Fact("On ICIMOD's 2020 list of 47 potentially dangerous lakes in and around Nepal, and rated in the highest "
                    "class. Modelled dam breaches give peak flows of about 1,400 to 5,400 m³/s; these are scenarios, not "
                    "forecasts.", ("morung-47", "annapurna-thu")),
               Fact("Downstream are four Marsyangdi hydropower projects and towns such as Besisahar. A lowering project is "
                    "being prepared, but no warning system covers this lake yet.", ("annapurna-thu", "ktm-2026"))],
        history=[],
        gaps="No outburst of this lake has happened."),
}

# A radar orbit pass whose median differs from the optical median by more than this is called out.
RADAR_PASS_LIMIT = 0.20
MIN_YEAR_IMAGES = 2
MIN_OPTICAL_FOR_RADAR_CHECK = 10   # fewer clear photos than this are no reference for radar


@dataclass
class Reading:
    tone: str        # ok, warn, muted
    text: str


@dataclass
class LakeInfo:
    facts: LakeFacts | None
    sources: list[tuple[str, str, str]]          # (key, label, url), in first-cited order
    elevation_m: float | None
    first_image: str | None                      # date of the oldest stored image (YYYY-MM-DD)
    readings: list[Reading] = field(default_factory=list)


def centre_elevation(dem_path: Path, lon: float, lat: float) -> float | None:
    """Height of the lake centre from the stored Copernicus 30 m DEM, or None if the file is missing."""
    if not dem_path.is_file():
        return None
    import rasterio
    from rasterio.warp import transform
    with rasterio.open(dem_path) as src:
        xs, ys = transform("EPSG:4326", src.crs, [lon], [lat])
        row, col = src.index(xs[0], ys[0])
        data = src.read(1)
        if not (0 <= row < data.shape[0] and 0 <= col < data.shape[1]):
            return None
        return float(data[row, col])


def _score_words(score: dict | None) -> Reading | None:
    if score is None:
        return None
    month = score["acquired_at"][:7]
    if score["status"] != "ok" or score["deviation_score"] is None:
        return Reading("muted", f"The latest clear photo ({month}) has no score yet: there are not enough earlier "
                                "clear photos from the same month to compare it with.")
    z = score["deviation_score"]
    side = "larger" if z > 0 else "smaller"
    if abs(z) < 1:
        return Reading("ok", f"The latest clear photo ({month}) is within the usual range for that month "
                             f"(score {z:+.2f}).")
    if abs(z) < 2:
        return Reading("ok", f"The latest clear photo ({month}) is a little {side} than usual for that month "
                             f"(score {z:+.2f}); this is common and not, by itself, a concern.")
    return Reading("warn", f"The latest clear photo ({month}) is clearly {side} than usual for that month "
                           f"(score {z:+.2f}, two or more spreads from normal). This is a statistical flag for a "
                           "person to check, not a danger level.")


def read_our_data(history: list[dict[str, Any]], latest_score: dict | None, latest_judged: dict | None) -> list[Reading]:
    """Plain-language sentences computed from the stored history (lake_history rows, oldest first)."""
    out: list[Reading] = []
    optical = [r for r in history if r["sensor"] == "optical" or r["source"] == "sentinel-2"]
    ok = [r for r in optical if r["measurement_status"] == "ok" and r["extent_ha"] is not None]
    if not optical:
        return [Reading("muted", "No images are stored for this lake yet.")]

    share = len(ok) / len(optical) * 100
    out.append(Reading("ok" if len(ok) >= 20 else "warn",
                       f"{len(ok)} of {len(optical)} satellite photos since {optical[0]['acquired_at'][:4]} were clear "
                       f"enough to measure ({share:.0f}%); the rest had cloud, snow or ice over the lake."
                       + ("" if len(ok) >= 20 else " That is thin, so treat the trend below with care.")))

    if latest_judged is not None and latest_judged.get("status") == "no_lake_detected":
        out.append(Reading("warn", f"The latest clear photo ({latest_judged['acquired_at'][:10]}) shows no water "
                                   "at the lake centre: the lake appears to have drained."))

    by_year: dict[str, list[float]] = {}
    for r in ok:
        by_year.setdefault(r["acquired_at"][:4], []).append(r["extent_ha"])
    years = [y for y in sorted(by_year) if len(by_year[y]) >= MIN_YEAR_IMAGES]
    if len(years) >= 2:
        first, last = years[0], years[-1]
        a, b = median(by_year[first]), median(by_year[last])
        change = (b - a) / a * 100
        if abs(change) < 3:
            out.append(Reading("ok", f"Its size has been steady: about {a:.1f} ha in {first} and {b:.1f} ha in {last} "
                                     f"({change:+.1f}%, median of the clear photos each year)."))
        else:
            verb = "grown" if change > 0 else "shrunk"
            out.append(Reading("warn" if abs(change) >= 10 else "ok",
                               f"It has {verb}: about {a:.1f} ha in {first} to {b:.1f} ha in {last} ({change:+.1f}%, "
                               "median of the clear photos each year)."))
    elif ok:
        out.append(Reading("muted", "Too few clear photos per year to describe a trend."))

    drained = latest_judged is not None and latest_judged.get("status") == "no_lake_detected"
    score = None if drained else _score_words(latest_score)   # an older score would read as the latest
    if score:
        out.append(score)

    radar = [r for r in history if r["source"] == "sentinel-1" and r["measurement_status"] == "ok" and r["extent_ha"]]
    if len(ok) < MIN_OPTICAL_FOR_RADAR_CHECK:
        if radar:
            out.append(Reading("muted", f"{len(radar)} radar images were measured, but there are too few clear photos to "
                                        "check them against. Radar is not used for the risk score."))
    elif radar:
        ref = median(r["extent_ha"] for r in ok)
        by_pass: dict[str, list[float]] = {}
        for r in radar:
            by_pass.setdefault(r["acquired_at"][11:13], []).append(r["extent_ha"])
        off = [(hour, (median(a) - ref) / ref, len(a)) for hour, a in sorted(by_pass.items()) if len(a) >= 10]
        bad = [(h, d, n) for h, d, n in off if abs(d) > RADAR_PASS_LIMIT]
        good = [h for h, d, n in off if abs(d) <= RADAR_PASS_LIMIT]
        if bad:
            parts = "; ".join(f"~{h}:00 UTC orbit {abs(d) * 100:.0f}% {'low' if d < 0 else 'high'} ({n} images)"
                              for h, d, n in bad)
            tail = (f" The ~{', ~'.join(good)}:00 UTC orbit agrees within {RADAR_PASS_LIMIT * 100:.0f}%." if good else "")
            out.append(Reading("warn", f"Radar disagrees with the clear photos here: {parts}.{tail} Steep valley sides "
                                       "can hide part of a lake from one viewing direction. Radar is not used for the risk score."))
        elif off:
            out.append(Reading("ok", f"Radar agrees with the clear photos to within {RADAR_PASS_LIMIT * 100:.0f}% "
                                     f"on every orbit ({sum(n for _, _, n in off)} images)."))
    return out


def build(lake: dict[str, Any], history: list[dict[str, Any]], latest_score: dict | None,
          latest_judged: dict | None, dem_dir: Path) -> LakeInfo:
    facts = FACTS.get(lake["code"])
    keys: list[str] = []
    if facts:
        for fact in facts.about + facts.history:
            for k in fact.sources:
                if k not in keys:
                    keys.append(k)
    return LakeInfo(
        facts=facts,
        sources=[(k, *SOURCES[k]) for k in keys],
        elevation_m=centre_elevation(dem_dir / f"{lake['code']}_dem.tif", lake["centre_lon"], lake["centre_lat"]),
        first_image=history[0]["acquired_at"][:10] if history else None,
        readings=read_our_data(history, latest_score, latest_judged),
    )
