"""Shared SSD1322 setup for every script on this rig."""

import os
from pathlib import Path

from luma.core.interface.serial import spi
from luma.oled.device import ssd1322

GPIO_CHIP = "/dev/gpiochip0"


class GpioBusyError(RuntimeError):
    pass


def gpio_holders():
    """Return [(pid, cmdline)] for other processes holding GPIO_CHIP open.

    Only sees processes this user can inspect; a root-owned holder would be
    invisible here.
    """
    holders = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            fds = list((proc / "fd").iterdir())
            if not any(os.readlink(fd) == GPIO_CHIP for fd in fds):
                continue
            cmdline = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode().strip()
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            continue
        holders.append((int(proc.name), cmdline))
    return holders


def check_gpio_free():
    holders = gpio_holders()
    if holders:
        detail = "\n".join(f"  PID {pid}: {cmd}" for pid, cmd in holders)
        raise GpioBusyError(
            f"{GPIO_CHIP} is already held by another process:\n{detail}\n"
            "Stop it first (e.g. `./rig stop`)."
        )


def get_device(**kwargs):
    """Return a configured ssd1322. Extra kwargs (e.g. framebuffer=) pass through."""
    check_gpio_free()
    serial = spi(port=0, device=0, gpio_DC=5, gpio_RST=6)
    device = ssd1322(serial, **kwargs)
    # luma.core registers an atexit hook that hides and clears the display on
    # process exit unless persist=True; without this, short-lived scripts
    # blank their own output (see CLAUDE.md).
    device.persist = True
    return device
