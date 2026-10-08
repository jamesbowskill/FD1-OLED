#!/usr/bin/env python3
"""Scramble-decode text reveal prototype, in an oled_fonts role. Also the
shared scramble primitive (schedule, frame_items, draw_items).

Each character gets a random start and end frame within the overall
duration: blank before its start, a new random Latin noise glyph every frame
until its end, then locked to the target character. Whitespace (including
U+3000) stays blank throughout so the word shapes read early. Every item is
drawn at its character's final position, so double-width text never
reflows; wide cells get two narrow noise glyphs (or one full-width glyph
with --wide-noise fullwidth). Runs once, holds the final text, and exits
(persist=True leaves the text on screen).

Only the text's bounding box is redrawn on a persistent frame each tick;
luma's default diff_to_previous framebuffer then pushes just that region.
"""

import argparse
import random
import string
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw

from oled_common import get_device
from oled_fonts import ROLES

NOISE = string.ascii_uppercase + string.digits + "!#$%&*+-=?@<>/\\|~^"
# The same characters as full-width forms (U+FF01..U+FF5E), one per wide cell.
FULLWIDTH_NOISE = "".join(chr(ord(c) + 0xFEE0) for c in NOISE)
WIDE_NOISE_MODES = ("pair", "fullwidth")
# ~25 fps. Deliberately not display.py's ANIMATION_TICK (0.08): 0.08 looked
# too slow for this effect on the real panel (see CLAUDE.md).
SCRAMBLE_TICK = 0.04
TEXT_X, TEXT_Y = 4, 12  # display.py's LEFT_MARGIN / LINE1_Y
MIN_NOISE_FRAMES = 3


def schedule(text, total_frames, rng):
    """Random (start, end) frame per character within total_frames."""
    spans = []
    for _ in text:
        start = rng.randint(0, total_frames // 2)
        end = rng.randint(min(start + MIN_NOISE_FRAMES, total_frames), total_frames)
        spans.append((start, end))
    return spans


def frame_items(text, spans, frame, rng, role, wide_noise="pair"):
    """What to draw at each character position this frame: "" (blank, also
    for any whitespace including U+3000), noise, or the character itself.
    Noise in a double-width position is two narrow glyphs ("pair") or one
    full-width glyph ("fullwidth"), so it fills the cell the character will
    occupy."""
    items = []
    for ch, (start, end) in zip(text, spans):
        if ch.isspace() or frame < start:
            items.append("")
        elif frame < end:
            if not role.is_wide(ch):
                items.append(rng.choice(NOISE))
            elif wide_noise == "fullwidth":
                items.append(rng.choice(FULLWIDTH_NOISE))
            else:
                items.append(rng.choice(NOISE) + rng.choice(NOISE))
        else:
            items.append(ch)
    return items


def draw_items(draw, xy, role, offsets, items, fill):
    """Draw each item at its character's final x offset (role.layout of the
    final text), so a scramble never reflows the line."""
    x, y = xy
    for dx, item in zip(offsets, items):
        if item:
            draw.text((x + dx, y), item, font=role.font, fill=fill)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("text", nargs="?", default="SURE SHOT")
    parser.add_argument("--role", choices=list(ROLES), default="title", help="oled_fonts role")
    parser.add_argument("--tick", type=float, default=SCRAMBLE_TICK, help="seconds per frame")
    parser.add_argument("--duration", type=float, default=1.6, help="seconds for the whole reveal")
    parser.add_argument("--hold", type=float, default=2.0, help="seconds to hold the final text")
    parser.add_argument("--seed", type=int, help="fix the random pattern to compare settings")
    parser.add_argument("--save-frames", type=Path, help="also write each frame as a PNG here")
    parser.add_argument("--wide-noise", choices=WIDE_NOISE_MODES, default="pair",
                        help="noise in double-width cells")
    args = parser.parse_args()

    role = ROLES[args.role]
    text = role.prepare(args.text)
    width = int(role.font.getlength(text))
    offsets = role.layout(text)
    box = (TEXT_X, TEXT_Y, TEXT_X + width - 1, TEXT_Y + role.cell_height - 1)

    device = get_device()
    if box[2] >= device.width:
        sys.exit(f"'{text}' is {width}px wide; doesn't fit at x={TEXT_X}")

    rng = random.Random(args.seed)
    spans = schedule(text, max(1, round(args.duration / args.tick)), rng)
    last_frame = max(end for _, end in spans)

    canvas = Image.new(device.mode, device.size, "black")
    draw = ImageDraw.Draw(canvas)
    if args.save_frames:
        args.save_frames.mkdir(parents=True, exist_ok=True)

    render_ms = []
    start_t = time.perf_counter()
    for frame in range(last_frame + 1):
        t0 = time.perf_counter()
        draw.rectangle(box, fill="black")
        items = frame_items(text, spans, frame, rng, role, args.wide_noise)
        draw_items(draw, (TEXT_X, TEXT_Y), role, offsets, items, "white")
        device.display(canvas)
        render_ms.append((time.perf_counter() - t0) * 1000)
        if args.save_frames:
            canvas.save(args.save_frames / f"frame_{frame:03d}.png")
        time.sleep(max(0.0, start_t + (frame + 1) * args.tick - time.perf_counter()))
    elapsed = time.perf_counter() - start_t

    print(f"'{text}' in {role.name}: {last_frame + 1} frames in {elapsed:.2f}s "
          f"({(last_frame + 1) / elapsed:.1f} fps, tick {args.tick * 1000:.0f} ms)")
    print(f"Render+push per frame: mean {sum(render_ms) / len(render_ms):.1f} ms, "
          f"max {max(render_ms):.1f} ms")
    time.sleep(args.hold)
    print("Done; final text left on screen.")


if __name__ == "__main__":
    main()
