// estop_watchdog: holds the VESC contactor closed only while everything is fine.
// Anything wrong (button pressed, button wire cut, Pi stops toggling, this chip hangs) opens it,
// and it stays open until someone presses re-arm. Boots open.
//   GP2  mushroom button, NC to GND. Reads HIGH if pressed OR the wire is cut
//   GP3  heartbeat from Pi GPIO27 (toggles at 10 Hz), or send 'H' over USB
//   GP4  re-arm button, NO to GND
//   GP15 gate of the low-side MOSFET on the contactor coil (flyback diode on the coil!)
//   GP14 status LED
// The button is also wired in series with the coil, so this board can only ever open it, never
// override a pressed button.
#include <Arduino.h>
#include <hardware/watchdog.h>

const int PIN_ESTOP = 2, PIN_HB = 3, PIN_REARM = 4, PIN_STATUS = 14, PIN_RELAY = 15;
const uint32_t HB_TIMEOUT_MS = 500;

uint32_t lastHb = 0; int lastHbLevel = -1;
bool latched = true;

void setup() {
  pinMode(PIN_RELAY, OUTPUT); digitalWrite(PIN_RELAY, LOW);
  pinMode(PIN_STATUS, OUTPUT); digitalWrite(PIN_STATUS, LOW);
  pinMode(PIN_ESTOP, INPUT_PULLUP); pinMode(PIN_HB, INPUT_PULLDOWN); pinMode(PIN_REARM, INPUT_PULLUP);
  Serial.begin(115200);
  watchdog_enable(200, true);  // hang -> reset -> boots open
}

void loop() {
  watchdog_update();
  int lv = digitalRead(PIN_HB);
  if (lv != lastHbLevel) { lastHbLevel = lv; lastHb = millis(); }
  while (Serial.available()) if (Serial.read() == 'H') lastHb = millis();

  bool estop = digitalRead(PIN_ESTOP) == HIGH;
  bool hbOk = millis() - lastHb < HB_TIMEOUT_MS;
  if (estop || !hbOk) latched = true;
  if (latched && !estop && hbOk && digitalRead(PIN_REARM) == LOW) latched = false;

  digitalWrite(PIN_RELAY, latched ? LOW : HIGH);
  digitalWrite(PIN_STATUS, latched ? LOW : HIGH);

  static uint32_t rep = 0;
  if (millis() - rep > 1000) { rep = millis();
    Serial.print(latched ? "STOP" : "RUN"); Serial.print(estop ? " estop" : "");
    Serial.println(hbOk ? "" : " no_heartbeat"); }
  delay(10);
}
