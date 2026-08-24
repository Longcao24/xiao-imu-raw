#!/usr/bin/env python3
"""Read the raw IMU stream from a XIAO nRF52840 pod over BLE.

Connects to the pod, subscribes to the notification characteristic, decodes each
16-byte packet, prints a live summary and (optionally) writes a CSV.

    python read_imu.py --list
    python read_imu.py --out walk.csv --duration 20

Raw data in, raw data out. This tool does no filtering, no fusion and no
integration -- the CSV holds exactly what the sensor reported.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import sys
import time

from bleak import BleakClient, BleakScanner

from packet import (
    CSV_HEADER,
    IMU_CHAR_UUID,
    SAMPLE_PERIOD_MS,
    SERVICE_UUID,
    decode,
)

DEFAULT_NAME_PREFIX = "XIAO-IMU"


async def list_pods(timeout: float) -> int:
    print(f"Scanning {timeout:.0f}s for BLE devices...")
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    rows = []
    for device, adv in devices.values():
        # Use the advertised name, not device.name: macOS caches stale names for
        # devices it has seen before, so a renamed pod keeps showing the old one.
        name = adv.local_name or device.name or "(unnamed)"
        ours = SERVICE_UUID.lower() in [u.lower() for u in adv.service_uuids]
        rows.append((not ours, name, device.address, adv.rssi, ours))
    if not rows:
        print("No devices found.")
        return 1
    for _, name, address, rssi, ours in sorted(rows):
        print(f"  {'*' if ours else ' '} {name:<24} {address}  {rssi:>4} dBm")
    print("\n  * = advertises the raw-IMU service")
    return 0


async def find_pod(name_prefix: str, address: str | None, timeout: float):
    if address:
        print(f"Connecting to {address}...")
        return address
    print(f"Scanning for a device named {name_prefix}* ...")
    device = await BleakScanner.find_device_by_filter(
        lambda d, adv: (adv.local_name or d.name or "").startswith(name_prefix),
        timeout=timeout,
    )
    if device is None:
        print(
            f"No device named {name_prefix}* found. Run with --list to see what is "
            "advertising, then pass --address.",
            file=sys.stderr,
        )
        return None
    print(f"Found {device.name or name_prefix} at {device.address}")
    return device


async def stream(args: argparse.Namespace) -> int:
    target = await find_pod(args.name, args.address, args.scan_timeout)
    if target is None:
        return 1

    csv_file = open(args.out, "w", newline="") if args.out else None
    writer = None
    if csv_file is not None:
        writer = csv.writer(csv_file)
        writer.writerow(CSV_HEADER)

    count = 0
    bad = 0
    first_t: int | None = None
    last_t: int | None = None
    started = time.monotonic()
    last_print = started
    stop = asyncio.Event()

    def on_packet(_characteristic, data: bytearray) -> None:
        nonlocal count, bad, first_t, last_t, last_print
        try:
            t_ms, ax, ay, az, gx, gy, gz = decode(bytes(data))
        except ValueError:
            bad += 1
            return
        count += 1
        if first_t is None:
            first_t = t_ms
        last_t = t_ms
        if writer is not None:
            writer.writerow(
                [t_ms, f"{ax:.4f}", f"{ay:.4f}", f"{az:.4f}",
                 f"{gx:.2f}", f"{gy:.2f}", f"{gz:.2f}"]
            )
        now = time.monotonic()
        if now - last_print >= 0.5:
            last_print = now
            rate = count / max(now - started, 1e-6)
            print(
                f"\r{count:6d} pkt  {rate:5.1f} Hz   "
                f"a=({ax:+6.2f},{ay:+6.2f},{az:+6.2f}) g   "
                f"g=({gx:+7.1f},{gy:+7.1f},{gz:+7.1f}) dps",
                end="",
                flush=True,
            )

    async with BleakClient(target, disconnected_callback=lambda _c: stop.set()) as client:
        print("Connected. Streaming -- Ctrl-C to stop.\n")
        await client.start_notify(IMU_CHAR_UUID, on_packet)
        try:
            if args.duration:
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=args.duration)
            else:
                await stop.wait()
        except asyncio.CancelledError:
            pass
        finally:
            # The pod may already be gone; a failed unsubscribe is not an error.
            with contextlib.suppress(Exception):
                await client.stop_notify(IMU_CHAR_UUID)

    if csv_file is not None:
        csv_file.close()

    elapsed = time.monotonic() - started
    print(f"\n\n{count} packets in {elapsed:.1f}s ({count / max(elapsed, 1e-6):.1f} Hz)")
    if bad:
        print(f"{bad} malformed packets skipped -- firmware/parser packet length mismatch?")
    if first_t is not None and last_t is not None and count > 1:
        # Device-clock rate, immune to host-side scheduling jitter.
        span_s = (last_t - first_t) / 1000.0
        if span_s > 0:
            print(f"device-clock rate: {(count - 1) / span_s:.1f} Hz over {span_s:.1f}s")
            expected = int(round(span_s * 1000.0 / SAMPLE_PERIOD_MS)) + 1
            dropped = expected - count
            if dropped > 0:
                print(f"~{dropped} packets dropped in transit ({dropped / expected:.1%})")
    if args.out:
        print(f"wrote {args.out}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list", action="store_true", help="scan and list BLE devices, then exit")
    p.add_argument("--name", default=DEFAULT_NAME_PREFIX, help=f"name prefix to connect to (default: {DEFAULT_NAME_PREFIX})")
    p.add_argument("--address", help="connect straight to this BLE address / UUID, skipping the scan")
    p.add_argument("--out", help="write decoded samples to this CSV file")
    p.add_argument("--duration", type=float, help="stop after this many seconds (default: until Ctrl-C)")
    p.add_argument("--scan-timeout", type=float, default=8.0, help="scan timeout in seconds (default: 8)")
    args = p.parse_args()

    try:
        if args.list:
            return asyncio.run(list_pods(args.scan_timeout))
        return asyncio.run(stream(args))
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
