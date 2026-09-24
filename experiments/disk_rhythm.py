#!/usr/bin/env python3
"""Rhythmic multi-disc screensaver for the INSERT DISK moment.

Discs animate on a steady beat (BEAT_SECONDS); the scene (disc count,
layout, scale, motion) changes every SCENE_BEATS beats. Scenes are data
(SCENES), so adding or tuning one never touches the render loop. Every disc
reuses wireframe_disc.py's geometry, face gating and projection via
draw_disc().

Motion types (all discs in a scene share one), with p = progress through
the beat, eased by a cosine ease-in-out:
  reset  full 360 deg turn per beat, landing on the start orientation
  rock   swing out ROCK_DEGREES and back within the beat, pendulum-style

Timing is frame-counted on deadline ticks, never taken from the wall
clock, so a slow frame can't make the motion (and luma's diff cost) look
smaller than it is (see CLAUDE.md).

Phase 1: a single worst-case scene (16 discs in a 2x8 grid) to measure
redraw cost before building the full set.
"""

import argparse
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from luma.core.framebuffer import diff_to_previous
from PIL import Image, ImageDraw

from wireframe_disc import PANEL_SIZE, build_model, draw_disc

BEAT_SECONDS = 1.0
SCENE_BEATS = 4
TICK = 0.04                 # 25 fps
ROCK_DEGREES = 60
STATS_EVERY_S = 10.0
DIFF_SEGMENT_CHOICES = (1, 4, 16, 64, 256)  # square and dividing 256x64 evenly


@dataclass(frozen=True)
class Scene:
    name: str
    discs: tuple            # ((screen_x, screen_y, height_px), ...)
    motion: str             # "reset" | "rock"
    base_deg: float = 0.0   # orientation at the top of each beat


def grid(cols, rows, height_px, size=PANEL_SIZE):
    """Disc placements centred in an evenly divided cols x rows grid."""
    w, h = size
    return tuple(((c + 0.5) * w / cols, (r + 0.5) * h / rows, height_px)
                 for r in range(rows) for c in range(cols))


def scenes(small_height):
    return [
        Scene("16 small, 2x8 grid, reset", grid(8, 2, small_height), "reset"),
    ]


def ease(p):
    return (1 - math.cos(math.pi * p)) / 2


def motion_deg(scene, p):
    if scene.motion == "reset":
        return scene.base_deg + 360 * ease(p)
    if scene.motion == "rock":
        return scene.base_deg + ROCK_DEGREES * (1 - math.cos(2 * math.pi * p)) / 2
    raise ValueError(f"unknown motion {scene.motion!r}")


def frame_state(scene_list, frame, tick):
    """(scene, progress through the beat) for a frame number."""
    frames_per_beat = round(BEAT_SECONDS / tick)
    beat = frame // frames_per_beat
    scene = scene_list[(beat // SCENE_BEATS) % len(scene_list)]
    return scene, (frame % frames_per_beat) / frames_per_beat


def render(draw, model, scene, p, outline_only, size=PANEL_SIZE):
    draw.rectangle((0, 0, size[0] - 1, size[1] - 1), fill="black")
    angle = math.radians(motion_deg(scene, p))
    for x, y, height_px in scene.discs:
        draw_disc(draw, model, angle, (x, y), height_px, outline_only)


def render_stills(out_dir, scene_list, outline_only, fractions=(0, 0.25, 0.5, 0.75)):
    model = build_model()
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, scene in enumerate(scene_list):
        for p in fractions:
            im = Image.new("RGB", PANEL_SIZE, "black")
            render(ImageDraw.Draw(im), model, scene, p, outline_only)
            im.save(out_dir / f"scene{i + 1}_p{p:.2f}.png")
    print(f"wrote {len(scene_list) * len(fractions)} stills to {out_dir}")


def run_live(scene_list, tick, outline_only, diff_segments):
    from oled_common import get_device

    model = build_model()
    device = get_device(framebuffer=diff_to_previous(num_segments=diff_segments))
    canvas = Image.new(device.mode, device.size, "black")
    draw = ImageDraw.Draw(canvas)
    print(f"{len(scene_list)} scene(s), beat {BEAT_SECONDS}s x {SCENE_BEATS}, tick "
          f"{tick * 1000:.0f} ms, {'outline only' if outline_only else 'face-gated detail'}, "
          f"luma diff segments {diff_segments}. Stop with ./rig stop.")

    frame = 0
    frame_ms = []
    shown = None
    start = stats_t = time.perf_counter()
    cpu0 = time.process_time()
    while True:
        scene, p = frame_state(scene_list, frame, tick)
        if scene is not shown:
            print(f"scene: {scene.name} ({len(scene.discs)} discs, {scene.motion})")
            shown = scene
        t0 = time.perf_counter()
        render(draw, model, scene, p, outline_only)
        device.display(canvas)
        frame_ms.append((time.perf_counter() - t0) * 1000)
        frame += 1

        now = time.perf_counter()
        if now - stats_t >= STATS_EVERY_S:
            cpu = time.process_time()
            print(f"{len(frame_ms) / (now - stats_t):.1f} fps; render+push mean "
                  f"{sum(frame_ms) / len(frame_ms):.1f} ms, max {max(frame_ms):.1f} ms; "
                  f"CPU {(cpu - cpu0) / (now - stats_t) * 100:.0f}% of one core")
            frame_ms.clear()
            stats_t, cpu0 = now, cpu
        time.sleep(max(0.0, start + frame * tick - time.perf_counter()))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stills", type=Path, metavar="DIR",
                        help="render PNGs at quarter-beat steps per scene instead of running live")
    parser.add_argument("--tick", type=float, default=TICK, help="seconds per frame")
    parser.add_argument("--disc-height", type=int, default=12,
                        help="small disc face height in px (12 = quarter of the single disc's 48)")
    parser.add_argument("--outline-only", action="store_true",
                        help="draw only outline + extrusion (no face details)")
    parser.add_argument("--diff-segments", type=int, default=4, choices=DIFF_SEGMENT_CHOICES,
                        help="luma diff_to_previous grid (4 = its default 2x2)")
    args = parser.parse_args()

    scene_list = scenes(args.disc_height)
    if args.stills:
        render_stills(args.stills, scene_list, args.outline_only)
    else:
        run_live(scene_list, args.tick, args.outline_only, args.diff_segments)


if __name__ == "__main__":
    main()
