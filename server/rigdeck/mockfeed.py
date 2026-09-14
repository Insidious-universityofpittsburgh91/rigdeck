"""Writes a believable telemetry block into the shared memory, no game required.

Lets the whole chain -- reader, server, websocket, panel -- be exercised while ETS2 is
closed. Never run this with the game open: both would write the same block.
"""

from __future__ import annotations

import math
import mmap
import struct
import time

from .telemetry import MMF_NAME, MMF_SIZE
from . import telemetry as T


# Two believable runs, each parked on a real stretch of the exported map so the mini
# GPS has actual roads under it rather than empty ground.
PROFILES = {
    "ETS2": dict(
        id=1, brand="Scania", model="R 2016", plate="ZG 1234 AB",
        cargo="Cement", src="Duisburg", src_co="Euroacres",
        dst="Rotterdam", dst_co="Euromax", trailer="Krone Profi Liner",
        income=3480, fuel_capacity=700.0, fuel=438.0, adblue_capacity=80.0,
        retarder_steps=3, limit_ms=22.22, planned_km=412, at=(-13801.0, -6486.0),
    ),
    "ATS": dict(
        id=2, brand="Kenworth", model="W900", plate="AZ 4471 T",
        cargo="Frozen Food", src="Phoenix", src_co="Chemso",
        dst="Las Vegas", dst_co="Wallbert", trailer="Reefer 53'",
        income=2140, fuel_capacity=568.0, fuel=402.0, adblue_capacity=0.0,
        retarder_steps=0, limit_ms=29.06, planned_km=478, at=(-76543.0, 24428.0),
    ),
}


def run(hz: int = 20, game: str = "ETS2") -> None:
    profile = PROFILES[game.upper()]
    mm = mmap.mmap(-1, MMF_SIZE, tagname=MMF_NAME, access=mmap.ACCESS_WRITE)

    def wf(off, value):
        struct.pack_into("<f", mm, off, float(value))

    def wd(off, value):
        struct.pack_into("<d", mm, off, float(value))

    def wi(off, value):
        struct.pack_into("<i", mm, off, int(value))

    def wu(off, value):
        struct.pack_into("<I", mm, off, int(value))

    def wq(off, value):
        struct.pack_into("<Q", mm, off, int(value))

    def wb(off, value):
        mm[off] = 1 if value else 0

    def ws(off, text, size=64):
        raw = text.encode("utf-8")[: size - 1]
        mm[off : off + size] = raw + b"\x00" * (size - len(raw))

    print(f"mock {game.upper()} telemetry writing to {MMF_NAME} at {hz} Hz -- ctrl+c to stop")

    # constants that do not change during the run
    wb(T.O_SDK_ACTIVE, True)
    wb(T.O_PAUSED, False)
    wu(T.O_PLUGIN_REV, 12)
    wu(T.O_GAME, profile["id"])
    wu(T.O_GEARS_FWD, 12)
    wu(T.O_RETARDER_STEPS, profile["retarder_steps"])
    wf(T.O_FUEL_CAPACITY, profile["fuel_capacity"])
    wf(T.O_ADBLUE_CAPACITY, profile["adblue_capacity"])
    wf(T.O_ENGINE_RPM_MAX, 2500)
    wf(T.O_CARGO_MASS, 22400)
    wu(T.O_PLANNED_DISTANCE_KM, profile["planned_km"])
    ws(T.O_TRUCK_BRAND, profile["brand"])
    ws(T.O_TRUCK_NAME, profile["model"])
    ws(T.O_LICENSE_PLATE, profile["plate"])
    ws(T.O_CARGO, profile["cargo"])
    ws(T.O_CITY_SRC, profile["src"])
    ws(T.O_COMP_SRC, profile["src_co"])
    ws(T.O_CITY_DST, profile["dst"])
    ws(T.O_COMP_DST, profile["dst_co"])
    ws(T.O_TRAILER0_NAME, profile["trailer"])
    wq(T.O_JOB_INCOME, profile["income"])
    wb(T.O_ON_JOB, True)
    wb(T.O_TRAILER0_ATTACHED, True)
    wb(T.O_ELECTRIC_ENABLED, True)
    wb(T.O_ENGINE_ENABLED, True)
    wb(T.O_LIGHTS_BEAM_LOW, True)

    for wear_off, value in (
        (T.O_WEAR_ENGINE, 0.04), (T.O_WEAR_TRANSMISSION, 0.02), (T.O_WEAR_CABIN, 0.11),
        (T.O_WEAR_CHASSIS, 0.07), (T.O_WEAR_WHEELS, 0.01), (T.O_JOB_CARGO_DAMAGE, 0.0),
    ):
        wf(wear_off, value)

    fuel, adblue, odo, stamp = profile["fuel"], 31.0, 318774.0, 0
    route_m = profile["planned_km"] * 1000.0
    home_x, home_z = profile["at"]
    minutes = 14 * 60 + 7
    step = 1.0 / hz
    t = 0.0

    try:
        while True:
            t += step
            speed = 22.0 + math.sin(t * 0.35) * 2.4        # m/s, about 80 km/h
            rpm = 700 + (speed / 25.0) * 1450 + math.sin(t * 1.6) * 90

            stamp += int(step * 1000)
            wq(T.O_TIME, stamp)
            wu(T.O_TIME_ABS, int(minutes))
            wu(T.O_TIME_ABS_DELIVERY, int(minutes) + 290)

            wf(T.O_SPEED, speed)
            wf(T.O_SPEED_LIMIT, profile["limit_ms"])
            wf(T.O_ENGINE_RPM, rpm)
            wi(T.O_GEAR, 9)
            wi(T.O_GEAR_DASHBOARD, 9)
            wb(T.O_CRUISE_CONTROL, True)
            wf(T.O_CRUISE_SPEED, profile["limit_ms"])

            fuel = max(0.0, fuel - speed * step * 0.00035 * 100)
            adblue = max(0.0, adblue - step * 0.0004)
            odo += speed * step / 1000.0
            route_m = max(0.0, route_m - speed * step)
            minutes += step * 0.4

            wf(T.O_FUEL, fuel)
            wf(T.O_FUEL_RANGE, fuel * 1.4)
            wf(T.O_FUEL_AVG_CONSUMPTION, 0.32)
            wb(T.O_FUEL_WARN, fuel < 120)
            wf(T.O_ADBLUE, adblue)
            wf(T.O_AIR_PRESSURE, 118 + math.sin(t * 0.2) * 4)
            wf(T.O_OIL_PRESSURE, 42)
            wf(T.O_OIL_TEMPERATURE, 94)
            wf(T.O_WATER_TEMPERATURE, 86)
            wf(T.O_BATTERY_VOLTAGE, 24.3)
            wf(T.O_ODOMETER, odo)
            wf(T.O_ROUTE_DISTANCE, route_m)
            wf(T.O_ROUTE_TIME, route_m / max(speed, 1.0))
            wi(T.O_REST_STOP, max(0, 192 - int(t * 0.4)))

            # a slow lap around a real city, so the mini GPS has roads to show
            wd(T.O_COORD_X, home_x + math.cos(t * 0.05) * 1500)
            wd(T.O_COORD_Y, 60.0)
            wd(T.O_COORD_Z, home_z + math.sin(t * 0.05) * 1500)
            wd(T.O_ROT_X, (t * 0.05 / (2 * math.pi)) % 1.0)

            time.sleep(step)
    except KeyboardInterrupt:
        wb(T.O_SDK_ACTIVE, False)
        print("\nmock feed stopped")
    finally:
        mm.close()
