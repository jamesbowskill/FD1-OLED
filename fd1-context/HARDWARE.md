# FD1 — Hardware

Source of truth for components, and current physical wiring (breadboard/Dupont prototype stage). GPIO assignments cross-referenced against `controls.py`/`display.py` (code) and the SSD1322 OLED module's own datasheet pinout.

## Buttons / Encoder (controls.py)

| Signal | Pi GPIO (BCM) | Physical pin | Notes |
|---|---|---|---|
| Play/Pause button | GPIO17 | 11 | `Button(17, bounce_time=0.05)` |
| Next button | GPIO27 | 13 | `Button(27, bounce_time=0.05)` |
| Prev button | GPIO22 | 15 | `Button(22, bounce_time=0.05)` |
| Encoder A | GPIO23 | 16 | `RotaryEncoder(23, 24, max_steps=0)` |
| Encoder B | GPIO24 | 18 | `RotaryEncoder(23, 24, max_steps=0)` |
| Encoder push/mute | GPIO25 | 22 | `Button(25, bounce_time=0.05)` |
| GND returns (buttons + encoder) | — | via breadboard GND rail | All three buttons and the encoder share the breadboard's common GND rail — no individual Pi GND pin per component |

## OLED — SSD1322 (display.py + module datasheet)

| OLED pin | Symbol | Pi connection | Physical pin | Notes |
|---|---|---|---|---|
| 1 | Vss (GND) | GND | 9 | |
| 2 | VBAT (3.3–5V) | 3V3 | 1 | |
| 3 | NC | — floating | — | Per datasheet: must float. (Not a mode-select pin — see note below.) |
| 4 | DB0 → SCLK | GPIO11 (SPI0 SCLK) | 23 | Serial mode: DB0 becomes SCLK |
| 5 | DB1 → SDIN/MOSI | GPIO10 (SPI0 MOSI) | 19 | Serial mode: DB1 becomes SDIN |
| 6 | DB2 | GND | 25 | Unused parallel-bus pin, tied low for serial mode |
| 7 | DB3 | GND | 34 | Unused parallel-bus pin, tied low for serial mode |
| 8 | DB4 | GND | 39 | Unused parallel-bus pin, tied low for serial mode |
| 9 | DB5 | GND (breadboard rail) | — | Unused parallel-bus pin, tied low for serial mode |
| 10 | DB6 | GND (breadboard rail) | — | Unused parallel-bus pin, tied low for serial mode |
| 11 | DB7 | GND | 14 | Unused parallel-bus pin, tied low for serial mode |
| 12 | /RD | GND | 20 | Tied low as part of serial-mode selection |
| 13 | /WR | GND | 30 | Tied low as part of serial-mode selection |
| 14 | /DC | GPIO5 | 29 | Data/command select |
| 15 | /Reset | GPIO6 | 31 | |
| 16 | /CS | GPIO8 (SPI0 CE0) | 24 | |

**Mode-select correction:** earlier assumption was that OLED pin 3 (unaccounted-for at the time) might be a BS0/BS1-style mode-select pin. The datasheet shows pin 3 is actually NC (float). The real serial-mode-select mechanism is tying the entire unused parallel data bus (DB2–DB7) plus /RD and /WR to GND — this is what the project context's "resistor rework" (8080 parallel → 4-wire SPI) actually did.

## Full 40-pin header reference

| Pin | Pi Function | FD1 Usage |
|---|---|---|
| 1 | 3V3 power | OLED pin 2 (VBAT) |
| 2 | 5V power | — |
| 3 | GPIO2 (SDA1) | — |
| 4 | 5V power | — |
| 5 | GPIO3 (SCL1) | — |
| 6 | GND | Buttons/encoder GND rail (shared) |
| 7 | GPIO4 | — |
| 8 | GPIO14 (TXD) | — |
| 9 | GND | OLED pin 1 (Vss) |
| 10 | GPIO15 (RXD) | — |
| 11 | GPIO17 | Play/Pause button |
| 12 | GPIO18 | — |
| 13 | GPIO27 | Next button |
| 14 | GND | OLED pin 11 (DB7) |
| 15 | GPIO22 | Prev button |
| 16 | GPIO23 | Encoder A |
| 17 | 3V3 power | — |
| 18 | GPIO24 | Encoder B |
| 19 | GPIO10 (SPI0 MOSI) | OLED pin 5 (SDIN/MOSI) |
| 20 | GND | OLED pin 12 (/RD) |
| 21 | GPIO9 (SPI0 MISO) | — (unused — OLED is write-only) |
| 22 | GPIO25 | Encoder push/mute |
| 23 | GPIO11 (SPI0 SCLK) | OLED pin 4 (SCLK) |
| 24 | GPIO8 (SPI0 CE0) | OLED pin 16 (/CS) |
| 25 | GND | OLED pin 6 (DB2) |
| 26 | GPIO7 (SPI0 CE1) | — |
| 27 | GPIO0 (ID_SD) | — (EEPROM ID, avoid) |
| 28 | GPIO1 (ID_SC) | — (EEPROM ID, avoid) |
| 29 | GPIO5 | OLED pin 14 (/DC) |
| 30 | GND | OLED pin 13 (/WR) |
| 31 | GPIO6 | OLED pin 15 (/Reset) |
| 32 | GPIO12 | — |
| 33 | GPIO13 | — |
| 34 | GND | OLED pin 7 (DB3) |
| 35 | GPIO19 | — |
| 36 | GPIO16 | — |
| 37 | GPIO26 | — |
| 38 | GPIO20 | — |
| 39 | GND | OLED pin 8 (DB4) |
| 40 | GPIO21 | — |

Note: OLED pins 9 (DB5) and 10 (DB6) are tied to the breadboard's common GND rail rather than a specific numbered Pi pin.

Free GPIO pins for future PCB use: GPIO2, 3, 4, 7, 12, 13, 14, 15, 16, 18, 19, 20, 21, 26 (14 pins; GPIO0/1 reserved for HAT ID EEPROM, best avoided).

## OLED module datasheet — full pin reference (as supplied)

| Pin No. | Symbol | I/O | Function |
|---|---|---|---|
| 1 | Vss | P | Ground of Logic Circuit — reference for logic pins, connect to external ground |
| 2 | VBAT | 3.3–5V | Power supply for display module circuit |
| 3 | NC | – | Must be left floating |
| 4–11 | DB0–DB7 | I/O | Host data bus (8-bit parallel). In serial mode: DB1 = serial data input (SDIN), DB0 = serial clock input (SCLK) |
| 12 | /RD | I | Read/Write enable or Read, depending on interface mode |
| 13 | /WR | I | Read/Write select or Write, depending on interface mode |
| 14 | /DC | I | Data/Command control — high = display data, low = command register |
| 15 | /Reset | I | Active-low reset — initializes the chip when pulled low |
| 16 | /CS | I | Chip select — MCU communication enabled only when asserted |


## OLED Notes

The SSD1322 is a genuine 4-bit greyscale device — not forced to hard 1-bit monochrome by the current code, meaning anti-aliased text rendering may already be happening on real hardware without deliberate design, pending confirmation. 

SSD1322 bring-up requires a resistor rework (switching from 8080 parallel to 4-wire SPI mode).

Font candidates under consideration: PP Neue Bit (polished vector-styled bitmap font, anti-aliasing behavior on real hardware unconfirmed), Bitcount (genuinely pixel-native, safer choice for a true "authentic bitmap" look), Spleen (open, genuinely pixel-native — best loaded via its raw BDF file directly through Pillow's ImageFont.load(), bypassing the OTF conversion its own author recommends avoiding), and for the katakana "scramble" transition idea specifically: DotGothic16 (Google Fonts, OFL, Fontworks), or the smaller Misaki/k8x12 (8×8 / 8×12, both from the same respected independent Japanese creator, M+ FONTS license).


## USB Notes

USB floppy drive vendor-string detection (rather than trusting /dev/sdX device letters, which drift based on plug order) is the pattern already proven for the floppy drive, and is the direct precedent for how future USB thumb-drive identification should work.

## Open items

- Current connector method: individual Dupont wires (breadboard stage). See docs/ROADMAP.md "Filed for later" and project chat history for the planned move to a custom PCB (HAT-style, GPIO routed directly to on-board button/encoder pads; OLED via 16-pin IDC ribbon into a PCB-mounted socket).