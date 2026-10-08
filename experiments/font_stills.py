#!/usr/bin/env python3
"""Offline stills for the font swap, drawn with player_screen.PlayerScreen
(the panel's own drawing code), no device needed.

  mockup.png / mockup_diff.png  the Figma mockup's content, compared pixel
                                for pixel with incoming/OLED.png (rows 1-2;
                                Row 3 is the live Spleen 5x8 design, not the
                                mockup's Figma rendering of it)
  player_stills.png             the full screen with a Japanese, a Latin, a
                                long scrolling Japanese, and a mixed title
  test_sheet.png                test strings (Latin, kana, kanji, mixed,
                                substitutions, long) in the player layout
  wide_noise.png                mid-scramble frames: two narrow noise
                                glyphs per wide cell vs one full-width glyph
  frames/*.png                  the same frames at 1:1 panel size

usage: font_stills.py OUT_DIR [--mockup PATH]
"""

import argparse
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageChops, ImageDraw

from oled_fonts import SUB, TIMER, TITLE
from player_screen import PlayerScreen

ROOT = Path(__file__).resolve().parent.parent
SIZE = (256, 64)
LABEL = (255, 200, 0)

TESTS = [
    ("latin", "Sure Shot", "Beastie Boys", "Ill Communication"),
    ("latin punctuation", "Don’t Stop — Live (2001)…", "Ryūichi Sakamoto", "Tōkyō Melody"),
    ("hiragana", "ひこうき雲", "荒井由実", "ひこうき雲"),
    ("katakana", "ライディーン", "イエロー・マジック・オーケストラ", "ソリッド・ステイト"),
    ("kanji", "東京は夜の七時", "ピチカート・ファイヴ", "東京は夜の七時"),
    ("mixed", "Perfume — ポリリズム", "椎名林檎", "無罪モラトリアム"),
    ("half-width kana", "ﾃｸﾉﾎﾟﾘｽ", "YMO", "ｿﾘｯﾄﾞ･ｽﾃｲﾄ･ｻｳﾞｧｲｳﾞｧｰ"),
    ("name variants", "髙橋幸宏", "山﨑まさよし", "𠮷野 – One more time"),
    ("wave dash", "夢〜ゆめ〜", "宇多田ヒカル", "First Love 〜Remix〜"),
    ("NFD input", "Beyoncé", "Ryūichi", "Café Tacvba"),
    ("long", "千と千尋の神隠し サウンドトラック 〜あの夏へ〜 (Live 2008)",
     "久石譲", "Joe Hisaishi Symphonic Suite Spirited Away"),
]


def settled(title, artist, album, duration=228, elapsed=84, number=1, count=12,
            wide_noise="pair", stop_at=None, seed=1):
    """Render a track after its initial-paint scramble has finished (or at
    frame `stop_at` of it). now stays 0, so nothing starts scrolling."""
    screen = PlayerScreen("RGB", SIZE, 40, random.Random(seed), wide_noise=wide_noise)
    screen.show_track(title, artist, album, duration, number, count, first=True)
    screen.set_elapsed(elapsed, duration)
    for frame in range(60 if stop_at is None else stop_at):
        screen.render()
        screen.tick(0.0, False)
    screen.render()
    return screen.canvas.copy()


def scrolling(title, artist, album, captures, duration=228, elapsed=84, seed=1):
    """Run a track past its reveal on the live loop's timing (0.04 s ticks,
    scroll steps every 2nd tick) and capture frames at the given tick
    counts after the reveal. Returns [(frame, title phase, title x)]."""
    screen = PlayerScreen("RGB", SIZE, 40, random.Random(seed))
    screen.show_track(title, artist, album, duration, 1, 12, first=True)
    screen.set_elapsed(elapsed, duration)
    now, out = 0.0, []
    for tick in range(max(captures) + 61):
        screen.render()
        if tick - 60 in captures:
            out.append((screen.canvas.copy(), screen.title.phase, screen.title.x))
        screen.tick(now, tick % 2 == 0)
        now += 0.04
    return out


def missing(role, text):
    have = {int(m) for m in re.findall(r"^ENCODING (\d+)$", role.path.read_text(errors="replace"), re.M)}
    return sorted({c for c in role.prepare(text) if ord(c) not in have and not c.isspace()})


def sheet(rows, scale=3, label_h=30):
    out = Image.new("RGB", (SIZE[0] * scale, len(rows) * (SIZE[1] * scale + label_h)), (45, 45, 45))
    d = ImageDraw.Draw(out)
    for i, (im, note) in enumerate(rows):
        y = i * (SIZE[1] * scale + label_h)
        d.text((6, y + 4), note, font=SUB.font, fill=LABEL)  # M+ so Japanese labels read
        out.paste(im.convert("RGB").resize((SIZE[0] * scale, SIZE[1] * scale), Image.NEAREST),
                  (0, y + label_h - 6))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--mockup", type=Path, default=ROOT / "incoming" / "OLED.png")
    args = parser.parse_args()
    frames = args.out / "frames"
    frames.mkdir(parents=True, exist_ok=True)

    # 1. The mockup's own content, compared with the export.
    ours = settled("ネオ東京上空の風", "芸能山城組", "Symphonic Suite AKIRA")
    ours.save(args.out / "mockup.png")
    mock = Image.open(args.mockup).convert("RGB")
    diff = ImageChops.difference(ours, mock).convert("L")
    bad = [(x, y) for y in range(SIZE[1]) for x in range(SIZE[0]) if diff.getpixel((x, y))]
    bands = {}
    for x, y in bad:
        band = "row 1" if y < 24 else "row 2" if y < 44 else "row 3"
        bands[band] = bands.get(band, 0) + 1
    print(f"mockup: {len(bad)} of {SIZE[0] * SIZE[1]} pixels differ from {args.mockup.name}"
          f"{' ' + str(bands) if bands else ''} (rows 1-2 should differ only by Figma's Row 2"
          f" anti-aliasing; Row 3 is the live Spleen 5x8 design, so it differs by design)")
    marked = Image.blend(mock, ours, 0.5)
    for x, y in bad:
        marked.putpixel((x, y), (255, 0, 0))
    sheet([(mock, "Figma mockup (incoming/OLED.png)"), (ours, "panel render (PlayerScreen)"),
           (marked, f"differences in red: {bands} (Row 3 differs by design)")]).save(
        args.out / "mockup_diff.png")

    # 2. The full player screen: Japanese, Latin, long scrolling Japanese, mixed.
    rows = []
    for label, title, artist, album in (
            ("(a) Japanese", "ネオ東京上空の風", "芸能山城組", "Symphonic Suite AKIRA"),
            ("(b) Latin", "Sure Shot", "Beastie Boys", "Ill Communication"),
            ("(d) mixed", "Perfume — ポリリズム (Live at 東京ドーム)", "Perfume", "GAME")):
        im = settled(title, artist, album)
        im.save(frames / f"player_{label[1]}.png")
        rows.append((im, f"{label}: {title}"))
    long_title = "千と千尋の神隠し サウンドトラック 〜あの夏へ〜 ふたたび"
    for im, phase, x in scrolling(long_title, "久石譲", "千と千尋の神隠し", captures=(20, 75, 140)):
        im.save(frames / f"player_c_{phase}.png")
        rows.insert(2 + sum(1 for _, n in rows if n.startswith("(c)")),
                    (im, f"(c) long Japanese title, scroll phase '{phase}', x offset {x} px"))
    sheet(rows).save(args.out / "player_stills.png")

    # 3. Test strings in the player layout.
    rows = []
    for name, title, artist, album in TESTS:
        im = settled(title, artist, album)
        im.save(frames / f"{name.replace(' ', '_')}.png")
        sub_text = SUB.prepare(f"{artist} | {album}")
        t_w, s_w = TITLE.font.getlength(TITLE.prepare(title)), SUB.font.getlength(sub_text)
        t_miss, s_miss = missing(TITLE, title), missing(SUB, f"{artist} | {album}")
        note = (f"{name}: title {t_w:.0f}px{' (scrolls)' if t_w > 241 else ''}"
                f"{' MISSING ' + ''.join(t_miss) if t_miss else ''} | sub {s_w:.0f}px"
                f"{' (scrolls)' if s_w > 240 else ''}{' MISSING ' + ''.join(s_miss) if s_miss else ''}")
        print(note)
        rows.append((im, note))
    sheet(rows).save(args.out / "test_sheet.png")

    # 4. Wide-cell noise: the same scramble frames, pair vs full-width.
    rows = []
    for stop_at in (8, 16):
        for mode in ("pair", "fullwidth"):
            im = settled("ネオ東京上空の風", "芸能山城組", "Symphonic Suite AKIRA",
                         wide_noise=mode, stop_at=stop_at, seed=7)
            im.save(frames / f"wide_noise_{mode}_f{stop_at}.png")
            rows.append((im, f"frame {stop_at} of the reveal, wide-cell noise: {mode}"))
    sheet(rows).save(args.out / "wide_noise.png")
    print(f"wrote mockup.png, mockup_diff.png, player_stills.png, test_sheet.png, wide_noise.png and frames/ to {args.out}")


if __name__ == "__main__":
    main()
