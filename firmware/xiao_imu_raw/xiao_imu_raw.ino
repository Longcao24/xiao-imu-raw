// XIAO nRF52840 Sense (Plus) — raw IMU BLE streamer.
//
// Streams the onboard LSM6DS3TR-C accelerometer + gyroscope over BLE as a
// 16-byte notification at 50 Hz. Raw sensor data only: no sensor fusion, no
// orientation estimate, no filtering, no on-device processing of any kind.
// Whatever you want to compute, compute it on the host.
//
// Stack: Seeed non-mbed core (Seeeduino:nrf52) + Bluefruit (SoftDevice S140).
// Do not port this to the mbed core + ArduinoBLE: its Cordio stack duplicates
// and truncates notifications after a reconnect.
//
// IMU: LSM6DS3TR-C at 0x6A on Wire1 via the Seeed LSM6DS3 library. You MUST
// build with -DTARGET_SEEED_XIAO_NRF52840_SENSE_PLUS or the library talks to
// the wrong I2C bus and imu.begin() never succeeds. See ../../README.md.

#include <Adafruit_TinyUSB.h> // required for USB CDC (Serial) on this core
#include <Wire.h>
#include <LSM6DS3.h>          // Seeed Arduino LSM6DS3; also handles the IMU power pin
#include <bluefruit.h>

// Advertised BLE name. Build with -DPOD_NAME='"XIAO-IMU-2"' for a second unit.
#ifndef POD_NAME
#define POD_NAME "XIAO-IMU"
#endif

// Sensor full-scale ranges. The packet scales below are chosen so neither
// channel can ever clip at these settings.
static const uint16_t ACCEL_RANGE_G   = 4;    // +/- 4 g   -> +/-  4000 in milli-g
static const uint16_t GYRO_RANGE_DPS  = 2000; // +/- 2000 dps -> +/- 20000 in 0.1 dps
static const uint32_t SAMPLE_PERIOD_MS = 20;  // 50 Hz

// 12345678-1234-5678-1234-56789abcdefX, little-endian byte order for the SoftDevice.
static const uint8_t SERVICE_UUID_LE[16]  = {0xF0,0xDE,0xBC,0x9A,0x78,0x56,0x34,0x12,0x78,0x56,0x34,0x12,0x78,0x56,0x34,0x12};
static const uint8_t IMU_CHAR_UUID_LE[16] = {0xF1,0xDE,0xBC,0x9A,0x78,0x56,0x34,0x12,0x78,0x56,0x34,0x12,0x78,0x56,0x34,0x12};

LSM6DS3 imu(I2C_MODE, 0x6A);
BLEService imuService(SERVICE_UUID_LE);
BLECharacteristic imuChar(IMU_CHAR_UUID_LE);

uint32_t lastSampleMs = 0;

void setup() {
  // Boot-time only. Never touch Serial again after setup(): writing to the
  // TinyUSB CDC object while USB is not fully enumerated can hardfault the MCU
  // into a reset loop. This begin() call exists so the USB serial port appears
  // and `arduino-cli upload` can auto-reset the board.
  Serial.begin(115200);

  // LEDs on the XIAO are active-low: HIGH = off.
  pinMode(LED_RED, OUTPUT);
  digitalWrite(LED_RED, HIGH);

  imu.settings.accelRange = ACCEL_RANGE_G;
  imu.settings.gyroRange = GYRO_RANGE_DPS;
  imu.settings.accelSampleRate = 104; // Hz, comfortably above our 50 Hz output
  imu.settings.gyroSampleRate = 104;

  // On a cold battery boot the IMU rail settles slower than on USB, so retry
  // for ~5 s before giving up.
  int tries = 0;
  while (imu.begin() != 0) {
    if (++tries >= 25) {
      // IMU init failed: fast red blink forever. Note that BLE advertising is
      // handled autonomously by the SoftDevice, so a crashed or wedged sketch
      // can still show up in a scan -- trust the LED, not the scan list.
      while (1) {
        digitalWrite(LED_RED, !digitalRead(LED_RED));
        delay(120);
      }
    }
    delay(200);
  }

  // Must precede begin(): raises the ATT MTU and deepens the notification
  // queue. Our packet fits in the 23-byte default MTU, but the deeper queue is
  // what keeps a steady 50 Hz instead of dropping samples under load.
  Bluefruit.configPrphBandwidth(BANDWIDTH_MAX);
  Bluefruit.begin();

  // Bluefruit's autoConnLed assumes active-high LEDs and renders "solid on" as
  // off on this board, so drive the blue LED manually:
  //   blinking = advertising, solid = connected.
  Bluefruit.autoConnLed(false);
  pinMode(LED_BLUE, OUTPUT);
  digitalWrite(LED_BLUE, HIGH); // off

  Bluefruit.setTxPower(4);
  Bluefruit.setName(POD_NAME);

  imuService.begin();
  imuChar.setProperties(CHR_PROPS_READ | CHR_PROPS_NOTIFY);
  imuChar.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
  imuChar.setFixedLen(16);
  imuChar.begin();

  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addTxPower();
  Bluefruit.Advertising.addService(imuService);
  Bluefruit.ScanResponse.addName();
  Bluefruit.Advertising.restartOnDisconnect(true);
  Bluefruit.Advertising.setInterval(32, 244); // 0.625 ms units: fast, then slower
  Bluefruit.Advertising.setFastTimeout(30);
  Bluefruit.Advertising.start(0); // advertise forever
}

void loop() {
  // Blue LED: blink while advertising, solid while connected.
  static uint32_t lastLedMs = 0;
  if (Bluefruit.connected()) {
    digitalWrite(LED_BLUE, LOW);
  } else if (millis() - lastLedMs >= 500) {
    lastLedMs = millis();
    digitalWrite(LED_BLUE, !digitalRead(LED_BLUE));
  }

  uint32_t now = millis();
  if (now - lastSampleMs >= SAMPLE_PERIOD_MS) {
    lastSampleMs = now;

    // The Seeed library returns accel in g and gyro in deg/s. Send fixed-point
    // integers: accel in milli-g, gyro in 0.1 deg/s.
    int16_t ax = (int16_t)lroundf(imu.readFloatAccelX() * 1000.0f);
    int16_t ay = (int16_t)lroundf(imu.readFloatAccelY() * 1000.0f);
    int16_t az = (int16_t)lroundf(imu.readFloatAccelZ() * 1000.0f);
    int16_t gx = (int16_t)lroundf(imu.readFloatGyroX() * 10.0f);
    int16_t gy = (int16_t)lroundf(imu.readFloatGyroY() * 10.0f);
    int16_t gz = (int16_t)lroundf(imu.readFloatGyroZ() * 10.0f);

    uint8_t packet[16];
    packet[0] = (now >>  0) & 0xFF;
    packet[1] = (now >>  8) & 0xFF;
    packet[2] = (now >> 16) & 0xFF;
    packet[3] = (now >> 24) & 0xFF;
    memcpy(packet +  4, &ax, 2);
    memcpy(packet +  6, &ay, 2);
    memcpy(packet +  8, &az, 2);
    memcpy(packet + 10, &gx, 2);
    memcpy(packet + 12, &gy, 2);
    memcpy(packet + 14, &gz, 2);

    // No-op if nothing has subscribed yet.
    if (Bluefruit.connected()) imuChar.notify(packet, sizeof(packet));
  }

  delay(1); // yield to the SoftDevice / FreeRTOS scheduler
}
