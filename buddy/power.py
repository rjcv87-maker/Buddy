"""
Turn peripherals on and off (lights, LiDAR, cameras, modules, solar charge path).

From the shell:
    python -m buddy.power                 # show everything
    python -m buddy.power on lights
    python -m buddy.power off geo sig
    python -m buddy.power all-off

The command saves the new state to POWER_STATE_FILE. If the buddy service is running it
picks the change up within a second; if not, it's applied at the next boot.
Use --now to drive the pins yourself (only when the service is stopped, it owns the pins).

Rule: a peripheral that is missing, unplugged or switched off never stops the rover from
driving. Everything here warns and keeps going.
"""
from __future__ import annotations

import json
import os
import sys
import time

from . import config


def _parse_override(raw: str) -> dict:
    out = {}
    for item in raw.split(","):
        if "=" in item:
            k, v = item.split("=", 1)
            out[k.strip()] = v.strip().lower() in ("1", "on", "true", "yes")
    return out


class Power:
    def __init__(self, simulate=False, rails=None, state_file=None, override=None):
        self.rails = dict(config.POWER_RAILS if rails is None else rails)
        self.state_file = state_file or config.POWER_STATE_FILE
        self.simulate = simulate
        self.state = {name: default for name, (_, _, default) in self.rails.items()}
        self.state.update({k: v for k, v in self.load().items() if k in self.rails})
        ov = _parse_override(config.POWER_OVERRIDE if override is None else override)
        for k in ov:
            if k not in self.rails:
                print(f"[power] BUDDY_POWER: unknown '{k}', ignored")
        self.state.update({k: v for k, v in ov.items() if k in self.rails})
        self._pins = {}
        self._mtime = 0.0
        self._last_check = 0.0

    # --- saved state ---
    def load(self) -> dict:
        try:
            with open(self.state_file) as f:
                return {k: bool(v) for k, v in json.load(f).items()}
        except (OSError, ValueError):
            return {}

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.state_file) or ".", exist_ok=True)
            with open(self.state_file, "w") as f:
                json.dump(self.state, f, indent=1)
        except OSError as e:
            print(f"[power] can't save state ({e}), it'll be lost at reboot")

    # --- pins ---
    def _pin(self, name):
        if name in self._pins:
            return self._pins[name]
        gpio, active_high, _ = self.rails[name]
        dev = None
        if gpio >= 0 and not self.simulate:
            try:
                from gpiozero import OutputDevice
                dev = OutputDevice(gpio, active_high=active_high, initial_value=False)
            except Exception as e:
                print(f"[power] {name}: no GPIO{gpio} ({e}), skipping")
        self._pins[name] = dev
        return dev

    def apply(self) -> None:
        for name, on in self.state.items():
            dev = self._pin(name)
            try:
                if dev is not None:
                    dev.on() if on else dev.off()
            except Exception as e:
                print(f"[power] {name}: {e}, skipping")

    def start(self):
        self.apply()
        print("[power] " + "  ".join(f"{n}={'on' if v else 'off'}" for n, v in self.state.items()))
        return self

    # --- API ---
    def set(self, name: str, on: bool, save=True) -> bool:
        if name not in self.rails:
            print(f"[power] unknown peripheral '{name}', I know: {', '.join(self.rails)}")
            return False
        self.state[name] = bool(on)
        dev = self._pin(name)
        try:
            if dev is not None:
                dev.on() if on else dev.off()
        except Exception as e:
            print(f"[power] {name}: {e}")
        if save:
            self.save()
        return True

    def on(self, name):
        return self.set(name, True)

    def off(self, name):
        return self.set(name, False)

    def is_on(self, name) -> bool:
        return self.state.get(name, True)   # no switch configured = always powered

    def all_off(self):
        for n in self.rails:
            self.set(n, False, save=False)
        self.save()

    def poll(self, now=None) -> None:
        """called from Rover.tick(): pick up changes made with the CLI"""
        now = time.monotonic() if now is None else now
        if now - self._last_check < 1.0:
            return
        self._last_check = now
        try:
            m = os.path.getmtime(self.state_file)
        except OSError:
            return
        if m == self._mtime:
            return
        self._mtime = m
        for k, v in self.load().items():
            if k in self.rails and self.state.get(k) != v:
                print(f"[power] {k} -> {'on' if v else 'off'}")
                self.set(k, v, save=False)

    def close(self):
        for dev in self._pins.values():
            try:
                if dev is not None:
                    dev.close()
            except Exception:
                pass


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog="python -m buddy.power", description="peripheral power on/off")
    p.add_argument("action", nargs="?", default="list", choices=["list", "on", "off", "all-off"])
    p.add_argument("names", nargs="*")
    p.add_argument("--now", action="store_true", help="drive the GPIO here (service must be stopped)")
    a = p.parse_args(argv)
    pw = Power(simulate=not a.now, override="")
    ok = True
    if a.action == "on":
        ok = all([pw.on(n) for n in a.names])
    elif a.action == "off":
        ok = all([pw.off(n) for n in a.names])
    elif a.action == "all-off":
        pw.all_off()
    for n, (gpio, _, _) in pw.rails.items():
        print(f"  {n:8s} {'ON ' if pw.state[n] else 'off'}  GPIO{gpio if gpio >= 0 else ' -'}")
    if a.now:
        time.sleep(0.1)
        # gpiozero resets pins on exit, so --now is for a quick bench test, not to leave things on
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
