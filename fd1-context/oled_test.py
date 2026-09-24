#!/usr/bin/env python3
"""
Polls mpv's IPC socket for the currently playing track and updates
the OLED display whenever it changes. Ctrl+C to exit.
"""

import socket
import json
import os
import time
from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.oled.device import ssd1322

SOCKET_PATH = "/tmp/mpvsocket"
POLL_INTERVAL = 1.0  # seconds between checks


def get_current_track():
    """Query mpv for the currently playing file path via IPC socket."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(SOCKET_PATH)
        command = json.dumps({"command": ["get_property", "path"]}) + "\n"
        s.sendall(command.encode())
        response = s.recv(4096).decode()
        s.close()

        for line in response.splitlines():
            try:
                parsed = json.loads(line)
                if "data" in parsed:
                    return parsed["data"]
            except json.JSONDecodeError:
                continue
        return None
    except Exception:
        return None  # socket not present, mpv not running, etc.


def draw_track(device, filename):
    with canvas(device) as draw:
        draw.rectangle(device.bounding_box, outline="white", fill="black")
        draw.text((4, 20), filename, fill="white")


def main():
    serial = spi(device=0, port=0, gpio_DC=5, gpio_RST=6)
    device = ssd1322(serial)

    last_shown = None

    print("Polling for track changes. Ctrl+C to exit.")

    while True:
        full_path = get_current_track()
        filename = os.path.basename(full_path) if full_path else "Nothing playing"

        if filename != last_shown:
            print(f"Now showing: {filename}")
            draw_track(device, filename)
            last_shown = filename

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting.")#!/usr/bin/env python3
"""
Quick test: read the currently playing track from mpv's IPC socket
and display the filename on the OLED.
"""

import socket
import json
import os
from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.oled.device import ssd1322

SOCKET_PATH = "/tmp/mpvsocket"


def get_current_track():
    """Query mpv for the currently playing file path via IPC socket."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(SOCKET_PATH)
        command = json.dumps({"command": ["get_property", "path"]}) + "\n"
        s.sendall(command.encode())
        response = s.recv(4096).decode()
        s.close()

        # mpv may send other event lines before our actual reply —
        # find the one that has a "data" field, that's our answer
        for line in response.splitlines():
            try:
                parsed = json.loads(line)
                if "data" in parsed:
                    return parsed["data"]
            except json.JSONDecodeError:
                continue
        return None
    except Exception as e:
        print(f"Could not reach mpv: {e}")
        return None


serial = spi(device=0, port=0, gpio_DC=5, gpio_RST=6)
device = ssd1322(serial)

full_path = get_current_track()
filename = os.path.basename(full_path) if full_path else "Nothing playing"

with canvas(device) as draw:
    draw.rectangle(device.bounding_box, outline="white", fill="black")
    draw.text((4, 20), filename, fill="white")

input("Press Enter to exit...")
