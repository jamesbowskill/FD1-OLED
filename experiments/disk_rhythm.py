#!/usr/bin/env python3
"""Rhythmic multi-disc screensaver for the INSERT DISK moment.

Discs animate on a steady beat; each scene lasts SCENE_BEATS beats and a
sequence of named scenes loops. Scenes are data (SCENES, addressed by
name), so adding or tuning one never touches the render loop. Every disc
reuses wireframe_disc.py's geometry, face gating and projection via
draw_disc().

Each beat, a disc's progress q (0..1) drives one or more motions:
  reset      full 360 deg turn, landing on the start orientation
  spin       half turn that keeps going: faces alternate each beat
  oscillate  half turn out on one beat, back on the next
  conveyor   slide by `slide` (dx, dy), wrapping round the panel edges
q is the beat progress, optionally staggered per disc by x position
(`spread`, a travelling wave), then eased. Every motion ends each beat at
rest, so scene cuts land cleanly. A disc's optional sign (-1) mirrors its
rotation and slide direction. `axis` "x" flips discs top-over-bottom
instead of turning them. A scene with `text` scrambles it in over the first
beat, holds, and scrambles it out over the last (scramble_test's reveal,
reversed for the exit).

Timing is frame-counted on deadline ticks, never taken from the wall
clock, so a slow frame can't make the motion (and luma's diff cost) look
smaller than it is (see CLAUDE.md).
"""

import argparse
import itertools
import math
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

from scramble_test import frame_chars, load_font, schedule
from wireframe_disc import PANEL_SIZE, build_model, draw_disc

BEAT_SECONDS = 1.0
SCENE_BEATS = 4
TICK = 0.04                 # 25 fps; also scramble_test's validated noise cadence
MIN_DISC_PX = 24            # floor for new scenes (smaller didn't read on the panel)
TEXT_FONT_PX = 16
DISC_ASPECT = 94 / 98       # face width / height


@dataclass(frozen=True)
class Scene:
    name: str
    about: str
    discs: tuple = ()       # ((x, y, height_px[, sign]), ...); sign -1 mirrors motion
    motion: object = "reset"  # a motion name, or a tuple of names to combine
    base_deg: float = 0.0   # orientation at the top of each beat
    axis: str = "y"         # "y" turns discs, "x" flips them top over bottom
    spread: float = 0.0     # wave: stagger start across x by this fraction of the beat
    slide: tuple = (0.0, 0.0)  # conveyor step (dx, dy) per beat
    text: str = None        # scrambling centred text (instead of / as well as discs)


def grid(cols, rows, height_px, size=PANEL_SIZE):
    """Disc placements centred in an evenly divided cols x rows grid."""
    w, h = size
    return tuple(((c + 0.5) * w / cols, (r + 0.5) * h / rows, height_px)
                 for r in range(rows) for c in range(cols))


def row(heights, size=PANEL_SIZE):
    """One disc per height, centres evenly spaced across the width."""
    w, h = size
    return tuple(((i + 0.5) * w / len(heights), h / 2, hp) for i, hp in enumerate(heights))


def packed_row(heights, gap, baseline=None, size=PANEL_SIZE):
    """Discs of varying heights side by side, `gap` px apart, centred
    horizontally; vertically centred, or bottom-aligned on `baseline`."""
    w, h = size
    widths = [hp * DISC_ASPECT for hp in heights]
    x = (w - sum(widths) - gap * (len(heights) - 1)) / 2
    placed = []
    for hp, dw in zip(heights, widths):
        placed.append((x + dw / 2, h / 2 if baseline is None else baseline - hp / 2, hp))
        x += dw + gap
    return tuple(placed)


def diagonal(count, height_px, y_top, y_bottom, size=PANEL_SIZE):
    """Evenly spaced across the width, stepping down from y_top to y_bottom."""
    w, _ = size
    return tuple(((i + 0.5) * w / count, y_top + (y_bottom - y_top) * i / (count - 1), height_px)
                 for i in range(count))


def signed(discs, sign_of):
    """Attach a direction sign to each placement: sign_of(index, x, y) -> +1/-1."""
    return tuple((x, y, h, sign_of(i, x, y)) for i, (x, y, h) in enumerate(discs))


W, H = PANEL_SIZE
CW = -1  # positive angles turn counter-clockwise seen from above (right edge swings away)

SCENES = [
    # Kept from the first two batches (pyramid, conveyor and gears predate the 24px floor).
    Scene("row-turn", "four discs, a full turn each beat",
          row([40] * 4), "reset"),
    Scene("pyramid", "sizes rising to the centre, a full turn each beat",
          packed_row([12, 22, 32, 44, 32, 22, 12], gap=8), "reset"),
    Scene("conveyor", "two rows sliding opposite ways, one slot per beat",
          signed(grid(8, 2, 20), lambda i, x, y: 1 if y < H / 2 else -1),
          "conveyor", slide=(W / 8, 0)),
    Scene("tumble", "four discs flipping top over bottom together",
          row([40] * 4), "reset", axis="x"),
    Scene("gears", "checkerboard of discs counter-rotating like gears",
          signed(grid(6, 2, 20), lambda i, x, y: 1 if (i + i // 6) % 2 == 0 else -1), "reset"),
    # Requested.
    Scene("tumble-staggered", "tumble with the flips cascading left to right",
          row([40] * 4), "reset", axis="x", spread=0.4),
    Scene("spin-cw", "five discs spinning clockwise, half a turn per beat",
          signed(row([36] * 5), lambda i, x, y: CW), "spin"),
    Scene("spin-ccw", "two rows spinning counter-clockwise, half a turn per beat",
          grid(5, 2, 24), "spin"),
    Scene("spin-oscillate", "three large discs half-turning out and back on alternate beats",
          row([48] * 3), "oscillate"),
    # Full-panel motion at 24px is the budget ceiling: 7 columns ran at 43 ms/frame
    # (23 fps); 6 columns holds 25 fps at ~38 ms.
    Scene("conveyor-v", "columns sliding alternately up and down, one slot per beat",
          signed(grid(6, 2, 24), lambda i, x, y: 1 if (i % 6) % 2 == 0 else -1),
          "conveyor", slide=(0, H / 2)),
    # New.
    Scene("mirror", "six discs turning, left and right halves mirrored",
          signed(row([32] * 6), lambda i, x, y: 1 if x < W / 2 else -1), "reset"),
    Scene("crescendo", "rising sizes on a shared baseline, spinning together",
          packed_row([24, 31, 38, 44, 50], gap=12, baseline=58), "spin"),
    Scene("tumble-rows", "two rows flipping in opposite directions",
          signed(grid(6, 2, 24), lambda i, x, y: 1 if y < H / 2 else -1), "reset", axis="x"),
    Scene("roll", "a row that spins as it slides along, one slot per beat",
          row([32] * 6), ("conveyor", "spin"), slide=(W / 6, 0)),
    Scene("stairs", "a descending diagonal flipping together",
          diagonal(6, 28, 20, 44), "reset", axis="x"),
    # 6 columns ran at 40 ms/frame (24.5 fps); 5 holds 25 fps at ~38 ms.
    Scene("conveyor-diagonal", "a lattice gliding diagonally, one slot per beat",
          grid(5, 2, 24), "conveyor", slide=(W / 5, H / 2)),
    Scene("insert-disk", "INSERT DISK scrambling in, holding, scrambling out",
          text="INSERT DISK"),
]
SCENES_BY_NAME = {s.name: s for s in SCENES}
DEFAULT_SEQUENCE = [
    "row-turn", "conveyor", "tumble", "mirror", "spin-cw", "conveyor-v", "pyramid",
    "tumble-staggered", "crescendo", "roll", "gears", "spin-oscillate", "tumble-rows",
    "conveyor-diagonal", "spin-ccw", "stairs", "insert-disk",
]


def ease(p):
    return (1 - math.cos(math.pi * p)) / 2


def motions_of(scene):
    return (scene.motion,) if isinstance(scene.motion, str) else scene.motion


def local_progress(scene, p, x_norm):
    """Beat progress for one disc, after the wave stagger."""
    return min(max((p - scene.spread * x_norm) / (1 - scene.spread), 0.0), 1.0)


def pose(scene, q, beat, sign):
    """(angle_deg, dx, dy) for one disc at local progress q."""
    angle, dx, dy = scene.base_deg, 0.0, 0.0
    for m in motions_of(scene):
        if m == "reset":
            angle += 360 * ease(q)
        elif m == "spin":
            angle += 180 * (beat % 2 + ease(q))
        elif m == "oscillate":
            angle += 180 * (ease(q) if beat % 2 == 0 else 1 - ease(q))
        elif m == "conveyor":
            dx += scene.slide[0] * ease(q)
            dy += scene.slide[1] * ease(q)
        else:
            raise ValueError(f"unknown motion {m!r}")
    return sign * angle, sign * dx, sign * dy


def disc_calls(scene, p, beat, size=PANEL_SIZE):
    """[(angle_rad, (x, y), height_px)] to draw, including conveyor wrap copies."""
    w, h = size
    xs = [d[0] for d in scene.discs]
    x_min, x_span = min(xs), (max(xs) - min(xs)) or 1.0
    wraps = "conveyor" in motions_of(scene)
    calls = []
    for d in scene.discs:
        x, y, hp = d[:3]
        sign = d[3] if len(d) > 3 else 1
        angle, dx, dy = pose(scene, local_progress(scene, p, (x - x_min) / x_span), beat, sign)
        x, y = x + dx, y + dy
        x_copies, y_copies = [x], [y]
        if wraps:
            x, y = x % w, y % h
            half_w, half_h = hp * DISC_ASPECT / 2 + 2, hp / 2 + 2
            x_copies = [x] + ([x + w] if x - half_w < 0 else []) + ([x - w] if x + half_w > w else [])
            y_copies = [y] + ([y + h] if y - half_h < 0 else []) + ([y - h] if y + half_h > h else [])
        calls += [(math.radians(angle), xy, hp) for xy in itertools.product(x_copies, y_copies)]
    return calls


def text_now(scene, beat, p, frames_per_beat):
    """The scene's text for this frame: scramble in on the first beat, hold,
    scramble out on the last. Seeded per scene occurrence and frame, so
    stills, GIFs and the panel agree."""
    occurrence, beat_in_scene = divmod(beat, SCENE_BEATS)
    k = round(p * frames_per_beat)
    if 0 < beat_in_scene < SCENE_BEATS - 1:
        return scene.text
    leaving = beat_in_scene == SCENE_BEATS - 1
    # Reveal frames -1 .. fpb-2: all blank at -1, all locked by fpb-2.
    reveal_frame = frames_per_beat - 2 - k if leaving else k - 1
    spans = schedule(scene.text, max(1, frames_per_beat - 2), random.Random(occurrence * 2 + leaving))
    noise = random.Random(occurrence * 100_000 + beat * 1_000 + k)
    return "".join(frame_chars(scene.text, spans, reveal_frame, noise))


def frame_state(sequence, frame, frames_per_beat):
    """(scene, beat number, progress through the beat) for a frame number."""
    beat = frame // frames_per_beat
    scene = sequence[(beat // SCENE_BEATS) % len(sequence)]
    return scene, beat, (frame % frames_per_beat) / frames_per_beat


def render(draw, model, font, scene, p, outline_only, beat=0, frames_per_beat=25, size=PANEL_SIZE):
    draw.rectangle((0, 0, size[0] - 1, size[1] - 1), fill="black")
    if scene.discs:
        for angle, xy, hp in disc_calls(scene, p, beat, size):
            draw_disc(draw, model, angle, xy, hp, outline_only, scene.axis)
    if scene.text:
        # Monospace: position by the full text so scrambling never shifts it.
        width = font.getlength(scene.text)
        draw.text(((size[0] - width) / 2, (size[1] - TEXT_FONT_PX) / 2),
                  text_now(scene, beat, p, frames_per_beat), font=font, fill="white")


def render_stills(out_dir, sequence, outline_only, fractions=(0, 0.25, 0.5, 0.75)):
    model, font = build_model(), load_font(TEXT_FONT_PX)
    out_dir.mkdir(parents=True, exist_ok=True)
    for scene in sequence:
        for p in fractions:
            im = Image.new("RGB", PANEL_SIZE, "black")
            render(ImageDraw.Draw(im), model, font, scene, p, outline_only, beat=1 if scene.text else 0)
            im.save(out_dir / f"{scene.name}_p{p:.2f}.png")
    print(f"wrote {len(sequence) * len(fractions)} stills to {out_dir}")


def render_gif(path, sequence, frames_per_beat, tick, outline_only, scale=2):
    """One loop of the sequence as an animated GIF at the live frame rate."""
    model, font = build_model(), load_font(TEXT_FONT_PX)
    frames = []
    for frame in range(len(sequence) * SCENE_BEATS * frames_per_beat):
        scene, beat, p = frame_state(sequence, frame, frames_per_beat)
        im = Image.new("RGB", PANEL_SIZE, "black")
        render(ImageDraw.Draw(im), model, font, scene, p, outline_only, beat, frames_per_beat)
        frames.append(im.convert("1").resize((PANEL_SIZE[0] * scale, PANEL_SIZE[1] * scale),
                                             Image.NEAREST))
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=round(tick * 1000), loop=0)
    print(f"wrote {len(frames)} frames ({len(frames) * tick:.0f}s) to {path}")


def run_live(sequence, frames_per_beat, tick, outline_only):
    from oled_common import get_device

    model, font = build_model(), load_font(TEXT_FONT_PX)
    device = get_device()
    canvas = Image.new(device.mode, device.size, "black")
    draw = ImageDraw.Draw(canvas)
    print(f"sequence: {','.join(s.name for s in sequence)}")
    print(f"beat {frames_per_beat * tick:.2f}s x {SCENE_BEATS}, tick {tick * 1000:.0f} ms"
          f"{', outline only' if outline_only else ''}. Stop with ./rig stop.")

    def report(scene, frame_ms, wall, cpu):
        print(f"{scene.name}: {len(frame_ms) / wall:.1f} fps, render+push mean "
              f"{sum(frame_ms) / len(frame_ms):.1f} ms, max {max(frame_ms):.1f} ms, "
              f"CPU {cpu / wall * 100:.0f}%")

    frame = 0
    current, current_scene_beat, frame_ms = None, None, []
    start = scene_t = time.perf_counter()
    scene_cpu = time.process_time()
    while True:
        scene, beat, p = frame_state(sequence, frame, frames_per_beat)
        scene_beat = beat // SCENE_BEATS
        if scene_beat != current_scene_beat:
            now, cpu = time.perf_counter(), time.process_time()
            if current is not None:
                report(current, frame_ms, now - scene_t, cpu - scene_cpu)
            current, current_scene_beat, frame_ms, scene_t, scene_cpu = scene, scene_beat, [], now, cpu
        t0 = time.perf_counter()
        render(draw, model, font, scene, p, outline_only, beat, frames_per_beat)
        device.display(canvas)
        frame_ms.append((time.perf_counter() - t0) * 1000)
        frame += 1
        time.sleep(max(0.0, start + frame * tick - time.perf_counter()))


def list_scenes():
    for s in SCENES:
        sizes = sorted({round(d[2]) for d in s.discs})
        motion = "+".join(motions_of(s)) + (", x axis" if s.axis == "x" else "") + \
            (f", spread {s.spread}" if s.spread else "") if s.discs else "text"
        size_text = (f"{len(s.discs):>2} x {'/'.join(map(str, sizes))}px" if s.discs else "text")
        floor = "  [below the 24px floor]" if s.discs and min(sizes) < MIN_DISC_PX else ""
        print(f"{s.name:<18} {size_text:<22} {motion:<26} {s.about}{floor}")


def parse_sequence(text, parser):
    names = [n.strip() for n in text.split(",") if n.strip()]
    unknown = [n for n in names if n not in SCENES_BY_NAME]
    if not names or unknown:
        parser.error(f"unknown scene(s): {', '.join(unknown) or '(none given)'}. "
                     f"Available: {', '.join(SCENES_BY_NAME)}")
    return [SCENES_BY_NAME[n] for n in names]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list-scenes", action="store_true", help="list scene names and exit")
    parser.add_argument("--sequence", metavar="NAMES",
                        help="comma-separated scene names to loop in order "
                             "(default: every scene, ending with insert-disk)")
    parser.add_argument("--beat-seconds", type=float, default=BEAT_SECONDS,
                        help="length of one beat; scales the pace of everything")
    parser.add_argument("--stills", type=Path, metavar="DIR",
                        help="render PNGs at quarter-beat steps per scene instead of running live")
    parser.add_argument("--gif", type=Path, metavar="PATH",
                        help="render one loop as an animated GIF instead of running live")
    parser.add_argument("--tick", type=float, default=TICK, help="seconds per frame")
    parser.add_argument("--outline-only", action="store_true",
                        help="draw only outline + extrusion (no face details)")
    args = parser.parse_args()

    if args.list_scenes:
        list_scenes()
        return
    sequence = parse_sequence(args.sequence or ",".join(DEFAULT_SEQUENCE), parser)
    frames_per_beat = max(1, round(args.beat_seconds / args.tick))
    if args.stills:
        render_stills(args.stills, sequence, args.outline_only)
    elif args.gif:
        render_gif(args.gif, sequence, frames_per_beat, args.tick, args.outline_only)
    else:
        run_live(sequence, frames_per_beat, args.tick, args.outline_only)


if __name__ == "__main__":
    main()
