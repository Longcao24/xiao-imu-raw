#!/usr/bin/env python3
"""The wire format of the raw IMU stream, and nothing else.

Deliberately dependency-free: you can read and reuse this without installing
bleak, and without a pod on the desk. If you move the data over something other
than BLE (a serial link, a file, a socket), this is the only piece you keep.

Packet layout -- 16 bytes, little-endian, one per sample at 50 Hz:

    offset  size  type  field
    0       4     u32   timestamp_ms   millis() on the pod since power-up
    4       2     i16   ax             accel X, milli-g
    6       2     i16   ay             accel Y, milli-g
    8       2     i16   az             accel Z, milli-g
    10      2     i16   gx             gyro X, 0.1 deg/s
    12      2     i16   gy             gyro Y, 0.1 deg/s
    14      2     i16   gz             gyro Z, 0.1 deg/s

The scales are chosen so neither channel can clip at the firmware's configured
full-scale ranges (+/-4 g -> +/-4000; +/-2000 dps -> +/-20000; int16 holds
+/-32767). Resolution is 1 mg and 0.1 deg/s.

The timestamp is the pod's own clock. Use it for timing rather than host arrival
time: BLE delivers notifications in bursts, so host timestamps are jittery even
when the pod is sampling perfectly evenly. It wraps after ~49.7 days of uptime.
"""

from __future__ import annotations

import struct

# BLE identifiers, for whatever transport layer you put on top.
SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
IMU_CHAR_UUID = "12345678-1234-5678-1234-56789abcdef1"

# u32 timestamp_ms | i16 ax,ay,az | i16 gx,gy,gz
PACKET = struct.Struct("<Ihhhhhh")
PACKET_LEN = PACKET.size  # 16

ACCEL_SCALE = 1000.0  # packet units per g
GYRO_SCALE = 10.0     # packet units per deg/s

SAMPLE_PERIOD_MS = 20  # firmware output rate: 50 Hz

CSV_HEADER = ["t_ms", "ax_g", "ay_g", "az_g", "gx_dps", "gy_dps", "gz_dps"]


def decode(data: bytes) -> tuple[int, float, float, float, float, float, float]:
    """Decode one packet into (t_ms, ax, ay, az in g, gx, gy, gz in deg/s)."""
    if len(data) != PACKET_LEN:
        raise ValueError(f"expected {PACKET_LEN} bytes, got {len(data)}")
    t_ms, ax, ay, az, gx, gy, gz = PACKET.unpack(data)
    return (
        t_ms,
        ax / ACCEL_SCALE,
        ay / ACCEL_SCALE,
        az / ACCEL_SCALE,
        gx / GYRO_SCALE,
        gy / GYRO_SCALE,
        gz / GYRO_SCALE,
    )


def encode(t_ms: int, accel_g, gyro_dps) -> bytes:
    """Build a packet the way the firmware does. For tests and replay only."""
    return PACKET.pack(
        t_ms & 0xFFFFFFFF,
        *(int(round(v * ACCEL_SCALE)) for v in accel_g),
        *(int(round(v * GYRO_SCALE)) for v in gyro_dps),
    )
