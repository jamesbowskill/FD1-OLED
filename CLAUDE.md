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
- `venv/` — Python venv with `luma.core`, `luma.oled`, `Pillow`, `watchdog`,
  etc. Always run scripts with `venv/bin/python3`, not system Python.
- `oled-watcher.service` (`/etc/systemd/system/oled-watcher.service`) — runs
  `watcher.py` on boot, as user `jbtokyo` (not root — this rig deliberately
  doesn't run as root, unlike FD1's four services; `jbtokyo`'s `spi`/`gpio`/
  `i2c` group membership covers SPI/GPIO access instead). Enabled via
  `systemctl enable`. Sets `PYTHONUNBUFFERED=1` so `journalctl -u
  oled-watcher.service -f` shows output live instead of buffered.


## Figma → OLED pipeline (Syncthing)

Figma exports sync automatically from the Mac to `~/oled/incoming` on this Pi, where `watcher.py` picks them up. Round trip is ~12 seconds, Figma export to OLED.

- **Mac side**: Syncthing app (`syncthing-app` cask), folder `/Volumes/Neptune/FD1/design/OLED/export`, type **Send Only**.
- **Pi side**: Syncthing installed via apt (official keyring-based repo, not the deprecated `apt-key` method), running as a `--user` systemd service under `jbtokyo` (`systemctl --user status syncthing.service`). Linger is enabled (`loginctl enable-linger jbtokyo`) so it keeps running without an active SSH session. Folder `~/oled/incoming`, type **Receive Only** — deliberately one-way, so nothing on the Pi (test files, leftovers) can sync back and pollute the Mac's export folder.
- Both folders have **Watch for Changes** enabled — near-instant sync on save, not a periodic rescan.

**Reaching bubblegum's Syncthing UI**: it only listens on `127.0.0.1:8384` (localhost-only by default), so it's not reachable directly from the Mac's browser. Tunnel it over SSH when needed (e.g. re-pairing, checking sync status):

```bash
ssh -L 8385:127.0.0.1:8384 jbtokyo@bubblegum.local
```

Then open `http://localhost:8385` on the Mac. (Port 8385 locally, not 8384, to avoid colliding with the Mac's own Syncthing UI.)

**Re-pairing from scratch** (e.g. new Mac, reinstalled Syncthing): each side needs the other's Device ID (**Actions → Show ID** in the UI) added as a remote device, and each side has to separately accept the resulting connection request — adding the ID on one side isn't enough on its own.


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

`watcher.py` is a long-running loop, so it wouldn't hit this in practice —
but it sets `device.persist = True` explicitly anyway (with a comment
pointing back here), so this can't be silently reintroduced if the script's
structure changes later. Any new one-shot test script on this rig should do
the same, or hold the process open before exiting.
