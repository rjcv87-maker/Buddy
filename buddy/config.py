"""
Every number I tune lives here. Two rovers run the same code; the only thing that
changes between them is BUDDY_ROVER_ID (and the team key if you use one), which
systemd passes in from /etc/buddy/env.
"""
import os

ROVER_ID = int(os.environ.get("BUDDY_ROVER_ID", "1"))   # 1 = unit A, 2 = unit B

# Pixhawk TELEM2 -> Pi UART0. For SITL use "udpin:0.0.0.0:14550".
DEFAULT_CONNECTION = os.environ.get("BUDDY_MAVLINK", "/dev/ttyAMA0")
SERIAL_BAUD = 921600

# Driving. Speeds are what I'm comfortable with in a parking lot, not the rover's max.
CRUISE_SPEED_MS = 0.8
TURN_RATE_DEG_S = 40.0          # 4-corner steering can't pivot; ArduPilot will arc instead
MAX_SPEED_MS = 1.5
MAX_TURN_DEG_S = 90.0

# Battery bay: 4 slots, run 2, 3 or 4 HRB 4S 10 Ah packs in parallel. Set BUDDY_BATT_PACKS in
# /etc/buddy/env to what is actually plugged in. On connect the Pi writes BATT_CAPACITY to the Pixhawk
# so the remaining-% and the low-battery failsafe match the packs on board.
PACK_MAH = 10000
BATT_SLOTS = 4
BATT_PACKS = int(os.environ.get("BUDDY_BATT_PACKS", "2"))


def batt_capacity_mah(packs: int = None) -> int:
    n = BATT_PACKS if packs is None else int(packs)
    if not 2 <= n <= BATT_SLOTS:
        raise ValueError(f"BUDDY_BATT_PACKS must be 2..{BATT_SLOTS}, got {n}")
    return n * PACK_MAH


# Safety. Packs are in parallel, so these are per-pack voltages.
MIN_BATTERY_VOLTS = 13.6        # 3.4 V/cell under load. Don't arm below this
MIN_BATTERY_PCT = 20
MISSION_TIMEOUT_S = 120
HEARTBEAT_TIMEOUT_S = 2.0       # Pixhawk went quiet
ESTOP_GPIO = 17                 # aux contact on the mushroom button, active low. -1 to disable
WATCHDOG_HEARTBEAT_GPIO = 27    # toggled every loop for firmware/estop_watchdog. -1 to disable

# LiDAR (RPLIDAR A1M8). 0 deg must point forward, check it after mounting.
LIDAR_PORT = "/dev/rplidar"
LIDAR_BAUD = 115200
STOP_DISTANCE_M = 0.6           # guess. Calibrate: drive at CRUISE_SPEED into a box, measure stop, add 0.3 m
FRONT_ARC_DEG = 60.0

# LoRa mesh (firmware/lora_node on a Pico).
MESH_PORT = "/dev/lora"
MESH_BAUD = 115200
# The open fleet key is public on purpose: it only proves "this speaks OTL".
# A team key keeps strangers from sending you STOP or FIND. Set one for real ops.
FLEET_KEY = "open-tech-lab-fleet-v1"
TEAM_KEY = os.environ.get("BUDDY_TEAM_KEY", "")
BEACON_PERIOD_S = 2.0
PEER_TIMEOUT_S = 10.0
REPLAY_WINDOW_S = 30            # needs GPS time on both units, see README

# Video. MJPEG over HTTP, good enough on the local Wi-Fi.
STREAM_PORT = 8080
STREAM_FPS = 10
THERMAL_DEVICE = "/dev/video_thermal"

CONTROL_HZ = 10

# Peripheral power. One relay/MOSFET channel per thing, driven from a Pi GPIO (BCM numbers).
# These pins are my proposal for the 8-ch relay board; change them to match your wiring.
# -1 = no switch fitted, the peripheral is always on. Nothing here can cut the drive: the
# motors, servos, Pixhawk and ExpressLRS are on their own power and are NOT in this list.
#   name: (gpio, active_high, default)
POWER_RAILS = {
    "lights":  (5,  True, False),   # light bar + strobes
    "lidar":   (6,  True, True),    # RPLIDAR, on by default because it feeds the obstacle stop
    "camera":  (13, True, True),    # Pi camera / USB hub port
    "thermal": (16, True, True),    # thermal camera
    "vic":     (19, True, False),   # victim pod (mic array, SCD30)
    "probe":   (20, True, False),   # endoscope probe + SCD41
    "sig":     (21, True, False),   # signal detector (RTL-SDR, ESP32-S3)
    "geo":     (26, True, False),   # geophone
    "sol":     (12, True, True),    # solar MPPT -> battery charge path
}
# last state you set is remembered here and restored at boot
POWER_STATE_FILE = os.environ.get("BUDDY_POWER_STATE", "/var/lib/buddy/power.json")
# quick override in /etc/buddy/env, wins over the saved state:  BUDDY_POWER=lights=on,geo=off
POWER_OVERRIDE = os.environ.get("BUDDY_POWER", "")
