"""
Safety before behavior. Three layers, and this file is only the top one:
the mushroom button + estop_watchdog cut motor power in hardware, ArduPilot has
its own RC/GCS/battery failsafes, and this catches the things only the Pi knows
about (LiDAR, a STOP from the other rover).
"""
from __future__ import annotations

import math
import time

from . import config
from .link import RoverState


class SafetyError(Exception):
    pass


def check_battery(state: RoverState) -> None:
    if 0 < state.battery_volts < config.MIN_BATTERY_VOLTS:
        raise SafetyError(f"battery low: {state.battery_volts:.1f} V (min {config.MIN_BATTERY_VOLTS} V)")
    if state.battery_pct < config.MIN_BATTERY_PCT:
        raise SafetyError(f"battery low: {state.battery_pct}% (min {config.MIN_BATTERY_PCT}%)")


def preflight_checks(state: RoverState) -> None:
    # TODO: GPS fix and geofence once we're outside the parking lot
    check_battery(state)
    if time.monotonic() - state.last_heartbeat > config.HEARTBEAT_TIMEOUT_S:
        raise SafetyError("no heartbeat from the Pixhawk")


class Watchdog:
    def __init__(self, estop_gpio: int = -1) -> None:
        self.remote_stop = False
        self._button = None
        if estop_gpio >= 0:
            try:
                from gpiozero import Button
                self._button = Button(estop_gpio, pull_up=True)
            except Exception as e:
                # the mushroom still cuts the contactor in hardware, we just can't see it from the Pi
                print(f"[safety] WARNING: can't read e-stop aux contact on GPIO{estop_gpio} ({e})")

    def stop_reasons(self, state: RoverState, front_m: float = math.inf, now: float | None = None) -> list[str]:
        now = time.monotonic() if now is None else now
        reasons = []
        if self._button and self._button.is_pressed:
            reasons.append("ESTOP")
        if self.remote_stop:
            reasons.append("REMOTE_STOP")
        if now - state.last_heartbeat > config.HEARTBEAT_TIMEOUT_S:
            reasons.append("PIXHAWK_LOST")
        if 0 < state.battery_volts < config.MIN_BATTERY_VOLTS:
            reasons.append("LOW_BATTERY")
        if front_m < config.STOP_DISTANCE_M:
            reasons.append("OBSTACLE")
        return reasons
