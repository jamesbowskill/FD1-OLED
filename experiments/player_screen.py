#!/usr/bin/env python3
"""Player screen prototype: all three rows, real fonts, scroll and scramble
triggers, driven by a mock playlist (no mpv/jukebox).

  Row 1  title            TITLE role (Unifont JP), scrolls if it overflows
  Row 2  artist | album   SUB role (M+ 12), scrolls if it overflows; the | is dim
  Row 3  elapsed, progress bar, total, counter in TIMER (Spleen 5x8)

Rows 1-2 match James's Figma mockup of 2026-10-08 (incoming/OLED.png) pixel
for pixel, except that the mockup's Row 2 sits 3/8 px off the pixel grid
(y=26.375) and is anti-aliased; the panel draws it crisp at y=26. Row 3 is
the live design (Spleen 5x8 on a 48-column grid, live greys): the mockup's
Row 3 was a Figma rendering artifact, as Figma has no 8px Spleen.

Scramble rules:
  - Every element scrambles in once, on the initial paint.
  - After that, the title re-scrambles on every track change, interrupting
    whatever is in flight; artist | album re-scrambles only if that string
    actually changed.
  - Row 3 never scrambles again: it resets and updates silently, including
    on track changes.
All display text goes through the role's prepare() (NFC + substitutions)
before it is measured or drawn. Scramble items are drawn at each
character's final position, so double-width text never reflows.

PlayerScreen does the drawing and is importable, so stills can be rendered
offline (experiments/font_stills.py) with exactly the panel's code.
"""

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

from oled_fonts import SUB, TIMER, TITLE
from scramble_test import SCRAMBLE_TICK, WIDE_NOISE_MODES, draw_items, frame_items, schedule

# display.py's scroll cadence and speed. Scrolling keeps this pace even
# though the loop ticks at SCRAMBLE_TICK (see CLAUDE.md on the two paces).
SCROLL_TICK = 0.08
SCROLL_PAUSE_DURATION = 1.5
SCROLL_SPEED_PX = 3

# Rows 1-2: cell top-left positions from the Figma mockup; both clip at x=248.
TEXT_RIGHT = 248
ROW1_X, ROW1_Y = 8, 6
ROW2_X, ROW2_Y = 9, 26
# Row 3: the live layout, TIMER cells on a 48-column grid from x=9.
ROW3_X, ROW3_Y = 9, 47
ELAPSED_COL = 0
BAR_COL, BAR_LEN = 6, 26
TOTAL_COL = 33
COUNTER_COL, COUNTER_WIDTH = 41, 7  # right-aligned in a "999/999" field

# The validated grey tiers (panel level = value // 16; see CLAUDE.md).
WHITE = (255, 255, 255)
MID_GREY = 136  # level 8
TOTAL_GREY = 68  # level 4
# Dim, level 2: the unplayed bar and Row 2's |. (The mockup's white | was a
# Figma omission, not a design change.)
DIM_GREY = 34
DIM = (DIM_GREY,) * 3
# The only defaults for PlayerScreen's greys and the matching --*-grey flags.
DEFAULT_GREYS = {
    "mid_grey": MID_GREY,  # elapsed and counter
    "played_grey": MID_GREY,  # played part of the bar
    "total_grey": TOTAL_GREY,  # total duration
    "pipe_grey": DIM_GREY,  # the | in Row 2
}
# What the mockup used, for the flags' help (try them with the flags).
MOCKUP_GREYS = {"mid_grey": 128, "played_grey": 114, "total_grey": 38, "pipe_grey": 255}

PLAYLIST = [
    ("ネオ東京上空の風", "芸能山城組", "Symphonic Suite AKIRA", 228),
    ("Kaneda", "芸能山城組", "Symphonic Suite AKIRA", 219),
    ("Tong Poo — 東風", "Ryūichi Sakamoto", "Tōkyō Melody", 301),
    ("千と千尋の神隠し サウンドトラック 〜あの夏へ〜 (Live 2008)", "久石譲", "千と千尋の神隠し", 1352),
    ("ｿﾘｯﾄﾞ･ｽﾃｲﾄ･ｻｳﾞｧｲｳﾞｧｰ", "YMO", "髙橋幸宏 Selection — Live", 250),
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

    def __init__(self, role, width, reveal_frames, rng, wide_noise="pair"):
        self.role = role
        self.width = width
        self.reveal_frames = reveal_frames
        self.rng = rng
        self.wide_noise = wide_noise
        self.text = None
        self.offsets = []
        self.text_width = 0
        self.x = 0
        self.phase = "static"
        self.phase_started_at = 0.0
        self.spans = []
        self.reveal_frame = 0
        self.reveal_last = 0

    def set_text(self, text, force=False):
        """Start a reveal of `text`; skipped if unchanged unless forced."""
        text = self.role.prepare(text)
        if text == self.text and not force:
            return False
        self._measure(text)
        self.x = 0
        self.phase = "revealing"
        self.spans = schedule(text, self.reveal_frames, self.rng)
        self.reveal_frame = 0
        self.reveal_last = max((end for _, end in self.spans), default=0)
        return True

    def update_text(self, text):
        """Change the text silently: no reveal restart, no scroll reset."""
        self._measure(self.role.prepare(text))

    def _measure(self, text):
        self.text = text
        self.offsets = self.role.layout(text)
        self.text_width = self.role.font.getlength(text)

    def visible_items(self):
        """Items to draw this frame, or None once the reveal is over (draw
        self.text). Advances an active reveal by one frame."""
        if self.phase != "revealing":
            return None
        items = frame_items(self.text, self.spans, self.reveal_frame, self.rng, self.role,
                            self.wide_noise)
        self.reveal_frame += 1
        return items

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


class PlayerScreen:
    def __init__(self, mode, size, reveal_frames, rng, wide_noise="pair", **greys):
        """greys: any of DEFAULT_GREYS' keys; the rest take their defaults."""
        unknown = set(greys) - set(DEFAULT_GREYS)
        if unknown:
            raise TypeError(f"unknown greys: {sorted(unknown)}")
        greys = {**DEFAULT_GREYS, **greys}
        self.mid = (greys["mid_grey"],) * 3
        self.played = (greys["played_grey"],) * 3
        self.total = (greys["total_grey"],) * 3
        self.pipe = (greys["pipe_grey"],) * 3
        self.canvas = Image.new(mode, size, "black")
        self.draw = ImageDraw.Draw(self.canvas)
        self.title = ScrollState(TITLE, TEXT_RIGHT + 1 - ROW1_X, reveal_frames, rng, wide_noise)
        self.artist_album = ScrollState(SUB, TEXT_RIGHT + 1 - ROW2_X, reveal_frames, rng, wide_noise)
        self.row3 = {name: ScrollState(TIMER, size[0], reveal_frames, rng)
                     for name in ("elapsed", "bar", "total", "counter")}
        self.strips = {
            "title": Image.new(mode, (self.title.width, TITLE.cell_height)),
            "sub": Image.new(mode, (self.artist_album.width, SUB.cell_height)),
        }
        self.bar_done = 0

    def show_track(self, name, artist, album, duration, number, count, first):
        """Returns whether artist | album changed (and so re-scrambles)."""
        self.title.set_text(name, force=True)
        row2_changed = self.artist_album.set_text(f"{artist} | {album}")
        row3_text = {
            "elapsed": mmss(0),
            "bar": "/" * BAR_LEN,
            "total": mmss(duration),
            "counter": f"{number}/{count}".rjust(COUNTER_WIDTH),
        }
        for key, text in row3_text.items():
            if first:
                self.row3[key].set_text(text, force=True)
            else:
                self.row3[key].update_text(text)
        return row2_changed

    def set_elapsed(self, elapsed, duration):
        self.row3["elapsed"].update_text(mmss(elapsed))
        self.bar_done = int(elapsed / duration * BAR_LEN)

    def tick(self, now, scroll_step):
        for state in (self.title, self.artist_album, *self.row3.values()):
            state.tick(now, scroll_step)

    def _draw_scrolling(self, state, strip_name, x, y, pipe=None):
        strip = self.strips[strip_name]
        sdraw = ImageDraw.Draw(strip)
        sdraw.rectangle((0, 0, strip.width - 1, strip.height - 1), fill="black")
        items = state.visible_items()
        if items is None:
            sdraw.text((state.x, 0), state.text, font=state.role.font, fill=WHITE)
        else:
            draw_items(sdraw, (state.x, 0), state.role, state.offsets, items, WHITE)
        # Redraw the | cell (positioned by getlength, via layout) in its own
        # grey, in every phase: settled, scramble reveal and scrolling.
        if pipe and pipe != WHITE and " | " in state.text:
            i = state.text.index(" | ") + 1
            px = state.x + state.offsets[i]
            sdraw.rectangle((px, 0, px + state.role.advance - 1, strip.height - 1), fill="black")
            char = state.text[i] if items is None else items[i]
            if char:
                sdraw.text((px, 0), char, font=state.role.font, fill=pipe)
        self.canvas.paste(strip, (x, y))

    def _draw_row3(self, state, x, y, fill):
        items = state.visible_items()
        if items is None:
            self.draw.text((x, y), state.text, font=state.role.font, fill=fill)
        else:
            draw_items(self.draw, (x, y), state.role, state.offsets, items, fill)

    def render(self):
        w, h = self.canvas.size
        self.draw.rectangle((0, 0, w - 1, h - 1), fill="black")
        self._draw_scrolling(self.title, "title", ROW1_X, ROW1_Y)
        self._draw_scrolling(self.artist_album, "sub", ROW2_X, ROW2_Y, pipe=self.pipe)
        col = TIMER.advance
        self._draw_row3(self.row3["elapsed"], ROW3_X + ELAPSED_COL * col, ROW3_Y, self.mid)
        bar = self.row3["bar"]
        bar_xy = (ROW3_X + BAR_COL * col, ROW3_Y)
        items = bar.visible_items() or list(bar.text)
        draw_items(self.draw, bar_xy, TIMER, bar.offsets, items, DIM)
        if self.bar_done:
            draw_items(self.draw, bar_xy, TIMER, bar.offsets[:self.bar_done],
                       items[:self.bar_done], self.played)
        self._draw_row3(self.row3["total"], ROW3_X + TOTAL_COL * col, ROW3_Y, self.total)
        self._draw_row3(self.row3["counter"], ROW3_X + COUNTER_COL * col, ROW3_Y, self.mid)


GREY_HELP = {
    "mid_grey": "elapsed and counter",
    "played_grey": "played part of the bar",
    "total_grey": "total duration",
    "pipe_grey": "the | in Row 2",
}


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tick", type=float, default=SCRAMBLE_TICK, help="seconds per frame")
    parser.add_argument("--reveal", type=float, default=1.6, help="seconds per scramble reveal")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--save-frames", type=Path, help="also write each frame as a PNG here")
    for name, default in DEFAULT_GREYS.items():
        parser.add_argument(f"--{name.replace('_', '-')}", type=int, default=default,
                            help=f"{GREY_HELP[name]} grey 0-255 (default {default} = level "
                                 f"{default // 16}; mockup {MOCKUP_GREYS[name]})")
    parser.add_argument("--wide-noise", choices=WIDE_NOISE_MODES, default="pair",
                        help="scramble noise in double-width cells")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    greys = {name: getattr(args, name) for name in DEFAULT_GREYS}
    for name, value in greys.items():
        if not 0 <= value <= 255:
            parser.error(f"--{name.replace('_', '-')} must be 0-255")

    from oled_common import get_device

    device = get_device()
    for role in (TITLE, SUB, TIMER):
        role.font  # load now: Unifont takes ~0.6 s, which would stall the first frame
    rng = random.Random(args.seed)
    reveal_frames = max(1, round(args.reveal / args.tick))
    scroll_every = max(1, round(SCROLL_TICK / args.tick))
    screen = PlayerScreen(device.mode, device.size, reveal_frames, rng,
                          wide_noise=args.wide_noise, **greys)
    if args.save_frames:
        args.save_frames.mkdir(parents=True, exist_ok=True)
    print("greys: " + ", ".join(f"{k} {v} (level {v // 16})" for k, v in greys.items())
          + f"; wide-cell noise: {args.wide_noise}")

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

        if index != track:
            first = track is None
            track = index
            changed = screen.show_track(name, artist, album, duration, index + 1, len(PLAYLIST), first)
            print(f"track {index + 1}: {name!r}; artist|album "
                  f"{'re-scrambled' if changed else 'unchanged, not re-scrambled'}"
                  f"{'; initial paint, everything scrambles in' if first else '; row 3 updated silently'}")
        screen.set_elapsed(elapsed, duration)

        screen.render()
        device.display(screen.canvas)
        frame_ms.append((time.perf_counter() - t0) * 1000)
        if args.save_frames:
            screen.canvas.save(args.save_frames / f"frame_{frame:04d}.png")

        now = time.perf_counter()
        screen.tick(now, frame % scroll_every == 0)

        frame += 1
        if now - stats_t >= STATS_EVERY_S:
            print(f"{len(frame_ms) / (now - stats_t):.1f} fps; render+push mean "
                  f"{sum(frame_ms) / len(frame_ms):.1f} ms, max {max(frame_ms):.1f} ms")
            frame_ms.clear()
            stats_t = now
        time.sleep(max(0.0, start_t + frame * args.tick - time.perf_counter()))


if __name__ == "__main__":
    main()
