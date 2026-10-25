"""Recipes built from drive() and turn(). Same ones as the first buddy_brain plus the shared search."""
from __future__ import annotations

import time

from . import config
from .mesh import split_area
from .rover import Rover


def drive_square(rover: Rover, side_m: float = 2.0) -> None:
    for _ in range(4):
        rover.drive(side_m)
        rover.turn(90)
        rover.print_telemetry()


def lawnmower_search(rover: Rover, width_m: float = 4.0, length_m: float = 3.0,
                     lane_spacing_m: float = 1.0) -> None:
    lanes = max(1, int(length_m / lane_spacing_m))
    direction = 1
    for lane in range(lanes):
        rover.drive(width_m)
        rover.print_telemetry()
        if lane < lanes - 1:
            rover.turn(90 * direction)
            rover.drive(lane_spacing_m)
            rover.turn(90 * direction)
            direction *= -1


def shared_search(rover: Rover, width_m: float = 8.0, length_m: float = 3.0,
                  wait_for_peers_s: float = 6.0) -> None:
    """Handshake, take my strip of the box, sweep it. Box starts at my position, heading = north."""
    end = time.monotonic() + wait_for_peers_s
    while time.monotonic() < end and not rover.mesh.live_peers():
        rover.tick()
        time.sleep(1 / config.CONTROL_HZ)
    team = rover.mesh.team()
    offset, strip = split_area(width_m, team, rover.mesh.node)
    print(f"[mission] team {team}, coordinator {rover.mesh.coordinator()}, "
          f"my strip starts {offset:.1f} m east, {strip:.1f} m wide")
    if offset:
        rover.turn(90)
        rover.drive(offset)
        rover.turn(-90)
    # lanes run north along the length here, spaced across my strip
    lawnmower_search(rover, width_m=length_m, length_m=strip, lane_spacing_m=1.0)
    for f in rover.mesh.finds:
        print(f"[mission] find from {f['from']}: {f['lat']:.6f}, {f['lon']:.6f} ({f['confidence']:.0%})")


def standby(rover: Rover, duration_s: float = 0) -> None:
    """What systemd runs: RC driver in charge, Pi keeps safety, mesh and video up."""
    end = time.monotonic() + duration_s
    while not duration_s or time.monotonic() < end:
        rover.tick()
        time.sleep(1 / config.CONTROL_HZ)
