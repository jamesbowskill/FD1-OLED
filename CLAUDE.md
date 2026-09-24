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
- `fonts/spleen/` — Spleen 6x12 and 8x16 BDF files plus their BSD-2-Clause
  licence, from github.com/fcambus/spleen (commit 57f9219). Other sizes
  there: 5x8, 12x24, 16x32, 32x64. Load with
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
