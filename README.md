# XIAO nRF52840 — raw IMU streaming kit

A Seeed XIAO nRF52840 Sense (Plus) streams its onboard accelerometer and
gyroscope over BLE as a 16-byte packet at 50 Hz. A small Python client connects,
decodes the stream, prints it live and writes a CSV.

That is the whole scope: **get raw IMU samples off the board and into a file.**
There is no sensor fusion, no orientation estimate, no filtering, no step
detection and no trajectory reconstruction anywhere in here — not on the pod,
not in the client. The numbers in the CSV are what the sensor reported.

```
firmware/xiao_imu_raw/xiao_imu_raw.ino   the pod: read IMU, pack 16 bytes, notify
python/packet.py                         the wire format (no dependencies)
python/read_imu.py                       connect, stream, write CSV
python/plot_csv.py                       plot a captured CSV
python/test_decode.py                    verify the codec without hardware
```

## Hardware

- Seeed **XIAO nRF52840 Sense** or **Sense Plus**
- IMU: onboard LSM6DS3TR-C, I²C address `0x6A` on `Wire1`, powered via P1.08
- Configured for ±4 g and ±2000 °/s, sampled at 104 Hz, transmitted at 50 Hz

## Flashing the firmware

Install the Seeed **non-mbed** core (`Seeeduino:nrf52`, Bluefruit / SoftDevice
S140) and the **Seeed Arduino LSM6DS3** library.

```bash
arduino-cli core install Seeeduino:nrf52
arduino-cli lib install "Seeed Arduino LSM6DS3"
```

Then compile and upload:

```bash
arduino-cli compile -b Seeeduino:nrf52:xiaonRF52840SensePlus \
  --build-property "compiler.cpp.extra_flags=-DTARGET_SEEED_XIAO_NRF52840_SENSE_PLUS" \
  firmware/xiao_imu_raw

arduino-cli upload -b Seeeduino:nrf52:xiaonRF52840SensePlus \
  -p /dev/cu.usbmodemXXXX firmware/xiao_imu_raw
```

Three things will cost you an afternoon if you skip them:

- **`-DTARGET_SEEED_XIAO_NRF52840_SENSE_PLUS` is mandatory.** Without it the
  LSM6DS3 library selects the wrong I²C bus, `imu.begin()` never returns 0, and
  you get the red-blink failure state below. (The Sense Plus variant header also
  defines it, so you will see a harmless "redefined" warning. Expected.)
- **The sketch folder must be named after the `.ino`** — `xiao_imu_raw/xiao_imu_raw.ino`.
  That is an Arduino rule, not ours.
- **Use the `Seeeduino:nrf52` core, not `Seeeduino:mbed` + ArduinoBLE.** The
  mbed core's Cordio stack leaks per-connection subscription state and starts
  duplicating and truncating notifications after a reconnect.

If no serial port shows up, double-tap the board's reset button to enter the
UF2 bootloader (a port appears along with a `XIAO-SENSE` volume) and upload
against that port. On macOS, watch for the OpenMV IDE or Arduino Cloud Agent
holding the port open.

### What the LEDs mean

LEDs on this board are **active-low**, and Bluefruit's `autoConnLed` assumes
active-high, so the sketch drives the blue LED itself.

| LED | Meaning |
|---|---|
| Blue blinking (0.5 s) | advertising, waiting for a connection |
| Blue solid | connected |
| Red fast blink, forever | IMU init failed — check the build flag above |

Trust the LED over the BLE scan list. Advertising is handled autonomously by the
SoftDevice, so a wedged sketch still shows up in a scan.

## Running the Python client

Python 3.9+.

```bash
cd python
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Check the codec first — this needs no hardware and no BLE:

```bash
python test_decode.py
# OK - 16-byte packet decodes correctly at 1 mg / 0.1 dps, no clipping at full scale
```

See what is advertising (`*` marks a pod running this firmware):

```bash
python read_imu.py --list
```

Stream, and save 20 seconds to a CSV:

```bash
python read_imu.py --out walk.csv --duration 20
```

```
Found XIAO-IMU at E1:9C:...:4A
Connected. Streaming -- Ctrl-C to stop.

  1000 pkt   50.0 Hz   a=( +0.02, -0.11, +0.99) g   g=(  +1.2,   -0.4,   +0.8) dps

1000 packets in 20.0s (50.0 Hz)
device-clock rate: 50.0 Hz over 20.0s
wrote walk.csv
```

Useful flags: `--address` connects straight to a BLE address and skips the scan
(much more reliable on macOS), `--name` changes the name prefix to match, and
`--scan-timeout` extends the scan.

Then plot it:

```bash
python plot_csv.py walk.csv            # or --save walk.png
```

## The packet format

16 bytes, little-endian, one per sample at 50 Hz:

| offset | size | type | field | units |
|---|---|---|---|---|
| 0 | 4 | `u32` | `timestamp_ms` | pod `millis()` since power-up |
| 4 | 2 | `i16` | `ax` | milli-g |
| 6 | 2 | `i16` | `ay` | milli-g |
| 8 | 2 | `i16` | `az` | milli-g |
| 10 | 2 | `i16` | `gx` | 0.1 °/s |
| 12 | 2 | `i16` | `gy` | 0.1 °/s |
| 14 | 2 | `i16` | `gz` | 0.1 °/s |

BLE service `12345678-1234-5678-1234-56789abcdef0`, notify characteristic
`...def1`. There is no command characteristic and the client never writes to the
pod: on some hosts (macOS in particular) any GATT write to this board drops the
link. Streaming is entirely one-way.

The fixed-point scales are picked so **neither channel can clip** at the
configured ranges: ±4 g → ±4000 and ±2000 °/s → ±20000, both well inside
`int16`'s ±32767. Resolution is 1 mg and 0.1 °/s. If you widen a sensor range in
the firmware, re-check these scales and update `python/packet.py` in the same
commit — the layout is documented in exactly those two places and nowhere else.

**Use `timestamp_ms`, not host arrival time.** BLE delivers notifications in
bursts, so host timestamps are jittery even when the pod samples perfectly
evenly. `read_imu.py` reports the device-clock rate separately for this reason,
and estimates how many packets were dropped in transit. The field wraps after
~49.7 days of uptime.

## Notes

- **Gyro bias.** A raw MEMS gyro reads a nonzero rate while perfectly still,
  typically a few °/s, and it drifts with temperature. Nothing here removes it.
  If you integrate these samples, subtract a bias you measure yourself from a
  stationary stretch of your own capture.
- **Axes** are the LSM6DS3's own body axes, in whatever orientation you mounted
  the board. There is no reference frame beyond that.
- **BLE on macOS** is the flakiest part of this stack; connections time out
  spuriously and CoreBluetooth caches device names, so a renamed board keeps
  reporting its old one (`--list` reads the name fresh from the air to sidestep
  that). Linux/BlueZ and Windows are both noticeably more reliable. Retrying a
  failed connect usually just works.
- **Two boards at once**: flash the second one with
  `--build-property "compiler.cpp.extra_flags=-DTARGET_SEEED_XIAO_NRF52840_SENSE_PLUS -DPOD_NAME=\"XIAO-IMU-2\""`
  and run a second client with `--name XIAO-IMU-2`. Quoting a string through
  `--build-property` is fragile; if the name comes out mangled, edit the
  `POD_NAME` default in the sketch instead.
