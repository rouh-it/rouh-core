"""Rouh Redact: the font demo mode draws the person's words in (`rouh/demo.py`).

Every letter, digit, mark and emoji is the same rounded bar, the same width, so what is left
of a word on the screen is its length and nothing else, whatever a blur is undone with.
Spaces stay spaces, so a paragraph keeps its shape. Characters it does not map fall to its
.notdef, which is the same bar, never to a real font.

Made here, not taken from anywhere: Rouh's own, under the repository's licence.

    uv run --with fonttools --with brotli python tools/demo-font/make.py
writes rouh/static/demo-redact.woff2.
"""
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

EM = 1000
ADVANCE = 560          # every character, so a word's width says only how long it is
LEFT, RIGHT = 0, ADVANCE  # the bar fills it, so the letters of a word run into one smudge
BOTTOM, TOP = -10, 540
R = 70                 # the rounding of its corners

SPACES = [0x20, 0xA0, 0x1680, *range(0x2000, 0x200B), 0x202F, 0x205F, 0x3000]
ZERO = [0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, *range(0xFE00, 0xFE10), *range(0x1F3FB, 0x1F400)]
RANGES = [(0x21, 0x7E), (0xA1, 0x24F), (0x250, 0x2FF), (0x370, 0x3FF), (0x400, 0x52F),
          (0x1E00, 0x1EFF), (0x2010, 0x205E), (0x20A0, 0x20CF), (0x2100, 0x2BFF),
          (0x3001, 0x30FF), (0xFB00, 0xFB06), (0xFF01, 0xFFEF),
          (0x1F000, 0x1FAFF)]


def bar():
    pen = TTGlyphPen(None)
    pen.moveTo((LEFT + R, BOTTOM))
    pen.lineTo((RIGHT - R, BOTTOM))
    pen.qCurveTo((RIGHT, BOTTOM), (RIGHT, BOTTOM + R))
    pen.lineTo((RIGHT, TOP - R))
    pen.qCurveTo((RIGHT, TOP), (RIGHT - R, TOP))
    pen.lineTo((LEFT + R, TOP))
    pen.qCurveTo((LEFT, TOP), (LEFT, TOP - R))
    pen.lineTo((LEFT, BOTTOM + R))
    pen.qCurveTo((LEFT, BOTTOM), (LEFT + R, BOTTOM))
    pen.closePath()
    return pen.glyph()


def empty():
    return TTGlyphPen(None).glyph()


def main() -> None:
    names = [".notdef", "bar", "space", "zero"]
    cmap = {}
    for lo, hi in RANGES:
        for cp in range(lo, hi + 1):
            if 0xD800 <= cp <= 0xDFFF:
                continue
            cmap[cp] = "bar"
    for cp in SPACES:
        cmap[cp] = "space"
    for cp in ZERO:
        cmap[cp] = "zero"
    fb = FontBuilder(EM, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf({".notdef": bar(), "bar": bar(), "space": empty(), "zero": empty()})
    fb.setupHorizontalMetrics({".notdef": (ADVANCE, LEFT), "bar": (ADVANCE, LEFT),
                               "space": (ADVANCE, 0), "zero": (0, 0)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "Rouh Redact", "styleName": "Regular",
                       "copyright": "Made for Rouh's demo mode; the repository's licence."})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200,
                xAvgCharWidth=ADVANCE)
    fb.setupPost(isFixedPitch=1)
    fb.font.flavor = "woff2"
    out = Path(__file__).resolve().parents[2] / "rouh" / "static" / "demo-redact.woff2"
    fb.save(str(out))
    print(out, out.stat().st_size, "bytes,", len(cmap), "characters")


if __name__ == "__main__":
    main()
