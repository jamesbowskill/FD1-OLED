#!/usr/bin/env python3
"""Wireframe floppy disc built from the SVGs in assets/disc/.

Step A (current): render still frames at several angles to PNGs for review.
No panel access yet; the live rotation loop comes once the geometry is
confirmed.

Model (SVG units, 94x98 canvas; +z points toward the viewer):
  outline.svg  at z=0 and z=DISC_DEPTH, joined point-to-point (extrusion)
  front.svg    at z=0
  media.svg    at z=MEDIA_DEPTH (the magnetic disk, recessed in the shell)
  back.svg     at z=DISC_DEPTH, x mirrored (x -> width - x): it was drawn
               as seen with the disc flipped over
"""

import argparse
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "disc"

# Tune by eye on the panel.
DISC_DEPTH = -10.0              # SVG units; exaggerated, real ratio won't read
MEDIA_DEPTH = DISC_DEPTH / 2
LINE_WIDTH = 1
DISC_HEIGHT_PX = 48             # on-screen height of the 98-unit disc face at 0 deg
CAMERA_DISTANCE = 300.0         # SVG units from the disc centre; mild perspective

PANEL_SIZE = (256, 64)
STILL_ANGLES = range(0, 360, 45)

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
    """Return (points3d, edges, (cx, cy, cz)) in SVG units."""
    pts, edges = [], []

    def add(path_pts, closed, z, mirror_width=None):
        start = len(pts)
        for x, y in path_pts:
            pts.append((mirror_width - x if mirror_width else x, y, z))
        n = len(path_pts)
        edges.extend((start + k, start + k + 1) for k in range(n - 1))
        if closed and n > 2:
            edges.append((start + n - 1, start))
        return start

    outline, width, height = load_svg("outline.svg")
    for path_pts, closed in outline:
        front_start = add(path_pts, closed, 0.0)
        back_start = add(path_pts, closed, DISC_DEPTH)
        edges.extend((front_start + k, back_start + k) for k in range(len(path_pts)))
    for path_pts, closed in load_svg("front.svg")[0]:
        add(path_pts, closed, 0.0)
    for path_pts, closed in load_svg("media.svg")[0]:
        add(path_pts, closed, MEDIA_DEPTH)
    for path_pts, closed in load_svg("back.svg")[0]:
        add(path_pts, closed, DISC_DEPTH, mirror_width=width)
    return pts, edges, (width / 2, height / 2, DISC_DEPTH / 2), height


def project(pts, centre, face_height, angle, size=PANEL_SIZE):
    """Rotate around the vertical axis through the disc centre, then
    perspective-project so the z=0 face is DISC_HEIGHT_PX tall at 0 deg."""
    cx, cy, cz = centre
    w, h = size
    scale = DISC_HEIGHT_PX / face_height
    c, s = math.cos(angle), math.sin(angle)
    out = []
    for x, y, z in pts:
        x, y, z = x - cx, y - cy, z - cz
        xr, zr = x * c + z * s, -x * s + z * c
        k = scale * (CAMERA_DISTANCE - (0.0 - cz)) / (CAMERA_DISTANCE - zr)
        out.append((w / 2 + xr * k, h / 2 + y * k))
    return out


def render(draw, proj, edges, size=PANEL_SIZE):
    draw.rectangle((0, 0, size[0] - 1, size[1] - 1), fill="black")
    for a, b in edges:
        draw.line((proj[a], proj[b]), fill="white", width=LINE_WIDTH)


def render_stills(out_dir):
    pts, edges, centre, face_height = build_model()
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for deg in STILL_ANGLES:
        im = Image.new("RGB", PANEL_SIZE, "black")
        render(ImageDraw.Draw(im), project(pts, centre, face_height, math.radians(deg)), edges)
        im.save(out_dir / f"disc_{deg:03d}.png")
        frames.append((deg, im))
    print(f"{len(pts)} points, {len(edges)} edges; wrote {len(frames)} stills to {out_dir}")
    return frames


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", type=Path, help="directory for the still PNGs")
    args = parser.parse_args()
    render_stills(args.out_dir)


if __name__ == "__main__":
    main()
