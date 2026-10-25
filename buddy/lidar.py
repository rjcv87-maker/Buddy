"""RPLIDAR A1M8. All I need from it for now is the closest thing in front."""
import math
import random

from . import config


def closest_ahead(scan, arc_deg=config.FRONT_ARC_DEG):
    half = arc_deg / 2
    hits = [d for a, d in scan if d > 0.05 and (a % 360 <= half or a % 360 >= 360 - half)]
    return min(hits) if hits else math.inf


class Lidar:
    def __init__(self, port=config.LIDAR_PORT, baud=config.LIDAR_BAUD):
        from rplidar import RPLidar
        self.dev = RPLidar(port, baudrate=baud)
        self._scans = self.dev.iter_scans(max_buf_meas=2000)

    def scan(self):
        return [(angle, mm / 1000) for _, angle, mm in next(self._scans)]

    def close(self):
        self.dev.stop()
        self.dev.stop_motor()
        self.dev.disconnect()


class MockLidar:
    def __init__(self, wall_m=None):
        self.wall_m = wall_m    # put a wall in front to test the stop

    def scan(self):
        out = []
        for a in range(0, 360, 2):
            d = 6 + random.random()
            if self.wall_m is not None and (a <= 15 or a >= 345):
                d = self.wall_m
            out.append((float(a), d))
        return out

    def close(self):
        pass
