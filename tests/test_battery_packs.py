import importlib

import pytest

from buddy import config
from buddy.link import MockRoverLink
from buddy.rover import Rover


@pytest.mark.parametrize("packs,mah", [(2, 20000), (3, 30000), (4, 40000)])
def test_capacity_follows_packs(packs, mah):
    assert config.batt_capacity_mah(packs) == mah


@pytest.mark.parametrize("bad", [0, 1, 5])
def test_rejects_impossible_pack_count(bad):
    with pytest.raises(ValueError):
        config.batt_capacity_mah(bad)


def test_env_sets_packs(monkeypatch):
    monkeypatch.setenv("BUDDY_BATT_PACKS", "3")
    importlib.reload(config)
    try:
        assert config.batt_capacity_mah() == 30000
    finally:
        monkeypatch.delenv("BUDDY_BATT_PACKS")
        importlib.reload(config)


def test_connect_pushes_capacity_to_pixhawk():
    link = MockRoverLink()
    r = Rover(link, simulate=True)
    r.connect()
    assert link.params["BATT_CAPACITY"] == config.batt_capacity_mah()


def test_param_files_default_two_packs():
    for f in ("params/buddy_6wd_rocker_4ws.parm", "params/buddy_6wd_skidsteer_alt.parm"):
        line = [l for l in open(f) if l.startswith("BATT_CAPACITY")][0]
        assert int(line.split()[1]) == 20000
