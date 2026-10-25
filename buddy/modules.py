"""
Removable modules on the GX16-8 interface sites (X01). The rover must run with any subset,
including none. A module is "present" when the env says so AND its hardware answers.

GX16-8 pinout (same on every site):
  1 VBAT (5 A fuse on the host)  2 GND  3 +5V  4 USB D+  5 USB D-  6 I2C SDA  7 I2C SCL  8 GND/ID

/etc/buddy/env:  BUDDY_MODULES=vic,probe,sig,geo,sol   (empty or unset = autodetect only)
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field

# what each module shows on the bus when it is plugged in
I2C_ID = {"vic": [0x61],          # SCD30 in the pod
          "probe": [0x62],        # SCD41 at the probe tip
          "geo": [0x48],          # ADS1256 front end bridge (ADS1115 address on the ID line)
          "servo": [0x40]}        # PCA9685 (probe pan/tilt, geophone arm)
USB_ID = {"vic": ["2752:0019"],   # XMOS XVF3800 mic array
          "probe": ["endoscope"],
          "sig": ["0bda:2838", "303a:1001"],   # RTL-SDR V4, ESP32-S3 USB-JTAG/serial
          "sol": ["0403:6015"]}   # Victron VE.Direct USB cable (FTDI)
KNOWN = ("vic", "probe", "sig", "geo", "sol")


@dataclass
class Modules:
    wanted: set = field(default_factory=set)
    found: set = field(default_factory=set)

    @property
    def active(self) -> set:
        return (self.wanted & self.found) if self.wanted else set(self.found)

    def missing(self) -> set:
        return self.wanted - self.found

    def has(self, name: str) -> bool:
        return name in self.active


def wanted_from_env(env=os.environ) -> set:
    raw = env.get("BUDDY_MODULES", "")
    out = {m.strip() for m in raw.split(",") if m.strip()}
    bad = out - set(KNOWN)
    if bad:
        raise ValueError(f"unknown module(s) in BUDDY_MODULES: {sorted(bad)}")
    return out


def scan_usb(root="/sys/bus/usb/devices") -> set:
    ids = set()
    for d in glob.glob(f"{root}/*"):
        try:
            v = open(f"{d}/idVendor").read().strip(); p = open(f"{d}/idProduct").read().strip()
            ids.add(f"{v}:{p}")
            prod = open(f"{d}/product").read().strip().lower() if os.path.exists(f"{d}/product") else ""
            if "endoscope" in prod or "usb camera" in prod: ids.add("endoscope")
        except OSError:
            continue
    return ids


def scan_i2c(bus=None) -> set:
    """addresses that ACK. bus: object with read_byte(addr) (smbus2.SMBus), None -> try /dev/i2c-1."""
    if bus is None:
        try:
            from smbus2 import SMBus
            bus = SMBus(1)
        except Exception:
            return set()
    found = set()
    for a in range(0x08, 0x78):
        try:
            bus.read_byte(a); found.add(a)
        except Exception:
            pass
    return found


def detect(usb_ids: set | None = None, i2c_addrs: set | None = None, env=os.environ) -> Modules:
    usb = scan_usb() if usb_ids is None else set(usb_ids)
    i2c = scan_i2c() if i2c_addrs is None else set(i2c_addrs)
    found = set()
    for m in KNOWN:
        if any(a in i2c for a in I2C_ID.get(m, [])) or any(u in usb for u in USB_ID.get(m, [])):
            found.add(m)
    return Modules(wanted_from_env(env), found)


def sensor_mask(mods: Modules) -> int:
    from .mesh import SENSORS
    m = 0
    if mods.has("vic") or mods.has("probe"): m |= SENSORS["co2"] | SENSORS["audio"]
    if mods.has("geo"): m |= SENSORS["seismic"]
    return m
