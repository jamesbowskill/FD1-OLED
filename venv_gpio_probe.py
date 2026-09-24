#!/usr/bin/env python3
"""Static GPIO probe: drives DC and RST to fixed known levels and holds them
so they can be checked with a multimeter, independent of SPI/timing.
"""
import RPi.GPIO as GPIO
import time

DC = 5
RST = 6

GPIO.setmode(GPIO.BCM)
GPIO.setup(DC, GPIO.OUT)
GPIO.setup(RST, GPIO.OUT)

print("Setting RST HIGH, DC HIGH. Holding for 60s.")
print("Probe with multimeter (DC volts, black lead to any GND pin):")
print("  - Pi pin 29 (GPIO5/DC)  -> expect ~3.3V")
print("  - Pi pin 31 (GPIO6/RST) -> expect ~3.3V")
print("  - OLED pin 14 (DC)      -> expect ~3.3V (if not, wire/connection fault)")
print("  - OLED pin 15 (RST)     -> expect ~3.3V (if not, wire/connection fault)")
GPIO.output(RST, GPIO.HIGH)
GPIO.output(DC, GPIO.HIGH)
time.sleep(60)

print("Now setting RST LOW, DC LOW. Holding for 60s.")
print("Same pins should now read ~0V.")
GPIO.output(RST, GPIO.LOW)
GPIO.output(DC, GPIO.LOW)
time.sleep(60)

GPIO.cleanup()
print("Done, pins released.")
