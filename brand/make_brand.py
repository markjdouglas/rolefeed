"""
Generate RoleFeed's brand marks as pixel-grid SVG.

Everything is drawn on an integer grid and emitted as <rect> runs. The marks stay crisp
at any size, need no image files or network requests, and the palette is editable here
rather than by redrawing.

Conventions borrowed from early-2000s isometric pixel art (Habbo being the reference
point):
  - Outline is a dark version of the local colour, not pure black. Black outlines look
    stamped on; a dark local tone looks lit.
  - Three tones per colour at most: base, shade, highlight. No gradients, no
    anti-aliasing, no dithering.
  - Chunky silhouette first. Detail is suggested, never drawn — if a feature needs more
    than a few pixels it gets cut.
  - No fiddly props. The first version of this goose carried an attaché case, which
    read as an unidentifiable grey box. A prop that needs explaining has failed.

Art deco enters through geometry rather than ornament: stepped ziggurat forms, a
stepped portal, thick verticals against thin horizontals, cream and gold on indigo.
"""

from __future__ import annotations

import pathlib

PAL = {
    ".": None,
    "O": "#2a2250",     # outline: dark indigo, a shade of the background not black
    "K": "#1a1533",     # deeper outline for the underside
    "C": "#f4eddf",     # cream base
    "S": "#d9d0bb",     # cream shade
    "H": "#fffdf7",     # cream highlight
    "B": "#f2a63a",     # beak and feet
    "D": "#c17d15",     # beak shade
    "E": "#241d47",     # eye
    "P": "#8b6cff",     # purple accent
    "G": "#e9c46a",     # deco gold
}

GRID_W = 28


def pad(rows: list[str], width: int = GRID_W) -> list[str]:
    """Pad every row to the same width, so a miscounted dot cannot shift the art."""
    return [r.ljust(width, ".")[:width] for r in rows]


# ---------------------------------------------------------------------------
# The goose. 28 x 26.
#
# Long body, neck rising from the front, head high and right, wedge beak. One eye as a
# 2x2 dark block with no highlight — at this size a highlight just muddies it. The wing
# is three rows of shade tone, which reads as a folded wing without an outline.
# ---------------------------------------------------------------------------
GOOSE = pad([
    "..............OOOOOO",
    ".............OHHHCCCO",
    "............OHCCCCCCO",
    "............OCCCCCCCO",
    "............OCCEECCCOBBB",
    "............OCCEECCCBBBBB",
    "............OCCCCCCCOBBB",
    ".............OCCCCCCO",
    ".............OCCCCO",
    ".............OCCCCO",
    ".............OCCCCO",
    "......OOOOOOOCCCCOO",
    "....OOSSCCCCCCCCCCO",
    "...OSSSCCCCCCCCCCCCO",
    "..OSSCCCCCCCCCCCCCCO",
    "..OSCCCCCCCCCCCCCCCO",
    ".OSCCCCCSSSSCCCCCCCO",
    ".OSCCCCSSSSSSCCCCCCO",
    ".OSSCCCSSSSSCCCCCCO",
    "..OSSCCCSSSCCCCCCO",
    "...KKSSCCCCCCCCKK",
    ".....KKKCCCCCKK",
    "........OBBOBBO",
    ".......OBBBOBBBO",
    "......OBDDBOBDDBO",
    ".......OOOO.OOOO",
])

# ---------------------------------------------------------------------------
# Deco capitals, 9 x 13. Deliberately heavy: 2px verticals, 2px horizontals, a high
# waist, square terminals. Meant to shout.
# ---------------------------------------------------------------------------
GLYPHS = {
    "R": ["111111100","111111110","110000110","110000110","110000110","111111110",
          "111111100","110011000","110001100","110000110","110000110","110000011","110000011"],
    "O": ["011111100","111111110","110000110","110000110","110000110","110000110",
          "110000110","110000110","110000110","110000110","110000110","111111110","011111100"],
    "L": ["110000000","110000000","110000000","110000000","110000000","110000000",
          "110000000","110000000","110000000","110000000","110000000","111111110","111111110"],
    "E": ["111111111","111111111","110000000","110000000","110000000","111111100",
          "111111100","110000000","110000000","110000000","110000000","111111111","111111111"],
    "F": ["111111111","111111111","110000000","110000000","110000000","111111100",
          "111111100","110000000","110000000","110000000","110000000","110000000","110000000"],
    "D": ["111111000","111111100","110000110","110000011","110000011","110000011",
          "110000011","110000011","110000011","110000011","110000110","111111100","111111000"],
}


def rects(grid: list[str], *, ox: int = 0, oy: int = 0, palette: dict | None = None) -> str:
    """One <rect> per horizontal run of identical pixels.

    Run-length encoded rather than a rect per pixel: roughly a fifth of the output for
    an identical result.
    """
    palette = palette or PAL
    out = []
    for y, row in enumerate(grid):
        x = 0
        while x < len(row):
            ch = row[x]
            run = 1
            while x + run < len(row) and row[x + run] == ch:
                run += 1
            colour = palette.get(ch)
            if colour:
                out.append(
                    f'<rect x="{ox + x}" y="{oy + y}" width="{run}" height="1" fill="{colour}"/>'
                )
            x += run
    return "".join(out)


def ziggurat(x: int, y: int, w: int, steps: int = 3) -> str:
    """A stepped plinth, widest at the bottom. The defining deco move."""
    out = []
    for s in range(steps):
        inset = (steps - 1 - s) * 3
        out.append(
            f'<rect x="{x + inset}" y="{y + s}" width="{w - inset * 2}" height="1" '
            f'fill="{PAL["G"]}" opacity="{0.40 + s * 0.22:.2f}"/>'
        )
    return "".join(out)


def mascot_svg(*, plinth: bool = True) -> str:
    """The goose. `plinth=False` gives the bare bird for tight spots like a favicon."""
    W, H = 30, 30 if plinth else 27
    body = [rects(GOOSE, ox=1, oy=0)]
    if plinth:
        body.append(ziggurat(6, 26, 18, steps=3))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'shape-rendering="crispEdges" role="img" aria-label="RoleFeed goose">'
        + "".join(body) + "</svg>"
    )


def wordmark_svg(word: str = "ROLEFEED", split: int = 4) -> str:
    """ROLEFEED in heavy deco capitals, with the second word in purple so the two
    halves separate without needing a space."""
    gw, gh, gap = 9, 13, 2
    W = len(word) * (gw + gap) - gap
    top, base = 4, 4 + gh
    parts = [
        # Stacked rules, thick over thin — the classic deco pair.
        f'<rect x="0" y="0" width="{W}" height="2" fill="{PAL["G"]}"/>',
        f'<rect x="0" y="3" width="{W}" height="1" fill="{PAL["G"]}" opacity="0.40"/>',
    ]
    x = 0
    for i, ch in enumerate(word):
        colour = PAL["P"] if i >= split else PAL["C"]
        parts.append(rects(GLYPHS[ch], ox=x, oy=top + 3, palette={"1": colour, "0": None}))
        x += gw + gap
    parts.append(f'<rect x="0" y="{base + 5}" width="{W}" height="2" fill="{PAL["G"]}"/>')
    parts.append(f'<rect x="0" y="{base + 8}" width="{W}" height="1" fill="{PAL["G"]}" opacity="0.40"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {base + 9}" '
        f'shape-rendering="crispEdges" role="img" aria-label="RoleFeed">'
        + "".join(parts) + "</svg>"
    )


def favicon_uri() -> str:
    """The bare goose, URL-encoded for a data: href."""
    svg = mascot_svg(plinth=False).replace(
        "<svg ", '<svg style="background:#14102b" '
    )
    return "data:image/svg+xml," + (
        svg.replace("<", "%3C").replace(">", "%3E").replace("#", "%23").replace('"', "'")
    )


if __name__ == "__main__":
    out = pathlib.Path(__file__).parent
    (out / "mascot.svg").write_text(mascot_svg() + "\n")
    (out / "goose-bare.svg").write_text(mascot_svg(plinth=False) + "\n")
    (out / "wordmark.svg").write_text(wordmark_svg() + "\n")
    (out / "favicon.txt").write_text(favicon_uri() + "\n")
    widths = {len(r) for r in GOOSE}
    print(f"goose rows: {len(GOOSE)}, widths: {widths}")
    print("mascot.svg, goose-bare.svg, wordmark.svg, favicon.txt written")
