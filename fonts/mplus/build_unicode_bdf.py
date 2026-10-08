#!/usr/bin/env python3
"""Merge the M+ 12px BDF sources into one Unicode BDF that Pillow can load.

Replicates PixelMplus12's build (src/build_PixelMplus12.sh + bdf2eps.pl):
the four sources are read in order (Latin-1, half-width kana, JIS X 0208,
JIS X 0213 extras); each file's encoding comes from the last two fields of
its FONT name; glyphs named STARTCHAR 0xNNNN are mapped to Unicode through
src/ucstable.d/<encoding>.TXT (+ .WIN.TXT overrides); unmapped glyphs are
dropped and the first file to claim a code point wins. The result has the
same 7,251 code points and glyph shapes as PixelMplus12-Regular.ttf.

usage: build_unicode_bdf.py [r|b]   (regular, the default, or bold)
writes mplus12<weight>-unicode.bdf next to this script.
"""

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"


def load_table(enc):
    table = {}
    for name in (f"{enc}.TXT", f"{enc}.WIN.TXT"):
        path = SRC / "ucstable.d" / name
        if not path.exists():
            continue
        for line in path.read_text(errors="replace").splitlines():
            m = re.match(r"^0x([0-9A-Fa-f]+)\s+0x([0-9A-Fa-f]+)", re.sub(r"\s*#.*$", "", line))
            if m:
                table[int(m.group(1), 16)] = int(m.group(2), 16)
    return table


def encoding_of(font_name):
    enc = "-".join(font_name.split("-")[13:15]).lower()
    for key, name in (("8859-1", "8859-1"), ("jisx0201", "JISX0201"),
                      ("jisx0208", "JISX0208"), ("jisx0213", "JISX0213")):
        if key in enc:
            return name
    raise ValueError(f"unknown encoding in FONT {font_name!r}")


def main():
    weight = sys.argv[1] if len(sys.argv) > 1 else "r"
    if weight not in ("r", "b"):
        sys.exit("weight must be r or b")
    sources = [f"mplus_f12{weight}.bdf", f"mplus_f12{weight}-jisx0201.bdf",
               f"mplus_j12{weight}.bdf", f"mplus_j12{weight}-jisx0213.bdf"]
    glyphs = {}
    for fname in sources:
        lines = (SRC / "bdf.d" / fname).read_text(errors="replace").splitlines()
        font = next(l for l in lines if l.startswith("FONT "))
        table = load_table(encoding_of(font[5:]))
        added = 0
        i = 0
        while i < len(lines):
            m = re.match(r"^STARTCHAR\s+0x([0-9A-Fa-f]{4})", lines[i])
            if not m:
                i += 1
                continue
            j = i
            while not lines[j].startswith("ENDCHAR"):
                j += 1
            u = table.get(int(m.group(1), 16))
            if u and u not in glyphs:
                glyphs[u] = [l for l in lines[i + 1:j] if not l.startswith("ENCODING")]
                added += 1
            i = j + 1
        print(f"{fname:<28} added {added}")

    out = HERE / f"mplus12{weight}-unicode.bdf"
    text = [
        "STARTFONT 2.1",
        f"FONT -mplus-gothic-{'bold' if weight == 'b' else 'medium'}-R-normal--12-120-75-75-C-60-iso10646-1",
        "SIZE 12 75 75",
        "FONTBOUNDINGBOX 12 13 0 -2",
        "STARTPROPERTIES 6",
        "PIXEL_SIZE 12",
        'SPACING "C"',
        'CHARSET_REGISTRY "ISO10646"',
        'CHARSET_ENCODING "1"',
        "FONT_ASCENT 11",
        "FONT_DESCENT 2",
        "ENDPROPERTIES",
        f"CHARS {len(glyphs)}",
    ]
    for u in sorted(glyphs):
        text += [f"STARTCHAR U+{u:04X}", f"ENCODING {u}"] + glyphs[u] + ["ENDCHAR"]
    text.append("ENDFONT")
    out.write_text("\n".join(text) + "\n")
    print(f"wrote {out.name}: {len(glyphs)} glyphs")


if __name__ == "__main__":
    main()
