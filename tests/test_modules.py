import pytest
from buddy import modules, victims, solar
from buddy.mesh import Mesh, MockAir, unpack, FIND


def test_bare_rover_no_modules():
    m = modules.detect(set(), set(), env={})
    assert m.active == set() and modules.sensor_mask(m) == 0


def test_autodetect_usb_i2c():
    m = modules.detect({"0bda:2838", "0403:6015"}, {0x61, 0x48}, env={})
    assert m.active == {"sig", "sol", "vic", "geo"}


def test_env_restricts_and_reports_missing():
    m = modules.detect({"0bda:2838"}, set(), env={"BUDDY_MODULES": "sig,geo"})
    assert m.active == {"sig"} and m.missing() == {"geo"}


def test_env_rejects_unknown():
    with pytest.raises(ValueError):
        modules.wanted_from_env({"BUDDY_MODULES": "laser"})


def test_co2_rise():
    d = victims.Co2Detector()
    assert not any(d.update(420, t) for t in range(0, 60))
    assert d.update(600, 61)


def test_knock_needs_three():
    k = victims.KnockDetector(); out = []
    for i in range(400):
        t = i*0.05; x = 0.5 if i in (100, 140, 180) else 0.01
        out.append(k.update(x, t))
    assert not any(out[:180]) and out[180]


def test_single_cue_does_not_report(tmp_path):
    f = victims.VictimFusion(log_path=str(tmp_path/"v.jsonl"))
    f.cue("co2", 0.0)
    assert f.reported == []


def test_mock_victim_sends_signed_find(tmp_path):
    air = MockAir(); tx = Mesh(air.radio(), 1); rx = Mesh(air.radio(), 2)
    f = victims.VictimFusion(mesh=tx, log_path=str(tmp_path/"v.jsonl"), position=lambda: (40.4168, -3.7038))
    f.rf.baseline([])
    for kind, v, t in victims.mock_stream(): f.feed(kind, v, t)
    assert f.reported and (tmp_path/"v.jsonl").read_text().count("\n") >= 1
    got = [m for m in rx.receive() if m.get("type") == FIND or m.get("kind") == FIND]
    assert got


def test_vedirect_parse():
    b = solar.parse_block(["V\t13250", "I\t1200", "VPV\t34100", "PPV\t18", "CS\t3", "H20\t12", "ERR\t0", "Checksum\tx"])
    assert b["battery_v"] == pytest.approx(13.25) and b["panel_w"] == 18 and solar.STATES[b["state"]] == "bulk"
