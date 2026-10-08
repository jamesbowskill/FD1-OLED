#!/usr/bin/env python3
"""Single-line status screen (FD1 display.py's non-playing states, such as
no_drive and mount_error) in the SUB role (M+ 12).

FD1 draws STATE_MESSAGES[state] as one white line at (4, 12) in Pillow's
default font, scrolling if it overflows. Here the line sits in the player
screen's Row 2 text area, (9, 26) clipped at x 248, which is also roughly
centred on the 64 px panel. It scramble-reveals once, like every player
screen element, then holds (scrolling only if it overflows). Status text
stays English. Runs until stopped (`./rig stop`).
"""

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

from oled_common import get_device
from oled_fonts import SUB
from player_screen import ROW2_X, ROW2_Y, TEXT_RIGHT, WHITE, ScrollState
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


class StatusScreen:
    def __init__(self, mode, size, reveal_frames, rng, x=ROW2_X, y=ROW2_Y, wide_noise="pair"):
        self.x, self.y = x, y
        self.line = ScrollState(SUB, TEXT_RIGHT + 1 - x, reveal_frames, rng, wide_noise)
        self.canvas = Image.new(mode, size, "black")
        self.draw = ImageDraw.Draw(self.canvas)
        self.strip = Image.new(mode, (self.line.width, SUB.cell_height))

    def show(self, text):
        return self.line.set_text(text)

    def tick(self, now, scroll_step):
        self.line.tick(now, scroll_step)

    def render(self):
        w, h = self.canvas.size
        self.draw.rectangle((0, 0, w - 1, h - 1), fill="black")
        sdraw = ImageDraw.Draw(self.strip)
        sdraw.rectangle((0, 0, self.strip.width - 1, self.strip.height - 1), fill="black")
        items = self.line.visible_items()
        if items is None:
            sdraw.text((self.line.x, 0), self.line.text, font=SUB.font, fill=WHITE)
        else:
            draw_items(sdraw, (self.line.x, 0), SUB, self.line.offsets, items, WHITE)
        self.canvas.paste(self.strip, (self.x, self.y))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("state", nargs="?", default="no_drive", choices=list(STATE_MESSAGES))
    parser.add_argument("--message", help="show this text instead of the state's message")
    parser.add_argument("--x", type=int, default=ROW2_X, help="cell left (default: Row 2's)")
    parser.add_argument("--y", type=int, default=ROW2_Y, help="cell top (default: Row 2's)")
    parser.add_argument("--reveal", type=float, default=1.6, help="seconds for the reveal")
    parser.add_argument("--tick", type=float, default=SCRAMBLE_TICK, help="seconds per frame")
    parser.add_argument("--wide-noise", choices=WIDE_NOISE_MODES, default="pair")
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()

    SUB.font  # load before the first frame
    device = get_device()
    screen = StatusScreen(device.mode, device.size, max(1, round(args.reveal / args.tick)),
                          random.Random(args.seed), args.x, args.y, args.wide_noise)
    text = args.message or STATE_MESSAGES[args.state]
    screen.show(text)
    print(f"{args.state}: {text!r} in SUB at ({args.x}, {args.y}), "
          f"{SUB.font.getlength(SUB.prepare(text)):.0f}px of {screen.line.width}px. Stop with ./rig stop.")

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
