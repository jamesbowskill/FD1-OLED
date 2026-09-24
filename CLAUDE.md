# OLED preview rig ("bubblegum")

Second OLED preview rig, separate from the FD1 prototype (`fd1-context/` holds
a read-only copy of FD1's own project docs and reference scripts for
comparison — SSD1322 wiring there is confirmed-working and matches this
rig's wiring, which has also been physically verified).

- `watcher.py` — watches `~/oled/incoming` for new/changed PNGs, validates
  exactly 256x64, converts to the device's native mode, and calls
  `device.display()` directly (no `canvas()`, no 1-bit thresholding — the
  panel's 4-bit greyscale steps are preserved). On startup, if `incoming/`
  has no `.png` files yet, it shows `~/oled/default.png` (the 16-step
  greyscale test bar) instead of leaving the screen blank — this only
  checks at startup, not on every file removal, so emptying `incoming/`
  afterward doesn't bring the default back until the next restart.
- `oled_common.py` — shared setup every script should use instead of its own
  init: `get_device()` returns a configured `ssd1322` (this rig's wiring,
  `persist=True`; extra kwargs such as `framebuffer=` pass through) and
  calls `check_gpio_free()` first, which raises with the holding PID if
  `/dev/gpiochip0` is already in use.
- `experiments/` — scratch space for one-off tests. Things that prove out
  graduate to top-level scripts; things that don't can stay here or be
  deleted later. Scripts here add the repo root to `sys.path` to import
  `oled_common`.
- `fonts/spleen/` — Spleen 5x8, 6x12 and 8x16 BDF files plus their
  BSD-2-Clause licence, from github.com/fcambus/spleen (commit 57f9219).
  Other sizes there: 12x24, 16x32, 32x64. 5x8 has a 5 px advance and an
  8 px cell (7 ascent + 1 descent); its `/` is a full-cell diagonal, so a
  run of slashes forms a continuous hatch on a 5 px pitch. Load with
  `ImageFont.truetype("…/spleen-8x16.bdf", size=16)`: FreeType reads BDF
  natively and rejects any size but the native one, so the font can't be
  scaled by accident. `ImageFont.load()` on a raw `.bdf` does **not**
  work (it wants Pillow's `.pil` format; FD1's HARDWARE.md says otherwise
  and is wrong). Rendering is pure black/white with no anti-aliasing,
  fixed advance (6 px / 8 px), and cells of 12 px (9 ascent + 3 descent)
  or 16 px (12 + 4).
- `venv/` — Python venv with `luma.core`, `luma.oled`, `Pillow`, `watchdog`,
  etc. Always run scripts with `venv/bin/python3`, not system Python.
- `rig` — picks which utility owns the OLED, one at a time. Nothing starts
  on boot; run what you need explicitly:
  - `./rig run <script> [args]` — stops whatever currently holds the OLED,
    then starts `<script>` detached (`setsid nohup`, survives SSH
    disconnects), logging to `logs/<name>.log`. Looks for `<script>` in the
    repo root, then `experiments/`, so `./rig run watcher.py` and
    `./rig run fps_benchmark.py` both work.
  - `./rig stop` — stops the rig-managed script, plus any other process
    still holding `/dev/gpiochip0` (e.g. a script started by hand).
  - `./rig status` — what's running (or last ran), its log, and whether the
    GPIO chip is free.
  State lives in `run/current`; `run/` and `logs/` are gitignored.
- `oled-watcher.service` (`/etc/systemd/system/oled-watcher.service`) — the
  old always-on way of running `watcher.py`. Now **disabled and stopped**
  in favour of `rig`; the unit file is kept but would compete with `rig`
  for the GPIO chip if re-enabled. It runs as user `jbtokyo`, not root
  (this rig deliberately doesn't run as root, unlike FD1's four services;
  `jbtokyo`'s `spi`/`gpio`/`i2c` group membership covers access instead).


## Figma → OLED pipeline (Syncthing)

Figma exports sync automatically from the Mac to `~/oled/incoming` on this Pi, where `watcher.py` picks them up (only while it's running: `./rig run watcher.py`). Round trip is ~12 seconds, Figma export to OLED.

- **Mac side**: Syncthing app (`syncthing-app` cask), folder `/Volumes/Neptune/FD1/design/OLED/export`, type **Send Only**.
- **Pi side**: Syncthing installed via apt (official keyring-based repo, not the deprecated `apt-key` method), running as a `--user` systemd service under `jbtokyo` (`systemctl --user status syncthing.service`). Linger is enabled (`loginctl enable-linger jbtokyo`) so it keeps running without an active SSH session. Folder `~/oled/incoming`, type **Receive Only** — deliberately one-way, so nothing on the Pi (test files, leftovers) can sync back and pollute the Mac's export folder.
- Both folders have **Watch for Changes** enabled — near-instant sync on save, not a periodic rescan.

**Reaching bubblegum's Syncthing UI**: it only listens on `127.0.0.1:8384` (localhost-only by default), so it's not reachable directly from the Mac's browser. Tunnel it over SSH when needed (e.g. re-pairing, checking sync status):

```bash
ssh -L 8385:127.0.0.1:8384 jbtokyo@bubblegum.local
```

Then open `http://localhost:8385` on the Mac. (Port 8385 locally, not 8384, to avoid colliding with the Mac's own Syncthing UI.)

**Re-pairing from scratch** (e.g. new Mac, reinstalled Syncthing): each side needs the other's Device ID (**Actions → Show ID** in the UI) added as a remote device, and each side has to separately accept the resulting connection request — adding the ID on one side isn't enough on its own.


## Measured SSD1322 redraw rate (`experiments/fps_benchmark.py`, 2026-09-24)

On this Pi 3B+ at luma's default 8 MHz SPI clock, full-frame pushes
(`full_frame()` framebuffer, 256x64) run at **22.6 fps, 44 ms/frame**
(median 44.4 ms, range about 31–67 ms). This was the same across three
separate runs.

- **The bottleneck is Python, not SPI.** A pre-packed full-frame SPI push
  takes about 9 ms (about 111 fps ceiling). The other about 35 ms is
  `luma.oled`'s pure-Python per-pixel RGB→4-bit packing loop
  (`greyscale_device._render_greyscale`), about 77% of frame time in a
  cProfile run. Raising the SPI clock can't lift the full-frame rate
  much; faster packing (e.g. numpy) is the bigger lever.
- **Partial redraw is already supported by the chip and done by luma.** The
  SSD1322 accepts writes to a column/row window, and luma's default
  `diff_to_previous()` framebuffer only pushes changed regions (diffed on a
  2x2 grid of 128x32 segments, then trimmed to the changed box). A 64x16
  region toggling ran at about 250 fps (4 ms/frame) in a one-off probe.
  An identical frame costs about 0.5 ms and sends nothing over SPI.
- Per-frame time depends on content: black pixels skip work in the packing
  loop, so all-black frames are faster than bright or busy ones.

## Rotating wireframe cost (`experiments/wireframe_benchmark.py`, 2026-09-24)

Synthetic stand-in geometry (not the real disc). It rotates at 120°/s
around the vertical axis with a live rotation matrix and perspective, is
drawn with `ImageDraw.line()` each frame, and uses luma's default diffing.
Measured on the Pi 3B+:

| Case | Edges | Max fps | ms/frame (draw + display) | CPU at 25 fps |
|---|---|---|---|---|
| Disc-sized proxy, centred (about 56x60 px) | 28 | 128 | 7.8 (0.4 + 7.4) | about 23% |
| Dense proxy, centred | 172 | 102 | 9.8 (1.7 + 8.0) | |
| Four disc proxies across the full width | 112 | 34.5 | 29.0 (1.2 + 27.8) | about 58% |
| Four dense proxies across the full width | 688 | 28 | 35.5 (6.2 + 29.2) | |
| Disc proxy, centred, `full_frame()` | 28 | 31 | 31.9 | |

- **On-screen footprint sets the cost, not edge count.** The expensive part
  is luma packing the changed region; the rotation maths and Pillow's line
  drawing are about 0.4 ms for disc-level geometry. Six times the edges at
  the same footprint adds about 2 ms. Four copies across the width cost
  nearly four times as much as one centred copy.
- **A single centred disc (at most 64 px) is cheap**, at about 5x the
  headroom needed for 25 fps. Full redraw of the canvas each frame with
  luma's diffing is enough; no special strategy is needed.
- **Broad full-width motion approaches full-frame cost** (about 30–36 ms),
  so it only just holds 25 fps, like the busy-state background.
- **Mostly-black line art is cheaper to pack than solid frames.** A full
  frame of wireframe costs about 32 ms (31 fps), against 44 ms for
  fps_benchmark's alternating solid frames.
- **Benchmark method: move by a fixed amount per frame, not by elapsed
  time.** With time-based motion, an unthrottled loop moves only a fraction
  of a degree per frame, so luma's diff sends almost nothing and fps
  inflates itself. The first run of this benchmark reported 319 fps for the
  disc, versus 128 fps with a fixed 4.8° per frame (the per-frame step at
  25 fps).

## Wireframe floppy disc (`experiments/wireframe_disc.py`)

A rotating 3D wireframe built live from `assets/disc/*.svg`, a 94x98
canvas with absolute M/L/H/V/Z paths only, read by a small hand-rolled
parser.

- **Model:**
  - `outline.svg` at z=0 and z=`DISC_DEPTH`, joined point-to-point.
  - `front.svg` at z=0: shutter, window, tall label (y 45–98).
  - `back.svg` at `DISC_DEPTH`, x mirrored (`94 - x`), because it was drawn
    as seen with the disc flipped over: shutter, window, short label strip
    (y 83–98), hub. After mirroring, its shutter and window land exactly
    on the front's, and both labels are centred (x 10–84).
  - 62 points, 63 edges; +z points toward the viewer.
  - The design is opaque: the earlier `media.svg` (a visible magnetic
    disc) was dropped.
- **Face gating:** outline and extrusion always draw. `front.svg` draws
  while `cos(angle) > -FACE_OVERLAP`, and `back.svg` while
  `cos(angle) < FACE_OVERLAP`. Without gating, both faces' details showed
  through at once and angled views were cluttered. `FACE_OVERLAP` defaults
  to 0 (a hard swap at edge-on): in captured frames, 0.1 drew both groups
  squashed into the edge-on sliver, making a white clump.
- **Detail points are clamped to the outline's bounds.** Figma centres
  the outline's 1 px stroke on half-units (0.5, 97.5), while details are
  drawn to the canvas edge (0, 98). Unclamped, the shutter tops and label
  bottoms poked 1 px past the outline when face-on.
- **Tuning constants at the top of the file:** `DISC_DEPTH` (-6.5),
  `LINE_WIDTH`, `FACE_OVERLAP`, `DEG_PER_FRAME` (4.8, i.e. 120°/s at
  25 fps), `DISC_HEIGHT_PX` (48), `CAMERA_DISTANCE`.
  - `DISC_DEPTH` -6.5 gives a clean 4 px edge-on sliver.
  - -7 rounds to 6 px, and the front details squashed into the sliver
    show as stray fragments.
- **Performance at 25 fps on the Pi 3B+:** about 9–11 ms per frame, about
  20–25% of one core.
- **Checking geometry changes:** `--stills DIR` renders PNGs at 45° steps
  without the panel.

## Animation pace: scramble-decode and scrolling need different ticks

On the real panel, the scramble-decode reveal
(`experiments/scramble_test.py`) looks right at a **0.04 s tick (~25 fps)**.
At display.py's scroll cadence (`ANIMATION_TICK = 0.08`, ~12.5 fps) it
looked too slow and chunky. A faster global tick alone fixed it;
per-position randomised noise timing was considered and not needed.

These are two animation types with two natural paces, not one shared
constant. Don't "just reuse `ANIMATION_TICK`" for the scramble effect;
it will quietly feel slow again. The scramble script names its own
`SCRAMBLE_TICK` for this reason. Both paces are far below the hardware
limit: a text-sized region redraws in about 5–6 ms.

## Player screen layout (`experiments/player_screen.py`)

Positions measured from James's Figma export (`incoming/OLED.png`). Rows
1–2 of the export match Spleen renders pixel for pixel, and the
prototype's rows 1–2 match the export exactly.

- **Text area:** x 9–248 (240 px = 30 cols at 8 px, 40 at 6 px, 48 at 5 px).
- **Greys, four tiers:**

  | Tier | Grey | Used for |
  |---|---|---|
  | White | 255 | Row 1 and Row 2 text only |
  | Mid | `--mid-grey`, default 136 (level 8) | elapsed, played bar, counter |
  | Total | `--total-grey`, default 68 (level 4) | total duration |
  | Dim | 34 (level 2, validated) | unplayed bar, Row 2's `\|` |

  Nothing in Row 3 is white, so it doesn't compete with the title. The mid
  and total defaults are starting points for judging on the panel. Choose
  values by eye with the flags, then fold the chosen ones in as defaults.
- **Row 1:** title, 8x16, cell y 10, white.
- **Row 2:** `artist | album`, 6x12, cell y 29, white. The `|` is Spleen's
  own glyph in dim.
- **Row 3:** 5x8, cell y 47, on a 48-column grid:

  | Element | Columns | Tier |
  |---|---|---|
  | Elapsed | 0–4 | mid |
  | Progress bar | 6–31 (26 slashes) | mid played, dim remaining |
  | Total | 33–37 | total |
  | Counter, right-aligned in a "999/999" field | 41–47 | mid |
- **Scrambles:**
  - Every element scrambles in once, on the first paint.
  - After that, the title re-scrambles on every track change, and
    `artist | album` only when that string changes (ScrollState's
    `set_text` dirty-check).
  - Row 3 never scrambles after the first paint. It resets and updates
    silently, including on track changes.
- **Scrolling** is ported from FD1's `ScrollState` and keeps display.py's
  pace (3 px per 0.08 s, 1.5 s pauses) by stepping on every 2nd tick of
  the 0.04 s scramble loop. Each row is clipped to the text area.

Two corrections made after watching the panel (2026-09-24):
1. **Counter and total no longer scramble on track change.** The first
   version re-scrambled them alongside the title. They now follow the same
   rule as elapsed and the bar, which leaves Row 3 calm and the title (plus
   `artist | album` when it changes) as the only thing that moves on a
   track change.
2. **The dim greys are now the validated level 2.** Row 3's first greys
   (121, 111, 48, 55, 158) were peak values read off an anti-aliased Figma
   export, not tested on the panel, and the `|` used Figma's 51 (level 3,
   which the busy-state test found too bright). The dim elements (remaining
   bar, total, `|`) now use (34,34,34), the grey validated for the
   busy-state background; elapsed, the played bar and the counter are
   white. Level 2 was validated as background texture, so check that the
   total duration is still easy enough to read at 5x8.

## Grey levels and fullscreen animation cost

- luma maps an RGB grey value `v` to panel level `floor(v / 16)`
  (`greyscale_device._render_greyscale`), so level 3 is 48–63 and level 2
  is 32–47; e.g. (51,51,51) is level 3 and (34,34,34) is level 2.
- **Dim background grey: use level 2 (34,34,34), not level 3.** Level 3
  (51,51,51) came from rounding Figma's 15% opacity up to the nearest
  panel level. Compared side by side on the panel, it looked brighter than
  intended and less refined; level 2 looked more premium and is the
  validated choice. Don't convert Figma opacities to panel levels by
  proportion. This is likely because luma sets up the SSD1322 with its
  linear greyscale table (`0xB9`), while Figma blends in gamma-encoded
  sRGB. That explanation fits what was seen but hasn't been measured, so
  judge greys on the panel.
- **Busy-state background (`experiments/scramble_bg_test.py`), validated
  defaults:** `--bg-interval 2`, `--bg-fraction 0.15` (32 of 210 cells
  change every 2nd tick), `--bg-grey 34`, with the status reveal every
  tick at 0.04 s. Alternatives looked worse on the panel:
  - every cell on every tick: "panic-inducing";
  - `--bg-interval 1`: too busy and intense;
  - `--bg-interval 8 --bg-fraction 0.08`: too pedestrian.

  The interval was the main lever for both how fast it feels and CPU
  cost; the fraction mattered less.
- **What that costs on a Pi 3B+, all at 25 fps:**

  | Background | Mean per frame | CPU (one core) |
  |---|---|---|
  | All cells every tick | 39.7 ms | about 81% |
  | **Validated: 32 cells every 2 ticks, grey 34** | **about 19 ms** | **about 36–40%** |
  | 32 cells every 4 ticks | 12 ms | about 25% |
  | 17 cells every 8 ticks | 8 ms | about 16% |
- **Scattered changes cost close to a full frame whatever the fraction.**
  luma's diffing sends one bounding box per 128x32 quarter of the screen,
  so a refresh tick with only 15% of cells changing still costs about
  28–34 ms (versus about 40 ms for all cells). Ticks with no background
  change cost about 4.5 ms. The grey level doesn't affect cost (any
  non-black pixel takes the same path in luma's packing loop).

## luma.core blanks the display on process exit unless `persist=True`

`luma.core.device.device.__init__` registers an `atexit` hook that calls
`self.cleanup()` when the process exits. `cleanup()` calls `self.hide()` and
`self.clear()` unless `self.persist` is `True` — so **any one-shot script
that calls `device.display()` and then exits will blank the screen again
immediately after**, with no exception and nothing in the logs.

This cost a long debugging session on this rig: hardware, wiring, SPI,
GPIO permissions, and the venv install were all fine the whole time. Every
quick test script exited right after printing "check the screen now",
which silently blanked the display before it could be observed.
`fd1-context/oled_test.py` appeared to "work" specifically because it ends
with a blocking `input("Press Enter to exit...")` — it never hit the
`atexit` hook while anyone was watching. A short-lived script only proves
anything if you either pause it before exit (e.g. `time.sleep(15)`) or run
it in the background and check the screen while it's still alive.

`oled_common.get_device()` sets `device.persist = True` (with a comment
pointing back here), so every script that uses it is covered, including
one-shot experiments. Don't build a device by hand with `spi()`/`ssd1322()`
in new scripts. Use `get_device()` so the guard can't be dropped by
accident.
