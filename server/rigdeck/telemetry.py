"""Reader for the scs-sdk-plugin shared memory block.

Offsets are derived from scs-telemetry-common.hpp (PLUGIN_REVID 12); the header is
kept in reference/ so the numbers below can be re-checked against it. The plugin maps
32 KiB under Local\\SCSTelemetry and rewrites it every game tick.

Windows note: mmap with a tagname CREATES the mapping when it does not exist yet -- and
read access creates it read-only, which would then stop the game's own plugin from
creating its read-write one. So the block is opened only after OpenFileMapping proves
somebody else made it. Even then a successful open proves nothing about liveness; that
comes from sdk_active plus a moving timestamp.
"""

from __future__ import annotations

import ctypes
import mmap
import struct
import time
from ctypes import wintypes
from dataclasses import dataclass, field

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_OpenFileMappingW = _kernel32.OpenFileMappingW
_OpenFileMappingW.restype = wintypes.HANDLE
_OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_CloseHandle = _kernel32.CloseHandle
_CloseHandle.argtypes = [wintypes.HANDLE]
FILE_MAP_READ = 0x0004

MMF_NAME = "Local\\SCSTelemetry"
MMF_SIZE = 32 * 1024  # must match SCS_PLUGIN_MMF_SIZE or we would shrink the plugin's map

STRING_SIZE = 64
TRAILER_BASE = 6000
TRAILER_STRIDE = 1560

GAME_NAMES = {0: "unknown", 1: "ETS2", 2: "ATS"}

# --- zone 1: status ---------------------------------------------------------
O_SDK_ACTIVE = 0
O_PAUSED = 4
O_TIME = 8

# --- zone 2: unsigned ints --------------------------------------------------
O_PLUGIN_REV = 40
O_GAME = 52
O_TIME_ABS = 64
O_GEARS_FWD = 68
O_RETARDER_STEPS = 76
O_TIME_ABS_DELIVERY = 88
O_PLANNED_DISTANCE_KM = 100
O_RETARDER_BRAKE = 108

# --- zone 3: signed ints ----------------------------------------------------
O_REST_STOP = 500
O_GEAR = 504
O_GEAR_DASHBOARD = 508

# --- zone 4: floats ---------------------------------------------------------
O_FUEL_CAPACITY = 704
O_ADBLUE_CAPACITY = 712
O_AIR_PRESSURE_WARNING = 720
O_ENGINE_RPM_MAX = 740
O_CARGO_MASS = 748
O_SPEED = 948
O_ENGINE_RPM = 952
O_CRUISE_SPEED = 988
O_AIR_PRESSURE = 992
O_FUEL = 1000
O_FUEL_AVG_CONSUMPTION = 1004
O_FUEL_RANGE = 1008
O_ADBLUE = 1012
O_OIL_PRESSURE = 1016
O_OIL_TEMPERATURE = 1020
O_WATER_TEMPERATURE = 1024
O_BATTERY_VOLTAGE = 1028
O_WEAR_ENGINE = 1036
O_WEAR_TRANSMISSION = 1040
O_WEAR_CABIN = 1044
O_WEAR_CHASSIS = 1048
O_WEAR_WHEELS = 1052
O_ODOMETER = 1056
O_ROUTE_DISTANCE = 1060
O_ROUTE_TIME = 1064
O_SPEED_LIMIT = 1068
O_JOB_CARGO_DAMAGE = 1468

# --- zone 5: bools ----------------------------------------------------------
O_PARK_BRAKE = 1566
O_MOTOR_BRAKE = 1567
O_AIR_WARN = 1568
O_AIR_EMERGENCY = 1569
O_FUEL_WARN = 1570
O_ADBLUE_WARN = 1571
O_OIL_WARN = 1572
O_WATER_WARN = 1573
O_BATTERY_WARN = 1574
O_ELECTRIC_ENABLED = 1575
O_ENGINE_ENABLED = 1576
O_WIPERS = 1577
O_BLINKER_LEFT_ACTIVE = 1578
O_BLINKER_RIGHT_ACTIVE = 1579
O_BLINKER_LEFT_ON = 1580
O_BLINKER_RIGHT_ON = 1581
O_LIGHTS_PARKING = 1582
O_LIGHTS_BEAM_LOW = 1583
O_LIGHTS_BEAM_HIGH = 1584
O_LIGHTS_BEACON = 1585
O_LIGHTS_BRAKE = 1586
O_LIGHTS_REVERSE = 1587
O_LIGHTS_HAZARD = 1588
O_CRUISE_CONTROL = 1589
O_DIFFERENTIAL_LOCK = 1608
O_LIFT_AXLE = 1609
O_LIFT_AXLE_INDICATOR = 1610
O_TRAILER_LIFT_AXLE = 1611

# --- zone 8: doubles (world placement) --------------------------------------
O_COORD_X = 2200
O_COORD_Y = 2208
O_COORD_Z = 2216
O_ROT_X = 2224  # heading, 0..1 (0 = north, counter-clockwise)

# --- zone 9: strings --------------------------------------------------------
O_TRUCK_BRAND = 2364
O_TRUCK_NAME = 2492
O_CARGO = 2620
O_CITY_DST = 2748
O_COMP_DST = 2876
O_CITY_SRC = 3004
O_COMP_SRC = 3132
O_LICENSE_PLATE = 3212

# --- zones 10-12: money and events ------------------------------------------
O_JOB_INCOME = 4000
O_FINE_AMOUNT = 4216
O_ON_JOB = 4300
O_JOB_DELIVERED = 4303
O_FINED = 4304
O_REFUEL = 4308

# --- zone 14: trailer 0 ------------------------------------------------------
O_TRAILER0_ATTACHED = TRAILER_BASE + 80
O_TRAILER0_CARGO_DAMAGE = TRAILER_BASE + 152
O_TRAILER0_WEAR_CHASSIS = TRAILER_BASE + 156
O_TRAILER0_WEAR_WHEELS = TRAILER_BASE + 160
O_TRAILER0_NAME = TRAILER_BASE + 920 + 5 * STRING_SIZE

_F = struct.Struct("<f")
_D = struct.Struct("<d")
_I = struct.Struct("<i")
_U = struct.Struct("<I")
_Q = struct.Struct("<Q")
_q = struct.Struct("<q")


@dataclass
class Snapshot:
    """One decoded frame plus the link state the UI needs to trust it."""

    online: bool = False
    paused: bool = False
    game: str = "unknown"
    plugin_rev: int = 0
    data: dict = field(default_factory=dict)


def _mapping_exists() -> bool:
    """True only if somebody else has already created the block.

    This matters more than it looks. `mmap` with a tagname *creates* the section if it
    is missing, and asking for read access creates it read-only -- so a panel started
    before the game would leave a read-only `Local\\SCSTelemetry` behind, and the game's
    plugin would then fail to create its own read-write one. The panel would sit there
    reporting no telemetry for as long as the game ran. So: never create, only attach.
    """
    handle = _OpenFileMappingW(FILE_MAP_READ, False, MMF_NAME)
    if not handle:
        return False
    _CloseHandle(handle)
    return True


class TelemetryReader:
    def __init__(self) -> None:
        self._mm: mmap.mmap | None = None
        self._last_time = -1
        self._last_change = 0.0

    # -- lifecycle -----------------------------------------------------------
    def open(self) -> bool:
        """Attach if the plugin is there. False is the ordinary answer before a game
        starts, not a failure -- so it is reported rather than raised."""
        if self._mm is None:
            if not _mapping_exists():
                return False
            self._mm = mmap.mmap(-1, MMF_SIZE, tagname=MMF_NAME, access=mmap.ACCESS_READ)
        return True

    def close(self) -> None:
        if self._mm is not None:
            self._mm.close()
            self._mm = None

    # -- primitives ----------------------------------------------------------
    def _f(self, off: int) -> float:
        return _F.unpack_from(self._mm, off)[0]

    def _d(self, off: int) -> float:
        return _D.unpack_from(self._mm, off)[0]

    def _i(self, off: int) -> int:
        return _I.unpack_from(self._mm, off)[0]

    def _u(self, off: int) -> int:
        return _U.unpack_from(self._mm, off)[0]

    def _ull(self, off: int) -> int:
        return _Q.unpack_from(self._mm, off)[0]

    def _ll(self, off: int) -> int:
        return _q.unpack_from(self._mm, off)[0]

    def _b(self, off: int) -> bool:
        return self._mm[off] != 0

    def _s(self, off: int, size: int = STRING_SIZE) -> str:
        raw = self._mm[off : off + size]
        end = raw.find(b"\x00")
        if end >= 0:
            raw = raw[:end]
        return raw.decode("utf-8", "replace").strip()

    # -- read ----------------------------------------------------------------
    def read(self) -> Snapshot:
        if not self.open():
            return Snapshot(online=False)
        now = time.monotonic()

        if not self._b(O_SDK_ACTIVE):
            return Snapshot(online=False)

        stamp = self._ull(O_TIME)
        if stamp != self._last_time:
            self._last_time = stamp
            self._last_change = now
        elif self._last_change and now - self._last_change > 5.0:
            # plugin loaded but the game stopped writing (quit or crashed)
            return Snapshot(online=False)

        beam = 0
        if self._b(O_LIGHTS_BEAM_HIGH):
            beam = 3
        elif self._b(O_LIGHTS_BEAM_LOW):
            beam = 2
        elif self._b(O_LIGHTS_PARKING):
            beam = 1

        # SI-ish raw values only; the client formats for metric or imperial
        data = {
            "speed_ms": self._f(O_SPEED),
            "speed_limit_ms": self._f(O_SPEED_LIMIT),
            "rpm": self._f(O_ENGINE_RPM),
            "rpm_max": self._f(O_ENGINE_RPM_MAX),
            "gear": self._i(O_GEAR),
            "gear_dash": self._i(O_GEAR_DASHBOARD),
            "gears_forward": self._u(O_GEARS_FWD),
            "cruise_on": self._b(O_CRUISE_CONTROL),
            "cruise_speed_ms": self._f(O_CRUISE_SPEED),
            "fuel_l": self._f(O_FUEL),
            "fuel_capacity_l": self._f(O_FUEL_CAPACITY),
            "fuel_range_km": self._f(O_FUEL_RANGE),
            "fuel_avg_l_km": self._f(O_FUEL_AVG_CONSUMPTION),
            "fuel_warn": self._b(O_FUEL_WARN),
            "adblue_l": self._f(O_ADBLUE),
            "adblue_capacity_l": self._f(O_ADBLUE_CAPACITY),
            "adblue_warn": self._b(O_ADBLUE_WARN),
            "air_psi": self._f(O_AIR_PRESSURE),
            "air_warn": self._b(O_AIR_WARN),
            "air_emergency": self._b(O_AIR_EMERGENCY),
            "oil_psi": self._f(O_OIL_PRESSURE),
            "oil_temp_c": self._f(O_OIL_TEMPERATURE),
            "water_temp_c": self._f(O_WATER_TEMPERATURE),
            "water_warn": self._b(O_WATER_WARN),
            "battery_v": self._f(O_BATTERY_VOLTAGE),
            "battery_warn": self._b(O_BATTERY_WARN),
            "odometer_km": self._f(O_ODOMETER),
            # wear is 0..1 from the SDK; damage percent is the useful form
            "wear": {
                "engine": self._f(O_WEAR_ENGINE),
                "transmission": self._f(O_WEAR_TRANSMISSION),
                "cabin": self._f(O_WEAR_CABIN),
                "chassis": self._f(O_WEAR_CHASSIS),
                "wheels": self._f(O_WEAR_WHEELS),
                "cargo": self._f(O_JOB_CARGO_DAMAGE),
                "trailer_chassis": self._f(O_TRAILER0_WEAR_CHASSIS),
                "trailer_wheels": self._f(O_TRAILER0_WEAR_WHEELS),
            },
            "lights": {
                "beam": beam,
                "parking": self._b(O_LIGHTS_PARKING),
                "low": self._b(O_LIGHTS_BEAM_LOW),
                "high": self._b(O_LIGHTS_BEAM_HIGH),
                "beacon": self._b(O_LIGHTS_BEACON),
                "hazard": self._b(O_LIGHTS_HAZARD),
                "brake": self._b(O_LIGHTS_BRAKE),
                "reverse": self._b(O_LIGHTS_REVERSE),
                "blinker_left": self._b(O_BLINKER_LEFT_ON),
                "blinker_right": self._b(O_BLINKER_RIGHT_ON),
                "blinker_left_active": self._b(O_BLINKER_LEFT_ACTIVE),
                "blinker_right_active": self._b(O_BLINKER_RIGHT_ACTIVE),
            },
            "park_brake": self._b(O_PARK_BRAKE),
            "motor_brake": self._b(O_MOTOR_BRAKE),
            "retarder": self._u(O_RETARDER_BRAKE),
            "retarder_steps": self._u(O_RETARDER_STEPS),
            "diff_lock": self._b(O_DIFFERENTIAL_LOCK),
            "lift_axle": self._b(O_LIFT_AXLE),
            "trailer_lift_axle": self._b(O_TRAILER_LIFT_AXLE),
            "wipers": self._b(O_WIPERS),
            "electric": self._b(O_ELECTRIC_ENABLED),
            "engine": self._b(O_ENGINE_ENABLED),
            "world": {
                "x": self._d(O_COORD_X),
                "y": self._d(O_COORD_Y),
                "z": self._d(O_COORD_Z),
                "heading": self._d(O_ROT_X),
            },
            "job": {
                "on_job": self._b(O_ON_JOB),
                "cargo": self._s(O_CARGO),
                "cargo_mass_kg": self._f(O_CARGO_MASS),
                "city_src": self._s(O_CITY_SRC),
                "comp_src": self._s(O_COMP_SRC),
                "city_dst": self._s(O_CITY_DST),
                "comp_dst": self._s(O_COMP_DST),
                "income": self._ull(O_JOB_INCOME),
                "planned_distance_km": self._u(O_PLANNED_DISTANCE_KM),
                "route_distance_m": self._f(O_ROUTE_DISTANCE),
                "route_time_s": self._f(O_ROUTE_TIME),
                "delivery_time_abs": self._u(O_TIME_ABS_DELIVERY),
                "trailer_attached": self._b(O_TRAILER0_ATTACHED),
                "trailer_name": self._s(O_TRAILER0_NAME),
            },
            "truck": {
                "brand": self._s(O_TRUCK_BRAND),
                "name": self._s(O_TRUCK_NAME),
                "plate": self._s(O_LICENSE_PLATE),
            },
            "time_abs": self._u(O_TIME_ABS),
            "rest_stop_min": self._i(O_REST_STOP),
        }

        return Snapshot(
            online=True,
            paused=self._b(O_PAUSED),
            game=GAME_NAMES.get(self._u(O_GAME), "unknown"),
            plugin_rev=self._u(O_PLUGIN_REV),
            data=data,
        )
