#!/usr/bin/env python3
"""Watches ~/oled/incoming for new or changed PNGs and displays them on the
SSD1322 OLED. Images must be exactly 256x64; anything else is logged and
skipped. Converts straight to the device's native mode and calls
device.display() directly — no canvas(), no 1-bit thresholding, so the
panel's 4-bit greyscale steps are preserved rather than flattened to
black/white.
"""

import time
from pathlib import Path

from PIL import Image
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from oled_common import get_device

INCOMING_DIR = Path.home() / "oled" / "incoming"
DEFAULT_IMAGE = Path.home() / "oled" / "default.png"
EXPECTED_SIZE = (256, 64)


def load_and_validate(path):
    try:
        image = Image.open(path)
        image.load()
    except Exception as e:
        print(f"Could not open {path.name}: {e}")
        return None

    if image.size != EXPECTED_SIZE:
        print(f"Skipping {path.name}: size {image.size} != {EXPECTED_SIZE}")
        return None

    return image


def show_image(device, path):
    image = load_and_validate(path)
    if image is None:
        return
    native = image.convert(device.mode)
    device.display(native)
    print(f"Displayed {path.name}")


def show_default_if_empty(device):
    if any(p.suffix.lower() == ".png" for p in INCOMING_DIR.iterdir()):
        return
    if not DEFAULT_IMAGE.exists():
        print(f"No default image at {DEFAULT_IMAGE}, nothing to show at startup.")
        return
    print(f"{INCOMING_DIR} is empty, showing default startup image.")
    show_image(device, DEFAULT_IMAGE)


class PngHandler(FileSystemEventHandler):
    def __init__(self, device):
        self.device = device

    def _handle(self, src_path):
        path = Path(src_path)
        if path.suffix.lower() != ".png":
            return
        show_image(self.device, path)

    def on_created(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._handle(event.src_path)


def main():
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)

    device = get_device()

    show_default_if_empty(device)

    handler = PngHandler(device)
    observer = Observer()
    observer.schedule(handler, str(INCOMING_DIR), recursive=False)
    observer.start()

    print(f"Watching {INCOMING_DIR} for PNGs (Ctrl+C to exit)...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nExiting.")
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
