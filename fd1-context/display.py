#!/usr/bin/env python3
"""
Floppy Jukebox OLED Display
Reads shared status from jukebox.py and, when playing, queries mpv
directly for the current track's title, artist, and album.

Line 1: track title (falls back to filename via mpv's media-title).
Line 2: artist/album, blank if the file has no such tags.

Either line scrolls independently if its current text is too wide
for the screen: pause at start, scroll left, pause at end, snap back.

Catches SIGTERM (systemd stop/reboot) to show a clean shutdown message,
held briefly since exiting immediately releases GPIO and blanks the
display almost instantly otherwise.
"""

import socket
import json
import os
import time
import signal
import sys
from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.oled.device import ssd1322
from PIL import ImageFont, Image, ImageDraw

STATUS_PATH = "/tmp/jukebox_status.json"
SOCKET_PATH = "/tmp/mpvsocket"
STATUS_POLL_INTERVAL = 1.0
ANIMATION_TICK = 0.08
MAX_MISSES_BEFORE_FALLBACK = 4
ACTIVITY_PATH = "/tmp/controls_activity"
SLEEP_TIMEOUT = 300  # seconds of inactivity

SCROLL_PAUSE_DURATION = 1.5
SCROLL_SPEED_PX = 3

LINE1_Y = 12
LINE2_Y = 34
LEFT_MARGIN = 4
RIGHT_MARGIN = 4

STATE_MESSAGES = {
    "no_drive": "No floppy drive found",
    "waiting": "Insert disk to play",
    "mounting": "Reading disk...",
    "blank": "Disk is blank",
    "mount_error": "Disk can't be read",
    "finished": "Disk finished - press play to restart",
}

device = None
font = ImageFont.load_default()

_measure_image = Image.new("1", (1, 1))
measuring_draw = ImageDraw.Draw(_measure_image)


def read_status():
    try:
        with open(STATUS_PATH, "r") as f:
            data = json.load(f)
        return data.get("state", "waiting")
    except (FileNotFoundError, json.JSONDecodeError):
        return "waiting"


def query_mpv(property_name):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(SOCKET_PATH)
        command = json.dumps({"command": ["get_property", property_name]}) + "\n"
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
        return None

def is_actually_playing():
    """Distinguishes actively playing from paused — jukebox.py's status
    file doesn't know about pause, since that's handled directly between
    controls.py and mpv."""
    paused = query_mpv("pause")
    return paused is False  # None (mpv not running) or True both count as "not playing"


def get_current_track_title():
    """media-title prefers embedded metadata and automatically falls
    back to filename if a file has no tags — no separate tag-reading
    code needed on our side."""
    title = query_mpv("media-title")
    if title:
        return title
    path = query_mpv("path")
    return os.path.basename(path) if path else None


def get_artist_and_album():
    """Reads mpv's generic metadata dict and matches keys case-insensitively,
    since different formats (m4a vs mp3) can report tag names differently."""
    metadata = query_mpv("metadata")
    if not isinstance(metadata, dict):
        return None, None

    lower_map = {k.lower(): v for k, v in metadata.items()}
    artist = lower_map.get("artist")
    album = lower_map.get("album")
    return artist, album


def get_last_activity_time():
    """Returns the most recent of: last button press, or this file's own
    mtime as a fallback if it doesn't exist yet (treated as 'long ago')."""
    try:
        return os.path.getmtime(ACTIVITY_PATH)
    except FileNotFoundError:
        return 0.0


class ScrollState:
    """Tracks bounce-scroll animation for whatever text is currently shown
    on one line. Resets automatically whenever the text changes."""

    def __init__(self, y):
        self.y = y
        self.text = None
        self.text_width = 0
        self.x = LEFT_MARGIN
        self.phase = "static"
        self.phase_started_at = 0.0

    def set_text(self, text):
        if text == self.text:
            return False
        self.text = text
        self.text_width = measuring_draw.textlength(text, font=font) if text else 0

        available_width = device.width - LEFT_MARGIN - RIGHT_MARGIN
        if self.text_width <= available_width:
            self.phase = "static"
            self.x = LEFT_MARGIN
        else:
            self.phase = "pause_start"
            self.x = LEFT_MARGIN
            self.phase_started_at = time.time()
        return True

    def tick(self):
        if self.phase == "static":
            return False

        now = time.time()
        available_width = device.width - LEFT_MARGIN - RIGHT_MARGIN
        max_scroll = self.text_width - available_width

        if self.phase == "pause_start":
            if now - self.phase_started_at >= SCROLL_PAUSE_DURATION:
                self.phase = "scrolling"
            return False

        if self.phase == "scrolling":
            self.x -= SCROLL_SPEED_PX
            if LEFT_MARGIN - self.x >= max_scroll:
                self.x = LEFT_MARGIN - max_scroll
                self.phase = "pause_end"
                self.phase_started_at = now
            return True

        if self.phase == "pause_end":
            if now - self.phase_started_at >= SCROLL_PAUSE_DURATION:
                self.phase = "pause_start"
                self.x = LEFT_MARGIN
                self.phase_started_at = now
                return True
            return False

        return False

    def draw(self, draw):
        if self.text:
            draw.text((self.x, self.y), self.text, fill="white", font=font)


line1 = None  # track title
line2 = None  # artist / album, rotating


def draw_frame():
    with canvas(device) as draw:
        draw.rectangle(device.bounding_box, outline="white", fill="black")
        line1.draw(draw)
        line2.draw(draw)


def handle_shutdown(signum, frame):
    if device is not None:
        try:
            with canvas(device) as draw:
                draw.rectangle(device.bounding_box, outline="white", fill="black")
                draw.text((LEFT_MARGIN, LINE1_Y), "Shutting down...", fill="white", font=font)
            time.sleep(2)
        except Exception:
            pass
    sys.exit(0)


def main():
    global device, line1, line2
    serial = spi(device=0, port=0, gpio_DC=5, gpio_RST=6)
    device = ssd1322(serial)
    line1 = ScrollState(LINE1_Y)
    line2 = ScrollState(LINE2_Y)
    last_activity_seen = time.time()  # start awake
    is_asleep = False

    signal.signal(signal.SIGTERM, handle_shutdown)

    consecutive_misses = 0
    last_status_check = 0.0

    print("Display service running. Ctrl+C to exit.")

    while True:
        now = time.time()
        redraw_needed = False

        if now - last_status_check >= STATUS_POLL_INTERVAL:
            last_status_check = now
            state = read_status()

                        # --- Wake/sleep logic ---
            button_activity = get_last_activity_time()
            if button_activity > last_activity_seen:
                last_activity_seen = button_activity

            # "finished" is idle in the same sense as waiting/no_drive -- a
            # disk sitting there having completed isn't "activity", and
            # excluding it lets the sleep timer actually count down instead
            # of resetting every poll tick forever. Physical button presses
            # still wake the display independently, via button_activity above.
            is_active_state = state not in ("waiting", "no_drive", "finished") and (state != "playing" or is_actually_playing())
            if is_active_state:
                last_activity_seen = now  # any non-idle state counts as activity

            should_sleep = (now - last_activity_seen) >= SLEEP_TIMEOUT

            if should_sleep and not is_asleep:
                is_asleep = True
                with canvas(device) as draw:
                    pass  # blank frame — screen goes dark
                print("Display sleeping (idle timeout)")

            if not should_sleep and is_asleep:
                is_asleep = False
                redraw_needed = True  # force a real redraw to wake visually
                print("Display waking")

            if state == "playing":
                title = get_current_track_title()
                if title:
                    consecutive_misses = 0
                    title_text = title
                else:
                    consecutive_misses += 1
                    title_text = None if consecutive_misses < MAX_MISSES_BEFORE_FALLBACK else "Nothing playing"

                if title_text is not None and title_text != line1.text:
                    print(f"State: {state} -> showing: {title_text}")
                    if line1.set_text(title_text):
                        redraw_needed = True

                # --- Artist + Album combined on one line ---
                artist, album = get_artist_and_album()
                if artist and album:
                    candidate = f"{artist} | {album}"
                else:
                    candidate = artist or album  # fall back to whichever exists, or None if neither

                if line2.set_text(candidate):
                    redraw_needed = True

            else:
                consecutive_misses = 0
                text = STATE_MESSAGES.get(state, state)
                if line1.set_text(text):
                    redraw_needed = True
                if line2.set_text(None):
                    redraw_needed = True

        if line1.tick():
            redraw_needed = True
        if line2.tick():
            redraw_needed = True

        if redraw_needed and not is_asleep:
            draw_frame()

        time.sleep(ANIMATION_TICK)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting.")
        if device is not None:
            with canvas(device) as draw:
                draw.rectangle(device.bounding_box, outline="white", fill="black")
                draw.text((LEFT_MARGIN, LINE1_Y), "Shutting down...", fill="white", font=font)
