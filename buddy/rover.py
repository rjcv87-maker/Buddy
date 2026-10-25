"""
The API missions are written against: connect, arm, drive, turn, stop.
tick() is the heartbeat of the whole thing: it reads the Pixhawk, the LiDAR and
the mesh, decides if we have to stop, and toggles the pin the hardware
watchdog listens to. Anything that loops has to call it.
"""
from __future__ import annotations

import math
import time

from . import config, safety
from .link import RoverLink
from .mesh import STOP


class Rover:
    def __init__(self, link: RoverLink, lidar=None, mesh=None, simulate=False, power=None) -> None:
        self.link, self.lidar, self.mesh, self.power = link, lidar, mesh, power
        self.watchdog = safety.Watchdog(-1 if simulate else config.ESTOP_GPIO)
        self.front_m = math.inf
        self.reasons: list[str] = []
        self._pulse = None
        if not simulate and config.WATCHDOG_HEARTBEAT_GPIO >= 0:
            try:
                from gpiozero import LED
                self._pulse = LED(config.WATCHDOG_HEARTBEAT_GPIO)
            except Exception as e:
                # estop_watchdog will keep the contactor open: you'll notice, but nothing crashes
                print(f"[rover] no watchdog pulse pin ({e})")

    def connect(self) -> None:
        self.link.connect()
        # packs on board -> Pixhawk, so battery % and BATT_FS_* are right for 2, 3 or 4 packs
        mah = config.batt_capacity_mah()
        self.link.set_param("BATT_CAPACITY", mah)
        print(f"[rover] {config.BATT_PACKS} packs, BATT_CAPACITY {mah} mAh")

    def close(self) -> None:
        self.stop()
        self.link.set_mode("HOLD")
        self.link.disarm()
        self.link.close()
        for dev in (self.lidar, self.power):
            if dev:
                try:
                    dev.close()
                except Exception as e:
                    print(f"[rover] close: {e}")

    def arm(self) -> None:
        safety.preflight_checks(self.link.get_state())
        self.link.set_mode("GUIDED")
        self.link.arm()

    def telemetry(self):
        return self.link.get_state()

    def print_telemetry(self) -> None:
        s = self.link.get_state()
        print(f"   pos=({s.x_m:5.2f}, {s.y_m:5.2f}) m  hdg={s.heading_deg:5.1f}  "
              f"{s.speed_ms:.2f} m/s  {s.battery_volts:.1f} V  {s.mode}  peers={self.mesh.live_peers() if self.mesh else []}")

    def tick(self, now: float | None = None) -> list[str]:
        state = self.link.get_state()
        if self.power:
            self.power.poll()
        # peripherals soft-fail: if one drops out we warn once, forget it and keep driving
        if self.lidar and self.power and not self.power.is_on("lidar"):
            print("[rover] LiDAR switched off: no obstacle stop")
            self._drop("lidar")
        if self.lidar:
            from .lidar import closest_ahead
            try:
                self.front_m = closest_ahead(self.lidar.scan())
            except Exception as e:
                print(f"[rover] LiDAR lost ({e}): no obstacle stop, drive carefully")
                self._drop("lidar")
        if self.mesh:
            try:
                self.mesh.tick(state, "ESTOP" in self.reasons, "OBSTACLE" in self.reasons, now)
                if self.mesh.stop_requested:
                    self.watchdog.remote_stop = True
            except Exception as e:
                print(f"[rover] LoRa mesh lost ({e}), carrying on alone")
                self.mesh = None
        reasons = self.watchdog.stop_reasons(state, self.front_m, now)
        if reasons and reasons != self.reasons:
            print(f"[safety] stop: {', '.join(reasons)}")
        self._react(state, reasons)
        self.reasons = reasons
        # no pulse while an e-stop is active, so the contactor opens too
        if self._pulse and not {"ESTOP", "REMOTE_STOP"} & set(reasons):
            self._pulse.toggle()
        return reasons

    def _drop(self, name) -> None:
        dev = getattr(self, name)
        setattr(self, name, None)
        if name == "lidar":
            self.front_m = math.inf
        try:
            dev.close()
        except Exception:
            pass

    def _react(self, state, reasons) -> None:
        # Pixhawk lost: nothing to tell it. FS_GCS_ENABLE on the Pixhawk side holds it.
        if not state.armed or not reasons or reasons == ["PIXHAWK_LOST"]:
            return
        if "ESTOP" in reasons or "REMOTE_STOP" in reasons:
            self.link.set_mode("HOLD")
            self.link.disarm(force=True)
        elif "LOW_BATTERY" in reasons and state.mode not in ("HOLD", "RTL", "SMART_RTL"):
            self.link.set_mode("HOLD")
        elif "OBSTACLE" in reasons and state.mode in ("GUIDED", "AUTO"):
            # in MANUAL the driver keeps control so they can back out
            self.link.set_mode("HOLD")

    def stop_everyone(self) -> None:
        if self.mesh:
            self.mesh.send(STOP)

    def stop(self) -> None:
        self.link.send_velocity(0.0, 0.0)

    def drive(self, distance_m: float, speed_ms: float | None = None) -> None:
        speed = speed_ms or config.CRUISE_SPEED_MS
        self._run_for(abs(distance_m) / speed, speed, 0.0, f"drive {distance_m:.1f} m")

    def turn(self, degrees: float) -> None:
        rate = math.copysign(config.TURN_RATE_DEG_S, degrees)
        self._run_for(abs(degrees) / config.TURN_RATE_DEG_S, 0.0, rate, f"turn {degrees:.0f} deg")

    def _run_for(self, duration_s, forward_ms, turn_deg_s, label) -> None:
        # Open loop on purpose for now. TODO: close it on telemetry like the old README said.
        print(f"[rover] {label}")
        if duration_s > config.MISSION_TIMEOUT_S:
            raise safety.SafetyError(f"'{label}' would take {duration_s:.0f}s, limit is {config.MISSION_TIMEOUT_S}s")
        period = 1 / config.CONTROL_HZ
        end = time.monotonic() + duration_s
        while time.monotonic() < end:
            self.link.send_velocity(forward_ms, turn_deg_s)
            reasons = self.tick()
            if reasons:
                self.stop()
                raise safety.SafetyError(", ".join(reasons))
            safety.check_battery(self.link.get_state())
            time.sleep(period)
        self.stop()
