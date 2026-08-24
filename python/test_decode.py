#!/usr/bin/env python3
"""Check the packet codec against the firmware's byte layout. No hardware, no deps.

    python test_decode.py
"""

import struct
import sys

from packet import ACCEL_SCALE, GYRO_SCALE, PACKET_LEN, decode


def pack_like_firmware(t_ms: int, accel_g, gyro_dps) -> bytes:
    """Mirror the byte packing in xiao_imu_raw.ino, written out longhand so this
    test fails if packet.py's struct format drifts from the firmware."""
    out = bytearray()
    out += struct.pack("<I", t_ms)
    for v in accel_g:
        out += struct.pack("<h", round(v * ACCEL_SCALE))
    for v in gyro_dps:
        out += struct.pack("<h", round(v * GYRO_SCALE))
    return bytes(out)


def main() -> int:
    failures = []

    def check(label, got, want, tol):
        if len(got) != len(want) or any(abs(g - w) > tol for g, w in zip(got, want)):
            failures.append(f"{label}: got {got}, want {want}")

    if PACKET_LEN != 16:
        failures.append(f"packet length: got {PACKET_LEN}, want 16")

    # One packet unit of resolution: 1 mg, 0.1 dps.
    accel = (0.001, -1.0, 0.5)
    gyro = (0.1, -250.0, 1999.9)
    pkt = pack_like_firmware(1234567, accel, gyro)

    t_ms, ax, ay, az, gx, gy, gz = decode(pkt)
    if t_ms != 1234567:
        failures.append(f"timestamp: got {t_ms}, want 1234567")
    check("accel", (ax, ay, az), accel, 1 / ACCEL_SCALE)
    check("gyro", (gx, gy, gz), gyro, 1 / GYRO_SCALE)

    # Byte offsets must match the documented layout exactly.
    if pkt[4:6] != struct.pack("<h", 1):
        failures.append("ax is not at offset 4")
    if pkt[10:12] != struct.pack("<h", 1):
        failures.append("gx is not at offset 10")

    # Full scale must not overflow int16 at the firmware's ranges (+/-4 g, +/-2000 dps).
    full = pack_like_firmware(0, (4.0, -4.0, 4.0), (2000.0, -2000.0, 2000.0))
    _, ax, ay, az, gx, gy, gz = decode(full)
    check("full-scale accel", (ax, ay, az), (4.0, -4.0, 4.0), 1 / ACCEL_SCALE)
    check("full-scale gyro", (gx, gy, gz), (2000.0, -2000.0, 2000.0), 1 / GYRO_SCALE)

    # Wrong-length packets must be rejected, not silently mis-parsed.
    for bad in (pkt[:-1], pkt + b"\x00", b""):
        try:
            decode(bad)
        except ValueError:
            pass
        else:
            failures.append(f"decode accepted a {len(bad)}-byte packet")

    if failures:
        print("FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print(f"OK - {PACKET_LEN}-byte packet decodes correctly at 1 mg / 0.1 dps, no clipping at full scale")
    return 0


if __name__ == "__main__":
    sys.exit(main())
