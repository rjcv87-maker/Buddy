[Español](README.es.md) | [English](README.en.md)

# Buddy software

Este es el software de Buddy, el rover de búsqueda y rescate de Open Tech Lab. Lo dividí igual que en la propuesta: la Pi piensa, la Pixhawk reacciona y unos Pico chiquitos hacen los trabajos sueltos. La estructura viene de [OLT](https://github.com/rjcv87-maker/OLT) (el paquete `buddy` con config, link, safety, rover, missions y main). Le añadí la malla LoRa, el LiDAR y la cámara.

## Qué corre dónde

| En la propuesta | Aquí |
|---|---|
| Pi 5, "cerebro" de misión y cooperación | `buddy/` en Python con pymavlink |
| handshake y malla LoRa | `buddy/mesh.py` |
| visión (cámara y térmica) | `buddy/vision.py` (Coral todavía es un TODO) |
| decisiones de misión | `buddy/missions.py`, `buddy/rover.py` |
| Pixhawk, "reflejos" (ArduPilot configurado, no reescrito) | `params/*.parm` |
| nodos dedicados en C/C++ | `firmware/lora_node`, `firmware/light_controller`, `firmware/estop_watchdog` |

La propuesta dice Arduino/ESP32 para los nodos. Yo usé Raspberry Pi Pico (RP2040) con el core Arduino porque es lo que ya está en el CAD v2. El código es Arduino normal, así que pasarlo a un ESP32 es cambiar pines.

Los enlaces siguen la arquitectura de flota: LoRa (RFM95W/SX1276, 915 MHz) para posición, batería, estado y alertas; Wi-Fi solo para video; ExpressLRS para el control manual desde la TX16S.

## El handshake

Está en `buddy/mesh.py` y sigue los seis pasos de la propuesta:

1. Descubrimiento: cada unidad manda un BEACON cada 2 s.
2. Identidad y capacidades: el beacon lleva tipo de módulo, sensores (bitmask), batería y posición, y va firmado.
3. Autenticación: todo va firmado con la clave abierta de la flota. Si un equipo pone `BUDDY_TEAM_KEY`, firma con esa y solo confía en quien tenga la misma.
4. Roles: el id más bajo que sigue vivo coordina. `split_area()` reparte la zona en franjas según la lista del equipo. El reloj es el de la Pi, que lo pongo en hora por GPS/NTP.
5. Ejecución: un hallazgo se manda como FIND a todos. STOP para a todo el equipo. Ambos se aceptan solo de pares de confianza.
6. Entrar y salir: si un par se calla 10 s, sale de la lista y cada uno recalcula su franja. No hay servidor central.

La trama:

```
"OT" ver tipo modulo nodo(u16) seq(u16) ts(u32) key_id len | payload | HMAC-SHA256[:8]
```

Tipos: 1 BEACON, 2 STATUS, 3 FIND, 4 STOP. Descarto tramas con seq repetido o con más de 30 s de diferencia de hora. Eso significa que la Pi necesita la hora bien puesta, y sin GPS ni internet no la tiene. El `lora_node` no entiende nada de esto; solo pasa bytes entre USB y radio.

En OLT se menciona un `fleet_handshake_demo.py` pero no está en el repo. Si aparece, alineo el formato con ese.

## Seguridad

Las capas, de más dura a más blanda:

- La seta de E-stop está en serie con la bobina del contactor de los VESC. Eso no depende de ningún software.
- `estop_watchdog` abre el contactor si la Pi deja de alternar GPIO27 por 500 ms o si el propio Pico se cuelga. Arranca abierto y hay que rearmarlo a mano.
- ArduPilot: failsafe de RC, de heartbeat de la Pi (FS_GCS_ENABLE), de batería y de choque. Todos a HOLD.
- `buddy/safety.py`, la clase `Watchdog`. Con la seta, un STOP remoto o batería baja, pone HOLD (y con la seta o el STOP también desarma). Con un obstáculo a menos de 0.6 m pone HOLD, pero solo en GUIDED o AUTO. En MANUAL el que maneja eres tú.

## Cableado

| Origen | Puerto | Destino | Notas |
|---|---|---|---|
| Pixhawk MAIN1/2 | PWM | servos DS3225 delanteros izq./der. | SERVO_FUNCTION 26 |
| Pixhawk MAIN3/4 | PWM | servos traseros izq./der. | 26, REVERSED |
| BEC 7.4 V, 10 A o más | | alimentación de los 4 servos | GND común con la Pixhawk, nunca del riel de la Pixhawk |
| Pixhawk MAIN5/6/7 | PWM | FSESC 1/2/3, Y-cable a las dos entradas PPM | Throttle 70 |
| Pixhawk MAIN8 | PWM | light_controller GP2 | RC8 directo, divisor si la señal pasa de 3.3 V |
| Pixhawk TELEM1 | UART | radio SiK 915 MHz | 57600 |
| Pixhawk TELEM2 | UART | Pi GPIO14/15 y GND | 921600, `/dev/ttyAMA0` |
| Pixhawk UART6 | CRSF | receptor ExpressLRS | |
| Pixhawk GPS1 / POWER1 | | GPS M10 / módulo de potencia | BATT_MONITOR 4 |
| Pi USB | | RPLIDAR A1M8 | udev `/dev/rplidar` |
| Pi USB | | lora_node | udev `/dev/lora` |
| Pi USB | | PureThermal 3 con Lepton 3.5 | udev `/dev/video_thermal` |
| Pi USB | | light_controller | opcional, "L0".."L100" |
| Pi CSI | | Camera Module 3 | |
| Pi GPIO27 | salida | estop_watchdog GP3 | latido a 10 Hz |
| Pi GPIO17 | entrada | contacto auxiliar de la seta | activo bajo |
| lora_node GP18/19/16/17/20/21 | SPI | RFM95W SCK/MOSI/MISO/NSS/RST/DIO0 | 3V3 |
| light_controller GP10-13 | PWM | DIM de los 4 drivers | GND común |
| light_controller GP26 | ADC | NTC 10k B3950 con 10k a 3V3 | opcional |
| estop_watchdog GP2 / GP4 | entrada | seta NC / rearme NO, a GND | |
| estop_watchdog GP15 | salida | MOSFET del contactor, con diodo en la bobina | HIGH = motores con potencia |

Fusibles: 60 A en la principal, 30 A por cada FSESC, 10 A para las luces.

Los udev rules todavía no están en el repo. Por ahora los saco con `udevadm info` en cada Pi.

## Instalar

En la Pi 5 (Raspberry Pi OS 64 bits):

```
sudo apt install python3-picamera2
python3 -m venv --system-site-packages /opt/buddy/venv
/opt/buddy/venv/bin/pip install -r requirements.txt
sudo cp systemd/buddy.service /etc/systemd/system/
sudo mkdir -p /etc/buddy
echo "BUDDY_ROVER_ID=1" | sudo tee /etc/buddy/env
echo "BUDDY_BATT_PACKS=2" | sudo tee -a /etc/buddy/env   # 2, 3 o 4 baterías montadas
sudo systemctl enable --now buddy
```

Cada rover necesita su propio `BUDDY_ROVER_ID`. El resto de valores está en `buddy/config.py`, y los que cambian por rover se pueden sobreescribir en `/etc/buddy/env`.

El orden en que lo monto:

1. Cargar los params en la Pixhawk con Mission Planner (Config, Full Parameter List, Load from file), con las ruedas en el aire. Ajustar MIN/TRIM/MAX de cada servo hasta que ninguno toque el tope.
2. Flashear los tres Pico: `cd firmware/<proyecto> && pio run -t upload`. Para la estación de tierra, `pio run -e pico_ground -t upload`.
3. Probar la seta y el watchdog antes de conectar las ruedas.
4. Arrancar el servicio en la Pi.

## Probar sin hardware

```
python3 -m buddy.main --sim                      # cuadrado con un rover simulado
python3 -m buddy.main --sim --mission search     # dos rovers que se encuentran y se reparten la zona
python3 -m pytest -q
```

El video en sim es un patrón de prueba en http://localhost:8080. Con `--no-video` no levanta el servidor.

Para algo más real uso SITL de ArduPilot: `sim_vehicle.py -v Rover --map --console` y luego `python3 -m buddy.main --connect udp:127.0.0.1:14550 --mission square`.

## Lo que falta

- Detección de personas con el Coral. `detect_people()` está vacía.
- El manejo es a lazo abierto (velocidad por tiempo). Falta usar la posición para cerrar el lazo.
- Las reglas udev.
- Medir TURN_RADIUS, los trims de los servos y la distancia de frenado de verdad.
- Prueba de alcance del RFM95W, SF9 contra SF10.
- La ventana de 30 s necesita la hora del GPS si no hay internet.

## Baterías modulares

La bahía tiene 4 ranuras. `BUDDY_BATT_PACKS` (2 a 4) dice cuántas hay puestas. Al conectar, `buddy/rover.py` escribe `BATT_CAPACITY` = packs x 10000 mAh en la Pixhawk, así el % restante y el failsafe de batería baja cuadran. Si cambias el número de baterías, cambia la variable y reinicia `buddy.service`.

## Módulos removibles
`buddy/modules.py` decide qué módulos hay. Lista deseada en `/etc/buddy/env`:

```
BUDDY_MODULES=vic,probe,sig,geo,sol   # vacío = solo autodetección
```

Un módulo está activo si está en la lista **y** responde en el bus (I2C 0x61 vic, 0x62 probe, 0x48 geo, 0x40 servos; USB 2752:0019 vic, 0bda:2838 / 303a:1001 sig, 0403:6015 sol). Si falta uno de la lista se avisa en el log y el resto sigue. Con la lista vacía se usa lo que se encuentre.

- `buddy/victims.py`: CO2 (+150 ppm sobre una base de 120 s), golpes en el geófono (6σ, 3 golpes en 10 s), conteo de dispositivos RF. Dos pistas distintas en 60 s generan un aviso FIND firmado en la malla y una línea en el log JSONL.
- `buddy/solar.py`: lee el MPPT Victron por VE.Direct (V, I, potencia PV, estado de carga).
- `mesh.py`: bits de sensor nuevos co2 = 32, audio = 64, seismic = 128.
- Pruebas: `python3 -m pytest tests` (30 pruebas, sin hardware; `mock_stream` simula los sensores).

## Prender y apagar periféricos

Cada periférico (luces, LiDAR, cámara, térmica, pod de víctimas, sonda, detector de señales, geófono, carga solar) va en un canal de relé/MOSFET manejado por un GPIO del Pi. Los pines están en `POWER_RAILS` de `buddy/config.py` (son mi propuesta, ajústalos a tu cableado; `-1` = sin interruptor).

```
python -m buddy.power              # ver estado
python -m buddy.power on lights
python -m buddy.power off geo sig
python -m buddy.power all-off
```

El estado se guarda en `/var/lib/buddy/power.json`; el servicio lo aplica en menos de 1 s y lo recuerda al reiniciar. Para forzar al arrancar: `BUDDY_POWER=lights=on,geo=off` en `/etc/buddy/env`. Por defecto: LiDAR, cámaras y solar prendidos; lo demás apagado.

Regla: un periférico desconectado, apagado o que falla **nunca** bloquea el manejo. Se avisa en el log y el rover sigue. Motores, servos, Pixhawk y ExpressLRS no están en esta lista. Ojo: sin LiDAR no hay parada por obstáculo.
