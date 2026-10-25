"""
python -m buddy.main --sim                     # square in the simulator
python -m buddy.main --sim --mission search    # two-rover shared search, both in one process
python -m buddy.main                           # standby on the real rover (what systemd runs)
"""
from __future__ import annotations

import argparse
import time

from . import config, missions
from .link import make_link
from .mesh import SENSORS, Mesh, MockAir, SerialRadio
from .power import Power
from .rover import Rover
from .safety import SafetyError

ONBOARD = SENSORS["gps"] | SENSORS["lidar"] | SENSORS["camera"] | SENSORS["thermal"]


def _try(what, make):
    # a missing peripheral must never keep the rover from driving: warn and carry on without it
    try:
        return make()
    except Exception as e:
        print(f"[buddy] {what} not available ({e}), running without it")
        return None


def build(simulate: bool, connection: str = config.DEFAULT_CONNECTION, node: int = config.ROVER_ID,
          air: MockAir | None = None, wall_m: float | None = None, power: Power | None = None) -> Rover:
    power = power or Power(simulate).start()
    if simulate:
        from .lidar import MockLidar
        radio, lidar = (air or MockAir()).radio(), MockLidar(wall_m)
    else:
        from .lidar import Lidar
        radio = _try("LoRa radio", SerialRadio)
        if power.is_on("lidar"):
            time.sleep(1.0)     # let the LiDAR spin up after its rail comes on
            lidar = _try("LiDAR", Lidar)
        else:
            lidar = None
            print("[buddy] LiDAR switched off: no obstacle stop, drive carefully")
    mesh = Mesh(radio, node, sensors=ONBOARD) if radio else None
    return Rover(make_link(simulate, connection), lidar, mesh, simulate, power=power)


def _sim_pair():
    import threading
    air = MockAir()
    a, b = build(True, node=1, air=air), build(True, node=2, air=air)
    for r in (a, b):
        r.connect()
        r.arm()
    t = threading.Thread(target=missions.shared_search, args=(b,), kwargs={"width_m": 4.0, "length_m": 2.0})
    t.start()
    missions.shared_search(a, width_m=4.0, length_m=2.0)
    t.join()
    for r in (a, b):
        r.close()


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Buddy rover brain")
    p.add_argument("--sim", action="store_true", help="no hardware")
    p.add_argument("--connect", default=config.DEFAULT_CONNECTION)
    p.add_argument("--mission", default=None, choices=["square", "search", "standby"])
    p.add_argument("--no-video", action="store_true")
    p.add_argument("--duration", type=float, default=0, help="standby only, 0 = forever")
    args = p.parse_args(argv)
    mission = args.mission or ("square" if args.sim else "standby")

    if args.sim and mission == "search":
        _sim_pair()
        return

    video = None
    if not args.no_video:
        from .vision import VideoServer
        video = _try("video", lambda: VideoServer(args.sim).start())
    buddy = build(args.sim, args.connect)
    try:
        buddy.connect()
        if mission == "standby":
            missions.standby(buddy, args.duration)
        else:
            buddy.arm()
            if mission == "square":
                missions.drive_square(buddy, 2.0)
            else:
                missions.shared_search(buddy)
    except SafetyError as e:
        print(f"\n[SAFETY STOP] {e}")
    except KeyboardInterrupt:
        pass
    finally:
        buddy.close()
        if video:
            video.stop()
        print("Done.")


if __name__ == "__main__":
    main()
