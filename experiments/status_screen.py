#!/usr/bin/env python3
"""Single-line status screen (FD1 display.py's non-playing states, such as
no_drive and mount_error) in the SUB role (M+ 12), centred on the panel.

FD1 draws STATE_MESSAGES[state] as one white line at (4, 12) in Pillow's
default font, scrolling if it overflows. Here the line is centred:

  - Horizontally on the panel, from getlength() of the final (prepared)
    text. The scramble reveal draws every item at its character's final
    offset, so the line never shifts while it decodes.
  - Vertically by M+'s 12px glyph band, not its 13px cell. Latin glyphs
    never ink the cell's top row, so the band is ascent + descent - 1 =
    12 rows (cap/ascender tops to descender bottoms), placed at cell top
    25 so it covers panel rows 26-37 around the centre line at 31.5. The
    position comes from the font metrics, not each message's ink, so the
    baseline stays put whether or not a message has descenders.

A message too wide for the text area (x 9-248, as on the player screen)
starts at its left edge and scrolls instead. --x/--y override the cell
position. It scramble-reveals once, like every player screen element, then
holds. Status text stays English. Runs until stopped (`./rig stop`);
--stills DIR renders every message offline with the panel's centre lines.
"""

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

from oled_fonts import SUB
from player_screen import ROW2_X, TEXT_RIGHT, WHITE, ScrollState
from scramble_test import SCRAMBLE_TICK, WIDE_NOISE_MODES, draw_items

# FD1's display.py STATE_MESSAGES (fd1-context/display.py), verbatim.
STATE_MESSAGES = {
    "no_drive": "No floppy drive found",
    "waiting": "Insert disk to play",
    "mounting": "Reading disk...",
    "blank": "Disk is blank",
    "mount_error": "Disk can't be read",
    "finished": "Disk finished - press play to restart",
}

SIZE = (256, 64)
TEXT_LEFT = ROW2_X  # the player screen's text area, x 9-248, for overflow
# M+'s Latin glyphs leave the cell's top row empty (only kanji ink it), so
# the glyph band is the rows below it down to the bottom of the descent.
GLYPH_TOP = 1
GLYPH_BAND = SUB.ascent + SUB.descent - GLYPH_TOP  # 12
CENTRED_Y = (SIZE[1] - GLYPH_BAND) // 2 - GLYPH_TOP  # cell top 25: band rows 26-37


class StatusScreen:
    """x=None centres each message horizontally; y=None centres the glyph
    band vertically."""

    def __init__(self, mode, size, reveal_frames, rng, x=None, y=None, wide_noise="pair"):
        self.size = size
        self.fixed_x = x
        self.strip_x = TEXT_LEFT if x is None else x
        self.y = (size[1] - GLYPH_BAND) // 2 - GLYPH_TOP if y is None else y
        self.line = ScrollState(SUB, TEXT_RIGHT + 1 - self.strip_x, reveal_frames, rng, wide_noise)
        self.pad = 0
        self.canvas = Image.new(mode, size, "black")
        self.draw = ImageDraw.Draw(self.canvas)
        self.strip = Image.new(mode, (self.line.width, SUB.cell_height))

    def show(self, text):
        changed = self.line.set_text(text)
        width = int(self.line.text_width)
        if self.fixed_x is None and width <= self.line.width:
            self.pad = (self.size[0] - width) // 2 - self.strip_x
        else:
            self.pad = 0  # explicit --x, or too wide: left-aligned, and it scrolls
        return changed

    @property
    def text_x(self):
        """Panel x of the text's left edge (before any scrolling)."""
        return self.strip_x + self.pad

    def tick(self, now, scroll_step):
        self.line.tick(now, scroll_step)

    def render(self):
        w, h = self.canvas.size
        self.draw.rectangle((0, 0, w - 1, h - 1), fill="black")
        sdraw = ImageDraw.Draw(self.strip)
        sdraw.rectangle((0, 0, self.strip.width - 1, self.strip.height - 1), fill="black")
        x = self.line.x + self.pad
        items = self.line.visible_items()
        if items is None:
            sdraw.text((x, 0), self.line.text, font=SUB.font, fill=WHITE)
        else:
            draw_items(sdraw, (x, 0), SUB, self.line.offsets, items, WHITE)
        self.canvas.paste(self.strip, (self.strip_x, self.y))


def ink_box(image):
    xs = [x for x in range(image.width) if any(image.getpixel((x, y))[0] for y in range(image.height))]
    ys = [y for y in range(image.height) if any(image.getpixel((x, y))[0] for x in range(image.width))]
    return (xs[0], ys[0], xs[-1], ys[-1]) if xs else None


def stills(out, args, scale=4, label_h=40):
    """Every message settled (plus one mid-reveal frame), with the panel's
    centre lines drawn between pixel rows 31/32 and columns 127/128."""
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for state, text in STATE_MESSAGES.items():
        for stop_at in ((60, 12) if state == "mount_error" else (60,)):
            screen = StatusScreen("RGB", SIZE, max(1, round(args.reveal / args.tick)),
                                  random.Random(args.seed or 1), args.x, args.y, args.wide_noise)
            screen.show(text)
            for frame in range(stop_at):
                screen.render()
                screen.tick(0.0, False)
            screen.render()
            im = screen.canvas.copy()
            name = f"status_{state}" + ("" if stop_at == 60 else f"_f{stop_at}")
            im.save(out / f"{name}.png")
            x0, y0, x1, y1 = ink_box(im)
            band = (screen.y + GLYPH_TOP, screen.y + GLYPH_TOP + GLYPH_BAND - 1)
            width = int(screen.line.text_width)
            note = (f"{state}: {text!r}" + ("" if stop_at == 60 else f" (reveal frame {stop_at})")
                    + f"  advance box x {screen.text_x}-{screen.text_x + width - 1}"
                    f" (margins {screen.text_x}/{SIZE[0] - screen.text_x - width}),"
                    f" band y {band[0]}-{band[1]} (margins {band[0]}/{SIZE[1] - 1 - band[1]}),"
                    f" ink x {x0}-{x1} y {y0}-{y1}")
            print(note)
            rows.append((im, note))

    w, h = SIZE[0] * scale, SIZE[1] * scale
    sheet = Image.new("RGB", (w, len(rows) * (h + label_h)), (45, 45, 45))
    d = ImageDraw.Draw(sheet)
    for i, (im, note) in enumerate(rows):
        top = i * (h + label_h)
        state_note, _, detail = note.partition("  ")
        d.text((6, top + 4), state_note, font=SUB.font, fill=(255, 200, 0))
        d.text((6, top + 20), detail, font=SUB.font, fill=(255, 200, 0))
        sheet.paste(im.resize((w, h), Image.NEAREST), (0, top + label_h))
        cx, cy = SIZE[0] // 2 * scale, top + label_h + SIZE[1] // 2 * scale
        d.line((cx, top + label_h, cx, top + label_h + h - 1), fill=(255, 0, 0))
        d.line((0, cy, w - 1, cy), fill=(255, 0, 0))
    sheet.save(out / "status_centred.png")
    print(f"wrote status_centred.png and status_*.png to {out}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("state", nargs="?", default="no_drive", choices=list(STATE_MESSAGES))
    parser.add_argument("--message", help="show this text instead of the state's message")
    parser.add_argument("--x", type=int, help="cell left, overriding horizontal centring")
    parser.add_argument("--y", type=int, help=f"cell top, overriding vertical centring ({CENTRED_Y})")
    parser.add_argument("--reveal", type=float, default=1.6, help="seconds for the reveal")
    parser.add_argument("--tick", type=float, default=SCRAMBLE_TICK, help="seconds per frame")
    parser.add_argument("--wide-noise", choices=WIDE_NOISE_MODES, default="pair")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--stills", type=Path, metavar="DIR",
                        help="render every message offline, with centre lines, and exit")
    args = parser.parse_args()
    if args.stills:
        return stills(args.stills, args)

    from oled_common import get_device

    SUB.font  # load before the first frame
    device = get_device()
    screen = StatusScreen(device.mode, device.size, max(1, round(args.reveal / args.tick)),
                          random.Random(args.seed), args.x, args.y, args.wide_noise)
    text = args.message or STATE_MESSAGES[args.state]
    screen.show(text)
    print(f"{args.state}: {text!r} in SUB, cell at ({screen.text_x}, {screen.y}), "
          f"{screen.line.text_width:.0f}px of {screen.line.width}px. Stop with ./rig stop.")

    start_t = time.perf_counter()
    frame = 0
    while True:
        now = time.perf_counter()
        screen.render()
        device.display(screen.canvas)
        screen.tick(now, frame % 2 == 0)
        frame += 1
        time.sleep(max(0.0, start_t + frame * args.tick - time.perf_counter()))


if __name__ == "__main__":
    main()
