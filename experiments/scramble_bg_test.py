#!/usr/bin/env python3
"""Fullscreen "busy state" prototype: scrambling noise background with a
status message overlaid on the centre row.

5 rows of noise in the sub font role (stacked at its 12px pitch, though the
M+ cell is 13px: noise and uppercase never ink the cell's top row) run for as long as the script does, updating more
slowly than the frame rate: every --bg-interval ticks, a random
--bg-fraction of the cells take a new noise character and the rest hold.
The centre row's status message reveals via scramble_test.py's
scramble primitive only when its text actually changes; the background never
restarts. Per frame, in order: noise rows (dim grey), a black mask over the
message's box, then the message in white.

Cycles READING DISK -> WRITING -> VERIFYING until stopped (`./rig stop`).
"""

import argparse
import random
import time
from pathlib import Path

from PIL import Image, ImageDraw

from scramble_test import NOISE, SCRAMBLE_TICK, draw_items, frame_items, schedule
from oled_common import get_device
from oled_fonts import SUB

ROWS = 5
STATUS_ROW = 2  # centre of 5
MESSAGES = ["READING DISK", "WRITING", "VERIFYING"]
STATS_EVERY_S = 10.0


class StatusReveal:
    """Scramble-reveals the status text, restarting only on a real change."""

    def __init__(self, role, reveal_frames, rng):
        self.role = role
        self.reveal_frames = reveal_frames
        self.rng = rng
        self.text = None
        self.offsets = []
        self.spans = []
        self.frame = 0

    def set_text(self, text):
        text = self.role.prepare(text)
        if text == self.text:
            return False
        self.text = text
        self.offsets = self.role.layout(text)
        self.spans = schedule(text, self.reveal_frames, self.rng)
        self.frame = 0
        return True

    def next_items(self):
        items = frame_items(self.text, self.spans, self.frame, self.rng, self.role)
        self.frame += 1
        return items


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tick", type=float, default=SCRAMBLE_TICK, help="seconds per frame")
    parser.add_argument("--bg-grey", type=int, default=34,
                        help="noise grey 0-255 (34 = panel level 2, 51 = level 3)")
    parser.add_argument("--bg-interval", type=int, default=2,
                        help="background may refresh only every N ticks")
    parser.add_argument("--bg-fraction", type=float, default=0.15,
                        help="fraction of background cells that change per refresh (0-1)")
    parser.add_argument("--dwell", type=float, default=4.0, help="seconds per status message")
    parser.add_argument("--reveal", type=float, default=1.6, help="seconds for a message reveal")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--save-frames", type=Path, help="also write each frame as a PNG here")
    args = parser.parse_args()
    if args.bg_interval < 1:
        parser.error("--bg-interval must be at least 1")
    if not 0.0 <= args.bg_fraction <= 1.0:
        parser.error("--bg-fraction must be between 0 and 1")

    rng = random.Random(args.seed)
    font, advance, pitch = SUB.font, SUB.advance, SUB.pitch

    device = get_device()
    cols = device.width // advance
    x0 = (device.width - cols * advance) // 2
    y0 = (device.height - ROWS * pitch) // 2
    status_y = y0 + STATUS_ROW * pitch
    bg = (args.bg_grey,) * 3
    grid = [[rng.choice(NOISE) for _ in range(cols)] for _ in range(ROWS)]
    cells = [(r, c) for r in range(ROWS) for c in range(cols)]
    bg_changes = round(args.bg_fraction * len(cells))

    canvas = Image.new(device.mode, device.size, "black")
    draw = ImageDraw.Draw(canvas)
    status = StatusReveal(SUB, max(1, round(args.reveal / args.tick)), rng)
    if args.save_frames:
        args.save_frames.mkdir(parents=True, exist_ok=True)

    print(f"{cols}x{ROWS} noise grid at ({x0},{y0}), bg grey {args.bg_grey}, "
          f"tick {args.tick * 1000:.0f} ms, bg: {bg_changes}/{len(cells)} cells "
          f"every {args.bg_interval} ticks. Stop with ./rig stop.")

    frame = 0
    refresh_ms, other_ms = [], []
    start_t = stats_t = time.perf_counter()
    while True:
        t0 = time.perf_counter()
        message = MESSAGES[int((t0 - start_t) // args.dwell) % len(MESSAGES)]
        if status.set_text(message):
            print(f"status -> {message}")

        bg_refresh = frame % args.bg_interval == 0
        if bg_refresh:
            for r, c in rng.sample(cells, bg_changes):
                grid[r][c] = rng.choice(NOISE)

        draw.rectangle((0, 0, device.width - 1, device.height - 1), fill="black")
        for row in range(ROWS):
            draw.text((x0, y0 + row * pitch), "".join(grid[row]), font=font, fill=bg)

        width = int(font.getlength(status.text))
        status_x = x0 + (cols - width // advance) // 2 * advance
        draw.rectangle((status_x, status_y, status_x + width - 1,
                        status_y + SUB.cell_height - 1), fill="black")
        draw_items(draw, (status_x, status_y), SUB, status.offsets, status.next_items(), "white")

        device.display(canvas)
        (refresh_ms if bg_refresh else other_ms).append((time.perf_counter() - t0) * 1000)
        if args.save_frames:
            canvas.save(args.save_frames / f"frame_{frame:04d}.png")

        frame += 1
        now = time.perf_counter()
        if now - stats_t >= STATS_EVERY_S:
            all_ms = refresh_ms + other_ms
            line = (f"{len(all_ms) / (now - stats_t):.1f} fps; render+push mean "
                    f"{sum(all_ms) / len(all_ms):.1f} ms, max {max(all_ms):.1f} ms")
            for label, ms in (("bg-refresh", refresh_ms), ("other", other_ms)):
                if ms:
                    line += f" | {label} ticks mean {sum(ms) / len(ms):.1f} ms"
            print(line)
            refresh_ms.clear()
            other_ms.clear()
            stats_t = now
        time.sleep(max(0.0, start_t + frame * args.tick - time.perf_counter()))


if __name__ == "__main__":
    main()
