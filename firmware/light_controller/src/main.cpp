// light_controller: 4x XHP70.2 on constant-current drivers with a DIM input.
// Level comes from the Pixhawk (RC8 passed through on MAIN8, 1000-2000 us on GP2) or from the Pi
// over USB as "L0".."L100". Serial wins while it keeps talking; after 3 s of silence it falls back
// to the RC channel.
// DIM outputs GP10..GP13. Optional 10k B3950 NTC on the heatsink: GP26 to GND, 10k pull-up to 3V3.
#include <Arduino.h>

const int PIN_RC = 2, PIN_NTC = 26;
const int PIN_DIM[4] = {10, 11, 12, 13};
const float DERATE_START_C = 60, DERATE_OFF_C = 85;

volatile uint32_t riseUs = 0, pulseUs = 0, pulseAt = 0;
int serialLevel = -1; uint32_t serialAt = 0;
bool ntcPresent = false;

void rcIsr() {
  uint32_t t = micros();
  if (digitalRead(PIN_RC)) riseUs = t; else { pulseUs = t - riseUs; pulseAt = millis(); }
}

float ntcC() {
  float raw = analogRead(PIN_NTC);
  if (raw < 5 || raw > 1018) return NAN;        // open or shorted: no NTC fitted
  float r = 10000.0f * raw / (1023.0f - raw);
  return 1.0f / (log(r / 10000.0f) / 3950.0f + 1.0f / 298.15f) - 273.15f;
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_RC, INPUT);
  attachInterrupt(digitalPinToInterrupt(PIN_RC), rcIsr, CHANGE);
  for (int p : PIN_DIM) { pinMode(p, OUTPUT); analogWrite(p, 0); }
  ntcPresent = !isnan(ntcC());
}

void loop() {
  while (Serial.available()) {
    String s = Serial.readStringUntil('\n');
    if (s.startsWith("L")) { serialLevel = constrain(s.substring(1).toInt(), 0, 100); serialAt = millis(); }
  }
  int level = 0;
  if (serialLevel >= 0 && millis() - serialAt < 3000) level = serialLevel;
  else if (millis() - pulseAt < 500) level = constrain(map(pulseUs, 1000, 2000, 0, 100), 0, 100);

  float t = ntcPresent ? ntcC() : NAN;
  float k = 1.0f;
  if (!isnan(t)) k = constrain((DERATE_OFF_C - t) / (DERATE_OFF_C - DERATE_START_C), 0.0f, 1.0f);
  int duty = (int)(level * k * 255 / 100);
  for (int p : PIN_DIM) analogWrite(p, duty);

  static uint32_t rep = 0;
  if (millis() - rep > 1000) { rep = millis(); Serial.print("level="); Serial.print(level);
    Serial.print(" duty="); Serial.print(duty); Serial.print(" tempC="); Serial.println(t); }
  delay(20);
}
