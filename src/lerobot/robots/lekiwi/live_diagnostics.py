#!/usr/bin/env python

"""Embedded, bus-safe telemetry for LeKiwi teleoperation.

The control loop is the only caller allowed to invoke :meth:`sample`.  HTTP and
SSE handlers only copy immutable cached snapshots and therefore never contend
with motor commands for the serial bus.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import tempfile
import threading
import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from werkzeug.serving import BaseWSGIServer, make_server

from .diagnostics import (
    EXPECTED_MODEL_NUMBER,
    LEKIWI_FOLLOWER_PROFILE,
    SO101_LEADER_PROFILE,
    assess_motor,
    combine_snapshots,
    estimate_battery,
    infer_power_state,
    model_name,
)
from .latency_tracing import LatencyTraceRecorder, TraceContext, trace_context_from_wire

SCHEMA_VERSION = "2.0"
PROTOCOL_VERSION = "lekiwi-v061-live-telemetry-v1"
JOINT_FRAME = "lekiwi-fusion-cad-v1"
STALE_AFTER_S = 2.0
CONTROL_PULSE_S = 0.35

ARM_CONTROL_LIMITS: dict[str, tuple[float, float]] = {
    "arm_shoulder_pan.pos": (-100.0, 100.0),
    "arm_shoulder_lift.pos": (-100.0, 100.0),
    "arm_elbow_flex.pos": (-100.0, 100.0),
    "arm_wrist_flex.pos": (-100.0, 100.0),
    "arm_wrist_roll.pos": (-180.0, 180.0),
    "arm_gripper.pos": (0.0, 100.0),
}
ARM_CONTROL_RATES = {name: (35.0 if name == "arm_gripper.pos" else 24.0) for name in ARM_CONTROL_LIMITS}
BASE_CONTROL_KEYS = frozenset("wasdzx")

FOLLOWER_NAMES = (
    "arm_shoulder_pan",
    "arm_shoulder_lift",
    "arm_elbow_flex",
    "arm_wrist_flex",
    "arm_wrist_roll",
    "arm_gripper",
    "base_left_wheel",
    "base_back_wheel",
    "base_right_wheel",
)
LEADER_NAMES = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
)
LABELS = {
    "shoulder_pan": "Shoulder pan",
    "shoulder_lift": "Shoulder lift",
    "elbow_flex": "Elbow flex",
    "wrist_flex": "Wrist flex",
    "wrist_roll": "Wrist roll",
    "gripper": "Gripper",
    "base_left_wheel": "Left wheel",
    "base_back_wheel": "Back wheel",
    "base_right_wheel": "Right wheel",
}

# The LeKiwi Fusion export uses a different axis/origin convention from the
# current LeRobot SO-101 calibration frame.  These transforms were derived by
# matching the Fusion joint chain to the official ``so101_new_calib.urdf`` and
# visually checked against the stationary physical leader/follower pose.  They
# affect telemetry visualization only; motor calibration and commands remain
# unchanged.
JOINT_TRANSFORMS: dict[str, tuple[float, float]] = {
    "arm_shoulder_pan": (1.0, 0.0),
    "arm_shoulder_lift": (-1.0, -math.pi / 2),
    "arm_elbow_flex": (-1.0, math.pi / 2),
    "arm_wrist_flex": (-1.0, math.pi / 2),
    "arm_wrist_roll": (1.0, 0.0),
    "arm_gripper": (-1.0, 0.0),
    "base_left_wheel": (1.0, 0.0),
    "base_back_wheel": (1.0, 0.0),
    "base_right_wheel": (1.0, 0.0),
}

HEALTH_REGISTERS: tuple[tuple[str, str, Callable[[Any], Any]], ...] = (
    ("Present_Voltage", "voltage_v", lambda value: round(float(value) / 10.0, 1)),
    ("Present_Temperature", "temperature_c", int),
    ("Present_Current", "current_raw", int),
    ("Present_Load", "load_raw", int),
    ("Torque_Enable", "torque_enabled", bool),
    ("Operating_Mode", "operating_mode", int),
    ("Moving", "moving", bool),
    ("Status", "status_raw", int),
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _parse_utc(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def calibrated_degrees_to_radians(name: str, degrees: float) -> float:
    """Convert LeRobot's calibrated degree position to a URDF joint value."""
    scale, offset = JOINT_TRANSFORMS[name]
    return scale * math.radians(float(degrees)) + offset


def gripper_percent_to_radians(percent: float, calibration: Any) -> float:
    """Map calibrated 0..100 gripper travel through its recorded raw span."""
    bounded = min(100.0, max(0.0, float(percent)))
    span = float(calibration.range_max - calibration.range_min)
    physical_travel = (bounded / 100.0) * span * (2.0 * math.pi / 4096.0)
    if getattr(calibration, "drive_mode", 0):
        physical_travel = (span * (2.0 * math.pi / 4096.0)) - physical_travel
    scale, offset = JOINT_TRANSFORMS["arm_gripper"]
    return scale * physical_travel + offset


def integrate_body_odometry(
    pose: dict[str, float], body_velocity: dict[str, float], dt_s: float
) -> dict[str, float]:
    """Integrate drift-prone body velocity into a visualization-only world pose."""
    theta = pose["theta"]
    x_body = float(body_velocity.get("x.vel", 0.0))
    y_body = float(body_velocity.get("y.vel", 0.0))
    theta_rate = math.radians(float(body_velocity.get("theta.vel", 0.0)))
    return {
        "x": pose["x"] + (math.cos(theta) * x_body - math.sin(theta) * y_body) * dt_s,
        "y": pose["y"] + (math.sin(theta) * x_body + math.cos(theta) * y_body) * dt_s,
        "theta": theta + theta_rate * dt_s,
    }


class SnapshotProvider(Protocol):
    def snapshot(self) -> dict[str, Any]: ...

    def reset_odometry(self) -> None: ...


class BusOwnedError(RuntimeError):
    pass


class ProtocolCompatibilityError(RuntimeError):
    """Raised before control when the Pi and Mac wire protocols differ."""


class BusLease:
    """Cross-process advisory lock preventing supported tools sharing a serial bus."""

    def __init__(self, serial_port: str, owner: str):
        digest = hashlib.sha256(os.path.realpath(serial_port).encode()).hexdigest()[:16]
        self.path = Path(tempfile.gettempdir()) / f"lerobot-bus-{digest}.lock"
        self.owner = owner
        self._handle: Any | None = None

    def acquire(self) -> None:
        self.path.touch(exist_ok=True)
        handle = self.path.open("r+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            current_owner = handle.read().strip() or "another LeRobot process"
            handle.close()
            raise BusOwnedError(
                f"Motor bus is owned by {current_owner}; diagnostics will use its embedded feed."
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(self.owner)
        handle.flush()
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None

    def __enter__(self) -> BusLease:
        self.acquire()
        return self

    def __exit__(self, *_args: Any) -> None:
        self.release()


@dataclass
class EmbeddedDiagnosticsConfig:
    role: str
    serial_port: str
    stale_after_s: float = STALE_AFTER_S
    health_refresh_s: float = 1.0
    num_read_retries: int = 2


class LiveDiagnosticsSampler:
    """Samples a bus only when called synchronously by its owning control loop."""

    def __init__(self, bus: Any, config: EmbeddedDiagnosticsConfig):
        if config.role not in {"leader", "follower"}:
            raise ValueError("role must be 'leader' or 'follower'")
        self.bus = bus
        self.config = config
        self.profile = SO101_LEADER_PROFILE if config.role == "leader" else LEKIWI_FOLLOWER_PROFILE
        self.bus_names = LEADER_NAMES if config.role == "leader" else FOLLOWER_NAMES
        self._lock = threading.RLock()
        self._health_index = 0
        self._next_health_at = 0.0
        self._last_pose_monotonic: float | None = None
        self._last_pose_utc: str | None = None
        self._pose_interval_ms: float | None = None
        self._max_pose_interval_ms = 0.0
        self._poll_latency_ms: float | None = None
        self._bus_available = False
        self._field_timestamps: dict[str, str] = {}
        self._errors: dict[str, dict[str, Any]] = {}
        self._wheel_angles = {name: 0.0 for name in FOLLOWER_NAMES if name.startswith("base_")}
        self._odometry = {"x": 0.0, "y": 0.0, "theta": 0.0}
        self._motors = [self._empty_motor(name, index + 1) for index, name in enumerate(self.bus_names)]

    def _public_name(self, bus_name: str) -> str:
        return bus_name if bus_name.startswith(("arm_", "base_")) else f"arm_{bus_name}"

    def _empty_motor(self, bus_name: str, id_: int) -> dict[str, Any]:
        public = self._public_name(bus_name)
        label_key = public.removeprefix("arm_")
        return {
            "name": public,
            "bus_name": bus_name,
            "label": LABELS.get(label_key, LABELS.get(public, public)),
            "id": id_,
            "group": "base" if public.startswith("base_") else "arm",
            "detected": True,
            "model_number": EXPECTED_MODEL_NUMBER,
            "model": model_name(EXPECTED_MODEL_NUMBER),
            "model_mismatch": False,
            "found_baudrate": 1_000_000,
            "expected_baudrate": 1_000_000,
            "wrong_baudrate": False,
            "position_raw": None,
            "position_deg": None,
            "joint_position_rad": None,
            "velocity_raw": None,
            "velocity_deg_s": None,
            "voltage_v": None,
            "temperature_c": None,
            "current_raw": None,
            "load_raw": None,
            "torque_enabled": None,
            "operating_mode": None,
            "moving": None,
            "status_raw": None,
            "read_error": None,
            "field_timestamps": {},
            "severity": "healthy",
            "findings": [],
            "in_profile": True,
        }

    def sample(
        self,
        positions: dict[str, float],
        *,
        wheel_velocity_raw: dict[str, float] | None = None,
        body_velocity: dict[str, float] | None = None,
    ) -> None:
        """Update pose and one staggered health register from the owning loop."""
        started = time.perf_counter()
        now = started
        stamp = utc_now()
        with self._lock:
            interval_s = 0.0 if self._last_pose_monotonic is None else now - self._last_pose_monotonic
            dt_s = min(interval_s, 0.5)
            if self._last_pose_monotonic is not None:
                self._pose_interval_ms = round(interval_s * 1000.0, 2)
                self._max_pose_interval_ms = max(self._max_pose_interval_ms, self._pose_interval_ms)
            self._last_pose_monotonic = now
            self._last_pose_utc = stamp
            self._field_timestamps["pose"] = stamp
            self._bus_available = True
            self._errors.pop("motor_bus", None)

            by_bus_name = {motor["bus_name"]: motor for motor in self._motors}
            for bus_name, value in positions.items():
                if bus_name not in by_bus_name:
                    continue
                motor = by_bus_name[bus_name]
                public_name = motor["name"]
                motor["position_deg"] = round(float(value), 3)
                if public_name == "arm_gripper":
                    calibration = self.bus.calibration.get(bus_name)
                    radians = (
                        gripper_percent_to_radians(float(value), calibration)
                        if calibration is not None
                        else math.radians(float(value))
                    )
                else:
                    radians = calibrated_degrees_to_radians(public_name, float(value))
                motor["joint_position_rad"] = radians
                motor["field_timestamps"]["joint_position_rad"] = stamp

            if wheel_velocity_raw:
                for bus_name, raw in wheel_velocity_raw.items():
                    motor = by_bus_name.get(bus_name)
                    if motor is None:
                        continue
                    rad_s = float(raw) * (2.0 * math.pi / 4096.0)
                    self._wheel_angles[bus_name] += rad_s * dt_s
                    scale, offset = JOINT_TRANSFORMS[bus_name]
                    motor["joint_position_rad"] = scale * self._wheel_angles[bus_name] + offset
                    motor["position_deg"] = math.degrees(motor["joint_position_rad"])
                    motor["velocity_raw"] = raw
                    motor["velocity_deg_s"] = math.degrees(rad_s)
                    motor["field_timestamps"]["joint_position_rad"] = stamp
                    motor["field_timestamps"]["velocity_raw"] = stamp

            if body_velocity is not None and dt_s > 0:
                self._odometry = integrate_body_odometry(self._odometry, body_velocity, dt_s)
                self._field_timestamps["odometry"] = stamp

            self._sample_one_health_register(now, stamp)
            self._poll_latency_ms = round((time.perf_counter() - started) * 1000.0, 2)

    def mark_bus_unavailable(self, exc: Exception) -> None:
        """Publish a rail-off/read-failure transition without touching the bus."""
        stamp = utc_now()
        with self._lock:
            previous = self._errors.get("motor_bus", {})
            self._bus_available = False
            self._last_pose_utc = stamp
            self._last_pose_monotonic = time.perf_counter()
            self._errors["motor_bus"] = {
                "message": " ".join(str(exc).split()) or exc.__class__.__name__,
                "at": stamp,
                "consecutive": int(previous.get("consecutive", 0)) + 1,
            }

    def _sample_one_health_register(self, now: float, stamp: str) -> None:
        interval = self.config.health_refresh_s / len(HEALTH_REGISTERS)
        if now < self._next_health_at:
            return
        register, field, convert = HEALTH_REGISTERS[self._health_index]
        self._health_index = (self._health_index + 1) % len(HEALTH_REGISTERS)
        self._next_health_at = now + interval
        try:
            values = self.bus.sync_read(
                register,
                list(self.bus_names),
                normalize=False,
                num_retry=self.config.num_read_retries,
            )
            by_bus_name = {motor["bus_name"]: motor for motor in self._motors}
            for bus_name, value in values.items():
                motor = by_bus_name[bus_name]
                motor[field] = convert(value)
                motor["field_timestamps"][field] = stamp
            self._field_timestamps[field] = stamp
            self._errors.pop(field, None)
        except Exception as exc:  # Telemetry must never abort teleoperation.
            previous = self._errors.get(field, {})
            self._errors[field] = {
                "message": " ".join(str(exc).split()) or exc.__class__.__name__,
                "at": stamp,
                "consecutive": int(previous.get("consecutive", 0)) + 1,
            }

    def reset_odometry(self) -> None:
        with self._lock:
            self._odometry = {"x": 0.0, "y": 0.0, "theta": 0.0}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            motors = deepcopy(self._motors)
            last_update = self._last_pose_utc
            last_epoch = _parse_utc(last_update)
            age_s = None if last_epoch is None else max(0.0, time.time() - last_epoch)
            stale = age_s is None or age_s > self.config.stale_after_s
            for motor in motors:
                motor["read_error"] = None
                severity, findings = assess_motor(motor, self.profile)
                if stale:
                    motor["severity"] = "offline"
                    motor["findings"] = ["Telemetry feed is stale"]
                elif not self._bus_available:
                    motor["detected"] = False
                    motor["severity"] = "unpowered"
                    motor["findings"] = ["No servo power or status packet detected"]
                else:
                    motor["severity"] = severity
                    motor["findings"] = findings

            counts = {
                "expected": len(motors),
                "detected": 0 if stale or not self._bus_available else len(motors),
                "healthy": sum(motor["severity"] == "healthy" for motor in motors),
                "warning": sum(motor["severity"] == "warning" for motor in motors),
                "critical": sum(motor["severity"] == "critical" for motor in motors),
                "unpowered": sum(motor["severity"] == "unpowered" for motor in motors),
            }
            overall = (
                "offline"
                if stale
                else "critical"
                if counts["critical"]
                else "warning"
                if counts["warning"] or counts["unpowered"]
                else "healthy"
            )
            voltages = [motor["voltage_v"] for motor in motors if motor.get("voltage_v") is not None]
            voltage = round(sum(voltages) / len(voltages), 1) if voltages else None
            findings = []
            if stale:
                findings.append(
                    {
                        "severity": "offline",
                        "title": "Telemetry feed",
                        "detail": "No control-loop sample arrived within two seconds.",
                    }
                )
            for field, error in self._errors.items():
                findings.append(
                    {"severity": "warning", "title": f"{field} sample", "detail": error["message"]}
                )

            return {
                "schema_version": SCHEMA_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "joint_frame": JOINT_FRAME,
                "sample_mode": "embedded_control_loop",
                "source": self.config.role,
                "source_label": "Leader arm" if self.config.role == "leader" else "Follower robot",
                "connected": not stale,
                "connecting": False,
                "demo": False,
                "serial_port": self.config.serial_port,
                "baudrate": 1_000_000,
                "last_update": last_update,
                "sample_age_s": age_s,
                "stale": stale,
                "stale_after_s": self.config.stale_after_s,
                "poll_latency_ms": self._poll_latency_ms,
                "pose_interval_ms": self._pose_interval_ms,
                "max_pose_interval_ms": self._max_pose_interval_ms,
                "overall": overall,
                "error": None,
                "errors": deepcopy(self._errors),
                "field_timestamps": deepcopy(self._field_timestamps),
                "counts": counts,
                "power": infer_power_state(not stale, counts["detected"], counts["expected"]),
                "battery": estimate_battery(voltage if self.config.role == "follower" else None),
                "motors": motors,
                "unexpected_motors": [],
                "findings": findings,
                "read_only": True,
                "profile": {
                    "key": self.profile.key,
                    "label": self.profile.label,
                    "expected_ids": list(self.profile.expected_ids),
                    "voltage_band": [self.profile.voltage_min, self.profile.voltage_max],
                },
                "odometry": {**self._odometry, "estimated": True, "drift_prone": True},
            }


class MutableSnapshotCache:
    """Thread-safe cache used by the ZMQ client; it never accesses hardware."""

    def __init__(self, role: str):
        self.role = role
        self._snapshot: dict[str, Any] | None = None
        self._odometry_origin = {"x": 0.0, "y": 0.0, "theta": 0.0}
        self._lock = threading.RLock()

    def publish(self, snapshot: dict[str, Any]) -> None:
        with self._lock:
            self._snapshot = deepcopy(snapshot)

    def reset_odometry(self) -> None:
        # Follower odometry is authoritative on the host; a Mac reset is sent to
        # the visualization cache only and does not touch motors.
        with self._lock:
            if self._snapshot is not None:
                current = self._snapshot.get("odometry", {})
                self._odometry_origin = {
                    "x": float(current.get("x", 0.0)),
                    "y": float(current.get("y", 0.0)),
                    "theta": float(current.get("theta", 0.0)),
                }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self._snapshot is None:
                return _empty_cached_source(self.role)
            value = deepcopy(self._snapshot)
            odometry = value.get("odometry")
            if isinstance(odometry, dict):
                origin = self._odometry_origin
                dx = float(odometry.get("x", 0.0)) - origin["x"]
                dy = float(odometry.get("y", 0.0)) - origin["y"]
                cos_origin = math.cos(origin["theta"])
                sin_origin = math.sin(origin["theta"])
                value["odometry"] = {
                    **odometry,
                    "x": cos_origin * dx + sin_origin * dy,
                    "y": -sin_origin * dx + cos_origin * dy,
                    "theta": float(odometry.get("theta", 0.0)) - origin["theta"],
                }
        last_epoch = _parse_utc(value.get("last_update"))
        age_s = None if last_epoch is None else max(0.0, time.time() - last_epoch)
        stale = age_s is None or age_s > STALE_AFTER_S
        value["sample_age_s"] = age_s
        value["stale"] = stale
        if stale:
            value["connected"] = False
            value["overall"] = "offline"
            value["counts"]["detected"] = 0
            for motor in value.get("motors", []):
                motor["severity"] = "offline"
        return value


class MutableCameraFrameCache:
    """Latest-only JPEG cache populated by the ZMQ receive loop.

    HTTP camera handlers wait on this cache and never touch an OpenCV device or
    the follower's motor bus.  Revisions let slow browsers drop frames instead
    of building an unbounded video queue.
    """

    def __init__(self, names: tuple[str, ...] = ("front", "wrist")):
        self.names = names
        self._frames: dict[str, bytes] = {}
        self._updated_at: dict[str, str] = {}
        self._updated_epoch: dict[str, float] = {}
        self._revisions: dict[str, int] = dict.fromkeys(names, 0)
        self._condition = threading.Condition(threading.RLock())

    def publish(self, name: str, jpeg: bytes) -> None:
        if name not in self.names or not jpeg:
            return
        with self._condition:
            self._frames[name] = bytes(jpeg)
            self._updated_at[name] = utc_now()
            self._updated_epoch[name] = time.time()
            self._revisions[name] = self._revisions.get(name, 0) + 1
            self._condition.notify_all()

    def wait_for_frame(
        self, name: str, after_revision: int = -1, timeout_s: float = 2.0
    ) -> tuple[bytes, int] | None:
        if name not in self.names:
            return None
        deadline = time.monotonic() + timeout_s
        with self._condition:
            while self._revisions.get(name, 0) <= after_revision:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            frame = self._frames.get(name)
            if frame is None:
                return None
            return frame, self._revisions[name]

    def status(self) -> dict[str, dict[str, Any]]:
        now = time.time()
        with self._condition:
            return {
                name: {
                    "available": name in self._frames,
                    "last_update": self._updated_at.get(name),
                    "sample_age_s": (
                        None if name not in self._updated_epoch else max(0.0, now - self._updated_epoch[name])
                    ),
                    "stale": name not in self._updated_epoch
                    or now - self._updated_epoch[name] > STALE_AFTER_S,
                    "stream_url": f"/api/cameras/{name}/stream",
                }
                for name in self.names
            }


class TeleopControlBridge:
    """Thread-safe dashboard intent consumed only by the teleop control loop.

    Flask handlers update short-lived intent.  They never send a ZMQ command or
    access either serial bus.  The 30 Hz owner calls :meth:`apply` to merge that
    intent into its normal action, preserving bus exclusivity and watchdogs.
    """

    SPEED_LEVELS = (
        {"label": "slow", "xy": 0.08, "theta": 25.0},
        {"label": "medium", "xy": 0.16, "theta": 50.0},
        {"label": "fast", "xy": 0.25, "theta": 75.0},
    )

    def __init__(self, pulse_s: float = CONTROL_PULSE_S, *, exclusive_base: bool = False):
        self.pulse_s = pulse_s
        self.exclusive_base = exclusive_base
        self._lock = threading.RLock()
        self._enabled = False
        self._permitted = False
        self._permit_reason = "Waiting for live follower telemetry."
        self._arm_takeover = False
        self._stop_latched = False
        self._speed_index = 0
        self._base_expiry: dict[str, float] = {}
        self._joint_expiry: dict[str, tuple[float, float]] = {}
        self._arm_targets: dict[str, float] | None = None
        self._last_apply_at: float | None = None
        self._last_command_at: str | None = None
        self._revision = 0
        self._pending_trace: TraceContext | None = None

    def note_trace(self, value: Any) -> None:
        """Attach a browser/client trace to the next owner-loop application."""
        context = trace_context_from_wire(value)
        if context is not None:
            with self._lock:
                self._pending_trace = context

    def take_trace_context(self) -> TraceContext | None:
        with self._lock:
            context = self._pending_trace
            self._pending_trace = None
            return context

    def set_permitted(self, permitted: bool, reason: str) -> None:
        with self._lock:
            previous = (self._permitted, self._permit_reason, self._enabled, self._arm_takeover)
            self._permitted = bool(permitted)
            self._permit_reason = reason
            if not self._permitted:
                self._enabled = False
                self._arm_takeover = False
                self._clear_motion_locked()
            current = (self._permitted, self._permit_reason, self._enabled, self._arm_takeover)
            if current != previous:
                self._revision += 1

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            if enabled and not self._permitted:
                raise RuntimeError(self._permit_reason)
            self._enabled = bool(enabled)
            self._stop_latched = False if enabled else self._stop_latched
            if not enabled:
                self._arm_takeover = False
                self._arm_targets = None
                self._clear_motion_locked()
            self._touch_locked()

    def set_speed(self, index: int) -> None:
        with self._lock:
            self._require_enabled_locked()
            if index not in range(len(self.SPEED_LEVELS)):
                raise ValueError("speed must be 0, 1, or 2")
            self._speed_index = index
            self._touch_locked()

    def pulse_base(self, key: str, active: bool) -> None:
        key = str(key).lower()
        if key not in BASE_CONTROL_KEYS:
            raise ValueError("base key must be one of W, A, S, D, Z, or X")
        with self._lock:
            self._require_enabled_locked()
            if active:
                self._base_expiry[key] = time.monotonic() + self.pulse_s
            else:
                self._base_expiry.pop(key, None)
            self._touch_locked()

    def set_arm_takeover(self, enabled: bool) -> None:
        with self._lock:
            self._require_enabled_locked()
            self._arm_takeover = bool(enabled)
            self._arm_targets = None
            self._joint_expiry.clear()
            self._last_apply_at = None
            self._touch_locked()

    def pulse_joint(self, joint: str, direction: float, active: bool) -> None:
        if joint not in ARM_CONTROL_LIMITS:
            raise ValueError(f"unknown arm joint: {joint}")
        direction = float(direction)
        if direction not in {-1.0, 1.0}:
            raise ValueError("joint direction must be -1 or 1")
        with self._lock:
            self._require_enabled_locked()
            if not self._arm_takeover:
                raise RuntimeError("Enable arm control before jogging a joint")
            if active:
                self._joint_expiry[joint] = (direction, time.monotonic() + self.pulse_s)
            else:
                self._joint_expiry.pop(joint, None)
            self._touch_locked()

    def stop(self) -> None:
        """Latch zero base velocity and hold the observed arm until re-enabled."""
        with self._lock:
            self._stop_latched = True
            self._enabled = False
            self._arm_takeover = True
            self._arm_targets = None
            self._clear_motion_locked()
            self._touch_locked()

    def _touch_locked(self) -> None:
        self._last_command_at = utc_now()
        self._revision += 1

    def _clear_motion_locked(self) -> None:
        self._base_expiry.clear()
        self._joint_expiry.clear()

    def _require_enabled_locked(self) -> None:
        if not self._permitted:
            raise RuntimeError(self._permit_reason)
        if not self._enabled:
            raise RuntimeError("Enable dashboard control first")
        if self._stop_latched:
            raise RuntimeError("Stop is latched; enable dashboard control to resume")

    def _fresh_base_keys_locked(self, now: float) -> set[str]:
        for key in [key for key, expiry in self._base_expiry.items() if expiry <= now]:
            del self._base_expiry[key]
        return set(self._base_expiry)

    def _base_action_locked(self, keys: set[str]) -> dict[str, float]:
        speed = self.SPEED_LEVELS[self._speed_index]
        return {
            "x.vel": speed["xy"] * (int("w" in keys) - int("s" in keys)),
            "y.vel": speed["xy"] * (int("a" in keys) - int("d" in keys)),
            "theta.vel": speed["theta"] * (int("z" in keys) - int("x" in keys)),
        }

    def apply(
        self,
        arm_action: dict[str, float],
        base_action: dict[str, float],
        observation: dict[str, Any],
        *,
        now: float | None = None,
    ) -> tuple[dict[str, float], dict[str, float]]:
        """Merge cached web intent; called synchronously by the 30 Hz owner."""
        now = time.monotonic() if now is None else now
        with self._lock:
            if self._stop_latched:
                if self._arm_targets is None:
                    self._arm_targets = {
                        name: float(observation.get(name, arm_action.get(name, 0.0)))
                        for name in ARM_CONTROL_LIMITS
                    }
                return dict(self._arm_targets), {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}

            if not self._enabled or not self._permitted:
                self._arm_targets = None
                self._last_apply_at = now
                return dict(arm_action), dict(base_action)

            keys = self._fresh_base_keys_locked(now)
            if keys:
                merged_base = self._base_action_locked(keys)
            elif self.exclusive_base:
                merged_base = {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}
            else:
                merged_base = dict(base_action)

            if not self._arm_takeover:
                self._arm_targets = None
                self._last_apply_at = now
                return dict(arm_action), merged_base

            if self._arm_targets is None:
                self._arm_targets = {
                    name: float(observation.get(name, arm_action.get(name, 0.0)))
                    for name in ARM_CONTROL_LIMITS
                }
            dt_s = 0.0 if self._last_apply_at is None else min(max(0.0, now - self._last_apply_at), 0.1)
            self._last_apply_at = now
            for joint in [
                joint for joint, (_direction, expiry) in self._joint_expiry.items() if expiry <= now
            ]:
                del self._joint_expiry[joint]
            for joint, (direction, _expiry) in self._joint_expiry.items():
                low, high = ARM_CONTROL_LIMITS[joint]
                target = self._arm_targets[joint] + direction * ARM_CONTROL_RATES[joint] * dt_s
                self._arm_targets[joint] = min(high, max(low, target))
            return dict(self._arm_targets), merged_base

    def status(self) -> dict[str, Any]:
        with self._lock:
            speed = self.SPEED_LEVELS[self._speed_index]
            return {
                "available": True,
                "permitted": self._permitted,
                "permit_reason": self._permit_reason,
                "enabled": self._enabled,
                "arm_takeover": self._arm_takeover,
                "stop_latched": self._stop_latched,
                "speed_index": self._speed_index,
                "speed_label": speed["label"],
                "xy_speed_m_s": speed["xy"],
                "theta_speed_deg_s": speed["theta"],
                "last_command_at": self._last_command_at,
                "deadman_timeout_s": self.pulse_s,
                "exclusive_base": self.exclusive_base,
                "revision": self._revision,
            }


def _empty_cached_source(role: str) -> dict[str, Any]:
    names = LEADER_NAMES if role == "leader" else FOLLOWER_NAMES
    profile = SO101_LEADER_PROFILE if role == "leader" else LEKIWI_FOLLOWER_PROFILE
    motors = []
    for index, bus_name in enumerate(names, 1):
        public = bus_name if bus_name.startswith(("arm_", "base_")) else f"arm_{bus_name}"
        motors.append(
            {
                "name": public,
                "bus_name": bus_name,
                "label": LABELS.get(public.removeprefix("arm_"), LABELS.get(public, public)),
                "id": index,
                "group": "base" if public.startswith("base_") else "arm",
                "detected": False,
                "model": "—",
                "position_raw": None,
                "position_deg": None,
                "joint_position_rad": None,
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
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "sample_mode": "embedded_control_loop",
        "source": role,
        "source_label": "Leader arm" if role == "leader" else "Follower robot",
        "connected": False,
        "demo": False,
        "serial_port": None,
        "baudrate": 1_000_000,
        "last_update": None,
        "poll_latency_ms": None,
        "overall": "offline",
        "error": "Waiting for teleoperation telemetry",
        "counts": {
            "expected": len(names),
            "detected": 0,
            "healthy": 0,
            "warning": 0,
            "critical": 0,
            "unpowered": 0,
        },
        "power": infer_power_state(False, 0, len(names)),
        "battery": estimate_battery(None),
        "motors": motors,
        "findings": [],
        "profile": {
            "key": profile.key,
            "label": profile.label,
            "expected_ids": list(profile.expected_ids),
            "voltage_band": [profile.voltage_min, profile.voltage_max],
        },
        "stale": True,
        "read_only": True,
        "odometry": {"x": 0.0, "y": 0.0, "theta": 0.0, "estimated": True, "drift_prone": True},
    }


class AggregateSnapshotProvider:
    def __init__(
        self,
        leader: SnapshotProvider,
        follower: SnapshotProvider,
        cameras: MutableCameraFrameCache | None = None,
        controls: TeleopControlBridge | None = None,
        latency: LatencyTraceRecorder | None = None,
    ):
        self.leader = leader
        self.follower = follower
        self.cameras = cameras
        self.controls = controls
        self.latency = latency

    @staticmethod
    def _control_permission(combined: dict[str, Any]) -> tuple[bool, str]:
        leader = combined["sources"]["leader"]
        follower = combined["sources"]["follower"]
        if not leader.get("connected"):
            return False, "Leader telemetry is offline."
        if not follower.get("connected") or follower.get("stale"):
            return False, "Follower telemetry is stale or offline."
        if follower.get("power", {}).get("servo_rail") != "powered":
            return False, "Follower servo power is not detected."
        if follower.get("counts", {}).get("critical", 0):
            return False, "Resolve critical follower motor faults before enabling controls."
        if follower.get("counts", {}).get("detected") != follower.get("counts", {}).get("expected"):
            return False, "All nine follower motors must be responding."
        return True, "Live teleoperation owns the motor bus; dashboard intent is ready."

    def snapshot(self) -> dict[str, Any]:
        combined = combine_snapshots(self.leader.snapshot(), self.follower.snapshot(), "embedded://zmq")
        combined["schema_version"] = SCHEMA_VERSION
        combined["protocol_version"] = PROTOCOL_VERSION
        combined["sample_mode"] = "embedded_control_loop"
        combined["read_only"] = self.controls is None
        combined["cameras"] = self.cameras.status() if self.cameras is not None else {}
        if self.controls is not None:
            permitted, reason = self._control_permission(combined)
            self.controls.set_permitted(permitted, reason)
            combined["control"] = self.controls.status()
        else:
            combined["control"] = {
                "available": False,
                "permitted": False,
                "permit_reason": "Start teleoperation to enable dashboard controls.",
                "enabled": False,
                "arm_takeover": False,
                "stop_latched": False,
            }
        return combined

    def reset_odometry(self) -> None:
        self.follower.reset_odometry()


class FollowerHostSnapshotProvider:
    """Aggregate-shaped cached state for the Pi-resident browser fallback.

    The follower host remains the only motor-bus owner.  HTTP handlers mutate
    only :class:`TeleopControlBridge`; the host loop consumes that intent and
    performs all hardware access synchronously.
    """

    def __init__(
        self,
        follower: SnapshotProvider,
        cameras: MutableCameraFrameCache,
        controls: TeleopControlBridge,
        latency: LatencyTraceRecorder | None = None,
    ):
        self.follower = follower
        self.cameras = cameras
        self.controls = controls
        self.latency = latency

    @staticmethod
    def _control_permission(follower: dict[str, Any]) -> tuple[bool, str]:
        if not follower.get("connected") or follower.get("stale"):
            return False, "Follower telemetry is stale or offline."
        if follower.get("power", {}).get("servo_rail") != "powered":
            return False, "Follower servo power is not detected."
        if follower.get("counts", {}).get("critical", 0):
            return False, "Resolve critical follower motor faults before enabling controls."
        if follower.get("counts", {}).get("detected") != follower.get("counts", {}).get("expected"):
            return False, "All nine follower motors must be responding."
        return True, "The follower owner loop is ready for dead-man browser control."

    def snapshot(self) -> dict[str, Any]:
        follower = self.follower.snapshot()
        leader = _empty_cached_source("leader")
        leader["source_label"] = "Remote leader / browser"
        leader["error"] = "Leader telemetry is available only while a remote teleop client is connected."
        combined = combine_snapshots(leader, follower, "embedded://follower-host")
        combined["schema_version"] = SCHEMA_VERSION
        combined["protocol_version"] = PROTOCOL_VERSION
        combined["sample_mode"] = "embedded_host_control_loop"
        combined["read_only"] = False
        combined["cameras"] = self.cameras.status()
        permitted, reason = self._control_permission(follower)
        self.controls.set_permitted(permitted, reason)
        combined["control"] = self.controls.status()
        return combined

    def reset_odometry(self) -> None:
        self.follower.reset_odometry()


def create_cached_app(provider: SnapshotProvider) -> Flask:
    """Create an HTTP/SSE app whose handlers only copy cached snapshots."""
    app = Flask(__name__)
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True
    app.config["snapshot_provider"] = provider

    @app.get("/")
    def index():
        return render_template("lekiwi_diagnostics.html")

    @app.get("/api/state")
    def api_state():
        return jsonify(provider.snapshot())

    @app.get("/api/stream")
    def api_stream():
        @stream_with_context
        def events():
            while True:
                yield f"event: state\ndata: {json.dumps(provider.snapshot(), separators=(',', ':'))}\n\n"
                time.sleep(1.0 / 15.0)

        return Response(
            events(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/odometry/reset")
    def api_odometry_reset():
        provider.reset_odometry()
        return jsonify({"ok": True, "state": provider.snapshot()})

    @app.get("/api/cameras/<name>/stream")
    def api_camera_stream(name: str):
        camera_cache = getattr(provider, "cameras", None)
        if camera_cache is None or name not in camera_cache.names:
            return jsonify({"ok": False, "error": f"Camera {name!r} is not available"}), 404

        try:
            requested_fps = float(request.args.get("fps", 12.0))
        except ValueError:
            requested_fps = 12.0
        stream_fps = min(15.0, max(1.0, requested_fps))

        def frames():
            revision = -1
            last_emit = 0.0
            while True:
                sample = camera_cache.wait_for_frame(name, revision, timeout_s=2.0)
                if sample is None:
                    continue
                jpeg, revision = sample
                remaining = 1.0 / stream_fps - (time.monotonic() - last_emit)
                if remaining > 0:
                    time.sleep(remaining)
                last_emit = time.monotonic()
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\nCache-Control: no-store\r\n\r\n" + jpeg + b"\r\n"
                )

        return Response(
            stream_with_context(frames()),
            mimetype="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-store, max-age=0", "X-Accel-Buffering": "no"},
        )

    def control_bridge() -> TeleopControlBridge | None:
        return getattr(provider, "controls", None)

    def control_json() -> dict[str, Any]:
        if not request.is_json or request.headers.get("X-LeKiwi-Control") != "dashboard-v1":
            raise ValueError("Dashboard control requests require same-origin JSON")
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ValueError("Invalid control request")
        return payload

    def control_result(callback: Callable[[TeleopControlBridge, dict[str, Any]], None]):
        bridge = control_bridge()
        if bridge is None:
            return jsonify({"ok": False, "error": "Start teleoperation to enable dashboard controls."}), 409
        try:
            started_ns = time.perf_counter_ns()
            payload = control_json()
            trace_wire = payload.pop("_trace", None)
            trace_context = trace_context_from_wire(trace_wire)
            if trace_context is not None:
                bridge.note_trace(trace_context.wire())
            latency = getattr(provider, "latency", None)
            if latency is not None:
                previous_browser = (
                    trace_wire.get("previous_control") if isinstance(trace_wire, dict) else None
                )
                previous_context = trace_context_from_wire(previous_browser)
                previous_rtt_ms = (
                    previous_browser.get("rtt_ms") if isinstance(previous_browser, dict) else None
                )
                if previous_context is not None and isinstance(previous_rtt_ms, (int, float)):
                    latency.record_duration(
                        "browser_control_rtt",
                        int(max(0.0, float(previous_rtt_ms)) * 1_000_000),
                        previous_context,
                        attributes={"measurement_clock": "browser.performance"},
                    )
                latency.mark(
                    "dashboard_control_received",
                    trace_context,
                    attributes={
                        "path": request.path,
                    },
                )
            # Refresh permission from cached telemetry before accepting intent.
            provider.snapshot()
            callback(bridge, payload)
            response = jsonify({"ok": True, "state": provider.snapshot()})
            if latency is not None:
                latency.record_span(
                    "dashboard_control_http",
                    started_ns,
                    time.perf_counter_ns(),
                    trace_context,
                    attributes={"path": request.path, "accepted": True},
                )
            return response
        except (RuntimeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc), "state": provider.snapshot()}), 409

    @app.post("/api/control/enable")
    def api_control_enable():
        return control_result(lambda bridge, payload: bridge.set_enabled(bool(payload.get("enabled"))))

    @app.post("/api/control/speed")
    def api_control_speed():
        return control_result(lambda bridge, payload: bridge.set_speed(int(payload.get("speed", -1))))

    @app.post("/api/control/base")
    def api_control_base():
        return control_result(
            lambda bridge, payload: bridge.pulse_base(
                str(payload.get("key", "")), bool(payload.get("active"))
            )
        )

    @app.post("/api/control/arm")
    def api_control_arm():
        return control_result(lambda bridge, payload: bridge.set_arm_takeover(bool(payload.get("enabled"))))

    @app.post("/api/control/joint")
    def api_control_joint():
        return control_result(
            lambda bridge, payload: bridge.pulse_joint(
                str(payload.get("joint", "")),
                float(payload.get("direction", 0)),
                bool(payload.get("active")),
            )
        )

    @app.post("/api/control/stop")
    def api_control_stop():
        return control_result(lambda bridge, _payload: bridge.stop())

    @app.get("/api/ports")
    def api_ports():
        state = provider.snapshot()
        return jsonify(
            {
                "ports": [],
                "selected": state.get("serial_port"),
                "remembered": state.get("serial_port"),
                "bus_owned_by": "teleoperation",
            }
        )

    @app.post("/api/connect")
    @app.post("/api/autodetect")
    @app.post("/api/disconnect")
    def api_bus_owned():
        return jsonify(
            {
                "ok": False,
                "error": "Motor bus is owned by teleoperation; this dashboard uses its embedded feed.",
                "state": provider.snapshot(),
            }
        ), 409

    @app.post("/api/follower")
    def api_follower():
        return jsonify(
            {
                "ok": True,
                "state": provider.snapshot(),
                "detail": "Follower telemetry is embedded in the ZMQ observation stream.",
            }
        )

    return app


class CachedDiagnosticsServer:
    def __init__(self, provider: SnapshotProvider, host: str, port: int):
        self.app = create_cached_app(provider)
        self.host = host
        self.port = port
        self._server: BaseWSGIServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            return
        self._server = make_server(self.host, self.port, self.app, threaded=True)
        self._thread = threading.Thread(
            target=self._server.serve_forever, name=f"lekiwi-diagnostics-{self.port}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._server = None
