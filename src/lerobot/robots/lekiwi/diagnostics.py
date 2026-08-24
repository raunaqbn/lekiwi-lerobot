#!/usr/bin/env python

# Copyright 2024 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Local, read-only web diagnostics for the LeKiwi motor bus."""

from __future__ import annotations

import argparse
import atexit
import contextlib
import json
import math
import os
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from serial.tools import list_ports


@dataclass(frozen=True)
class ExpectedMotor:
    name: str
    label: str
    id: int
    group: str


@dataclass(frozen=True)
class BusProfile:
    key: str
    label: str
    expected_ids: tuple[int, ...]
    voltage_min: float
    voltage_max: float
    critical_voltage_min: float
    critical_voltage_max: float


EXPECTED_MOTORS = (
    ExpectedMotor("arm_shoulder_pan", "Shoulder pan", 1, "arm"),
    ExpectedMotor("arm_shoulder_lift", "Shoulder lift", 2, "arm"),
    ExpectedMotor("arm_elbow_flex", "Elbow flex", 3, "arm"),
    ExpectedMotor("arm_wrist_flex", "Wrist flex", 4, "arm"),
    ExpectedMotor("arm_wrist_roll", "Wrist roll", 5, "arm"),
    ExpectedMotor("arm_gripper", "Gripper", 6, "arm"),
    ExpectedMotor("base_left_wheel", "Left wheel", 7, "base"),
    ExpectedMotor("base_back_wheel", "Back wheel", 8, "base"),
    ExpectedMotor("base_right_wheel", "Right wheel", 9, "base"),
)

LEKIWI_FOLLOWER_PROFILE = BusProfile(
    key="lekiwi_follower_12v",
    label="LeKiwi follower · 9 motors · 12 V",
    expected_ids=tuple(range(1, 10)),
    voltage_min=10.0,
    voltage_max=14.0,
    critical_voltage_min=8.0,
    critical_voltage_max=15.0,
)
SO101_LEADER_PROFILE = BusProfile(
    key="so101_leader_5v",
    label="SO-101 leader · 6 motors · 5 V",
    expected_ids=tuple(range(1, 7)),
    voltage_min=4.5,
    voltage_max=6.0,
    critical_voltage_min=4.0,
    critical_voltage_max=7.0,
)

DEFAULT_BAUDRATE = 1_000_000
EXPECTED_MODEL_NUMBER = 777
KNOWN_MODEL_NAMES = {777: "STS3215", 2825: "STS3250", 11272: "SM8512BL", 1284: "SCS0009"}
POLL_INTERVAL_S = 1.0
POWER_RESCAN_INTERVAL_S = 2.0
REMOTE_POLL_INTERVAL_S = 1.0
REMOTE_TIMEOUT_S = 0.8
SETTINGS_FILENAME = "lekiwi_diagnostics.json"
BATTERY_NOMINAL_V = 11.1
BATTERY_FULL_V = 12.6
BATTERY_CUTOFF_V = 8.1
BATTERY_CAPACITY_AH = 5.2
BATTERY_CAPACITY_WH = 57.72
TELEMETRY_REGISTERS = (
    "Present_Position",
    "Present_Velocity",
    "Present_Load",
    "Present_Voltage",
    "Present_Temperature",
    "Present_Current",
    "Torque_Enable",
    "Operating_Mode",
    "Moving",
    "Status",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def default_settings_path() -> Path:
    lerobot_home = os.getenv("HF_LEROBOT_HOME")
    root = Path(lerobot_home).expanduser() if lerobot_home else Path.home() / ".cache/huggingface/lerobot"
    return root / SETTINGS_FILENAME


def expected_motor_bus(port: str):
    # Keep the optional Feetech dependency lazy so `--demo` and the web UI can
    # still start in a base LeRobot environment.
    from lerobot.motors import Motor, MotorNormMode
    from lerobot.motors.feetech import FeetechMotorsBus

    motors = {
        motor.name: Motor(motor.id, "sts3215", MotorNormMode.RANGE_M100_100) for motor in EXPECTED_MOTORS
    }
    return FeetechMotorsBus(port=port, motors=motors)


def model_name(model_number: int | None) -> str:
    if model_number is None:
        return "—"
    return KNOWN_MODEL_NAMES.get(model_number, f"Model {model_number}")


def assess_motor(
    motor: dict[str, Any], profile: BusProfile = LEKIWI_FOLLOWER_PROFILE
) -> tuple[str, list[str]]:
    """Return a severity and terse findings for one expected motor."""
    if not motor["detected"]:
        return "critical", ["No response on the selected baud rate"]
    if motor.get("model_mismatch"):
        return "critical", ["Unexpected motor model"]
    if motor.get("wrong_baudrate"):
        return "critical", [
            f"Responded at {motor['found_baudrate']:,} baud; LeKiwi expects {motor['expected_baudrate']:,}"
        ]
    if motor.get("read_error"):
        return "critical", ["Telemetry read failed"]

    findings = []
    severity = "healthy"
    temperature = motor.get("temperature_c")
    voltage = motor.get("voltage_v")
    status = motor.get("status_raw")

    if temperature is not None and temperature >= 70:
        severity = "critical"
        findings.append("Temperature is at or above 70 °C")
    elif temperature is not None and temperature >= 55:
        severity = "warning"
        findings.append("Temperature is elevated")

    if voltage is not None and not profile.voltage_min <= voltage <= profile.voltage_max:
        severity = (
            "critical"
            if voltage < profile.critical_voltage_min or voltage > profile.critical_voltage_max
            else max_severity(severity, "warning")
        )
        findings.append(
            f"Bus voltage is outside the {profile.voltage_min:g}–{profile.voltage_max:g} V "
            f"band for {profile.label}"
        )

    if status not in (None, 0):
        severity = max_severity(severity, "warning")
        findings.append(f"Motor status register is {status}")

    if motor.get("torque_enabled") is False:
        findings.append("Torque is disabled")

    return severity, findings


def max_severity(first: str, second: str) -> str:
    order = {"healthy": 0, "notice": 1, "warning": 2, "critical": 3}
    return first if order[first] >= order[second] else second


def estimate_battery(voltage_v: float | None) -> dict[str, Any]:
    """Return a deliberately broad, voltage-only estimate for the follower's 3S pack."""
    estimate = {
        "available": voltage_v is not None,
        "voltage_v": voltage_v,
        "percent_min": None,
        "percent_max": None,
        "confidence": "unavailable" if voltage_v is None else "low",
        "method": "3S pack voltage under unknown load",
        "calibrated": False,
        "runtime_available": False,
        "remaining_wh_min": None,
        "remaining_wh_max": None,
        "pack": {
            "chemistry": "3S lithium-ion",
            "nominal_voltage_v": BATTERY_NOMINAL_V,
            "full_voltage_v": BATTERY_FULL_V,
            "cutoff_voltage_v": BATTERY_CUTOFF_V,
            "capacity_ah": BATTERY_CAPACITY_AH,
            "capacity_wh": BATTERY_CAPACITY_WH,
        },
    }
    if voltage_v is None:
        return estimate

    # These intentionally overlapping bands account for servo-bus voltage drop,
    # load, temperature, cell age, and the lack of a robot-specific discharge curve.
    if voltage_v >= 12.45:
        percent_min, percent_max = 90, 100
    elif voltage_v >= 12.1:
        percent_min, percent_max = 70, 100
    elif voltage_v >= 11.7:
        percent_min, percent_max = 45, 85
    elif voltage_v >= 11.3:
        percent_min, percent_max = 20, 60
    elif voltage_v >= 10.8:
        percent_min, percent_max = 5, 35
    elif voltage_v >= 10.2:
        percent_min, percent_max = 0, 20
    else:
        percent_min, percent_max = 0, 10

    estimate.update(
        percent_min=percent_min,
        percent_max=percent_max,
        remaining_wh_min=round(BATTERY_CAPACITY_WH * percent_min / 100, 1),
        remaining_wh_max=round(BATTERY_CAPACITY_WH * percent_max / 100, 1),
    )
    return estimate


def infer_power_state(connected: bool, detected_count: int, expected_count: int) -> dict[str, Any]:
    """Infer controller and servo-rail state from read-only evidence."""
    if not connected:
        return {
            "usb_controller": "offline",
            "servo_rail": "unknown",
            "confidence": "unknown",
            "detail": "The serial controller is not connected, so servo power cannot be inferred.",
        }
    if detected_count:
        return {
            "usb_controller": "online",
            "servo_rail": "powered",
            "confidence": "confirmed",
            "detail": f"{detected_count} of {expected_count} servos returned powered status packets.",
        }
    return {
        "usb_controller": "online",
        "servo_rail": "no_power_detected",
        "confidence": "inferred",
        "detail": "The USB controller is online, but no servo returned a status packet. The rail is likely off; a loose power or data cable can look the same.",
    }


class LeKiwiDiagnostics:
    """Owns one read-only serial connection and its latest diagnostic snapshot."""

    def __init__(
        self,
        serial_port: str | None = None,
        baudrate: int = DEFAULT_BAUDRATE,
        demo: bool = False,
        settings_path: Path | None = None,
    ) -> None:
        self.settings_path = settings_path or default_settings_path()
        self.preferences = self._load_preferences()
        self.remembered_port = self.preferences.get("serial_port")
        self.remembered_baudrate = int(self.preferences.get("baudrate", DEFAULT_BAUDRATE))
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.demo = demo
        self.bus: Any | None = None
        self._lease: Any | None = None
        self.connected = False
        self.connecting = False
        self.error: str | None = None
        self.discovered_models: dict[int, int] = {}
        self.scan_results: dict[int, list[int]] = {}
        self.scan_models: dict[int, dict[int, int]] = {}
        self.latest_motors: list[dict[str, Any]] = []
        self.last_update: str | None = None
        self.poll_latency_ms: float | None = None
        self._last_bus_probe_at = 0.0
        self.autodetecting = False
        self.autodetect_status = "demo" if demo else "idle"
        self.autodetect_source: str | None = None
        self._lock = threading.RLock()
        self._connection_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._autodetect_thread: threading.Thread | None = None

        if demo:
            self.connected = True
            self.serial_port = "SIMULATED /dev/ttyACM0"
            self.discovered_models = {motor.id: EXPECTED_MODEL_NUMBER for motor in EXPECTED_MOTORS}
            self.discovered_models.pop(8)
            self.scan_results = {baudrate: sorted(self.discovered_models)}
            self.scan_models = {baudrate: dict(self.discovered_models)}

    def ports(self) -> list[dict[str, Any]]:
        ports = [
            {
                "device": port.device,
                "description": port.description or "Serial device",
                "hwid": port.hwid or "",
                "plausible": self._is_plausible_port(port.device, port.description or "", port.hwid or ""),
                "remembered": port.device == self.remembered_port,
            }
            for port in list_ports.comports()
        ]
        return sorted(ports, key=lambda item: item["device"])

    def connect(self, serial_port: str, baudrate: int = DEFAULT_BAUDRATE, deep: bool = False) -> None:
        if not serial_port:
            raise ValueError("Select a serial port before scanning.")
        if self.demo:
            raise RuntimeError("Restart without --demo to connect to hardware.")

        with self._connection_lock:
            self._stop_poller()
            with self._lock:
                self._close_bus()
                self.connecting = True
                self.error = None
                self.serial_port = serial_port
                self.baudrate = baudrate

                # Lazy import avoids a module cycle: the embedded telemetry
                # module reuses this file's snapshot formatting helpers.
                from .live_diagnostics import BusLease

                lease = BusLease(serial_port, "standalone offline diagnostics")
                lease.acquire()
                self._lease = lease
                bus = None
                try:
                    bus = expected_motor_bus(serial_port)
                    bus.connect(handshake=False)
                    baudrates = bus.available_baudrates if deep else [baudrate]
                    scan_results: dict[int, list[int]] = {}
                    scan_models: dict[int, dict[int, int]] = {}

                    for candidate in baudrates:
                        bus.set_baudrate(candidate)
                        found = bus.broadcast_ping(num_retry=1) or {}
                        if found:
                            scan_results[candidate] = sorted(found)
                            scan_models[candidate] = found

                    active_baudrate = self._choose_baudrate(scan_results, baudrate)
                    bus.set_baudrate(active_baudrate)
                    self.baudrate = active_baudrate
                    self.scan_results = scan_results
                    self.scan_models = scan_models
                    self.discovered_models = scan_models.get(active_baudrate, {})
                    self.bus = bus
                    self.connected = True
                    self.connecting = False
                except Exception as exc:
                    self.connecting = False
                    self.connected = False
                    self.error = friendly_error(exc)
                    if bus is not None:
                        with contextlib.suppress(Exception):
                            bus.port_handler.closePort()
                    lease.release()
                    self._lease = None
                    raise RuntimeError(self.error) from exc

        self.poll_once()
        if self.discovered_models:
            self._save_preferences(serial_port, self.baudrate)
        self._start_poller()

    def disconnect(self) -> None:
        self._stop_poller()
        with self._connection_lock, self._lock:
            self._close_bus()
            self.connected = False
            self.latest_motors = []
            self.last_update = None
            self.poll_latency_ms = None
            self.error = None
            self.autodetect_status = "idle"
            self.autodetect_source = None

    def start_autodetect(self) -> bool:
        """Start a bounded background attempt to find the most likely LeKiwi bus."""
        if self.demo or self.connected or self.connecting or self.autodetecting:
            return False
        self.autodetecting = True
        self.autodetect_status = "scanning_ports"
        self.autodetect_source = None
        self.error = None
        self._autodetect_thread = threading.Thread(
            target=self._autodetect_worker,
            name="lekiwi-autodetect",
            daemon=True,
        )
        self._autodetect_thread.start()
        return True

    def close(self) -> None:
        if not self.demo:
            self.disconnect()

    def poll_once(self) -> None:
        if self.demo:
            return
        started = time.perf_counter()
        with self._lock:
            if not self.connected or self.bus is None:
                return
            try:
                now = time.monotonic()
                if now - self._last_bus_probe_at >= POWER_RESCAN_INTERVAL_S:
                    # Motor power can be switched independently of USB. Refresh
                    # bus presence so an off→on or on→off transition is visible
                    # without restarting the diagnostics service.
                    found = self.bus.broadcast_ping(num_retry=1) or {}
                    self.discovered_models = dict(found)
                    self.scan_results[self.baudrate] = sorted(found)
                    self.scan_models[self.baudrate] = dict(found)
                    self._last_bus_probe_at = now
                self.latest_motors = [self._read_motor(motor) for motor in EXPECTED_MOTORS]
                self.last_update = utc_now()
                self.poll_latency_ms = round((time.perf_counter() - started) * 1000, 1)
                self.error = None
            except Exception as exc:
                self.error = friendly_error(exc)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            motors = self._demo_motors() if self.demo else [dict(motor) for motor in self.latest_motors]
            if not motors:
                motors = [self._empty_motor(motor) for motor in EXPECTED_MOTORS]

            profile = self._detect_profile(motors)
            expected_ids = set(profile.expected_ids)
            active_detected = sum(motor["detected"] for motor in motors if motor["id"] in expected_ids)
            for motor in motors:
                motor["in_profile"] = motor["id"] in expected_ids
                if self.connected and not motor["in_profile"]:
                    motor.update(
                        severity="not_applicable",
                        findings=[],
                    )
                elif self.connected:
                    severity, motor_findings = assess_motor(motor, profile)
                    motor.update(severity=severity, findings=motor_findings)

            # When every expected servo is silent, the evidence points to one
            # shared power/data-path problem rather than N simultaneous faults.
            if self.connected and active_detected == 0:
                for motor in motors:
                    if motor["in_profile"]:
                        motor.update(
                            severity="unpowered",
                            findings=["No servo power or status packet detected"],
                        )

            configured_ids = {motor.id for motor in EXPECTED_MOTORS}
            unexpected = [
                {"id": id_, "model_number": number, "model": model_name(number)}
                for id_, number in sorted(self.discovered_models.items())
                if id_ not in configured_ids
            ]
            findings = self._findings(motors, unexpected)
            active_motors = [motor for motor in motors if motor["in_profile"]]
            counts = {
                "expected": len(active_motors),
                "detected": sum(motor["detected"] for motor in active_motors),
                "healthy": sum(motor["severity"] == "healthy" for motor in active_motors),
                "warning": sum(motor["severity"] == "warning" for motor in active_motors),
                "critical": sum(motor["severity"] == "critical" for motor in active_motors),
                "unpowered": sum(motor["severity"] == "unpowered" for motor in active_motors),
            }
            overall = "offline"
            if self.connected:
                overall = (
                    "critical"
                    if counts["critical"]
                    else "warning"
                    if counts["warning"] or counts["unpowered"]
                    else "healthy"
                )

            power = infer_power_state(self.connected, counts["detected"], counts["expected"])

            return {
                "connected": self.connected,
                "connecting": self.connecting,
                "demo": self.demo,
                "serial_port": self.serial_port,
                "baudrate": self.baudrate,
                "last_update": utc_now() if self.demo else self.last_update,
                "poll_latency_ms": 42.6 if self.demo else self.poll_latency_ms,
                "overall": overall,
                "error": self.error,
                "counts": counts,
                "power": power,
                "battery": estimate_battery(
                    round(
                        sum(
                            motor["voltage_v"]
                            for motor in active_motors
                            if motor.get("voltage_v") is not None
                        )
                        / sum(motor.get("voltage_v") is not None for motor in active_motors),
                        1,
                    )
                    if any(motor.get("voltage_v") is not None for motor in active_motors)
                    else None
                ),
                "motors": motors,
                "unexpected_motors": unexpected,
                "scan_results": {str(key): value for key, value in self.scan_results.items()},
                "findings": findings,
                "read_only": True,
                "profile": {
                    "key": profile.key,
                    "label": profile.label,
                    "expected_ids": list(profile.expected_ids),
                    "voltage_band": [profile.voltage_min, profile.voltage_max],
                },
                "autodetecting": self.autodetecting,
                "autodetect_status": self.autodetect_status,
                "autodetect_source": self.autodetect_source,
                "remembered_port": self.remembered_port,
            }

    def _read_motor(self, expected: ExpectedMotor) -> dict[str, Any]:
        found_model = self.discovered_models.get(expected.id)
        motor = self._empty_motor(expected)
        found_baudrate = self.baudrate
        if found_model is None:
            for candidate, models in self.scan_models.items():
                if expected.id in models:
                    found_baudrate = candidate
                    found_model = models[expected.id]
                    break

        motor["detected"] = found_model is not None
        motor["model_number"] = found_model
        motor["model"] = model_name(found_model)
        motor["model_mismatch"] = found_model not in (None, EXPECTED_MODEL_NUMBER)
        motor["found_baudrate"] = found_baudrate if found_model is not None else None
        motor["wrong_baudrate"] = found_model is not None and found_baudrate != self.baudrate

        if self.discovered_models.get(expected.id) is None or self.bus is None:
            severity, findings = assess_motor(motor)
            motor.update(severity=severity, findings=findings)
            return motor

        values: dict[str, Any] = {}
        errors = []
        for register in TELEMETRY_REGISTERS:
            try:
                values[register] = self.bus.read(register, expected.name, normalize=False, num_retry=1)
            except Exception as exc:
                errors.append(f"{register}: {friendly_error(exc)}")

        position = values.get("Present_Position")
        velocity = values.get("Present_Velocity")
        motor.update(
            position_raw=position,
            position_deg=round((position % 4096) * 360 / 4096, 1) if position is not None else None,
            velocity_raw=velocity,
            velocity_deg_s=round(velocity * 360 / 4096, 1) if velocity is not None else None,
            load_raw=values.get("Present_Load"),
            voltage_v=round(values["Present_Voltage"] / 10, 1)
            if values.get("Present_Voltage") is not None
            else None,
            temperature_c=values.get("Present_Temperature"),
            current_raw=values.get("Present_Current"),
            torque_enabled=bool(values["Torque_Enable"]) if values.get("Torque_Enable") is not None else None,
            operating_mode=values.get("Operating_Mode"),
            moving=bool(values["Moving"]) if values.get("Moving") is not None else None,
            status_raw=values.get("Status"),
            read_error="; ".join(errors) if errors else None,
        )
        severity, findings = assess_motor(motor)
        motor.update(severity=severity, findings=findings)
        return motor

    def _empty_motor(self, expected: ExpectedMotor) -> dict[str, Any]:
        return {
            "name": expected.name,
            "label": expected.label,
            "id": expected.id,
            "group": expected.group,
            "detected": False,
            "model_number": None,
            "model": "—",
            "model_mismatch": False,
            "found_baudrate": None,
            "expected_baudrate": self.baudrate,
            "wrong_baudrate": False,
            "position_raw": None,
            "position_deg": None,
            "velocity_raw": None,
            "velocity_deg_s": None,
            "load_raw": None,
            "voltage_v": None,
            "temperature_c": None,
            "current_raw": None,
            "torque_enabled": None,
            "operating_mode": None,
            "moving": None,
            "status_raw": None,
            "read_error": None,
            "severity": "critical" if self.connected else "offline",
            "findings": ["No response on the selected baud rate"] if self.connected else [],
        }

    def _demo_motors(self) -> list[dict[str, Any]]:
        phase = time.monotonic()
        motors = []
        for expected in EXPECTED_MOTORS:
            motor = self._empty_motor(expected)
            if expected.id == 8:
                motor.update(severity="critical", findings=["No response on the selected baud rate"])
                motors.append(motor)
                continue
            position = int((1700 + expected.id * 211 + math.sin(phase / 4 + expected.id) * 160) % 4096)
            temperature = 58 if expected.id == 3 else 34 + expected.id
            motor.update(
                detected=True,
                model_number=EXPECTED_MODEL_NUMBER,
                model="STS3215",
                position_raw=position,
                position_deg=round(position * 360 / 4096, 1),
                velocity_raw=0 if expected.group == "arm" else int(math.sin(phase + expected.id) * 14),
                velocity_deg_s=0.0
                if expected.group == "arm"
                else round(math.sin(phase + expected.id) * 1.2, 1),
                load_raw=82 + expected.id * 9,
                voltage_v=12.1,
                temperature_c=temperature,
                current_raw=18 + expected.id * 3,
                torque_enabled=True,
                operating_mode=0 if expected.group == "arm" else 1,
                moving=False,
                status_raw=0,
            )
            severity, findings = assess_motor(motor)
            motor.update(severity=severity, findings=findings)
            motors.append(motor)
        return motors

    def _findings(
        self, motors: list[dict[str, Any]], unexpected: list[dict[str, Any]]
    ) -> list[dict[str, str]]:
        findings = []
        if self.error:
            findings.append(
                {"severity": "critical", "title": "Serial communication failed", "detail": self.error}
            )
        unpowered = [motor for motor in motors if motor["severity"] == "unpowered"]
        if unpowered:
            findings.append(
                {
                    "severity": "warning",
                    "title": "No servo power detected",
                    "detail": "The USB controller is online, but none of the servos responded. This usually means the servo rail is switched off or disconnected; check the shared data cable too.",
                }
            )
        for motor in motors:
            if motor["severity"] in ("healthy", "not_applicable", "unpowered"):
                continue
            for detail in motor["findings"]:
                findings.append(
                    {
                        "severity": motor["severity"],
                        "title": motor["label"],
                        "detail": detail,
                    }
                )
        for motor in unexpected:
            findings.append(
                {
                    "severity": "warning",
                    "title": f"Unexpected motor ID {motor['id']}",
                    "detail": f"The bus reported {motor['model']}, which is not part of the expected LeKiwi map.",
                }
            )
        if self.connected and not findings:
            expected_count = sum(motor.get("in_profile", True) for motor in motors)
            findings.append(
                {
                    "severity": "healthy",
                    "title": "No faults detected",
                    "detail": f"All {expected_count} expected motors responded and their live readings are "
                    "inside the diagnostic bands.",
                }
            )
        return findings

    def _detect_profile(self, motors: list[dict[str, Any]]) -> BusProfile:
        """Recognize a complete 5 V leader arm without masking a partial follower fault."""
        if not self.connected or self.demo:
            return LEKIWI_FOLLOWER_PROFILE

        detected_ids = {motor["id"] for motor in motors if motor["detected"]}
        leader_ids = set(SO101_LEADER_PROFILE.expected_ids)
        voltages = [
            motor["voltage_v"]
            for motor in motors
            if motor["id"] in leader_ids and motor.get("voltage_v") is not None
        ]
        if detected_ids == leader_ids and len(voltages) >= 4:
            average_voltage = sum(voltages) / len(voltages)
            if SO101_LEADER_PROFILE.voltage_min <= average_voltage <= SO101_LEADER_PROFILE.voltage_max:
                return SO101_LEADER_PROFILE
        return LEKIWI_FOLLOWER_PROFILE

    def _start_poller(self) -> None:
        self._stop_event.clear()
        self._poll_thread = threading.Thread(target=self._poll_loop, name="lekiwi-diagnostics", daemon=True)
        self._poll_thread.start()

    def _stop_poller(self) -> None:
        self._stop_event.set()
        if self._poll_thread and self._poll_thread is not threading.current_thread():
            self._poll_thread.join(timeout=2)
        self._poll_thread = None

    def _poll_loop(self) -> None:
        while not self._stop_event.wait(POLL_INTERVAL_S):
            self.poll_once()

    def _autodetect_worker(self) -> None:
        try:
            ports = self.ports()
            candidates = self._autodetect_candidates(ports, self.remembered_port, self.remembered_baudrate)
            if not candidates:
                plausible_count = sum(port.get("plausible", False) for port in ports)
                self.autodetect_status = "choose_port" if plausible_count > 1 else "no_ports"
                return

            last_error = None
            for candidate in candidates:
                self.autodetect_source = candidate["source"]
                try:
                    self.connect(candidate["device"], candidate["baudrate"])
                except RuntimeError as exc:
                    last_error = friendly_error(exc)
                    continue

                if self.discovered_models:
                    self.autodetect_status = "connected"
                    self.error = None
                    return

                self.disconnect()
                last_error = f"No Feetech motors responded on {candidate['device']}."

            self.error = last_error
            self.autodetect_status = "no_motors" if last_error and "No Feetech" in last_error else "failed"
        finally:
            self.autodetecting = False

    @staticmethod
    def _autodetect_candidates(
        ports: list[dict[str, Any]],
        remembered_port: str | None,
        remembered_baudrate: int = DEFAULT_BAUDRATE,
    ) -> list[dict[str, Any]]:
        available = {port["device"]: port for port in ports}
        plausible = [port for port in ports if port.get("plausible")]
        candidates = []

        if remembered_port in available:
            candidates.append(
                {
                    "device": remembered_port,
                    "baudrate": remembered_baudrate,
                    "source": "remembered",
                }
            )
            alternatives = [port for port in plausible if port["device"] != remembered_port]
            if len(alternatives) == 1:
                candidates.append(
                    {
                        "device": alternatives[0]["device"],
                        "baudrate": DEFAULT_BAUDRATE,
                        "source": "single_port_fallback",
                    }
                )
            return candidates

        if len(plausible) == 1:
            candidates.append(
                {
                    "device": plausible[0]["device"],
                    "baudrate": DEFAULT_BAUDRATE,
                    "source": "single_port",
                }
            )
        return candidates

    @staticmethod
    def _is_plausible_port(device: str, description: str, hwid: str) -> bool:
        text = f"{device} {description} {hwid}".lower()
        usb_markers = ("ttyacm", "ttyusb", "usbmodem", "usbserial", "usb serial", "ch340", "cp210", "ftdi")
        excluded = ("bluetooth", "debug-console", "wireless")
        return any(marker in text for marker in usb_markers) and not any(
            marker in text for marker in excluded
        )

    def _load_preferences(self) -> dict[str, Any]:
        try:
            data = json.loads(self.settings_path.read_text())
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        port = data.get("serial_port")
        baudrate = data.get("baudrate")
        preferences: dict[str, Any] = {}
        if isinstance(port, str) and port:
            preferences["serial_port"] = port
        if not isinstance(baudrate, int) or baudrate <= 0:
            baudrate = DEFAULT_BAUDRATE
        preferences["baudrate"] = baudrate
        follower_url = data.get("follower_url")
        if isinstance(follower_url, str) and follower_url:
            preferences["follower_url"] = follower_url
        return preferences

    def _save_preferences(self, serial_port: str, baudrate: int) -> None:
        payload = {
            "version": 1,
            "serial_port": serial_port,
            "baudrate": baudrate,
            "updated_at": utc_now(),
        }
        if self.preferences.get("follower_url"):
            payload["follower_url"] = self.preferences["follower_url"]
        self._write_preferences(payload)

    def save_follower_url(self, follower_url: str | None) -> None:
        payload = dict(self.preferences)
        payload.update(
            version=1,
            serial_port=self.serial_port or self.remembered_port,
            baudrate=self.baudrate or self.remembered_baudrate,
            updated_at=utc_now(),
        )
        if follower_url:
            payload["follower_url"] = follower_url
        else:
            payload.pop("follower_url", None)
        self._write_preferences(payload)

    def _write_preferences(self, payload: dict[str, Any]) -> None:
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.settings_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, indent=2) + "\n")
            temporary.replace(self.settings_path)
            self.preferences = payload
            self.remembered_port = payload.get("serial_port")
            self.remembered_baudrate = int(payload.get("baudrate", DEFAULT_BAUDRATE))
        except OSError:
            # Diagnostics must remain usable even if the preference directory is read-only.
            return

    def _close_bus(self) -> None:
        if self.bus is not None:
            try:
                if self.bus.is_connected:
                    self.bus.disconnect(disable_torque=False)
            except Exception:
                with contextlib.suppress(Exception):
                    self.bus.port_handler.closePort()
            finally:
                self.bus = None
        if self._lease is not None:
            self._lease.release()
            self._lease = None

    @staticmethod
    def _choose_baudrate(scan_results: dict[int, list[int]], preferred: int) -> int:
        if not scan_results:
            return preferred
        expected_ids = {motor.id for motor in EXPECTED_MOTORS}
        scores = {
            rate: len(expected_ids.intersection(responding_ids))
            for rate, responding_ids in scan_results.items()
        }
        best_score = max(scores.values())
        if scores.get(preferred) == best_score:
            return preferred
        return max(scores, key=scores.get)


def friendly_error(exc: Exception) -> str:
    text = str(exc).strip()
    if not text:
        return exc.__class__.__name__
    return " ".join(text.split())


def _offline_source(role: str, endpoint: str | None = None, error: str | None = None) -> dict[str, Any]:
    profile = SO101_LEADER_PROFILE if role == "leader" else LEKIWI_FOLLOWER_PROFILE
    expected_ids = set(profile.expected_ids)
    motors = []
    for expected in EXPECTED_MOTORS:
        if expected.id not in expected_ids:
            continue
        motors.append(
            {
                "source": role,
                "name": expected.name,
                "label": expected.label,
                "id": expected.id,
                "group": expected.group,
                "detected": False,
                "model": "—",
                "position_raw": None,
                "position_deg": None,
                "velocity_raw": None,
                "velocity_deg_s": None,
                "voltage_v": None,
                "temperature_c": None,
                "current_raw": None,
                "torque_enabled": None,
                "severity": "offline",
                "findings": [],
                "in_profile": True,
            }
        )
    return {
        "source": role,
        "source_label": "Leader arm" if role == "leader" else "Follower robot",
        "connected": False,
        "demo": False,
        "serial_port": None,
        "baudrate": DEFAULT_BAUDRATE,
        "last_update": None,
        "poll_latency_ms": None,
        "overall": "offline",
        "error": error,
        "endpoint": endpoint,
        "counts": {
            "expected": len(motors),
            "detected": 0,
            "healthy": 0,
            "warning": 0,
            "critical": 0,
            "unpowered": 0,
        },
        "power": infer_power_state(False, 0, len(motors)),
        "battery": estimate_battery(None),
        "motors": motors,
        "findings": [],
        "profile": {
            "key": profile.key,
            "label": profile.label,
            "expected_ids": list(profile.expected_ids),
            "voltage_band": [profile.voltage_min, profile.voltage_max],
        },
    }


def _as_source(snapshot: dict[str, Any], role: str, endpoint: str | None = None) -> dict[str, Any]:
    source = deepcopy(snapshot)
    source["source"] = role
    source["source_label"] = "Leader arm" if role == "leader" else "Follower robot"
    source["endpoint"] = endpoint
    if role == "leader":
        # The leader's 5 V supply is a separate USB/servo rail, never a battery signal.
        source["battery"] = estimate_battery(None)
    expected_ids = set(source.get("profile", {}).get("expected_ids", []))
    source["motors"] = [
        motor for motor in source.get("motors", []) if not expected_ids or motor.get("id") in expected_ids
    ]
    for motor in source["motors"]:
        motor["source"] = role
    return source


def combine_snapshots(
    local_snapshot: dict[str, Any],
    remote_snapshot: dict[str, Any] | None = None,
    remote_url: str | None = None,
) -> dict[str, Any]:
    """Return the legacy local snapshot plus simultaneous leader/follower source views."""
    leader = _offline_source("leader")
    follower = _offline_source("follower", remote_url)

    local_role = (
        "leader" if local_snapshot.get("profile", {}).get("key") == SO101_LEADER_PROFILE.key else "follower"
    )
    if local_snapshot.get("connected") or local_snapshot.get("demo"):
        if local_role == "leader":
            leader = _as_source(local_snapshot, "leader")
        else:
            follower = _as_source(local_snapshot, "follower")

    if remote_snapshot:
        remote = _as_source(remote_snapshot, "follower", remote_url)
        if remote.get("connected") or not follower.get("connected"):
            follower = remote

    sources = {"leader": leader, "follower": follower}
    all_motors = [motor for source in sources.values() for motor in source["motors"]]
    counts = {
        "expected": sum(source["counts"]["expected"] for source in sources.values()),
        "detected": sum(source["counts"]["detected"] for source in sources.values()),
        "healthy": sum(source["counts"]["healthy"] for source in sources.values()),
        "warning": sum(source["counts"]["warning"] for source in sources.values()),
        "critical": sum(source["counts"]["critical"] for source in sources.values()),
        "unpowered": sum(source["counts"].get("unpowered", 0) for source in sources.values()),
    }
    connected_sources = sum(bool(source.get("connected")) for source in sources.values())
    if not connected_sources:
        overall = "offline"
    elif counts["critical"]:
        overall = "critical"
    elif counts["warning"] or counts["unpowered"] or connected_sources < 2:
        overall = "warning"
    else:
        overall = "healthy"

    combined = deepcopy(local_snapshot)
    combined.update(
        sources=sources,
        system_counts=counts,
        system_overall=overall,
        connected_sources=connected_sources,
        all_motors=all_motors,
        follower_url=remote_url,
        battery=follower.get("battery", estimate_battery(None)),
    )
    return combined


class RemoteDiagnosticsProxy:
    """Poll a read-only diagnostics service running beside the follower bus."""

    def __init__(self, url: str | None = None) -> None:
        self.url: str | None = None
        self.latest: dict[str, Any] | None = None
        self.error: str | None = None
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        if url:
            self.configure(url)

    @staticmethod
    def normalize_url(url: str) -> str:
        normalized = url.strip().rstrip("/")
        if not normalized:
            return ""
        if not normalized.startswith(("http://", "https://")):
            normalized = f"http://{normalized}"
        if not normalized.endswith("/api/state"):
            normalized += "/api/state"
        return normalized

    def configure(self, url: str | None) -> None:
        self.close()
        normalized = self.normalize_url(url or "")
        with self._lock:
            self.url = normalized or None
            self.latest = None
            self.error = None
        if self.url:
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._poll_loop, name="lekiwi-follower-diagnostics", daemon=True
            )
            self._thread.start()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self.error:
                return _offline_source("follower", self.url, self.error)
            if self.latest is not None:
                return deepcopy(self.latest)
            return _offline_source("follower", self.url)

    def close(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.5)
        self._thread = None

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            started = time.perf_counter()
            try:
                request_ = urllib.request.Request(self.url or "", headers={"Accept": "application/json"})
                # normalize_url permits only explicit HTTP(S) schemes.
                with urllib.request.urlopen(  # nosec B310
                    request_, timeout=REMOTE_TIMEOUT_S
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                # A remote aggregator may include sources; use its follower source only.
                if isinstance(payload.get("sources", {}).get("follower"), dict):
                    payload = payload["sources"]["follower"]
                if payload.get("profile", {}).get("key") != LEKIWI_FOLLOWER_PROFILE.key:
                    raise ValueError("Remote endpoint is not reporting a LeKiwi follower bus")
                with self._lock:
                    self.latest = payload
                    self.error = None
            except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
                message = friendly_error(exc)
                if "timed out" in message.lower():
                    message = "Follower diagnostics endpoint did not respond in time"
                elif "connection refused" in message.lower():
                    message = "Follower diagnostics service is not running on the Pi"
                with self._lock:
                    self.error = message
            elapsed = time.perf_counter() - started
            self._stop_event.wait(max(REMOTE_POLL_INTERVAL_S - elapsed, 0.05))


def create_app(
    service: LeKiwiDiagnostics | None = None, follower: RemoteDiagnosticsProxy | None = None
) -> Flask:
    service = service or LeKiwiDiagnostics()
    follower = follower or RemoteDiagnosticsProxy()
    app = Flask(__name__)
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True
    app.config["diagnostics"] = service
    app.config["follower_diagnostics"] = follower

    def current_state() -> dict[str, Any]:
        return combine_snapshots(service.snapshot(), follower.snapshot(), follower.url)

    @app.get("/")
    def index():
        return render_template("lekiwi_diagnostics.html")

    @app.get("/api/ports")
    def api_ports():
        return jsonify(
            {
                "ports": service.ports(),
                "selected": service.serial_port or service.remembered_port,
                "remembered": service.remembered_port,
            }
        )

    @app.get("/api/state")
    def api_state():
        return jsonify(current_state())

    @app.get("/api/stream")
    def api_stream():
        @stream_with_context
        def events():
            while True:
                yield f"event: state\ndata: {json.dumps(current_state(), separators=(',', ':'))}\n\n"
                time.sleep(1.0 / 15.0)

        return Response(
            events(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/odometry/reset")
    def api_odometry_reset():
        # Standalone maintenance diagnostics has no chassis integrator. Keep
        # the endpoint compatible with the embedded dashboard without touching
        # a motor or serial register.
        return jsonify({"ok": True, "visualization_only": True, "state": current_state()})

    @app.post("/api/connect")
    def api_connect():
        payload = request.get_json(silent=True) or {}
        try:
            service.connect(
                str(payload.get("port", "")).strip(),
                int(payload.get("baudrate", DEFAULT_BAUDRATE)),
                bool(payload.get("deep", False)),
            )
        except (TypeError, ValueError, RuntimeError) as exc:
            return jsonify({"ok": False, "error": friendly_error(exc), "state": current_state()}), 400
        return jsonify({"ok": True, "state": current_state()})

    @app.post("/api/autodetect")
    def api_autodetect():
        started = service.start_autodetect()
        return jsonify({"ok": started, "state": current_state()}), 202 if started else 200

    @app.post("/api/disconnect")
    def api_disconnect():
        service.disconnect()
        return jsonify({"ok": True, "state": current_state()})

    @app.post("/api/follower")
    def api_follower():
        payload = request.get_json(silent=True) or {}
        follower.configure(str(payload.get("url", "")).strip() or None)
        service.save_follower_url(follower.url)
        return jsonify({"ok": True, "state": current_state()})

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the LeKiwi read-only motor diagnostics app.")
    parser.add_argument("--serial-port", help="Motor bus serial port, for example /dev/ttyACM0.")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address.")
    parser.add_argument("--http-port", type=int, default=8090, help="HTTP port.")
    parser.add_argument(
        "--follower-url",
        help="Remote follower diagnostics URL, for example http://lekiwi.local:8091.",
    )
    parser.add_argument(
        "--demo", action="store_true", help="Show simulated diagnostic data without hardware."
    )
    parser.add_argument("--no-open", action="store_true", help="Do not open a browser automatically.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    service = LeKiwiDiagnostics(args.serial_port, args.baudrate, args.demo)
    follower_url = args.follower_url or service.preferences.get("follower_url")
    follower = RemoteDiagnosticsProxy(follower_url)
    app = create_app(service, follower)
    atexit.register(service.close)
    atexit.register(follower.close)

    if args.serial_port and not args.demo:
        with contextlib.suppress(RuntimeError):
            service.connect(args.serial_port, args.baudrate)
    elif not args.demo:
        service.start_autodetect()

    url = f"http://{args.host}:{args.http_port}"
    if not args.no_open:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    print(f"LeKiwi Diagnostics: {url}")
    app.run(host=args.host, port=args.http_port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
