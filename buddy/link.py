"""
The Pi <-> Pixhawk link. Same idea as the first buddy_brain: one interface,
a mock for the kitchen table and the real thing over MAVLink. Everything above
this file doesn't care which one it got.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

from . import config


@dataclass
class RoverState:
    x_m: float = 0.0            # local frame, east
    y_m: float = 0.0            # local frame, north
    lat: float = 0.0
    lon: float = 0.0
    heading_deg: float = 0.0
    speed_ms: float = 0.0
    armed: bool = False
    mode: str = "HOLD"
    battery_volts: float = 16.4
    battery_pct: int = 100
    last_heartbeat: float = 0.0


class RoverLink:
    def connect(self) -> None: raise NotImplementedError
    def close(self) -> None: raise NotImplementedError
    def arm(self) -> None: raise NotImplementedError
    def disarm(self, force: bool = False) -> None: raise NotImplementedError
    def set_mode(self, mode: str) -> None: raise NotImplementedError
    def send_velocity(self, forward_ms: float, turn_deg_s: float) -> None: raise NotImplementedError
    def go_to(self, lat: float, lon: float) -> None: raise NotImplementedError
    def get_state(self) -> RoverState: raise NotImplementedError
    def set_param(self, name: str, value: float) -> None: raise NotImplementedError


def _clamp(v, lim):
    return max(-lim, min(lim, v))


class MockRoverLink(RoverLink):
    """Starts in a parking lot in San Juan. Only GUIDED moves it, like the real one."""

    def __init__(self) -> None:
        self.state = RoverState(lat=18.4655, lon=-66.1057)
        self.link_ok = True
        self._fwd = self._turn = 0.0
        self._t = time.monotonic()

    def connect(self) -> None:
        print("[mock] virtual Buddy online")
        self.state.last_heartbeat = self._t = time.monotonic()

    def close(self) -> None:
        print("[mock] virtual Buddy shut down")

    def set_param(self, name: str, value: float) -> None:
        self.params = getattr(self, "params", {})
        self.params[name] = value

    def arm(self) -> None:
        self.state.armed = True

    def disarm(self, force: bool = False) -> None:
        self.state.armed = False
        self._fwd = self._turn = 0.0

    def set_mode(self, mode: str) -> None:
        self.state.mode = mode.upper()
        if self.state.mode == "HOLD":
            self._fwd = self._turn = 0.0

    def send_velocity(self, forward_ms: float, turn_deg_s: float) -> None:
        self._fwd = _clamp(forward_ms, config.MAX_SPEED_MS)
        self._turn = _clamp(turn_deg_s, config.MAX_TURN_DEG_S)

    def go_to(self, lat: float, lon: float) -> None:
        self.state.lat, self.state.lon = lat, lon   # teleport, it's a mock

    def get_state(self) -> RoverState:
        now = time.monotonic()
        dt, self._t = now - self._t, now
        s = self.state
        if self.link_ok:
            s.last_heartbeat = now
        moving = s.armed and s.mode == "GUIDED"
        fwd, turn = (self._fwd, self._turn) if moving else (0.0, 0.0)
        s.heading_deg = (s.heading_deg + turn * dt) % 360
        rad = math.radians(s.heading_deg)
        dx, dy = fwd * math.sin(rad) * dt, fwd * math.cos(rad) * dt
        s.x_m += dx
        s.y_m += dy
        s.lat += dy / 111_320
        s.lon += dx / (111_320 * math.cos(math.radians(s.lat)))
        s.speed_ms = abs(fwd)
        if moving:
            s.battery_volts = max(13.0, s.battery_volts - 0.0005 * dt)
        return s


class MavlinkRoverLink(RoverLink):
    def __init__(self, connection: str, baud: int = config.SERIAL_BAUD) -> None:
        self.connection, self.baud = connection, baud
        self.master = None
        self.state = RoverState(mode="UNKNOWN")
        self._home = None

    def connect(self, timeout: float = 30) -> None:
        from pymavlink import mavutil
        self.mavutil = mavutil
        print(f"[mavlink] connecting to {self.connection} ...")
        self.master = mavutil.mavlink_connection(self.connection, baud=self.baud,
                                                 source_system=255, source_component=191)
        if not self.master.wait_heartbeat(timeout=timeout):
            raise TimeoutError("no heartbeat from the Pixhawk")
        self.state.last_heartbeat = time.monotonic()
        self.master.mav.request_data_stream_send(
            self.master.target_system, self.master.target_component,
            mavutil.mavlink.MAV_DATA_STREAM_ALL, 5, 1)

    def close(self) -> None:
        if self.master:
            self.master.close()

    def set_param(self, name: str, value: float) -> None:
        self.master.mav.param_set_send(self.master.target_system, self.master.target_component,
                                       name.encode(), float(value),
                                       self.mavutil.mavlink.MAV_PARAM_TYPE_REAL32)

    def _command(self, cmd, *params):
        p = list(params) + [0] * (7 - len(params))
        self.master.mav.command_long_send(self.master.target_system,
                                          self.master.target_component, cmd, 0, *p)

    def arm(self) -> None:
        self._command(self.mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1)

    def disarm(self, force: bool = False) -> None:
        # 21196 is ArduPilot's magic number for "disarm even if moving"
        self._command(self.mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 21196 if force else 0)

    def set_mode(self, mode: str) -> None:
        self.master.set_mode(self.master.mode_mapping()[mode.upper()])

    def send_velocity(self, forward_ms: float, turn_deg_s: float) -> None:
        # GUIDED body-frame velocity + yaw rate. ArduPilot stops by itself if these stop coming.
        mav = self.mavutil.mavlink
        self.master.mav.set_position_target_local_ned_send(
            0, self.master.target_system, self.master.target_component,
            mav.MAV_FRAME_BODY_NED, 0b0000_0101_1100_0111,
            0, 0, 0, _clamp(forward_ms, config.MAX_SPEED_MS), 0, 0, 0, 0, 0, 0,
            math.radians(_clamp(turn_deg_s, config.MAX_TURN_DEG_S)))

    def go_to(self, lat: float, lon: float) -> None:
        mav = self.mavutil.mavlink
        self.master.mav.set_position_target_global_int_send(
            0, self.master.target_system, self.master.target_component,
            mav.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT, 0b0000_1111_1111_1000,
            int(lat * 1e7), int(lon * 1e7), 0, 0, 0, 0, 0, 0, 0, 0, 0)

    def get_state(self) -> RoverState:
        s, mav = self.state, self.mavutil.mavlink
        while (msg := self.master.recv_match(blocking=False)) is not None:
            t = msg.get_type()
            if t == "HEARTBEAT" and msg.get_srcComponent() == 1:
                s.armed = bool(msg.base_mode & mav.MAV_MODE_FLAG_SAFETY_ARMED)
                s.mode = self.mavutil.mode_string_v10(msg)
                s.last_heartbeat = time.monotonic()
            elif t == "GLOBAL_POSITION_INT":
                s.lat, s.lon = msg.lat / 1e7, msg.lon / 1e7
                if msg.hdg != 65535:
                    s.heading_deg = msg.hdg / 100
                s.speed_ms = math.hypot(msg.vx, msg.vy) / 100
            elif t == "LOCAL_POSITION_NED":
                s.x_m, s.y_m = msg.y, msg.x
            elif t == "SYS_STATUS":
                s.battery_volts = msg.voltage_battery / 1000
                s.battery_pct = max(0, msg.battery_remaining)
        return s


def make_link(simulate: bool, connection: str) -> RoverLink:
    return MockRoverLink() if simulate else MavlinkRoverLink(connection)
