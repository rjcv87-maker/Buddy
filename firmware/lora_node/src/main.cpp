// lora_node: the same radio firmware for every OTL module (rover, ground station, later the drone).
// It's a dumb pipe on purpose. The Pi sends [len][frame] over USB, this puts the frame on air,
// and anything heard comes back up the same way. Auth and parsing live in buddy/mesh.py.
//
// Pico -> RFM95W: GP18 SCK, GP19 MOSI, GP16 MISO, GP17 NSS, GP20 RST, GP21 DIO0, 3V3, GND.
// Build with -e pico_ground for the ground station, it only adds an RX blink.
#include <Arduino.h>
#include <SPI.h>
#include <LoRa.h>

#ifndef GROUND_STATION
#define GROUND_STATION 0
#endif

const int PIN_NSS = 17, PIN_RST = 20, PIN_DIO0 = 21;
const long FREQ = 915E6;          // US/PR ISM band. 868E6 in Europe
const uint8_t SYNC = 0x42;        // OTL fleet, keep it the same on every node
const uint32_t SERIAL_GAP_MS = 50; // drop a half frame after this

uint8_t buf[256];
uint16_t have = 0;
uint32_t lastByte = 0;

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
  LoRa.setPins(PIN_NSS, PIN_RST, PIN_DIO0);
  while (!LoRa.begin(FREQ)) { digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN)); delay(100); }
  LoRa.setSpreadingFactor(9);     // starting point, frames are < 50 B so airtime is fine. TODO: range test SF9 vs SF10
  LoRa.setSignalBandwidth(125E3);
  LoRa.setCodingRate4(5);
  LoRa.setTxPower(17);
  LoRa.setSyncWord(SYNC);
  LoRa.enableCrc();
}

void loop() {

  while (Serial.available()) {
    buf[have++] = Serial.read();
    lastByte = millis();
    if (have > 1 && have == buf[0] + 1) {
      LoRa.beginPacket(); LoRa.write(buf + 1, buf[0]); LoRa.endPacket();
      LoRa.receive();
      have = 0;
    }
  }
  if (have && millis() - lastByte > SERIAL_GAP_MS) have = 0;


  int n = LoRa.parsePacket();
  if (n > 0 && n < 256) {
    uint8_t pkt[255]; int i = 0;
    while (LoRa.available() && i < n) pkt[i++] = LoRa.read();
    Serial.write((uint8_t)i); Serial.write(pkt, i);
    if (GROUND_STATION) digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
  }
}
