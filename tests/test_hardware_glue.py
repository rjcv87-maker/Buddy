import threading
import time
import urllib.request
from pathlib import Path

from pymavlink import mavutil

from buddy.link import MavlinkRoverLink
from buddy.vision import VideoServer


def test_mavlink_link_against_fake_pixhawk():
    fake = mavutil.mavlink_connection("udpout:127.0.0.1:14599", source_system=1, source_component=1)
    done = threading.Event()

    def pixhawk():
        while not done.is_set():
            fake.mav.heartbeat_send(10, 3, 128 | 1, 15, 0)   # ground rover, ardupilot, armed, GUIDED
            fake.mav.sys_status_send(0, 0, 0, 0, 16200, -1, 80, 0, 0, 0, 0, 0, 0)
            time.sleep(0.05)

    threading.Thread(target=pixhawk, daemon=True).start()
    link = MavlinkRoverLink("udpin:127.0.0.1:14599")
    try:
        link.connect(timeout=5)
        time.sleep(0.2)
        s = link.get_state()
        assert s.armed and s.mode == "GUIDED" and abs(s.battery_volts - 16.2) < 1e-6
        link.set_mode("HOLD")
        assert fake.recv_match(type=["SET_MODE", "COMMAND_LONG"], blocking=True, timeout=2) is not None
    finally:
        done.set()
        link.close()


def test_video_test_pattern():
    v = VideoServer(True, host="127.0.0.1", port=0, fps=20).start()
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{v.httpd.server_address[1]}/thermal", timeout=3)
        assert b"\xff\xd8" in r.read(20000)
    finally:
        v.stop()


def test_param_files_parse():
    for f in Path(__file__).parent.parent.joinpath("params").glob("*.parm"):
        p = dict(l.split("#")[0].split() for l in f.read_text().splitlines() if l.split("#")[0].strip())
        assert p["FS_THR_ENABLE"] == "1" and p["FS_GCS_ENABLE"] == "1", f.name
