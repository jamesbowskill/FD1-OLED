#!/usr/bin/env python3
"""Rhythmic multi-disc screensaver for the INSERT DISK moment.

Discs animate on a steady beat (BEAT_SECONDS); the scene changes every
SCENE_BEATS beats and the sequence loops, ending on an INSERT DISK text
scene. Scenes are data (BATCHES), so adding or tuning one never touches the
render loop. Every disc reuses wireframe_disc.py's geometry, face gating and
projection via draw_disc().

Each beat, a disc's progress q (0..1) drives one or more motions:
  reset     full 360 deg turn, landing on the start orientation
  rock      swing out ROCK_DEGREES from base_deg and back
  flipflop  180 deg turn; alternate beats show front, then back
  hop       jump HOP_PX up and land
  pulse     grow by PULSE_GROWTH and shrink back
  conveyor  slide slide_px sideways, wrapping round the panel edges
q is the beat progress, optionally staggered per disc by x position
(`spread`, a travelling wave) and compressed into the start of the beat
(`duty`, move-then-hold), then eased. Every motion ends each beat at rest,
so scene cuts land cleanly. A disc's optional sign (-1) mirrors its
rotation and slide direction. `axis` "x" flips discs top-over-bottom
instead of turning them.

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
HOP_PX = 8
PULSE_GROWTH = 0.2
SMALL_DISC_PX = 12          # validated on the panel; a quarter of the single disc's 48
TEXT_FONT_PX = 16
DISC_ASPECT = 94 / 98       # face width / height


@dataclass(frozen=True)
class Scene:
    name: str
    discs: tuple = ()       # ((x, y, height_px[, sign]), ...); sign -1 mirrors motion
    motion: object = "reset"  # a motion name, or a tuple of names to combine
    base_deg: float = 0.0   # orientation at the top of each beat
    axis: str = "y"         # "y" turns discs, "x" flips them top over bottom
    duty: float = 1.0       # fraction of the beat spent moving (then hold)
    spread: float = 0.0     # wave: stagger start across x by this fraction of the beat
    slide_px: float = 0.0   # conveyor step per beat
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
    widths = [hp * DISC_ASPECT for hp in heights]
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


def signed(discs, sign_of):
    """Attach a direction sign to each placement: sign_of(index, x, y) -> +1/-1."""
    return tuple((x, y, h, sign_of(i, x, y)) for i, (x, y, h) in enumerate(discs))


S = SMALL_DISC_PX
W, H = PANEL_SIZE
INSERT_DISK = Scene("INSERT DISK", text="INSERT DISK")

BATCH_A = [
    Scene("four in a row", row([40] * 4), "reset"),
    Scene("one, centred", ((128, 32, 48),), "rock", base_deg=-ROCK_DEGREES / 2),
    Scene("2x8 grid", grid(8, 2, S), "reset"),
    Scene("row of eight", row([24] * 8), "rock", base_deg=-ROCK_DEGREES / 2),
    Scene("pyramid", packed_row([S, 22, 32, 44, 32, 22, S], gap=8), "reset"),
    Scene("two, backs", ((80, 32, 50), (176, 32, 50)), "rock", base_deg=180 - ROCK_DEGREES / 2),
    Scene("brick", brick(8, S), "reset"),
    Scene("3x8 grid", grid(8, 3, S), "rock", base_deg=-ROCK_DEGREES / 2),
]

BATCH_B = [
    Scene("two conveyors", signed(grid(8, 2, 20), lambda i, x, y: 1 if y < H / 2 else -1),
          "conveyor", slide_px=W / 8),
    Scene("heartbeat", ((128, 32, 40),), "pulse", base_deg=-25, duty=0.35),
    Scene("ripple", grid(8, 2, S), "reset", spread=0.5),
    Scene("tumble", row([40] * 4), "reset", axis="x"),
    Scene("hop and sway", signed(row([24] * 7), lambda i, x, y: 1 if i % 2 == 0 else -1),
          ("hop", "rock"), base_deg=-ROCK_DEGREES / 2),
    Scene("domino", grid(8, 3, S), "reset", axis="x", spread=0.7),
    Scene("flip-flop staccato", row([24] * 8), "flipflop", duty=0.3),
    Scene("gears", signed(grid(6, 2, 20), lambda i, x, y: 1 if (i + i // 6) % 2 == 0 else -1),
          "reset"),
]

BATCHES = {
    "a": BATCH_A + [INSERT_DISK],
    "b": BATCH_B + [INSERT_DISK],
    "all": BATCH_A + BATCH_B + [INSERT_DISK],
}


def ease(p):
    return (1 - math.cos(math.pi * p)) / 2


def local_progress(scene, p, x_norm):
    """Beat progress for one disc, after wave stagger and move-then-hold."""
    window = (1 - scene.spread) * scene.duty
    start = scene.spread * x_norm
    return min(max((p - start) / window, 0.0), 1.0)


def pose(scene, q, beat, sign):
    """(angle_deg, dx, dy, scale) for one disc at local progress q."""
    motions = (scene.motion,) if isinstance(scene.motion, str) else scene.motion
    angle, dx, dy, scale = scene.base_deg, 0.0, 0.0, 1.0
    for m in motions:
        if m == "reset":
            angle += 360 * ease(q)
        elif m == "rock":
            angle += ROCK_DEGREES * (1 - math.cos(2 * math.pi * q)) / 2
        elif m == "flipflop":
            angle += 180 * (beat % 2 + ease(q))
        elif m == "hop":
            dy -= HOP_PX * math.sin(math.pi * q)
        elif m == "pulse":
            scale += PULSE_GROWTH * math.sin(math.pi * q)
        elif m == "conveyor":
            dx += scene.slide_px * ease(q)
        else:
            raise ValueError(f"unknown motion {m!r}")
    return sign * angle, sign * dx, dy, scale


def disc_calls(scene, p, beat, size=PANEL_SIZE):
    """[(angle_rad, (x, y), height_px)] to draw, including conveyor wrap copies."""
    w = size[0]
    xs = [d[0] for d in scene.discs]
    x_min, x_span = min(xs), (max(xs) - min(xs)) or 1.0
    wraps = "conveyor" in ((scene.motion,) if isinstance(scene.motion, str) else scene.motion)
    calls = []
    for d in scene.discs:
        x, y, h = d[:3]
        sign = d[3] if len(d) > 3 else 1
        angle, dx, dy, scale = pose(scene, local_progress(scene, p, (x - x_min) / x_span), beat, sign)
        hp = h * scale
        x += dx
        copies = [x]
        if wraps:
            x %= w
            half = hp * DISC_ASPECT / 2 + 2
            copies = [x] + ([x + w] if x - half < 0 else []) + ([x - w] if x + half > w else [])
        calls += [(math.radians(angle), (cx, y + dy), hp) for cx in copies]
    return calls


def frame_state(scene_list, frame, tick):
    """(scene index, beat number, progress through the beat) for a frame number."""
    frames_per_beat = round(BEAT_SECONDS / tick)
    beat = frame // frames_per_beat
    return (beat // SCENE_BEATS) % len(scene_list), beat, (frame % frames_per_beat) / frames_per_beat


def render(draw, model, font, scene, p, outline_only, beat=0, size=PANEL_SIZE):
    draw.rectangle((0, 0, size[0] - 1, size[1] - 1), fill="black")
    if scene.discs:
        for angle, xy, hp in disc_calls(scene, p, beat, size):
            draw_disc(draw, model, angle, xy, hp, outline_only, scene.axis)
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


def render_gif(path, scene_list, tick, outline_only, scale=2):
    """One loop of the sequence as an animated GIF at the live frame rate."""
    model, font = build_model(), load_font(TEXT_FONT_PX)
    frames_per_beat = round(BEAT_SECONDS / tick)
    frames = []
    for frame in range(len(scene_list) * SCENE_BEATS * frames_per_beat):
        index, beat, p = frame_state(scene_list, frame, tick)
        im = Image.new("RGB", PANEL_SIZE, "black")
        render(ImageDraw.Draw(im), model, font, scene_list[index], p, outline_only, beat)
        frames.append(im.convert("1").resize((PANEL_SIZE[0] * scale, PANEL_SIZE[1] * scale),
                                             Image.NEAREST))
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=round(tick * 1000), loop=0)
    print(f"wrote {len(frames)} frames ({len(frames) * tick:.0f}s) to {path}")


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
        print(f"scene {index + 1} {scene.name!r} ({len(scene.discs)} discs): "
              f"{len(frame_ms) / wall:.1f} fps, render+push mean "
              f"{sum(frame_ms) / len(frame_ms):.1f} ms, max {max(frame_ms):.1f} ms, "
              f"CPU {cpu / wall * 100:.0f}%")

    frame = 0
    current, frame_ms = None, []
    start = scene_t = time.perf_counter()
    scene_cpu = time.process_time()
    while True:
        index, beat, p = frame_state(scene_list, frame, tick)
        if index != current:
            now, cpu = time.perf_counter(), time.process_time()
            if current is not None:
                report(current, frame_ms, now - scene_t, cpu - scene_cpu)
            current, frame_ms, scene_t, scene_cpu = index, [], now, cpu
        t0 = time.perf_counter()
        render(draw, model, font, scene_list[index], p, outline_only, beat)
        device.display(canvas)
        frame_ms.append((time.perf_counter() - t0) * 1000)
        frame += 1
        time.sleep(max(0.0, start + frame * tick - time.perf_counter()))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch", choices=sorted(BATCHES), default="a",
                        help="which scene batch to loop (each ends with INSERT DISK)")
    parser.add_argument("--scene", type=int, metavar="N",
                        help="loop only scene N of the batch")
    parser.add_argument("--stills", type=Path, metavar="DIR",
                        help="render PNGs at quarter-beat steps per scene instead of running live")
    parser.add_argument("--gif", type=Path, metavar="PATH",
                        help="render one loop as an animated GIF instead of running live")
    parser.add_argument("--tick", type=float, default=TICK, help="seconds per frame")
    parser.add_argument("--outline-only", action="store_true",
                        help="draw only outline + extrusion (no face details)")
    args = parser.parse_args()

    scene_list = BATCHES[args.batch]
    if args.scene is not None:
        if not 1 <= args.scene <= len(scene_list):
            parser.error(f"--scene must be 1-{len(scene_list)} for batch {args.batch}")
        scene_list = [scene_list[args.scene - 1]]
    if args.stills:
        render_stills(args.stills, scene_list, args.outline_only)
    elif args.gif:
        render_gif(args.gif, scene_list, args.tick, args.outline_only)
    else:
        run_live(scene_list, args.tick, args.outline_only)


if __name__ == "__main__":
    main()
