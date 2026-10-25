import time

from buddy import mesh
from buddy.main import build


def test_two_rovers_handshake_and_find():
    air = mesh.MockAir()
    a, b = build(True, node=1, air=air), build(True, node=2, air=air)
    for r in (a, b):
        r.connect()
        r.tick()
    a.tick()
    assert a.mesh.team() == b.mesh.team() == [1, 2] and b.mesh.coordinator() == 1
    assert a.mesh.peers[2]["status"]["mode"] == "HOLD"
    b.mesh.report_find(18.47, -66.10, 0.9)
    a.tick()
    assert a.mesh.finds[0]["from"] == 2


def test_peer_drops_out():
    air = mesh.MockAir()
    a, b = build(True, node=1, air=air), build(True, node=2, air=air)
    a.connect(); b.connect(); b.tick(); a.tick()
    assert a.mesh.live_peers(time.monotonic() + 60) == []


def test_obstacle_holds_guided_not_manual():
    r = build(True, wall_m=0.3)
    r.connect()
    r.arm()
    assert "OBSTACLE" in r.tick() and r.telemetry().mode == "HOLD"
    r.link.set_mode("MANUAL")
    r.tick()
    assert r.telemetry().mode == "MANUAL"


def test_remote_stop_disarms():
    air = mesh.MockAir()
    a, b = build(True, node=1, air=air), build(True, node=2, air=air)
    a.connect(); a.arm()
    b.stop_everyone()
    a.tick()
    assert not a.telemetry().armed


def test_square_runs():
    from buddy.main import main
    main(["--sim", "--mission", "standby", "--duration", "0.3", "--no-video"])
