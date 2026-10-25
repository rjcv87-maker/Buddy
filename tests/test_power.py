import math

from buddy.main import build
from buddy.power import Power

RAILS = {"lights": (5, True, False), "lidar": (6, True, True)}


def test_defaults_save_and_restore(tmp_path):
    f = str(tmp_path / "power.json")
    p = Power(simulate=True, rails=RAILS, state_file=f, override="")
    assert not p.is_on("lights") and p.is_on("lidar")
    p.on("lights"); p.off("lidar")
    q = Power(simulate=True, rails=RAILS, state_file=f, override="")
    assert q.is_on("lights") and not q.is_on("lidar")


def test_override_and_unknown(tmp_path):
    p = Power(simulate=True, rails=RAILS, state_file=str(tmp_path / "p.json"), override="lights=on,nope=on")
    assert p.is_on("lights")
    assert p.set("nope", True) is False


def test_cli_change_is_picked_up(tmp_path):
    f = str(tmp_path / "p.json")
    svc = Power(simulate=True, rails=RAILS, state_file=f, override="")
    Power(simulate=True, rails=RAILS, state_file=f, override="").on("lights")
    svc.poll(now=1e9)
    assert svc.is_on("lights")


class BrokenLidar:
    def scan(self):
        raise OSError("unplugged")

    def close(self):
        pass


def test_lost_lidar_does_not_stop_driving():
    r = build(True)
    r.lidar = BrokenLidar()
    r.connect(); r.arm()
    r.drive(0.5)                      # must not raise
    assert r.lidar is None and r.front_m == math.inf
    r.close()


def test_lidar_switched_off_does_not_stop_driving(tmp_path):
    p = Power(simulate=True, rails=RAILS, state_file=str(tmp_path / "p.json"), override="")
    r = build(True, power=p)
    p.off("lidar")
    r.connect(); r.arm()
    r.drive(0.5)
    assert r.lidar is None
    r.close()
