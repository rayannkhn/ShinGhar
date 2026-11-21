"""ShinGhar alert layer: department briefing (English) + community messages (Urdu, Pashto), human in the loop.

  - Text comes from fixed templates filled ONLY with the risk result's numbers and reasons. (An optional Claude API
    path may be added later; when it is not configured, these templates are what is shown, and the page says so.)
  - Urdu and Pashto text is machine-written and must be checked by a native speaker before any use.
  - States: draft -> reviewed (an expert clicks "Reviewed by expert") -> ready. A "high" alert can never become
    ready without the review step. NOTHING IS EVER SENT: there is no sending code in this prototype.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

STATES = ("draft", "reviewed", "ready")
LANG_NOTE = "Machine-generated text, to be checked by a native speaker before any use."
EMERGENCY_NUMBER = "1122"   # Rescue 1122, Khyber Pakhtunkhwa emergency service

DEPARTMENTS = {
    "high": "PDMA Khyber Pakhtunkhwa, District Administration Swat, Forest Department (Swat circle)",
    "watch": "District Administration Swat, Forest Department (Swat circle)",
    "low": "Forest Department (Swat circle), for information",
}
ACTIONS_EN = {
    "high": ["Field-check the upstream lake outlet and the listed vegetation-loss sites within the week.",
             "Brief village elders and confirm a safe high-ground route; check that Rescue 1122 contact is known.",
             "Approve (or correct) the community message below before any use."],
    "watch": ["Add the listed vegetation-loss sites to the next ranger round.",
              "Re-check the lake after the next clear satellite pass."],
    "low": ["No action beyond routine monitoring."],
}

# Community messages. {village} is the village name in the message's own script.
COMMUNITY = {
    "ur": {
        "high": ("اطلاع برائے {village}: سیٹلائٹ کے جائزے میں آپ کے علاقے میں سیلاب اور لینڈ سلائیڈ کا خطرہ زیادہ پایا گیا ہے۔ "
                 "یہ پیشگوئی نہیں ہے۔ دریا اور نالوں کے کنارے سے دور رہیں، محفوظ اونچی جگہ کا راستہ معلوم رکھیں، "
                 "اور پی ڈی ایم اے اور ضلعی انتظامیہ کی ہدایات پر عمل کریں۔ ہنگامی صورت میں {num} پر رابطہ کریں۔"),
        "watch": ("اطلاع برائے {village}: سیٹلائٹ کے جائزے میں آپ کے علاقے میں سیلاب اور لینڈ سلائیڈ کا درمیانہ خطرہ پایا گیا ہے۔ "
                  "یہ پیشگوئی نہیں ہے۔ بارش اور نالوں کے پانی پر نظر رکھیں اور غیر معمولی تبدیلی کی اطلاع ضلعی انتظامیہ کو دیں۔ "
                  "ہنگامی صورت میں {num} پر رابطہ کریں۔"),
    },
    "ps": {
        "high": ("د {village} اوسېدونکو ته خبرتیا: د سپوږمکۍ په جاج کې ستاسو په سیمه کې د سیلاب او د ځمکې د ښوېدو خطر لوړ موندل شوی. "
                 "دا وړاندوینه نه ده. د سیند او خوړونو له غاړې لرې اوسئ، لوړ او خوندي ځای ته لاره وپېژنئ، "
                 "او د پي ډي ايم اې او ضلعي ادارې لارښوونې ومنئ. په بیړني حالت کې {num} ته زنګ ووهئ."),
        "watch": ("د {village} اوسېدونکو ته خبرتیا: د سپوږمکۍ په جاج کې ستاسو په سیمه کې د سیلاب او د ځمکې د ښوېدو منځنی خطر موندل شوی. "
                  "دا وړاندوینه نه ده. باران او د خوړونو اوبو ته پام کوئ او هر غیر معمولي بدلون ضلعي ادارې ته ووایاست. "
                  "په بیړني حالت کې {num} ته زنګ ووهئ."),
    },
}


# Per-village community messages: opening (band) + the village's own top reasons with their numbers + what to do.
# Lakes are unnamed locally, so the messages say "the glacial lake above" instead of our working names.
OPEN = {
    "ur": {"high": "اطلاع برائے {village}: سیٹلائٹ کے جائزے میں آپ کے علاقے میں سیلاب اور لینڈ سلائیڈ کا خطرہ زیادہ پایا گیا ہے۔",
           "watch": "اطلاع برائے {village}: سیٹلائٹ کے جائزے میں آپ کے علاقے میں سیلاب اور لینڈ سلائیڈ کا درمیانہ خطرہ پایا گیا ہے۔",
           "low": "اطلاع برائے {village}: سیٹلائٹ کے جائزے میں آپ کے علاقے میں سیلاب اور لینڈ سلائیڈ کا خطرہ کم پایا گیا ہے، لیکن یہ باتیں معلوم رہیں۔"},
    "ps": {"high": "د {village} اوسېدونکو ته خبرتیا: د سپوږمکۍ په جاج کې ستاسو په سیمه کې د سیلاب او د ځمکې د ښوېدو خطر لوړ موندل شوی.",
           "watch": "د {village} اوسېدونکو ته خبرتیا: د سپوږمکۍ په جاج کې ستاسو په سیمه کې د سیلاب او د ځمکې د ښوېدو منځنی خطر موندل شوی.",
           "low": "د {village} اوسېدونکو ته خبرتیا: د سپوږمکۍ په جاج کې ستاسو په سیمه کې د سیلاب او د ځمکې د ښوېدو خطر ټیټ موندل شوی، خو دا خبرې په یاد ولرئ."},
}
FACT = {
    "ur": {"flood_path": "آپ کا گاؤں اوپر کی گلیشیائی جھیل سے نکلنے والے پانی کے راستے پر، جھیل سے تقریباً {v} کلومیٹر نیچے ہے۔",
           "forest_loss_upslope": "آپ کے گاؤں سے {r} کلومیٹر کے اندر اوپر کی ڈھلوانوں پر 2019 سے 2025 تک {v} ہیکٹر سبزہ ختم ہوا ہے۔",
           "loss_slope": "یہ ڈھلوانیں تقریباً {v} درجے تک ڈھلوان ہیں، جہاں ننگی مٹی بارش میں پھسل سکتی ہے۔",
           "lake_growth": "اوپر کی گلیشیائی جھیل ہر سال تقریباً {v} فیصد بڑھ رہی ہے۔",
           "lake_anomaly": "اوپر کی گلیشیائی جھیل حالیہ سیٹلائٹ تصویر میں اپنے معمول سے بڑی تھی۔"},
    "ps": {"forest_loss_upslope": "ستاسو د کلي پورته د {r} کیلومترو دننه په غرونو له 2019 څخه تر 2025 پورې {v} هکتاره شنه ځمکه له منځه تللې.",
           "loss_slope": "دا غرونه شاوخوا {v} درجې ځوړ دي، چېرې چې لوڅه خاوره په باران کې ښوېدای شي.",
           "flood_path": "ستاسو کلی له پورته یخچالي جهیل څخه د راوتونکو اوبو په لاره کې، له جهیل څخه شاوخوا {v} کیلومتره ښکته پروت دی.",
           "lake_growth": "پورته یخچالي جهیل هر کال شاوخوا {v} سلنه لویږي.",
           "lake_anomaly": "پورته یخچالي جهیل په وروستي سپوږمکۍ انځور کې له خپل معمول څخه لوی و."},
}
NOT_FORECAST = {"ur": "یہ پیشگوئی نہیں ہے۔", "ps": "دا وړاندوینه نه ده."}
ACTION = {
    "ur": {"high": "دریا اور نالوں کے کنارے سے دور رہیں، محفوظ اونچی جگہ کا راستہ معلوم رکھیں، اور پی ڈی ایم اے اور ضلعی انتظامیہ کی ہدایات پر عمل کریں۔",
           "watch": "بارش اور نالوں کے پانی پر نظر رکھیں اور غیر معمولی تبدیلی کی اطلاع ضلعی انتظامیہ کو دیں۔"},
    "ps": {"high": "د سیند او خوړونو له غاړې لرې اوسئ، لوړ او خوندي ځای ته لاره وپېژنئ، او د پي ډي ايم اې او ضلعي ادارې لارښوونې ومنئ.",
           "watch": "باران او د خوړونو اوبو ته پام کوئ او هر غیر معمولي بدلون ضلعي ادارې ته ووایاست."},
}
CLOSE = {"ur": "ہنگامی صورت میں {num} پر رابطہ کریں۔", "ps": "په بیړني حالت کې {num} ته زنګ ووهئ."}
FACT_FORMAT = {"forest_loss_upslope": "{:.1f}", "loss_slope": "{:.0f}", "flood_path": "{:.0f}", "lake_growth": "{:.1f}",
               "lake_anomaly": "{:.1f}"}


def top_facts(components: list[dict], n: int = 2) -> list[tuple[str, float]]:
    """The village's n strongest score parts (most points first) that a community message can state: (name, raw value)."""
    ok = [c for c in components if c.get("points", 0) > 0 and c.get("raw") is not None and c["name"] in FACT["ur"]]
    ok.sort(key=lambda c: (-c["points"], -c["weight"]))
    chosen = sorted(ok[:n], key=lambda c: list(FACT["ur"]).index(c["name"]))   # read naturally: area before its slope
    return [(c["name"], float(c["raw"])) for c in chosen]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def briefing_en(village: str, district: str, score: float, band: str, coverage: float, reasons: list[str],
                as_of: str, example: bool = False) -> str:
    """Department briefing: what, where, why (the reasons, verbatim), what to do. Numbers only from the inputs."""
    lines = [
        *([f"EXAMPLE ONLY: {village} is {band.upper()}, so no alert is needed today. This shows how an alert would flow."]
          if example else []),
        f"SCREENING BRIEFING (not a forecast) - {village}, {district}",
        f"To: {DEPARTMENTS[band]}",
        f"Data: {as_of}",
        "",
        f"WHAT: Combined GLOF / landslide screening score {score:.1f}/100, band {band.upper()} "
        f"(data available for {coverage:.0%} of the score's weight).",
        f"WHERE: {village} and the slopes and lakes upstream of it.",
        "WHY:",
        *[f"  - {r}" for r in reasons],
        "WHAT TO DO:",
        *[f"  - {a}" for a in ACTIONS_EN[band]],
        "",
        "Source: ShinGhar prototype (Sentinel-2, Hansen Global Forest Change, Copernicus DEM). "
        "Hazard screening only; this briefing has not been sent to anyone.",
    ]
    return "\n".join(lines)


def community_message(lang: str, band: str, village_local: str, facts: list[tuple[str, float]] | None = None,
                      radius_km: float = 3, example: bool = False) -> str | None:
    """Short community message. With facts (top_facts of the village's score): opening + the village's own reasons
    with their numbers + what to do. Without facts: the older generic template. None for 'low' unless example."""
    if facts is None:
        tpl = COMMUNITY[lang].get(band)
        return tpl.format(village=village_local, num=EMERGENCY_NUMBER) if tpl else None
    if band == "low" and not example:
        return None
    parts = [OPEN[lang][band].format(village=village_local)]
    parts += [FACT[lang][name].format(v=FACT_FORMAT[name].format(value), r=f"{radius_km:.0f}") for name, value in facts]
    parts += [NOT_FORECAST[lang], ACTION[lang]["high" if band == "high" else "watch"], CLOSE[lang].format(num=EMERGENCY_NUMBER)]
    return " ".join(parts)


@dataclass
class Alert:
    alert_id: str
    village: str
    band: str
    score: float
    briefing_en: str
    message_ur: str | None
    message_ps: str | None
    text_source: str = "templates"          # "templates" or "claude-api"
    audio_ur: str | None = None             # MP3 path relative to the data dir, if generated
    audio_ps: str | None = None
    state: str = "draft"
    history: list[dict] = field(default_factory=list)
    sent: bool = False                      # always False: there is no sending code
    example: bool = False                   # True: drafted for a LOW village only to show the flow (labelled on screen)

    def as_dict(self) -> dict:
        return asdict(self)


class ReviewError(ValueError):
    pass


def mark_reviewed(alert: Alert, reviewer: str) -> Alert:
    if alert.state != "draft":
        raise ReviewError(f"alert {alert.alert_id} is '{alert.state}', only a draft can be reviewed")
    if not reviewer.strip():
        raise ReviewError("a reviewer name is required")
    alert.state = "reviewed"
    alert.history.append({"at": utc_now(), "event": "reviewed by expert", "by": reviewer.strip()})
    return alert


def mark_ready(alert: Alert) -> Alert:
    """draft -> ready is allowed only for non-high alerts; a high alert must be reviewed first."""
    if alert.state == "ready":
        raise ReviewError(f"alert {alert.alert_id} is already ready")
    if alert.band == "high" and alert.state != "reviewed":
        raise ReviewError("a HIGH alert needs 'Reviewed by expert' before it can be marked ready")
    alert.state = "ready"
    alert.history.append({"at": utc_now(), "event": "marked ready to send (not sent: prototype)"})
    return alert


def reset_to_draft(alert: Alert) -> Alert:
    """Demo helper: back to draft so the review flow can be shown again. The history keeps every step."""
    alert.state = "draft"
    alert.history.append({"at": utc_now(), "event": "reset to draft (demo)"})
    return alert


VOICES = {"ur": "ur-PK-AsadNeural", "ps": "ps-AF-GulNawazNeural"}   # Microsoft Edge neural voices via edge-tts


def synthesize(text: str, lang: str, out_path: str | Path) -> Path:
    """Text -> MP3 with edge-tts (needs internet). Written to a temp file first, renamed only when complete."""
    import asyncio

    import edge_tts

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    partial = out_path.with_name(out_path.name + ".partial")
    last: Exception | None = None
    for _ in range(3):                      # the service sometimes returns no audio; retry, never keep a partial file
        try:
            asyncio.run(edge_tts.Communicate(text, VOICES[lang]).save(str(partial)))
            if partial.stat().st_size < 1000:
                raise RuntimeError(f"edge-tts returned an implausibly small file for {lang}")
            partial.replace(out_path)
            return out_path
        except Exception as exc:  # noqa: BLE001 - retried, then re-raised
            last = exc
            partial.unlink(missing_ok=True)
    raise RuntimeError(f"edge-tts failed 3 times for {lang}: {last}") from last


class AlertStore:
    """Alerts kept in one JSON file so review state survives a restart (and the demo runs offline)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> dict[str, Alert]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {a["alert_id"]: Alert(**a) for a in raw}

    def save(self, alerts: dict[str, Alert]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([a.as_dict() for a in alerts.values()], ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)
