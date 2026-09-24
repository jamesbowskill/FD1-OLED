#!/usr/bin/env python3
"""Rhythmic multi-disc screensaver for the INSERT DISK moment.

Discs animate on a steady beat (BEAT_SECONDS); the scene (disc count,
layout, scale, motion, or text) changes every SCENE_BEATS beats, and the
sequence loops. Scenes are data (SCENES), so adding or tuning one never
touches the render loop. Every disc reuses wireframe_disc.py's geometry,
face gating and projection via draw_disc().

Motion types (all discs in a scene share one), with p = progress through
the beat, eased by a cosine ease-in-out:
  reset  full 360 deg turn per beat, landing on the start orientation
  rock   swing out ROCK_DEGREES from base_deg and back, pendulum-style
Both end each beat at base_deg, so scene cuts land with the discs at rest.

Timing is frame-counted on deadline ticks, never taken from the wall
clock, so a slow frame can't make the motion (and luma's diff cost) look
smaller than it is (see CLAUDE.md).
"""

import argparse
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

from scramble_test import load_font
from wireframe_disc import PANEL_SIZE, build_model, draw_disc

BEAT_SECONDS = 1.0
SCENE_BEATS = 4
TICK = 0.04                 # 25 fps
ROCK_DEGREES = 60
SMALL_DISC_PX = 12          # validated on the panel; a quarter of the single disc's 48
TEXT_FONT_PX = 16


@dataclass(frozen=True)
class Scene:
    name: str
    discs: tuple = ()       # ((screen_x, screen_y, height_px), ...)
    motion: str = "reset"   # "reset" | "rock"
    base_deg: float = 0.0   # orientation at the top of each beat
    text: str = None        # centred text drawn instead of / as well as discs


def grid(cols, rows, height_px, size=PANEL_SIZE):
    """Disc placements centred in an evenly divided cols x rows grid."""
    w, h = size
    return tuple(((c + 0.5) * w / cols, (r + 0.5) * h / rows, height_px)
                 for r in range(rows) for c in range(cols))


def row(heights, size=PANEL_SIZE):
    """One disc per height, centres evenly spaced across the width."""
    w, h = size
    return tuple(((i + 0.5) * w / len(heights), h / 2, hp) for i, hp in enumerate(heights))


def packed_row(heights, gap, size=PANEL_SIZE):
    """Discs of varying heights side by side, `gap` px apart, centred."""
    w, h = size
    widths = [hp * 94 / 98 for hp in heights]  # disc face aspect
    x = (w - sum(widths) - gap * (len(heights) - 1)) / 2
    placed = []
    for hp, dw in zip(heights, widths):
        placed.append((x + dw / 2, h / 2, hp))
        x += dw + gap
    return tuple(placed)


def brick(cols, height_px, size=PANEL_SIZE):
    """Two rows, the lower one offset by half a cell (cols and cols - 1 discs)."""
    w, h = size
    top = [((c + 0.5) * w / cols, h / 4, height_px) for c in range(cols)]
    bottom = [((c + 1) * w / cols, 3 * h / 4, height_px) for c in range(cols - 1)]
    return tuple(top + bottom)


S = SMALL_DISC_PX
SCENES = [
    Scene("four in a row", row([40] * 4), "reset"),
    Scene("one, centred", ((128, 32, 48),), "rock", base_deg=-ROCK_DEGREES / 2),
    Scene("2x8 grid", grid(8, 2, S), "reset"),
    Scene("row of eight", row([24] * 8), "rock", base_deg=-ROCK_DEGREES / 2),
    Scene("pyramid", packed_row([S, 22, 32, 44, 32, 22, S], gap=8), "reset"),
    Scene("two, backs", ((80, 32, 50), (176, 32, 50)), "rock", base_deg=180 - ROCK_DEGREES / 2),
    Scene("brick", brick(8, S), "reset"),
    Scene("3x8 grid", grid(8, 3, S), "rock", base_deg=-ROCK_DEGREES / 2),
    Scene("INSERT DISK", text="INSERT DISK"),
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
    """(scene index, progress through the beat) for a frame number."""
    frames_per_beat = round(BEAT_SECONDS / tick)
    beat = frame // frames_per_beat
    return (beat // SCENE_BEATS) % len(scene_list), (frame % frames_per_beat) / frames_per_beat


def render(draw, model, font, scene, p, outline_only, size=PANEL_SIZE):
    draw.rectangle((0, 0, size[0] - 1, size[1] - 1), fill="black")
    if scene.discs:
        angle = math.radians(motion_deg(scene, p))
        for x, y, height_px in scene.discs:
            draw_disc(draw, model, angle, (x, y), height_px, outline_only)
    if scene.text:
        width = font.getlength(scene.text)
        draw.text(((size[0] - width) / 2, (size[1] - TEXT_FONT_PX) / 2), scene.text,
                  font=font, fill="white")


def render_stills(out_dir, scene_list, outline_only, fractions=(0, 0.25, 0.5, 0.75)):
    model, font = build_model(), load_font(TEXT_FONT_PX)
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, scene in enumerate(scene_list):
        for p in fractions:
            im = Image.new("RGB", PANEL_SIZE, "black")
            render(ImageDraw.Draw(im), model, font, scene, p, outline_only)
            im.save(out_dir / f"scene{i + 1}_p{p:.2f}.png")
    print(f"wrote {len(scene_list) * len(fractions)} stills to {out_dir}")


def run_live(scene_list, tick, outline_only):
    from oled_common import get_device

    model, font = build_model(), load_font(TEXT_FONT_PX)
    device = get_device()
    canvas = Image.new(device.mode, device.size, "black")
    draw = ImageDraw.Draw(canvas)
    print(f"{len(scene_list)} scene(s), beat {BEAT_SECONDS}s x {SCENE_BEATS}, tick "
          f"{tick * 1000:.0f} ms{', outline only' if outline_only else ''}. Stop with ./rig stop.")

    def report(index, frame_ms, wall, cpu):
        scene = scene_list[index]
        print(f"scene {index + 1} {scene.name!r} ({len(scene.discs)} discs"
              f"{', ' + scene.motion if scene.discs else ''}): {len(frame_ms) / wall:.1f} fps, "
              f"render+push mean {sum(frame_ms) / len(frame_ms):.1f} ms, max {max(frame_ms):.1f} ms, "
              f"CPU {cpu / wall * 100:.0f}%")

    frame = 0
    current, frame_ms = None, []
    start = scene_t = time.perf_counter()
    scene_cpu = time.process_time()
    while True:
        index, p = frame_state(scene_list, frame, tick)
        if index != current:
            now, cpu = time.perf_counter(), time.process_time()
            if current is not None:
                report(current, frame_ms, now - scene_t, cpu - scene_cpu)
            current, frame_ms, scene_t, scene_cpu = index, [], now, cpu
        t0 = time.perf_counter()
        render(draw, model, font, scene_list[index], p, outline_only)
        device.display(canvas)
        frame_ms.append((time.perf_counter() - t0) * 1000)
        frame += 1
        time.sleep(max(0.0, start + frame * tick - time.perf_counter()))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stills", type=Path, metavar="DIR",
                        help="render PNGs at quarter-beat steps per scene instead of running live")
    parser.add_argument("--scene", type=int, metavar="N",
                        help=f"run only scene N (1-{len(SCENES)}), looping")
    parser.add_argument("--tick", type=float, default=TICK, help="seconds per frame")
    parser.add_argument("--outline-only", action="store_true",
                        help="draw only outline + extrusion (no face details)")
    args = parser.parse_args()

    scene_list = SCENES
    if args.scene is not None:
        if not 1 <= args.scene <= len(SCENES):
            parser.error(f"--scene must be 1-{len(SCENES)}")
        scene_list = [SCENES[args.scene - 1]]
    if args.stills:
        render_stills(args.stills, scene_list, args.outline_only)
    else:
        run_live(scene_list, args.tick, args.outline_only)


if __name__ == "__main__":
    main()
