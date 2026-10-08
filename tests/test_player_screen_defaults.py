"""player_screen.py's grey defaults, checked through the same path the panel
uses: the script's real entry point with no flags, on a fake device.

Run: venv/bin/python3 -m unittest discover tests
"""

import contextlib
import io
import runpy
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "experiments" / "player_screen.py"
sys.path[:0] = [str(ROOT), str(ROOT / "experiments")]

import oled_common  # noqa: E402
import player_screen  # noqa: E402
from oled_fonts import SUB  # noqa: E402

# The validated tiers (CLAUDE.md, "Player screen layout").
VALIDATED = {"mid_grey": 136, "played_grey": 136, "total_grey": 68, "pipe_grey": 34}
CAPTURE_FRAME = 80  # 3.2 s in: track 1's reveal (1.6 s) is over, Row 2 is static


class _Stop(Exception):
    pass


class FakeDevice:
    mode, size, width, height, persist = "RGB", (256, 64), 256, 64, True

    def __init__(self):
        self.frames = 0
        self.captured = None

    def display(self, image):
        self.frames += 1
        if self.frames == CAPTURE_FRAME:
            self.captured = image.copy()
            raise _Stop


def run_entry_point(argv):
    """Run player_screen.py as __main__ with argv on a fake device and a
    fake clock. Returns (stdout, captured frame)."""
    device = FakeDevice()
    clock = [1000.0]
    saved = (time.perf_counter, time.sleep, oled_common.get_device, sys.argv)
    time.perf_counter = lambda: clock[0]
    time.sleep = lambda s: clock.__setitem__(0, clock[0] + max(0.0, s))
    oled_common.get_device = lambda **kwargs: device
    sys.argv = [str(SCRIPT), *argv]
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            runpy.run_path(str(SCRIPT), run_name="__main__")
    except _Stop:
        pass
    finally:
        time.perf_counter, time.sleep, oled_common.get_device, sys.argv = saved
    return out.getvalue(), device.captured


class GreyDefaults(unittest.TestCase):
    def test_constants_are_the_validated_tiers(self):
        self.assertEqual(player_screen.DEFAULT_GREYS, VALIDATED)

    def test_argparse_defaults_match_constants(self):
        args = player_screen.build_parser().parse_args([])
        self.assertEqual({k: getattr(args, k) for k in VALIDATED}, player_screen.DEFAULT_GREYS)

    def test_player_screen_defaults_match_constants(self):
        screen = player_screen.PlayerScreen("RGB", (256, 64), 40, None)
        self.assertEqual(screen.pipe, (34, 34, 34))
        self.assertEqual((screen.mid, screen.played, screen.total),
                         ((136,) * 3, (136,) * 3, (68,) * 3))

    def test_entry_point_no_flags(self):
        stdout, frame = run_entry_point([])
        greys_line = next(line for line in stdout.splitlines() if line.startswith("greys: "))
        for name, value in VALIDATED.items():
            self.assertIn(f"{name} {value} (level {value // 16})", greys_line)

        # The | cell in track 1's Row 2, where the script draws it.
        _, artist, album, _ = player_screen.PLAYLIST[0]
        text = SUB.prepare(f"{artist} | {album}")
        i = text.index(" | ") + 1
        x0 = player_screen.ROW2_X + SUB.layout(text)[i]
        y0 = player_screen.ROW2_Y
        cell = {frame.getpixel((x, y)) for x in range(x0, x0 + SUB.advance)
                for y in range(y0, y0 + SUB.cell_height)}
        self.assertEqual(cell, {(0, 0, 0), (34, 34, 34)}, "the | must be dim (34), never white")

        # Artist and album stay white.
        before = {frame.getpixel((x, y)) for x in range(player_screen.ROW2_X, x0)
                  for y in range(y0, y0 + SUB.cell_height)}
        self.assertIn((255, 255, 255), before)


if __name__ == "__main__":
    unittest.main()
