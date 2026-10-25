"""
Victim detection: CO2 rise (SCD30 in the pod / SCD41 at the probe tip), knocking on the mic array
or the geophone, RF activity (phones) from the signals module. Every source is optional; each one
has a mock so the rover and the tests run without the hardware.

A CANDIDATE needs two independent cues inside WINDOW_S (CO2 + knock, or knock + RF, ...).
Then the rover sends a signed FIND on the LoRa mesh and writes a log line.
"""
from __future__ import annotations

import json
import math
import random
import time
from collections import deque

CO2_RISE_PPM = 150.0        # over the rolling baseline (people in a void raise it fast)
CO2_BASE_S = 120.0
KNOCK_SIGMA = 6.0           # peak vs. running RMS
KNOCK_MIN_GAP_S = 0.25
KNOCKS_NEEDED = 3           # in KNOCK_WINDOW_S
KNOCK_WINDOW_S = 10.0
RF_NEW_DEVICES = 1          # new WiFi/BLE MACs not in the baseline
WINDOW_S = 60.0


class Co2Detector:
    def __init__(self):
        self.hist = deque()

    def update(self, ppm: float, now: float) -> bool:
        self.hist.append((now, ppm))
        while self.hist and now - self.hist[0][0] > CO2_BASE_S:
            self.hist.popleft()
        if now - self.hist[0][0] < 10:
            return False
        base = min(p for _, p in self.hist)
        return ppm - base >= CO2_RISE_PPM


class KnockDetector:
    """works on any 1-D stream: mic envelope or geophone volts."""
    def __init__(self):
        self.rms = None; self.last = -1e9; self.knocks = deque()

    def update(self, x: float, now: float) -> bool:
        a = abs(x)
        if self.rms is None:
            self.rms = a or 1e-6; return False
        hit = a > KNOCK_SIGMA * self.rms and now - self.last > KNOCK_MIN_GAP_S
        self.rms = 0.995 * self.rms + 0.005 * a
        if hit:
            self.last = now; self.knocks.append(now)
        while self.knocks and now - self.knocks[0] > KNOCK_WINDOW_S:
            self.knocks.popleft()
        return len(self.knocks) >= KNOCKS_NEEDED


class RfCounter:
    """MACs seen by the ESP32 sniffer (one per line on its serial port, 'mac,rssi')."""
    def __init__(self):
        self.base = None; self.seen = {}

    def baseline(self, macs):
        self.base = set(macs)

    def update(self, mac: str, rssi: int, now: float) -> bool:
        self.seen[mac] = (rssi, now)
        new = [m for m in self.seen if self.base is not None and m not in self.base]
        return len(new) >= RF_NEW_DEVICES

    def count(self) -> int:
        return len(self.seen)


class VictimFusion:
    def __init__(self, mesh=None, log_path="/var/log/buddy/victims.jsonl", position=lambda: (0.0, 0.0)):
        self.co2 = Co2Detector(); self.knock = KnockDetector(); self.rf = RfCounter()
        self.cues = {}; self.mesh = mesh; self.log_path = log_path; self.position = position; self.reported = []

    def cue(self, name: str, now: float):
        self.cues[name] = now
        live = {k for k, t in self.cues.items() if now - t <= WINDOW_S}
        if len(live) >= 2:
            self._report(live, now); self.cues.clear()

    def feed(self, kind: str, value, now: float | None = None):
        now = time.time() if now is None else now
        if kind == "co2" and self.co2.update(value, now): self.cue("co2", now)
        elif kind in ("audio", "seismic") and self.knock.update(value, now): self.cue("knock", now)
        elif kind == "rf" and self.rf.update(*value, now): self.cue("rf", now)

    def _report(self, cues, now):
        lat, lon = self.position(); conf = min(0.99, 0.4 + 0.25 * len(cues))
        sensor = "co2" if "co2" in cues else ("audio" if "knock" in cues else "co2")
        if self.mesh is not None: self.mesh.report_find(lat, lon, conf, sensor=sensor)
        rec = dict(t=now, lat=lat, lon=lon, cues=sorted(cues), confidence=round(conf, 2), rf_devices=self.rf.count())
        self.reported.append(rec)
        if self.log_path:
            try:
                import os; os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
                open(self.log_path, "a").write(json.dumps(rec) + "\n")
            except OSError:
                pass


def mock_stream(seconds=120, victim_at=60.0, seed=1, dt=0.05):
    """yields (kind, value, t): flat background, then a person: CO2 ramps up, 3 knocks, a new phone."""
    rnd = random.Random(seed); t = 0.0; knocks = [victim_at + 2 + 1.5*i for i in range(4)]
    while t < seconds:
        x = rnd.gauss(0, 0.01)
        if any(abs(t - k) < dt/2 for k in knocks): x = 0.5
        yield ("audio", x, t)
        if int(t*20) % 20 == 0:
            ppm = 420 + rnd.gauss(0, 5) + (max(0.0, t - victim_at) * 8 if t > victim_at else 0)
            yield ("co2", ppm, t)
        if abs(t - (victim_at + 5)) < dt/2: yield ("rf", ("aa:bb:cc:00:11:22", -61), t)
        t += dt
