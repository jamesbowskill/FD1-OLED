#!/usr/bin/env python3
"""Minimal hardware smoke test: draws a greyscale gradient bar."""
from luma.core.interface.serial import spi
from luma.oled.device import ssd1322
from PIL import Image, ImageDraw

serial = spi(port=0, device=0, gpio_DC=5, gpio_RST=6, bus_speed_hz=1000000)
device = ssd1322(serial, mode="RGB", width=256, height=64)

img = Image.new("RGB", (256, 64), "black")
draw = ImageDraw.Draw(img)
# 16 vertical bars sweeping from black to white to check 4-bit greyscale steps
bar_w = 256 // 16
for i in range(16):
    grey = int(i * 255 / 15)
    draw.rectangle([i * bar_w, 0, (i + 1) * bar_w - 1, 63], fill=(grey, grey, grey))

device.display(img)
print("Displayed 16-step greyscale bar. Check the OLED now.")
