#!/usr/bin/env python3
"""Rotating wireframe floppy disc built from the SVGs in assets/disc/.

Model (SVG units, 94x98 canvas; +z points toward the viewer):
  outline.svg  at z=0 and z=DISC_DEPTH, joined point-to-point (extrusion)
  front.svg    at z=0 (shutter, window, label)
  back.svg     at z=DISC_DEPTH, x mirrored (x -> width - x): it was drawn
               as seen with the disc flipped over (shutter, window, label, hub)

Face gating: the outline and extrusion always draw; front.svg's details
draw only while the front faces the viewer, back.svg's only while the back
does (facing = cos(angle), single-axis rotation), each with FACE_OVERLAP of
slack around edge-on.

Live mode spins at a fixed DEG_PER_FRAME on deadline ticks (not elapsed
time, so frame cost stays honest; see CLAUDE.md). --stills DIR renders PNGs
at 45 degree steps instead, without touching the panel.
"""

import argparse
import math
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "disc"

# Tune by eye on the panel.
DISC_DEPTH = -6.5               # SVG units; exaggerated, real ratio won't read
LINE_WIDTH = 1
FACE_OVERLAP = 0.0              # facing slack at edge-on; >0 shows both groups briefly
DEG_PER_FRAME = 4.8             # 120 deg/s at 25 fps
TICK = 0.04                     # 25 fps
DISC_HEIGHT_PX = 48             # on-screen height of the 98-unit disc face at 0 deg
CAMERA_DISTANCE = 300.0         # SVG units from the disc centre; mild perspective

PANEL_SIZE = (256, 64)
STILL_ANGLES = range(0, 360, 45)
STATS_EVERY_S = 10.0

_TOKEN = re.compile(r"[A-Za-z]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def parse_path(d):
    """Absolute M/L/H/V/Z path data -> [(points, closed)] per subpath."""
    tokens = _TOKEN.findall(d)
    subpaths, pts, closed = [], [], False
    x = y = 0.0
    i = 0
    cmd = None
    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
            if cmd == "Z":
                closed = True
                continue
            if cmd not in "MLHV":
                raise ValueError(f"unsupported SVG path command {cmd!r}")
        if cmd == "M":
            if pts:
                subpaths.append((pts, closed))
            x, y = float(tokens[i]), float(tokens[i + 1])
            pts, closed = [(x, y)], False
            i += 2
            cmd = "L"  # implicit lineto after the first moveto pair
            continue
        if cmd == "L":
            x, y = float(tokens[i]), float(tokens[i + 1])
            i += 2
        elif cmd == "H":
            x = float(tokens[i])
            i += 1
        elif cmd == "V":
            y = float(tokens[i])
            i += 1
        if (x, y) != pts[-1]:
            pts.append((x, y))
    if pts:
        subpaths.append((pts, closed))
    # A closed path that returns to its start before Z shouldn't repeat it.
    return [(p[:-1] if c and len(p) > 1 and p[-1] == p[0] else p, c) for p, c in subpaths]


def load_svg(name):
    root = ET.parse(ASSETS / name).getroot()
    width = float(root.get("viewBox").split()[2])
    height = float(root.get("viewBox").split()[3])
    paths = []
    for el in root.iter("{http://www.w3.org/2000/svg}path"):
        paths += parse_path(el.get("d"))
    return paths, width, height


def build_model():
    """Return (points3d, edge groups, centre, face height) in SVG units.

    Edge groups: "always" (outline + extrusion), "front", "back"."""
    pts = []
    groups = {"always": [], "front": [], "back": []}

    outline, width, height = load_svg("outline.svg")
    ox = [x for p, _ in outline for x, _ in p]
    oy = [y for p, _ in outline for _, y in p]

    def add(group, path_pts, closed, z, mirror_width=None, clamp=False):
        start = len(pts)
        for x, y in path_pts:
            if mirror_width:
                x = mirror_width - x
            if clamp:
                # Figma centres the outline's 1px stroke on half-units (0.5,
                # 97.5); details drawn to the canvas edge (0, 98) would
                # otherwise poke 1px past it face-on.
                x = min(max(x, min(ox)), max(ox))
                y = min(max(y, min(oy)), max(oy))
            pts.append((x, y, z))
        n = len(path_pts)
        groups[group].extend((start + k, start + k + 1) for k in range(n - 1))
        if closed and n > 2:
            groups[group].append((start + n - 1, start))
        return start

    for path_pts, closed in outline:
        front_start = add("always", path_pts, closed, 0.0)
        back_start = add("always", path_pts, closed, DISC_DEPTH)
        groups["always"].extend((front_start + k, back_start + k) for k in range(len(path_pts)))
    for path_pts, closed in load_svg("front.svg")[0]:
        add("front", path_pts, closed, 0.0, clamp=True)
    for path_pts, closed in load_svg("back.svg")[0]:
        add("back", path_pts, closed, DISC_DEPTH, mirror_width=width, clamp=True)
    return pts, groups, (width / 2, height / 2, DISC_DEPTH / 2), height


def visible_edges(groups, angle):
    facing = math.cos(angle)
    edges = list(groups["always"])
    if facing > -FACE_OVERLAP:
        edges += groups["front"]
    if facing < FACE_OVERLAP:
        edges += groups["back"]
    return edges


def project(pts, centre, face_height, angle, screen_xy, height_px):
    """Rotate around the vertical axis through the disc centre, then
    perspective-project so the z=0 face is height_px tall at 0 deg, centred
    on screen_xy."""
    cx, cy, cz = centre
    sx, sy = screen_xy
    scale = height_px / face_height
    c, s = math.cos(angle), math.sin(angle)
    out = []
    for x, y, z in pts:
        x, y, z = x - cx, y - cy, z - cz
        xr, zr = x * c + z * s, -x * s + z * c
        k = scale * (CAMERA_DISTANCE - (0.0 - cz)) / (CAMERA_DISTANCE - zr)
        out.append((sx + xr * k, sy + y * k))
    return out


def draw_disc(draw, model, angle, screen_xy, height_px, outline_only=False):
    """Draw one disc instance (no canvas clear), face-gated unless outline_only."""
    pts, groups, centre, face_height = model
    proj = project(pts, centre, face_height, angle, screen_xy, height_px)
    edges = groups["always"] if outline_only else visible_edges(groups, angle)
    for a, b in edges:
        draw.line((proj[a], proj[b]), fill="white", width=LINE_WIDTH)


def render(draw, model, angle, size=PANEL_SIZE):
    draw.rectangle((0, 0, size[0] - 1, size[1] - 1), fill="black")
    draw_disc(draw, model, angle, (size[0] / 2, size[1] / 2), DISC_HEIGHT_PX)


def render_stills(out_dir, angles=STILL_ANGLES):
    model = build_model()
    out_dir.mkdir(parents=True, exist_ok=True)
    for deg in angles:
        im = Image.new("RGB", PANEL_SIZE, "black")
        render(ImageDraw.Draw(im), model, math.radians(deg))
        im.save(out_dir / f"disc_{deg:05.1f}.png")
    print(f"{len(model[0])} points; wrote {len(angles)} stills to {out_dir}")


def run_live(deg_per_frame, tick):
    from oled_common import get_device

    model = build_model()
    device = get_device()
    canvas = Image.new(device.mode, device.size, "black")
    draw = ImageDraw.Draw(canvas)
    print(f"Spinning at {deg_per_frame} deg/frame, {1 / tick:.0f} fps "
          f"({deg_per_frame / tick:.0f} deg/s). Stop with ./rig stop.")

    frame = 0
    frame_ms = []
    start = stats_t = time.perf_counter()
    cpu0 = time.process_time()
    while True:
        t0 = time.perf_counter()
        render(draw, model, math.radians(frame * deg_per_frame))
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
                        help="render PNGs at 45 degree steps to DIR instead of spinning on the panel")
    parser.add_argument("--deg-per-frame", type=float, default=DEG_PER_FRAME)
    parser.add_argument("--tick", type=float, default=TICK, help="seconds per frame")
    args = parser.parse_args()
    if args.stills:
        render_stills(args.stills)
    else:
        run_live(args.deg_per_frame, args.tick)


if __name__ == "__main__":
    main()
