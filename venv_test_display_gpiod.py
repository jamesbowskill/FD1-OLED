#!/usr/bin/env python3
"""Same greyscale test as venv_test_display.py, but drives DC/RST via native
gpiod (libgpiod v2) instead of RPi.GPIO/rpi-lgpio, to isolate whether the
GPIO compatibility shim is the fault on this OS/kernel.
"""
import gpiod
from gpiod.line import Direction, Value
from luma.core.interface.serial import spi
from luma.oled.device import ssd1322
from PIL import Image, ImageDraw

CHIP = "/dev/gpiochip0"
DC_LINE = 5
RST_LINE = 6


class GpiodAdapter:
    BCM = "BCM"
    OUT = Direction.OUTPUT
    LOW = Value.INACTIVE
    HIGH = Value.ACTIVE

    def __init__(self, pins):
        self._chip = gpiod.Chip(CHIP)
        settings = gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.INACTIVE)
        self._request = self._chip.request_lines(
            consumer="oled-test",
            config={pin: settings for pin in pins},
        )

    def setup(self, pin, direction):
        pass  # lines already requested as outputs in __init__

    def output(self, pin, value):
        v = Value.ACTIVE if value else Value.INACTIVE
        self._request.set_value(pin, v)

    def cleanup(self):
        if self._request:
            self._request.release()
        self._chip.close()


gpio = GpiodAdapter([DC_LINE, RST_LINE])
serial = spi(port=0, device=0, gpio=gpio, gpio_DC=DC_LINE, gpio_RST=RST_LINE, bus_speed_hz=1000000)
device = ssd1322(serial, mode="RGB", width=256, height=64)

img = Image.new("RGB", (256, 64), "black")
draw = ImageDraw.Draw(img)
bar_w = 256 // 16
for i in range(16):
    grey = int(i * 255 / 15)
    draw.rectangle([i * bar_w, 0, (i + 1) * bar_w - 1, 63], fill=(grey, grey, grey))

device.display(img)
print("Displayed 16-step greyscale bar via native gpiod. Check the OLED now.")
