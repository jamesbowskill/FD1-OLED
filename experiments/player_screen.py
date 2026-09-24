#!/usr/bin/env python3
"""Player screen prototype: all three rows, real fonts, scroll and scramble
triggers, driven by a mock playlist (no mpv/jukebox).

  Row 1  title            Spleen 8x16, full width, scrolls if it overflows
  Row 2  artist | album   Spleen 6x12, full width, scrolls if it overflows
  Row 3  elapsed, progress bar, total, track counter   Spleen 5x8

Scramble rules:
  - Title, total and counter re-scramble on every track change, together;
    a track change interrupts whatever is in flight.
  - Artist | album re-scrambles only if that string actually changed.
  - Elapsed and progress bar never scramble, except once in the initial
    paint when every element scrambles in; after that they reset and
    update silently.
Positions and greys come from James's Figma export (incoming/OLED.png):
rows 1-2 match Spleen renders pixel for pixel; row 3 sits on the same
5px grid, with greys taken from the export.
"""

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

from oled_common import get_device
from scramble_test import SCRAMBLE_TICK, frame_chars, load_font, schedule

# display.py's scroll cadence and speed. Scrolling keeps this pace even
# though the loop ticks at SCRAMBLE_TICK (see CLAUDE.md on the two paces).
SCROLL_TICK = 0.08
SCROLL_PAUSE_DURATION = 1.5
SCROLL_SPEED_PX = 3

TEXT_X = 9
TEXT_WIDTH = 240  # x 9..248: 30 cols at 8px, 40 at 6px, 48 at 5px
ROW1_Y, ROW2_Y, ROW3_Y = 10, 29, 47

WHITE = (255, 255, 255)
PIPE_GREY = (51, 51, 51)
ELAPSED_GREY = (121, 121, 121)
BAR_DONE_GREY = (111, 111, 111)
BAR_TODO_GREY = (48, 48, 48)
TOTAL_GREY = (55, 55, 55)
COUNTER_GREY = (158, 158, 158)

# Row 3 columns on the 5px grid (48 cols from x=9).
ELAPSED_COL = 0
BAR_COL, BAR_LEN = 6, 26
TOTAL_COL = 33
COUNTER_COL, COUNTER_WIDTH = 41, 7  # worst case "999/999"

PLAYLIST = [
    ("Sure Shot", "Beastie Boys", "Ill Communication", 199),
    ("Sabotage", "Beastie Boys", "Ill Communication", 178),
    ("Chicago (Adult Contemporary Easy Listening Version)",
     "Sufjan Stevens", "The Avalanche", 318),
    ("Storm", "Godspeed You! Black Emperor",
     "Lift Your Skinny Fists Like Antennas to Heaven", 1352),
]
# MOCK-ONLY SCAFFOLDING, not part of the design: each track lasts this many
# real seconds, and its elapsed time is sped up to fill the bar in that
# window instead of taking the track's real length.
TRACK_SECONDS = 10.0
STATS_EVERY_S = 10.0


class ScrollState:
    """Ported from fd1-context/display.py: pause at start, scroll left,
    pause at end, snap back. Adapted to run a scramble reveal (scramble_test
    primitive) on each new text first, then hand off to scrolling, and to
    work within a strip `width` px wide starting at x=0."""

    def __init__(self, font, width, reveal_frames, rng):
        self.font = font
        self.width = width
        self.reveal_frames = reveal_frames
        self.rng = rng
        self.text = None
        self.text_width = 0
        self.x = 0
        self.phase = "static"
        self.phase_started_at = 0.0
        self.spans = []
        self.reveal_frame = 0
        self.reveal_last = 0

    def set_text(self, text, force=False):
        """Start a reveal of `text`; skipped if unchanged unless forced."""
        if text == self.text and not force:
            return False
        self.text = text
        self.text_width = self.font.getlength(text)
        self.x = 0
        self.phase = "revealing"
        self.spans = schedule(text, self.reveal_frames, self.rng)
        self.reveal_frame = 0
        self.reveal_last = max((end for _, end in self.spans), default=0)
        return True

    def update_text(self, text):
        """Change the text silently: no reveal restart, no scroll reset."""
        self.text = text

    def visible_text(self):
        """Text to draw this frame; advances an active reveal by one frame."""
        if self.phase != "revealing":
            return self.text
        chars = frame_chars(self.text, self.spans, self.reveal_frame, self.rng)
        self.reveal_frame += 1
        return "".join(chars)

    def tick(self, now, scroll_step):
        if self.phase == "revealing":
            if self.reveal_frame > self.reveal_last:
                overflow = self.text_width > self.width
                self.phase = "pause_start" if overflow else "static"
                self.phase_started_at = now
            return

        max_scroll = self.text_width - self.width

        if self.phase == "pause_start":
            if now - self.phase_started_at >= SCROLL_PAUSE_DURATION:
                self.phase = "scrolling"
        elif self.phase == "scrolling" and scroll_step:
            self.x -= SCROLL_SPEED_PX
            if -self.x >= max_scroll:
                self.x = -max_scroll
                self.phase = "pause_end"
                self.phase_started_at = now
        elif self.phase == "pause_end":
            if now - self.phase_started_at >= SCROLL_PAUSE_DURATION:
                self.phase = "pause_start"
                self.x = 0
                self.phase_started_at = now


def mmss(seconds):
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tick", type=float, default=SCRAMBLE_TICK, help="seconds per frame")
    parser.add_argument("--reveal", type=float, default=1.6, help="seconds per scramble reveal")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--save-frames", type=Path, help="also write each frame as a PNG here")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    fonts = {px: load_font(px) for px in (16, 12, 8)}
    adv8 = int(fonts[8].getlength("0"))
    reveal_frames = max(1, round(args.reveal / args.tick))
    scroll_every = max(1, round(SCROLL_TICK / args.tick))

    title = ScrollState(fonts[16], TEXT_WIDTH, reveal_frames, rng)
    artist_album = ScrollState(fonts[12], TEXT_WIDTH, reveal_frames, rng)
    row3 = {name: ScrollState(fonts[8], TEXT_WIDTH, reveal_frames, rng)
            for name in ("elapsed", "bar", "total", "counter")}

    device = get_device()
    canvas = Image.new(device.mode, device.size, "black")
    draw = ImageDraw.Draw(canvas)
    strips = {16: Image.new(device.mode, (TEXT_WIDTH, 16)), 12: Image.new(device.mode, (TEXT_WIDTH, 12))}
    if args.save_frames:
        args.save_frames.mkdir(parents=True, exist_ok=True)

    def draw_scrolling(state, px, y, pipe_grey=None):
        strip = strips[px]
        sdraw = ImageDraw.Draw(strip)
        sdraw.rectangle((0, 0, strip.width - 1, strip.height - 1), fill="black")
        text = state.visible_text()
        sdraw.text((state.x, 0), text, font=fonts[px], fill=WHITE)
        if pipe_grey and " | " in state.text:
            i = state.text.index(" | ") + 1
            adv = int(fonts[px].getlength("M"))
            cx = state.x + i * adv
            sdraw.rectangle((cx, 0, cx + adv - 1, px - 1), fill="black")
            sdraw.text((cx, 0), text[i], font=fonts[px], fill=pipe_grey)
        canvas.paste(strip, (TEXT_X, y))

    def draw_row3_text(state, col, fill):
        draw.text((TEXT_X + col * adv8, ROW3_Y), state.visible_text(), font=fonts[8], fill=fill)

    track = None
    frame = 0
    frame_ms = []
    start_t = stats_t = time.perf_counter()
    while True:
        t0 = time.perf_counter()
        index = int((t0 - start_t) // TRACK_SECONDS) % len(PLAYLIST)
        name, artist, album, duration = PLAYLIST[index]
        into_track = (t0 - start_t) % TRACK_SECONDS
        elapsed = min(duration, into_track / TRACK_SECONDS * duration)  # mock acceleration
        bar_done = int(elapsed / duration * BAR_LEN)

        if index != track:
            first = track is None
            track = index
            title.set_text(name, force=True)
            row2_changed = artist_album.set_text(f"{artist} | {album}")
            row3["total"].set_text(mmss(duration), force=True)
            row3["counter"].set_text(f"{index + 1}/{len(PLAYLIST)}".rjust(COUNTER_WIDTH), force=True)
            if first:
                row3["elapsed"].set_text(mmss(elapsed), force=True)
                row3["bar"].set_text("/" * BAR_LEN, force=True)
            print(f"track {index + 1}: {name!r}; artist|album "
                  f"{'re-scrambled' if row2_changed else 'unchanged, not re-scrambled'}"
                  f"{'; initial paint, everything scrambles in' if first else ''}")
        row3["elapsed"].update_text(mmss(elapsed))

        draw.rectangle((0, 0, device.width - 1, device.height - 1), fill="black")
        draw_scrolling(title, 16, ROW1_Y)
        draw_scrolling(artist_album, 12, ROW2_Y, pipe_grey=PIPE_GREY)
        draw_row3_text(row3["elapsed"], ELAPSED_COL, ELAPSED_GREY)
        bar = row3["bar"].visible_text()
        draw.text((TEXT_X + BAR_COL * adv8, ROW3_Y), bar, font=fonts[8], fill=BAR_TODO_GREY)
        if bar_done:
            draw.text((TEXT_X + BAR_COL * adv8, ROW3_Y), bar[:bar_done], font=fonts[8], fill=BAR_DONE_GREY)
        draw_row3_text(row3["total"], TOTAL_COL, TOTAL_GREY)
        draw_row3_text(row3["counter"], COUNTER_COL, COUNTER_GREY)

        device.display(canvas)
        frame_ms.append((time.perf_counter() - t0) * 1000)
        if args.save_frames:
            canvas.save(args.save_frames / f"frame_{frame:04d}.png")

        now = time.perf_counter()
        scroll_step = frame % scroll_every == 0
        for state in (title, artist_album, *row3.values()):
            state.tick(now, scroll_step)

        frame += 1
        if now - stats_t >= STATS_EVERY_S:
            print(f"{len(frame_ms) / (now - stats_t):.1f} fps; render+push mean "
                  f"{sum(frame_ms) / len(frame_ms):.1f} ms, max {max(frame_ms):.1f} ms")
            frame_ms.clear()
            stats_t = now
        time.sleep(max(0.0, start_t + frame * args.tick - time.perf_counter()))


if __name__ == "__main__":
    main()
