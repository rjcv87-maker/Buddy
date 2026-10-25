"""
LoRa mesh + the open fleet handshake from the proposal:

  1 discovery        BEACON every couple of seconds: module type and role
  2 identity/caps    STATUS: sensors, battery, position, mode
  3 authentication   every frame carries an HMAC. Fleet key = "speaks OTL",
                     team key = trusted. Only trusted peers can send STOP/FIND
                     (if no team key is set, fleet peers are trusted)
  4 role negotiation no extra messages: lowest node id among live peers
                     coordinates, and everyone splits the area by rank
  5 cooperative exec FIND broadcasts a confirmed detection
  6 join / exit      peers time out and the split is recomputed

Frame on air, big-endian:
  "OT" ver type module node(u16) seq(u16) ts(u32) key_id len | payload | hmac[:8]
The Pico in firmware/lora_node just moves these bytes; it never looks inside.
"""
from __future__ import annotations

import hashlib
import hmac
import struct
import time

from . import config

VERSION = 1
BEACON, STATUS, FIND, STOP = 1, 2, 3, 4
MODULES = {"rover": 1, "drone": 2, "asv": 3, "rov": 4, "telescope": 5, "ground": 6}
SENSORS = {"gps": 1, "lidar": 2, "camera": 4, "thermal": 8, "coral": 16, "co2": 32, "audio": 64, "seismic": 128}
MODES = ["UNKNOWN", "MANUAL", "HOLD", "GUIDED", "AUTO", "RTL", "SMART_RTL", "ACRO", "STEERING"]
FLEET_KEY_ID, TEAM_KEY_ID = 0, 1
TAG_LEN = 8

_HEADER = struct.Struct(">2sBBBHHIBB")
_STATUS = struct.Struct(">BHiiHBB")      # sensors, battery dV, lat e7, lon e7, heading, mode, flags
_FIND = struct.Struct(">iiBB")           # lat e7, lon e7, confidence %, sensor


class BadFrame(ValueError):
    pass


def _tag(key: bytes, body: bytes) -> bytes:
    return hmac.new(key, body, hashlib.sha256).digest()[:TAG_LEN]


def pack(key: bytes, key_id: int, kind: int, node: int, seq: int, payload: bytes = b"",
         module: int = MODULES["rover"], ts: int | None = None) -> bytes:
    ts = int(time.time()) if ts is None else ts
    body = _HEADER.pack(b"OT", VERSION, kind, module, node, seq & 0xFFFF, ts, key_id, len(payload)) + payload
    return body + _tag(key, body)


def unpack(keys: dict[int, bytes], frame: bytes) -> dict:
    if len(frame) < _HEADER.size + TAG_LEN:
        raise BadFrame("short")
    body, tag = frame[:-TAG_LEN], frame[-TAG_LEN:]
    magic, ver, kind, module, node, seq, ts, key_id, n = _HEADER.unpack_from(body)
    if magic != b"OT" or ver != VERSION or len(body) != _HEADER.size + n:
        raise BadFrame("header")
    key = keys.get(key_id)
    if key is None or not hmac.compare_digest(tag, _tag(key, body)):
        raise BadFrame("auth")
    return {"kind": kind, "module": module, "node": node, "seq": seq, "ts": ts,
            "trusted": key_id == TEAM_KEY_ID or TEAM_KEY_ID not in keys,
            "payload": body[_HEADER.size:]}


def status_payload(state, sensors: int, estop=False, obstacle=False) -> bytes:
    flags = state.armed | (estop << 1) | (obstacle << 2)
    mode = MODES.index(state.mode) if state.mode in MODES else 0
    return _STATUS.pack(sensors, int(state.battery_volts * 10), int(state.lat * 1e7),
                        int(state.lon * 1e7), int(state.heading_deg) % 360, mode, flags)


def read_status(p: bytes) -> dict:
    sensors, bat, lat, lon, hdg, mode, flags = _STATUS.unpack(p)
    return {"sensors": [k for k, b in SENSORS.items() if sensors & b], "battery_volts": bat / 10,
            "lat": lat / 1e7, "lon": lon / 1e7, "heading_deg": hdg,
            "mode": MODES[mode] if mode < len(MODES) else "UNKNOWN",
            "armed": bool(flags & 1), "estop": bool(flags & 2), "obstacle": bool(flags & 4)}


class Mesh:
    def __init__(self, radio, node: int, fleet_key: str = config.FLEET_KEY,
                 team_key: str = config.TEAM_KEY, sensors: int = 0) -> None:
        self.radio, self.node, self.sensors = radio, node, sensors
        self.keys = {FLEET_KEY_ID: fleet_key.encode()}
        if team_key:
            self.keys[TEAM_KEY_ID] = team_key.encode()
        self.send_key_id = TEAM_KEY_ID if team_key else FLEET_KEY_ID
        self.seq = 0
        self.peers: dict[int, dict] = {}
        self.finds: list[dict] = []
        self.dropped = 0
        self.stop_requested = False
        self._next_beacon = 0.0

    def send(self, kind: int, payload: bytes = b"") -> None:
        self.seq = (self.seq + 1) & 0xFFFF
        self.radio.write(pack(self.keys[self.send_key_id], self.send_key_id, kind, self.node, self.seq, payload))

    def report_find(self, lat: float, lon: float, confidence: float, sensor: str = "thermal") -> None:
        self.send(FIND, _FIND.pack(int(lat * 1e7), int(lon * 1e7), int(confidence * 100), SENSORS[sensor]))

    def tick(self, state, estop=False, obstacle=False, now: float | None = None) -> list[dict]:
        now = time.monotonic() if now is None else now
        if now >= self._next_beacon:
            self._next_beacon = now + config.BEACON_PERIOD_S
            self.send(BEACON)
            self.send(STATUS, status_payload(state, self.sensors, estop, obstacle))
        return self.receive(now)

    def receive(self, now: float | None = None) -> list[dict]:
        now = time.monotonic() if now is None else now
        got = []
        while (frame := self.radio.read_frame()) is not None:
            try:
                m = unpack(self.keys, frame)
            except BadFrame:
                self.dropped += 1
                continue
            peer = self.peers.get(m["node"])
            # seq has to move forward; anything else is a replay or an old frame
            fresh = peer is None or 0 < ((m["seq"] - peer["seq"]) & 0xFFFF) < 0x8000
            if m["node"] == self.node or not fresh or abs(time.time() - m["ts"]) > config.REPLAY_WINDOW_S:
                self.dropped += 1
                continue
            if peer is None:
                print(f"[mesh] new peer {m['node']} (module {m['module']}, trusted={m['trusted']})")
                peer = self.peers[m["node"]] = {"module": m["module"], "status": None}
            peer.update(seq=m["seq"], last=now, trusted=m["trusted"])
            if m["kind"] == STATUS:
                peer["status"] = read_status(m["payload"])
            elif m["kind"] == FIND and m["trusted"]:
                lat, lon, conf, _ = _FIND.unpack(m["payload"])
                self.finds.append({"from": m["node"], "lat": lat / 1e7, "lon": lon / 1e7, "confidence": conf / 100})
            elif m["kind"] == STOP and m["trusted"]:
                self.stop_requested = True
            got.append(m)
        return got

    def live_peers(self, now: float | None = None) -> list[int]:
        now = time.monotonic() if now is None else now
        return sorted(n for n, p in self.peers.items() if now - p["last"] < config.PEER_TIMEOUT_S)

    def team(self, now: float | None = None) -> list[int]:
        """Everyone sharing the search, me included, in rank order."""
        return sorted(set(self.live_peers(now)) | {self.node})

    def coordinator(self, now: float | None = None) -> int:
        return self.team(now)[0]


def split_area(width_m: float, team: list[int], me: int) -> tuple[float, float]:
    """Strips across the width, one per unit. Returns (offset, strip width)."""
    strip = width_m / len(team)
    return team.index(me) * strip, strip


class SerialRadio:
    """firmware/lora_node on USB. Each frame is [len][bytes] both ways."""

    def __init__(self, port=config.MESH_PORT, baud=config.MESH_BAUD):
        import serial
        self.port = serial.Serial(port, baud, timeout=0)
        self.buf = b""

    def write(self, frame: bytes) -> None:
        self.port.write(bytes([len(frame)]) + frame)

    def read_frame(self):
        self.buf += self.port.read(512)
        if self.buf and len(self.buf) > self.buf[0]:
            n = self.buf[0]
            frame, self.buf = self.buf[1:1 + n], self.buf[1 + n:]
            return frame
        return None


class MockAir:
    """Shared fake airwaves for running two rovers in one process."""

    def __init__(self):
        self.radios = []

    def radio(self):
        r = _MockRadio(self)
        self.radios.append(r)
        return r


class _MockRadio:
    def __init__(self, air):
        self.air, self.inbox = air, []

    def write(self, frame):
        for r in self.air.radios:
            if r is not self:
                r.inbox.append(frame)

    def read_frame(self):
        return self.inbox.pop(0) if self.inbox else None
