#!/usr/bin/env python3
"""Scramble-decode text reveal prototype (Latin only), Spleen bitmap font.

Each character gets a random start and end frame within the overall
duration: blank before its start, a new random noise glyph every frame until
its end, then locked to the target character. Spaces stay blank throughout
so the word shapes read early. Runs once, holds the final text, and exits
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

from PIL import Image, ImageDraw, ImageFont

from oled_common import get_device

FONTS = {
    12: ROOT / "fonts" / "spleen" / "spleen-6x12.bdf",
    16: ROOT / "fonts" / "spleen" / "spleen-8x16.bdf",
}
NOISE = string.ascii_uppercase + string.digits + "!#$%&*+-=?@<>/\\|~^"
ANIMATION_TICK = 0.08  # display.py's cadence (~12.5 fps)
TEXT_X, TEXT_Y = 4, 12  # display.py's LEFT_MARGIN / LINE1_Y
MIN_NOISE_FRAMES = 3


def load_font(px):
    # ImageFont.load() can't read raw .bdf; FreeType can, at its native size only.
    return ImageFont.truetype(str(FONTS[px]), size=px)


def schedule(text, total_frames, rng):
    """Random (start, end) frame per character within total_frames."""
    spans = []
    for _ in text:
        start = rng.randint(0, total_frames // 2)
        end = rng.randint(min(start + MIN_NOISE_FRAMES, total_frames), total_frames)
        spans.append((start, end))
    return spans


def frame_chars(text, spans, frame, rng):
    chars = []
    for ch, (start, end) in zip(text, spans):
        if ch == " " or frame < start:
            chars.append(" ")
        elif frame < end:
            chars.append(rng.choice(NOISE))
        else:
            chars.append(ch)
    return chars


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("text", nargs="?", default="SURE SHOT")
    parser.add_argument("--size", type=int, choices=sorted(FONTS), default=16)
    parser.add_argument("--tick", type=float, default=ANIMATION_TICK, help="seconds per frame")
    parser.add_argument("--duration", type=float, default=1.6, help="seconds for the whole reveal")
    parser.add_argument("--hold", type=float, default=2.0, help="seconds to hold the final text")
    parser.add_argument("--seed", type=int, help="fix the random pattern to compare settings")
    parser.add_argument("--save-frames", type=Path, help="also write each frame as a PNG here")
    args = parser.parse_args()

    font = load_font(args.size)
    advance = int(font.getlength("M"))
    box = (TEXT_X, TEXT_Y, TEXT_X + advance * len(args.text) - 1, TEXT_Y + args.size - 1)

    device = get_device()
    if box[2] >= device.width:
        sys.exit(f"'{args.text}' is {advance * len(args.text)}px wide; doesn't fit at x={TEXT_X}")

    rng = random.Random(args.seed)
    spans = schedule(args.text, max(1, round(args.duration / args.tick)), rng)
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
        for i, ch in enumerate(frame_chars(args.text, spans, frame, rng)):
            draw.text((TEXT_X + i * advance, TEXT_Y), ch, font=font, fill="white")
        device.display(canvas)
        render_ms.append((time.perf_counter() - t0) * 1000)
        if args.save_frames:
            canvas.save(args.save_frames / f"frame_{frame:03d}.png")
        time.sleep(max(0.0, start_t + (frame + 1) * args.tick - time.perf_counter()))
    elapsed = time.perf_counter() - start_t

    print(f"'{args.text}' at {args.size}px: {last_frame + 1} frames in {elapsed:.2f}s "
          f"({(last_frame + 1) / elapsed:.1f} fps, tick {args.tick * 1000:.0f} ms)")
    print(f"Render+push per frame: mean {sum(render_ms) / len(render_ms):.1f} ms, "
          f"max {max(render_ms):.1f} ms")
    time.sleep(args.hold)
    print("Done; final text left on screen.")


if __name__ == "__main__":
    main()
