import time

import pytest

from buddy import mesh
from buddy.link import RoverState


def test_frame_roundtrip_and_auth():
    keys = {mesh.FLEET_KEY_ID: b"fleet"}
    f = mesh.pack(b"fleet", 0, mesh.BEACON, 7, 3, b"hi")
    m = mesh.unpack(keys, f)
    assert (m["kind"], m["node"], m["payload"], m["trusted"]) == (mesh.BEACON, 7, b"hi", True)
    with pytest.raises(mesh.BadFrame):
        mesh.unpack({0: b"other"}, f)
    # fleet-signed frame is valid but not trusted once I have a team key
    assert not mesh.unpack({0: b"fleet", 1: b"team"}, f)["trusted"]


def test_replay_old_and_untrusted_stop():
    air = mesh.MockAir()
    tx, rx = air.radio(), mesh.Mesh(air.radio(), 2, "fleet", team_key="team")
    f = mesh.pack(b"fleet", 0, mesh.STOP, 1, 5)
    tx.write(f)
    tx.write(f)
    tx.write(mesh.pack(b"fleet", 0, mesh.BEACON, 1, 6, ts=int(time.time()) - 3600))
    rx.receive()
    assert rx.dropped == 2 and not rx.stop_requested


def test_status_payload():
    s = RoverState(armed=True, mode="GUIDED", lat=18.5, lon=-66.1, heading_deg=270, battery_volts=16.1)
    st = mesh.read_status(mesh.status_payload(s, mesh.SENSORS["lidar"], obstacle=True))
    assert st["mode"] == "GUIDED" and st["armed"] and st["obstacle"] and st["sensors"] == ["lidar"]
    assert abs(st["lat"] - 18.5) < 1e-6


def test_split_area():
    assert mesh.split_area(8, [1, 2], 2) == (4, 4)
    assert mesh.split_area(9, [1, 4, 7], 1) == (0, 3)
