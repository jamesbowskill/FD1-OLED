#!/usr/bin/env python3
"""Rotating wireframe benchmark: cost of broad per-frame redraw.

Synthetic geometry only (a throwaway proxy, not the real disc), rotated
around the vertical axis with a live rotation matrix, perspective-projected
and drawn with ImageDraw.line() every frame. Cases vary edge count and
on-screen footprint independently.

Each frame rotates by a fixed step: the angle it would turn at
SPIN_DEG_PER_S when running at --pace-fps. With time-based rotation, an
unthrottled loop turns only a fraction of a degree per frame, so luma's diff
sends almost nothing and the fps inflates itself. A fixed step makes every
frame change as much as a real frame at the target rate.

Each case runs twice:
  1. Unthrottled for --duration seconds, like fps_benchmark.py: fps and
     ms/frame, split into draw (rotation maths + ImageDraw) and display
     (luma diff + packing + SPI).
  2. Paced at --pace-fps (deadline ticks, like the scramble scripts): CPU %
     of one core, from the process's own CPU time.
The default diff_to_previous() framebuffer is used except where a case says
full_frame, for comparison with fps_benchmark.py's 22.6 fps baseline.
"""

import argparse
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from luma.core.framebuffer import diff_to_previous, full_frame
from PIL import Image, ImageDraw

from oled_common import get_device

WARMUP_FRAMES = 5
SPIN_DEG_PER_S = 120
TILT_DEG = 20          # fixed pre-tilt so the face reads as 3D; not animated
CAMERA_DISTANCE = 3.0
UNIT_PX = 50           # a 1.0-unit object stays within 64 px while spinning


def box(w, h, d, x=0.0, y=0.0, z=0.0):
    pts = [(x + sx * w / 2, y + sy * h / 2, z + sz * d / 2)
           for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    edges = [(i, j) for i in range(8) for j in range(i + 1, 8)
             if bin(i ^ j).count("1") == 1]
    return pts, edges


def ring(r, n, z, cx=0.0, cy=0.0):
    pts = [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n), z)
           for k in range(n)]
    return pts, [(k, (k + 1) % n) for k in range(n)]


def rect(x0, y0, x1, y1, z):
    return [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)], [(0, 1), (1, 2), (2, 3), (3, 0)]


def merge(*parts):
    pts, edges = [], []
    for p, e in parts:
        edges += [(a + len(pts), b + len(pts)) for a, b in e]
        pts += p
    return pts, edges


def cube():
    return box(0.8, 0.8, 0.8)


def disc_proxy():
    """~Disc complexity: thin body, hub ring, shutter. 24 points, 28 edges."""
    return merge(box(1.0, 1.0, 0.08),
                 ring(0.14, 12, 0.04),
                 rect(-0.3, 0.18, 0.3, 0.5, 0.04))


def dense():
    """Disc proxy plus front/back 48-gons joined by struts: 120 points, 172 edges."""
    pts, edges = merge(ring(0.4, 48, 0.04), ring(0.4, 48, -0.04))
    edges += [(k, k + 48) for k in range(48)]
    return merge(disc_proxy(), (pts, edges))


COPY_SPACING_PX = 64  # x4 cases: four copies, each spinning on its own axis

# (name, model, copies, framebuffer)
CASES = [
    ("cube, centred", cube(), 1, diff_to_previous),
    ("disc proxy, centred", disc_proxy(), 1, diff_to_previous),
    ("dense, centred", dense(), 1, diff_to_previous),
    ("disc proxy x4, full width", disc_proxy(), 4, diff_to_previous),
    ("dense x4, full width", dense(), 4, diff_to_previous),
    ("disc proxy, centred, full_frame", disc_proxy(), 1, full_frame),
]
PACED_CASES = {"disc proxy, centred", "disc proxy x4, full width"}


def tilted(pts):
    c, s = math.cos(math.radians(TILT_DEG)), math.sin(math.radians(TILT_DEG))
    return [(x, y * c - z * s, y * s + z * c) for x, y, z in pts]


def render(draw, size, pts, edges, angle, copies=1):
    """Rotate around Y, perspective-project, draw every edge, per copy."""
    w, h = size
    c, s = math.cos(angle), math.sin(angle)
    focal = UNIT_PX * CAMERA_DISTANCE
    draw.rectangle((0, 0, w - 1, h - 1), fill="black")
    for i in range(copies):
        cx = w / 2 + (i - (copies - 1) / 2) * COPY_SPACING_PX
        proj = []
        for x, y, z in pts:
            xr, zr = x * c + z * s, -x * s + z * c
            k = focal / (zr + CAMERA_DISTANCE)
            proj.append((cx + xr * k, h / 2 - y * k))
        for a, b in edges:
            draw.line((proj[a], proj[b]), fill="white")


def run_case(device, canvas, draw, pts, edges, copies, duration, step, pace_fps=None):
    for i in range(WARMUP_FRAMES):
        render(draw, device.size, pts, edges, i * step, copies)
        device.display(canvas)

    draw_ms, display_ms = [], []
    cpu0 = time.process_time()
    start = time.perf_counter()
    frame = WARMUP_FRAMES
    while time.perf_counter() - start < duration:
        t0 = time.perf_counter()
        render(draw, device.size, pts, edges, frame * step, copies)
        t1 = time.perf_counter()
        device.display(canvas)
        t2 = time.perf_counter()
        draw_ms.append((t1 - t0) * 1000)
        display_ms.append((t2 - t1) * 1000)
        frame += 1
        if pace_fps:
            time.sleep(max(0.0, start + len(draw_ms) / pace_fps - time.perf_counter()))
    elapsed = time.perf_counter() - start
    cpu_pct = (time.process_time() - cpu0) / elapsed * 100
    return len(draw_ms), elapsed, draw_ms, display_ms, cpu_pct


def mean(xs):
    return sum(xs) / len(xs)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--duration", type=float, default=10.0, help="seconds per unthrottled case")
    parser.add_argument("--pace-fps", type=float, default=25.0, help="rate for the CPU %% runs")
    args = parser.parse_args()

    device = get_device()
    canvas = Image.new(device.mode, device.size, "black")
    draw = ImageDraw.Draw(canvas)

    step = math.radians(SPIN_DEG_PER_S) / args.pace_fps
    print(f"Unthrottled, {args.duration:.0f}s per case, {math.degrees(step):.1f} deg/frame "
          f"({SPIN_DEG_PER_S} deg/s at {args.pace_fps:.0f} fps). ms/frame = mean total, split into "
          f"draw (maths + ImageDraw) and display (luma diff + pack + SPI).")
    print(f"{'case':<34}{'pts':>5}{'edges':>6}{'fps':>7}{'mean':>7}{'draw':>7}{'display':>9}"
          f"{'median':>8}{'max':>7}")
    paced = []
    for name, (pts, edges), copies, framebuffer in CASES:
        pts = tilted(pts)
        device.framebuffer = framebuffer()
        n, elapsed, d_ms, p_ms, _ = run_case(device, canvas, draw, pts, edges, copies, args.duration, step)
        total = sorted(a + b for a, b in zip(d_ms, p_ms))
        print(f"{name:<34}{len(pts) * copies:>5}{len(edges) * copies:>6}{n / elapsed:>7.1f}"
              f"{elapsed / n * 1000:>7.1f}{mean(d_ms):>7.1f}{mean(p_ms):>9.1f}"
              f"{total[n // 2]:>8.1f}{total[-1]:>7.1f}", flush=True)
        if name in PACED_CASES:
            device.framebuffer = framebuffer()
            n, elapsed, _, _, cpu = run_case(device, canvas, draw, pts, edges, copies,
                                             args.duration, step, args.pace_fps)
            paced.append(f"{name:<34} {n / elapsed:5.1f} fps held, CPU {cpu:4.0f}% of one core")

    print(f"\nPaced at {args.pace_fps:.0f} fps:")
    for line in paced:
        print(line)


if __name__ == "__main__":
    main()
