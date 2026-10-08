"""Font roles for the OLED. Every script gets its fonts from here, so changing a
font means changing a path in ROLES, not each layout.

Each role reads its metrics from the BDF header and loads the font once, on
first use. Run this file to print the role table.
"""

from functools import cached_property
from pathlib import Path

from PIL import ImageFont

FONT_DIR = Path(__file__).resolve().parent / "fonts"


class FontRole:
    def __init__(self, name, path):
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
        self.cell_height = self.ascent + self.descent  # strip height / row pitch

    @cached_property
    def font(self):
        # ImageFont.load() can't read raw .bdf; FreeType can, at its native size only.
        return ImageFont.truetype(str(self.path), size=self.size)

    @cached_property
    def advance(self):
        """Advance of a single-width (Latin) character, in px."""
        return int(self.font.getlength("M"))

    def __repr__(self):
        return f"FontRole({self.name!r}, {self.path.relative_to(FONT_DIR)})"


TITLE = FontRole("title", FONT_DIR / "spleen" / "spleen-8x16.bdf")
SUB = FontRole("sub", FONT_DIR / "spleen" / "spleen-6x12.bdf")
MONO8 = FontRole("mono8", FONT_DIR / "spleen" / "spleen-5x8.bdf")
ROLES = {role.name: role for role in (TITLE, SUB, MONO8)}


if __name__ == "__main__":
    for role in ROLES.values():
        print(f"{role.name:<6} {str(role.path.relative_to(FONT_DIR)):<26} size {role.size:>2}, "
              f"advance {role.advance}, ascent {role.ascent} + descent {role.descent} "
              f"= cell {role.cell_height}")
