#!/usr/bin/env python3
"""Exact match of fd1-context/oled_test.py's device init (no explicit
bus_speed_hz, mode, width, height overrides) with the same greyscale
bar test pattern, to isolate whether bus_speed_hz=1000000 was the fault."""
from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.oled.device import ssd1322

serial = spi(device=0, port=0, gpio_DC=5, gpio_RST=6)
device = ssd1322(serial)

with canvas(device) as draw:
    draw.rectangle(device.bounding_box, outline="white", fill="black")
    bar_w = 256 // 16
    for i in range(16):
        grey = int(i * 255 / 15)
        draw.rectangle([i * bar_w, 0, (i + 1) * bar_w - 1, 63], fill=(grey, grey, grey))

print("Displayed 16-step greyscale bar using reference-exact init. Check the OLED now.")
