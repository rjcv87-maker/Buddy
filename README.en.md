[Español](README.es.md) | [English](README.en.md)

# Buddy software

This is the software for Buddy, Open Tech Lab's search and rescue rover. I split it the same way the proposal does: the Pi thinks, the Pixhawk reacts, and a few small Picos handle the odd jobs. The structure comes from [OLT](https://github.com/rjcv87-maker/OLT) (the `buddy` package with config, link, safety, rover, missions and main). I added the LoRa mesh, the LiDAR and the cameras.

## What runs where

| In the proposal | Here |
|---|---|
| Pi 5, mission and cooperation "brain" | `buddy/`, Python with pymavlink |
| handshake and LoRa mesh | `buddy/mesh.py` |
| vision (camera and thermal) | `buddy/vision.py` (Coral is still a TODO) |
| mission decisions | `buddy/missions.py`, `buddy/rover.py` |
| Pixhawk "reflexes" (ArduPilot configured, not rewritten) | `params/*.parm` |
| dedicated C/C++ nodes | `firmware/lora_node`, `firmware/light_controller`, `firmware/estop_watchdog` |

The proposal says Arduino/ESP32 for the nodes. I used Raspberry Pi Picos (RP2040) on the Arduino core because that's what the v2 CAD has. It's plain Arduino code, so moving to an ESP32 is mostly changing pins.

The links follow the fleet architecture: LoRa (RFM95W/SX1276, 915 MHz) for position, battery, status and alerts; Wi-Fi only for video; ExpressLRS for manual control from the TX16S.

## The handshake

It lives in `buddy/mesh.py` and follows the six steps in the proposal:

1. Discovery: every unit sends a BEACON every 2 s.
2. Identity and capability: the beacon carries module type, sensors (a bitmask), battery and position, and it's signed.
3. Authentication: everything is signed with the open fleet key. If a team sets `BUDDY_TEAM_KEY`, it signs with that and only trusts peers that have the same key.
4. Roles: the lowest live id coordinates. `split_area()` cuts the area into strips based on the team list. The clock is the Pi's, which I set from GPS/NTP.
5. Execution: a find goes out to everyone as FIND. STOP halts the whole team. Both are only accepted from trusted peers.
6. Join and exit: if a peer goes quiet for 10 s it drops off the list and everyone recomputes their strip. There's no central server.

The frame:

```
"OT" ver type module node(u16) seq(u16) ts(u32) key_id len | payload | HMAC-SHA256[:8]
```

Types: 1 BEACON, 2 STATUS, 3 FIND, 4 STOP. I drop frames with a repeated seq or a clock more than 30 s off. That means the Pi needs the right time, and without GPS or internet it doesn't have it. `lora_node` knows nothing about any of this; it just moves bytes between USB and the radio.

OLT mentions a `fleet_handshake_demo.py`, but it isn't in the repo. If it turns up, I'll match this format to it.

## Safety

The layers, hardest first:

- The E-stop button is in series with the VESC contactor coil. No software involved.
- `estop_watchdog` opens the contactor if the Pi stops toggling GPIO27 for 500 ms or if the Pico itself hangs. It boots open and has to be re-armed by hand.
- ArduPilot: RC, Pi heartbeat (FS_GCS_ENABLE), battery and crash failsafes, all set to HOLD.
- The `Watchdog` class in `buddy/safety.py`. The button, a remote STOP or low battery switch to HOLD, and the button or a STOP also disarm. An obstacle closer than 0.6 m switches to HOLD, but only in GUIDED or AUTO. In MANUAL, you're the one driving.

## Wiring

| From | Port | To | Notes |
|---|---|---|---|
| Pixhawk MAIN1/2 | PWM | front left/right DS3225 servos | SERVO_FUNCTION 26 |
| Pixhawk MAIN3/4 | PWM | rear left/right servos | 26, REVERSED |
| 7.4 V BEC, 10 A or more | | power for the 4 servos | common GND with the Pixhawk, never off the Pixhawk rail |
| Pixhawk MAIN5/6/7 | PWM | FSESC 1/2/3, Y-cable to both PPM inputs | Throttle 70 |
| Pixhawk MAIN8 | PWM | light_controller GP2 | RC8 passthrough, add a divider if the signal is above 3.3 V |
| Pixhawk TELEM1 | UART | SiK 915 MHz radio | 57600 |
| Pixhawk TELEM2 | UART | Pi GPIO14/15 and GND | 921600, `/dev/ttyAMA0` |
| Pixhawk UART6 | CRSF | ExpressLRS receiver | |
| Pixhawk GPS1 / POWER1 | | M10 GPS / power module | BATT_MONITOR 4 |
| Pi USB | | RPLIDAR A1M8 | udev `/dev/rplidar` |
| Pi USB | | lora_node | udev `/dev/lora` |
| Pi USB | | PureThermal 3 with Lepton 3.5 | udev `/dev/video_thermal` |
| Pi USB | | light_controller | optional, "L0".."L100" |
| Pi CSI | | Camera Module 3 | |
| Pi GPIO27 | out | estop_watchdog GP3 | 10 Hz heartbeat |
| Pi GPIO17 | in | E-stop aux contact | active low |
| lora_node GP18/19/16/17/20/21 | SPI | RFM95W SCK/MOSI/MISO/NSS/RST/DIO0 | 3V3 |
| light_controller GP10-13 | PWM | DIM on the 4 drivers | common GND |
| light_controller GP26 | ADC | 10k B3950 NTC with 10k to 3V3 | optional |
| estop_watchdog GP2 / GP4 | in | E-stop NC / re-arm NO, to GND | |
| estop_watchdog GP15 | out | contactor MOSFET, diode across the coil | HIGH = motors powered |

Fuses: 60 A main, 30 A per FSESC, 10 A for the lights.

The udev rules aren't in the repo yet. For now I get them with `udevadm info` on each Pi.

## Install

On the Pi 5 (Raspberry Pi OS 64-bit):

```
sudo apt install python3-picamera2
python3 -m venv --system-site-packages /opt/buddy/venv
/opt/buddy/venv/bin/pip install -r requirements.txt
sudo cp systemd/buddy.service /etc/systemd/system/
sudo mkdir -p /etc/buddy
echo "BUDDY_ROVER_ID=1" | sudo tee /etc/buddy/env
echo "BUDDY_BATT_PACKS=2" | sudo tee -a /etc/buddy/env   # 2, 3 or 4 packs fitted
sudo systemctl enable --now buddy
```

Every rover needs its own `BUDDY_ROVER_ID`. Everything else is in `buddy/config.py`, and anything that differs per rover can be overridden in `/etc/buddy/env`.

The order I bring it up in:

1. Load the params into the Pixhawk with Mission Planner (Config, Full Parameter List, Load from file), wheels in the air. Adjust each servo's MIN/TRIM/MAX until none of them hit their stop.
2. Flash the three Picos: `cd firmware/<project> && pio run -t upload`. For the ground station, `pio run -e pico_ground -t upload`.
3. Test the E-stop and the watchdog before the wheels are connected.
4. Start the service on the Pi.

## Testing without hardware

```
python3 -m buddy.main --sim                      # a square with one simulated rover
python3 -m buddy.main --sim --mission search     # two rovers find each other and split the area
python3 -m pytest -q
```

In sim the video is a test pattern at http://localhost:8080. `--no-video` skips the server.

For something closer to the real thing I use ArduPilot SITL: `sim_vehicle.py -v Rover --map --console`, then `python3 -m buddy.main --connect udp:127.0.0.1:14550 --mission square`.

## What's missing

- Person detection on the Coral. `detect_people()` is empty.
- Driving is open loop (speed for a time). It still needs to use position to close the loop.
- The udev rules.
- Measuring the real TURN_RADIUS, servo trims and stopping distance.
- A range test on the RFM95W, SF9 against SF10.
- The 30 s window needs GPS time when there's no internet.

## Modular batteries

The bay has 4 slots. `BUDDY_BATT_PACKS` (2 to 4) is how many are fitted. On connect, `buddy/rover.py` writes `BATT_CAPACITY` = packs x 10000 mAh to the Pixhawk so remaining % and the low-battery failsafe are right. If you change the pack count, change the variable and restart `buddy.service`.

## Removable modules
`buddy/modules.py` decides which modules are fitted. Wanted list in `/etc/buddy/env`:

```
BUDDY_MODULES=vic,probe,sig,geo,sol   # empty = autodetect only
```

A module is active when it is on the list **and** answers on the bus (I2C 0x61 vic, 0x62 probe, 0x48 geo, 0x40 servos; USB 2752:0019 vic, 0bda:2838 / 303a:1001 sig, 0403:6015 sol). A listed module that is missing is logged and the rest carries on. With an empty list, whatever is found is used.

- `buddy/victims.py`: CO2 (+150 ppm over a 120 s baseline), geophone knocks (6σ, 3 knocks in 10 s), RF device count. Two different cues within 60 s raise a signed FIND on the mesh and a JSONL log line.
- `buddy/solar.py`: reads the Victron MPPT over VE.Direct (V, I, PV power, charge state).
- `mesh.py`: new sensor bits co2 = 32, audio = 64, seismic = 128.
- Tests: `python3 -m pytest tests` (30 tests, no hardware; `mock_stream` fakes the sensors).

## Peripheral power on/off

Each peripheral (lights, LiDAR, camera, thermal, victim pod, probe, signal detector, geophone, solar charge path) sits on a relay/MOSFET channel driven by a Pi GPIO. Pins are in `POWER_RAILS` in `buddy/config.py` (my proposal, match them to your wiring; `-1` = no switch).

```
python -m buddy.power              # show state
python -m buddy.power on lights
python -m buddy.power off geo sig
python -m buddy.power all-off
```

State is saved to `/var/lib/buddy/power.json`; the running service picks it up within 1 s and restores it at boot. To force at boot: `BUDDY_POWER=lights=on,geo=off` in `/etc/buddy/env`. Defaults: LiDAR, cameras and solar on, the rest off.

Rule: a peripheral that is unplugged, switched off or failing **never** blocks driving. It's logged and the rover carries on. Motors, servos, Pixhawk and ExpressLRS are not in this list. Note: without the LiDAR there is no obstacle stop.
