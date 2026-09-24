# FD1 — Floppy Disk Jukebox

A personal hardware project built around a Raspberry Pi music player where inserting a 3.5” floppy disk into a connected USB disk drive triggers playback of tracks listed in a text file on that disk. The music files are stored on the Pi’s SD card. A web app (Flask) provides a UI for burning track lists to disks. An OLED display shows playback state. Physical buttons/encoder provide hardware controls. A (yet to be designed) 3D-printed case will package it together.

## Project docs

| File                   | Role                                                                |
| ---------------------- | ------------------------------------------------------------------- |
| `CLAUDE.md`            | This file — overview, architecture, operational rules, git workflow |
| `docs/ROADMAP.md`      | Active and planned work                                             |
| `docs/KNOWN-ISSUES.md` | Existing bugs/inconsistencies, not yet scheduled                    |
| `docs/CHANGELOG.md`    | Completed fixes, full reasoning kept, newest on top                 |
| `docs/HARDWARE.md`     | Hardware specs, pinouts                                             |


## Architecture — four systemd services

| Service | File | Role |
|---|---|---|
| `jukebox.service` | `~/floppy_jukebox/jukebox.py` | Core daemon: detects disk insert/eject, mounts, reads `album.txt`, launches `mpv` for playback |
| `controls.service` | `~/floppy_jukebox/controls.py` | Physical buttons/rotary encoder → sends commands to mpv via IPC socket at `/tmp/mpvsocket` |
| `display.service` | `~/floppy_jukebox/display.py` | SSD1322 OLED (SPI) — shows playback state, scrolling track info, sleep/wake on idle |
| `webapp.service` | `~/floppy_jukebox/webapp/app.py` | Flask app — labeling/burn UI, disk prepare/format, Home screen status |

Webapp structure: `webapp/app.py` (backend), `webapp/templates/index.html`, `webapp/static/style.css`, `webapp/static/app.js`.

All four run as **root** (needed for mount/GPIO/SPI access).

## Git workflow

This project is a git repo on the Pi (`~/floppy_jukebox`), with a remote on GitHub (`jamesbowskill/FD1`) and a clone kept on the user's Mac for backup. Use git as part of normal work, not as an afterthought:

- After a real, working change (not mid-debugging), commit it: `git add .` then `git commit -m "<clear description of what changed and why>"`.
- Push after committing: `git push`.
- Prefer several small, clearly-described commits over one large one.
- Don't commit broken/half-finished states as a matter of course — if a change needs several iterations to get working, commit once it's actually working, not after every failed attempt.
- If asked to make a risky or large structural change, consider committing the current working state first, so there's an easy rollback point.

## Operational rules

**Always restart `webapp.service` after changing `index.html`.** Static CSS/JS files serve fresh automatically; the Flask-rendered template does not reliably pick up changes without a restart.
   ```
   sudo systemctl restart webapp.service
   ```

**Mount/unmount discipline is critical.** `unmount_floppy()` in both `jukebox.py` and `app.py` loops (`for _ in range(10)`) to fully clear the mountpoint, because Linux allows the same device to be mounted repeatedly on one mountpoint without erroring — mismatched mount/unmount pairs silently stack rather than failing loudly. Always call the looping unmount, never a bare single `umount`.

**A settle delay is required before mounting.** Floppy drives need real time to mechanically settle after insertion. `jukebox.py` has always paused unconditionally before mounting; `app.py`'s `mount_floppy()` now does the same — an unconditional `time.sleep(SETTLE_DELAY)` at the top, on every call. (A prior version used a `_needs_settle` flag set only on a presence transition, but that flag didn't reliably get set on every path that calls `mount_floppy()` — e.g. it silently never fired on the burn flow's initial entry — so it was replaced with an unconditional sleep. Don't reintroduce conditional settle logic without a strong reason.)

**`read_pointer_file()` must never crash on bad data.** A corrupted `album.txt` (non-UTF-8 bytes) must be caught and treated as "disk unreadable," not allowed to propagate and crash the whole service into a restart-loop. Both `jukebox.py`'s and `app.py`'s copies of this function catch `UnicodeDecodeError` and return `None` (distinct from `[]`, which means "blank disk").

**CSS Grid/Flexbox children need an explicit `height`, not just `max-height`, plus `min-height: 0`, to actually constrain and scroll internally.** Give the parent a real `height` (not just a ceiling), and add `min-height: 0` to any flex/grid child that needs to shrink below its content size.

**Any `.screen` needing an absolutely-positioned child needs `position: relative` on itself (or the shared `.screen` class).** Already added globally — don't remove it.

**Height math using hardcoded `vh` subtractions is fragile.** Several elements use `calc(100vh - Npx)` to account for sibling elements (nav bars, status bars). Removing or resizing any sibling breaks this silently elsewhere. When restructuring layout, expect to need to recalculate these — check `main`'s height calc and anything referencing it whenever a sibling above it changes. This is a known area of technical debt worth revisiting (e.g. CSS custom properties for shared heights) rather than continuing to patch — see docs/KNOWN-ISSUES.md.

**Don't attempt to launch or use a browser for verification**. The Claude in Chrome browser extension is not connected in this environment. Verify changes via curl, grep, and code review instead. Flag anything that needs visual/manual browser testing for the user to check themselves.

**When a fix is completed: add it to docs/CHANGELOG.md (top of file)**. Use the same level of reasoning/detail as existing entries, and remove it from wherever it was tracked (docs/ROADMAP.md or docs/KNOWN-ISSUES.md).

## Style

Currently unstyled/functional (system default fonts, minimal color). A deliberate visual pass is planned but not yet begun — don't add decorative styling unprompted.