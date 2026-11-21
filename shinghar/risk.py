"""ShinGhar risk fusion: a transparent 0-100 screening score per settlement. No model training.

Hazard SCREENING, not forecasting: the score ranks where to look first; it is not a probability of a flood.

score = sum over components of  weight x component (each component 0..1 on a FIXED, stated scale)

A component with no data contributes 0 and is listed as "missing" (it is never filled in with a guess); the
result also says how much of the total weight had data ("coverage"), so a low score with low coverage reads as
"we don't know", not "safe".
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Weights (sum to 1). Judgement calls, shown on screen.
WEIGHTS = {
    "lake_growth": 0.25,         # upstream lake area growth, %/yr (summer median trend)
    "lake_anomaly": 0.15,        # latest seasonal z-score of an upstream lake (only "bigger than usual" counts)
    "flood_path": 0.20,          # village ON an upstream lake's downhill path: how far down that path it is (km)
    "forest_loss_upslope": 0.25, # tree cover loss (ha) within FOREST_RADIUS_M and above the village
    "loss_slope": 0.15,          # mean slope of that loss (steeper = more runoff / landslide potential)
}
# Fixed scales: (value giving 0, value giving 1); linear in between, clipped.
SCALES = {
    "lake_growth": (0.0, 10.0),            # %/yr
    "lake_anomaly": (0.0, 3.0),            # z-score
    "flood_path": (50.0, 5.0),             # km along the path from the lake: 1 at <= 5 km, 0 at >= 50 km (reversed)
    "forest_loss_upslope": (0.0, 20.0),    # ha
    "loss_slope": (15.0, 35.0),            # degrees
}
# Per forest site (the brief: "per settlement (and per forest site)"): how much a loss site could matter for people
# below it. Same fuse(), same bands; its own components.
SITE_WEIGHTS = {
    "site_area": 0.30,           # size of the loss patch, ha
    "loss_slope": 0.30,          # its mean slope
    "village_below": 0.30,       # distance to the nearest listed village LOWER than the site
    "near_water": 0.10,          # distance to mapped surface water (soil and debris can reach a stream)
}
SCALES.update({
    "site_area": (0.0, 10.0),              # ha
    "village_below": (5_000.0, 250.0),     # metres, reversed: 1 at <= 250 m, 0 at >= 5 km
    "near_water": (1_000.0, 50.0),         # metres, reversed
})
UNITS = {"lake_growth": "%/yr", "lake_anomaly": "z", "flood_path": "km", "forest_loss_upslope": "ha", "loss_slope": "°",
         "site_area": "ha", "village_below": "m", "near_water": "m"}
FOREST_RADIUS_M = 3000.0
BANDS = ((60.0, "high"), (30.0, "watch"), (0.0, "low"))   # score >= 60 high, >= 30 watch, else low
FAST_EXPANSION_PCT_PER_YR = 5.0                            # the glacier-layer "fast expansion" flag


def scale(name: str, value: float | None) -> float | None:
    """Map a raw value onto 0..1 with the component's fixed scale; None stays None."""
    if value is None:
        return None
    lo, hi = SCALES[name]
    t = (value - lo) / (hi - lo)
    return max(0.0, min(1.0, t))


def band(score: float) -> str:
    for threshold, name in BANDS:
        if score >= threshold:
            return name
    return "low"


@dataclass
class Component:
    name: str
    raw: float | None
    scaled: float | None
    weight: float
    points: float              # weight x scaled x 100 (0 when missing)
    detail: str = ""           # e.g. which lake / how many patches
    not_applicable: bool = False   # known not to apply (e.g. no monitored lake upstream): 0 points, NOT missing data


@dataclass
class RiskResult:
    target: str
    score: float
    band: str
    coverage: float            # share of total weight with data, 0..1
    components: list[Component]
    reasons: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    not_applicable: list[str] = field(default_factory=list)


def fuse(target: str, raw: dict[str, float | None], details: dict[str, str] | None = None,
         weights: dict[str, float] = WEIGHTS, not_applicable: dict[str, str] | None = None) -> RiskResult:
    """Weighted sum of the scaled components. raw maps component name -> raw value (None = no data).

    not_applicable maps component name -> why it does not apply (e.g. "no monitored lake upstream"). Such a component
    adds 0 points but counts as KNOWN for coverage; it is different from missing data, and the reasons say which is which.
    """
    details = details or {}
    na = not_applicable or {}
    comps: list[Component] = []
    for name, w in weights.items():
        if name in na:
            comps.append(Component(name, None, None, w, 0.0, na[name], not_applicable=True))
            continue
        s = scale(name, raw.get(name))
        comps.append(Component(name, raw.get(name), s, w, 0.0 if s is None else round(100.0 * w * s, 1),
                               details.get(name, "")))
    score = round(sum(c.points for c in comps), 1)
    coverage = round(sum(c.weight for c in comps if c.scaled is not None or c.not_applicable) / sum(weights.values()), 2)
    result = RiskResult(target, score, band(score), coverage, comps,
                        missing=[c.name for c in comps if c.scaled is None and not c.not_applicable],
                        not_applicable=[c.name for c in comps if c.not_applicable])
    result.reasons = reasons(result)
    return result


def _fmt(name: str, v: float) -> str:
    if name in ("village_below", "near_water"):
        return f"{v / 1000:.1f} km" if v >= 1000 else f"{v:.0f} m"
    if name == "flood_path":
        return f"{v:.0f} km"
    if name == "lake_anomaly":
        return f"{v:+.2f}"
    if name == "lake_growth":
        return f"{v:+.1f} %/yr"
    if name == "loss_slope":
        return f"{v:.0f}°"
    return f"{v:.1f} ha"


_TEMPLATES = {
    "lake_growth": "Upstream glacial lake {detail}is growing by {value} (summer median trend){flag}.",
    "lake_anomaly": "Latest clear-sky area of {detail}is {value} standard deviations from its usual size for that month.",
    "flood_path": "The village is on the downhill path of water from {detail_plain}, {value} below the lake "
                  "(closer means more points: full at 5 km, none beyond 50 km).",
    "forest_loss_upslope": "{value} of vegetation loss in forest areas {detail}within {r:.0f} km upslope of the village "
                           "(satellite, 2019-2025; cause not known).",
    "site_area": "{value} of vegetation lost in this patch{detail_paren}.",
    "village_below": "The nearest village below the site, {detail_plain}, is {value} away.",
    "near_water": "Mapped surface water is {value} away, so loose soil and debris can reach a stream.",
    "loss_slope": "The vegetation loss {detail}is on steep ground (mean slope {value}), where bare soil sheds water and can slide.",
}


def reasons(result: RiskResult, max_reasons: int = 3) -> list[str]:
    """2-3 plain-language reasons from the numbers: the components that added the most points (ties: weight).
    Components with no data are mentioned once at the end if any are missing."""
    ranked = sorted((c for c in result.components if c.scaled is not None and c.points > 0),
                    key=lambda c: (-c.points, -c.weight))
    out = []
    for c in ranked[:max_reasons]:
        flag = f", above the {FAST_EXPANSION_PCT_PER_YR:.0f} %/yr fast-expansion flag" \
            if c.name == "lake_growth" and c.raw is not None and c.raw > FAST_EXPANSION_PCT_PER_YR else ""
        detail = (c.detail + " ") if c.detail else ""
        out.append(_TEMPLATES[c.name].format(value=_fmt(c.name, c.raw), detail=detail, detail_plain=c.detail, flag=flag,
                                             detail_paren=f" ({c.detail})" if c.detail else "",
                                             r=FOREST_RADIUS_M / 1000) + f" (+{c.points:.0f} points)")
    if not out:
        out.append("None of the measured factors adds to the score at the moment.")
    if result.not_applicable:
        groups: dict[str, list[str]] = {}
        for c in result.components:
            if c.not_applicable:
                groups.setdefault(c.detail, []).append(c.name.replace("_", " "))
        out.append("Does not apply: " + "; ".join(f"{', '.join(names)} ({why})" for why, names in groups.items()) + ".")
    if result.missing:
        out.append("No data for: " + ", ".join(m.replace("_", " ") for m in result.missing)
                   + f" (score covers {result.coverage:.0%} of the weight).")
    return out
