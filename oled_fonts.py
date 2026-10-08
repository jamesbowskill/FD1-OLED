"""Font roles for the OLED. Every script gets its fonts from here, so changing a
font means changing a path in ROLES, not each layout.

Each role reads its metrics from the BDF header and loads the font once, on
first use. The device only ever loads BDFs: the TTF/OTF files in fonts/ are
for Figma only (Pillow's outline rasteriser clips edge rows at these sizes).
Run this file to print the role table.
"""

import unicodedata
from functools import cached_property
from pathlib import Path

from PIL import ImageFont

FONT_DIR = Path(__file__).resolve().parent / "fonts"


class FontRole:
    def __init__(self, name, path, pitch=None, substitutions=None):
        self.name = name
        self.path = Path(path)
        props = {}
        with open(self.path) as f:
            for line in f:
                if line.startswith("CHARS "):
                    break
                key, _, value = line.strip().partition(" ")
                props[key] = value
        self.size = int(props["PIXEL_SIZE"])
        self.ascent = int(props["FONT_ASCENT"])
        self.descent = int(props["FONT_DESCENT"])
        self.cell_height = self.ascent + self.descent  # height a strip must have
        self.pitch = pitch or self.cell_height  # distance between stacked rows
        self.substitutions = dict(substitutions or {})
        self._translate = str.maketrans(self.substitutions)

    @cached_property
    def font(self):
        # ImageFont.load() can't read raw .bdf; FreeType can, at its native size only.
        return ImageFont.truetype(str(self.path), size=self.size)

    @cached_property
    def advance(self):
        """Advance of a single-width (Latin) character, in px."""
        return int(self.font.getlength("M"))

    def prepare(self, text):
        """Display text only: NFC-normalise, then apply this role's substitutions
        for characters the font lacks. Never use on file paths or anything used
        for file lookup (macOS filenames are often NFD on disk)."""
        return unicodedata.normalize("NFC", text).translate(self._translate)

    def layout(self, text):
        """x offset of each character within the text, from per-character
        advances (BDFs have no kerning, so this matches drawing the string)."""
        offsets, x = [], 0
        for ch in text:
            offsets.append(x)
            x += int(self.font.getlength(ch))
        return offsets

    def is_wide(self, ch):
        """Double-width (kana, kanji, full-width forms)."""
        return self.font.getlength(ch) > self.advance

    def __repr__(self):
        return f"FontRole({self.name!r}, {self.path.relative_to(FONT_DIR)})"


# Characters M+ lacks, mapped at render time to ones it has (the BDF stays as
# built). Anything else missing falls through to the font's placeholder glyph.
SUB_SUBSTITUTIONS = {
    "–": "-", "—": "-", "〜": "～",
    "ō": "o", "ū": "u", "Ō": "O", "Ū": "U",
    "髙": "高", "﨑": "崎", "𠮷": "吉",
}

TITLE = FontRole("title", FONT_DIR / "unifont" / "unifont_jp-18.0.01.bdf")
# 13px cell, but uppercase/Latin noise never inks the top row, so the busy
# screen stacks rows at 12px (5 x 12 = 60px fits the 64px panel).
SUB = FontRole("sub", FONT_DIR / "mplus" / "mplus12r-unicode.bdf", pitch=12,
               substitutions=SUB_SUBSTITUTIONS)
# Row 3: times, counter and progress bar. Spleen 5x8, as on the live
# player screen; the 2026-10-08 Figma mockup's Row 3 was a rendering
# artifact (Figma has no 8px Spleen), not a design change.
TIMER = FontRole("timer", FONT_DIR / "spleen" / "spleen-5x8.bdf")
ROLES = {role.name: role for role in (TITLE, SUB, TIMER)}


if __name__ == "__main__":
    for role in ROLES.values():
        print(f"{role.name:<6} {str(role.path.relative_to(FONT_DIR)):<30} size {role.size:>2}, "
              f"advance {role.advance}, ascent {role.ascent} + descent {role.descent} "
              f"= cell {role.cell_height}, pitch {role.pitch}"
              f"{f', {len(role.substitutions)} substitutions' if role.substitutions else ''}")
