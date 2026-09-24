#!/usr/bin/env python3
"""Measures the achievable full-frame SSD1322 redraw rate.

Uses the full_frame() framebuffer so every display() call packs and pushes
all 256x64 pixels. The default diff_to_previous() skips unchanged 128x32
segments and would overstate the rate (an identical frame costs no SPI at
all).
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from luma.core.framebuffer import full_frame
from PIL import Image

from oled_common import get_device

DURATION_S = 10.0
SPI_ONLY_DURATION_S = 3.0
WARMUP_FRAMES = 5


def make_frames(size, mode):
    white = Image.new(mode, size, "white")
    black = Image.new(mode, size, "black")
    checker = Image.new(mode, size, "black")
    grey = (128, 128, 128)
    for y in range(size[1]):
        for x in range(y % 2, size[0], 2):
            checker.putpixel((x, y), grey)
    return [white, black, checker]


def main():
    device = get_device(framebuffer=full_frame())
    frames = make_frames(device.size, device.mode)

    for i in range(WARMUP_FRAMES):
        device.display(frames[i % len(frames)])

    print(f"Pushing alternating full frames for {DURATION_S:.0f}s...")
    frame_times = []
    start = time.perf_counter()
    while time.perf_counter() - start < DURATION_S:
        t0 = time.perf_counter()
        device.display(frames[len(frame_times) % len(frames)])
        frame_times.append(time.perf_counter() - t0)
    elapsed = time.perf_counter() - start

    n = len(frame_times)
    ms = sorted(t * 1000 for t in frame_times)
    print(f"Frames:     {n} in {elapsed:.2f}s")
    print(f"FPS:        {n / elapsed:.1f}")
    print(f"ms/frame:   mean {elapsed / n * 1000:.1f}, "
          f"min {ms[0]:.1f}, median {ms[n // 2]:.1f}, max {ms[-1]:.1f}")

    # Same window + byte count as a full frame, but pre-packed, so this is
    # SPI transfer cost alone; the gap to the figure above is Python packing.
    packed = list(bytes(device.width * device.height // 2))
    spi_n = 0
    start = time.perf_counter()
    while time.perf_counter() - start < SPI_ONLY_DURATION_S:
        device._set_position(0, device.width, device.height, 0)
        device.data(packed)
        spi_n += 1
    spi_ms = (time.perf_counter() - start) / spi_n * 1000
    print(f"SPI only:   {spi_ms:.1f} ms/frame ({1000 / spi_ms:.1f} fps ceiling "
          f"if packing were free)")


if __name__ == "__main__":
    main()
