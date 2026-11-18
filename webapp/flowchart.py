"""The dashboard's flowchart of one check, step by step (the same steps the Live check page shows).

Drawn as inline SVG from STEPS below; colours come from style.css classes, so it follows the page's theme.
Main path, left to right in two rows, then the three side branches the code really takes:
  no new image   -> the newest stored image is replayed through steps 3-9, nothing saved (webapp/walkthrough.py)
  too cloudy     -> recorded only, not downloaded (sailab/pipeline.py, _process_scene)
  radar          -> no cloud check (radar sees through cloud); measured but not risk-scored (SCORE_RADAR = False)
"""
from __future__ import annotations

from html import escape

# (number, title, one-line detail). Kept short on purpose: the Live check page holds the full explanation.
STEPS = [
    (1, "Sign in", "Google Earth Engine"),
    (2, "Search", "optical + radar"),
    (3, "Verify source", "same image at ESA"),
    (4, "Cloud check", "≤ 10% over the lake"),
    (5, "Download", "window + fingerprint"),
    (6, "Detect water", "NDWI · slope + Otsu"),
    (7, "Grow the lake", "from the centre pixel"),
    (8, "Area", "pixels × 100 m² → ha"),
    (9, "Risk score", "vs earlier same month"),
    (10, "Save", "database + run log"),
]

W, BOX_W, BOX_H, GAP_X = 1080, 184, 70, 38
ROW_Y = (24, 172)


def _box(x: float, y: float, n: int, title: str, detail: str) -> str:
    return (f'<g class="fc-step"><rect x="{x}" y="{y}" width="{BOX_W}" height="{BOX_H}" rx="10"/>'
            f'<circle cx="{x + 20}" cy="{y + 22}" r="12" class="fc-num"/>'
            f'<text x="{x + 20}" y="{y + 26.5}" text-anchor="middle" class="fc-num-t">{n}</text>'
            f'<text x="{x + 40}" y="{y + 27}" class="fc-title">{escape(title)}</text>'
            f'<text x="{x + 14}" y="{y + 50}" class="fc-detail">{escape(detail)}</text></g>')


def _arrow(x1: float, y1: float, x2: float, y2: float, cls: str = "fc-arrow") -> str:
    return f'<path d="M{x1},{y1} L{x2},{y2}" class="{cls}" marker-end="url(#fc-head)"/>'


def svg() -> str:
    parts = ['<svg viewBox="0 0 1080 272" class="flowchart" role="img" '
             'aria-label="Flowchart of one check: sign in, search, verify source, cloud check, download, detect water, '
             'grow the lake, area, risk score, save">',
             '<defs><marker id="fc-head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
             'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="fc-head"/></marker></defs>']
    pos = {}
    for i, (n, title, detail) in enumerate(STEPS):
        row, col = divmod(i, 5)
        x, y = 10 + col * (BOX_W + GAP_X), ROW_Y[row]
        pos[n] = (x, y)
        parts.append(_box(x, y, n, title, detail))
    for n in range(1, 10):
        (x1, y1), (x2, y2) = pos[n], pos[n + 1]
        if n == 5:   # end of the first row: down and back to the start of the second
            parts.append(f'<path d="M{x1 + BOX_W / 2},{y1 + BOX_H} V{y1 + BOX_H + 52} H{x2 + BOX_W / 2} V{y2 - 4}" '
                         f'class="fc-arrow" fill="none" marker-end="url(#fc-head)"/>')
        else:
            parts.append(_arrow(x1 + BOX_W, y1 + BOX_H / 2, x2 - 3, y2 + BOX_H / 2))

    # Branches the code really takes.
    x2, y2 = pos[2]
    parts.append(f'<path d="M{x2 + BOX_W / 2},{y2 + BOX_H} V{y2 + BOX_H + 18}" class="fc-branch"/>'
                 f'<text x="{x2 + BOX_W / 2 + 6}" y="{y2 + BOX_H + 16}" class="fc-note fc-replay">no new image → replay newest stored one (steps 3–9, nothing saved)</text>')
    x4, y4 = pos[4]
    parts.append(f'<text x="{x4 + BOX_W / 2}" y="{y4 - 6}" text-anchor="middle" class="fc-note fc-stop">&gt; 10% → recorded only · radar skips this</text>')
    for n, text, cls in ((9, "radar: measured, not scored", "fc-muted"),):
        x, y = pos[n]
        parts.append(f'<text x="{x + BOX_W / 2}" y="{y + BOX_H + 20}" text-anchor="middle" class="fc-note {cls}">{escape(text)}</text>')
    x6, y6 = pos[6]
    parts.append(f'<text x="{x6 + BOX_W / 2}" y="{y6 + BOX_H + 20}" text-anchor="middle" class="fc-note fc-muted">optical: NDWI · radar: Otsu</text>')
    parts.append("</svg>")
    return "".join(parts)
