from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass

import pytest

from lerobot.robots.lekiwi.lekiwi_client import LeKiwiClient, ProtocolCompatibilityError
from lerobot.robots.lekiwi.live_diagnostics import (
    HEALTH_REGISTERS,
    JOINT_FRAME,
    PROTOCOL_VERSION,
    BusLease,
    BusOwnedError,
    EmbeddedDiagnosticsConfig,
    FollowerHostSnapshotProvider,
    LiveDiagnosticsSampler,
    MutableCameraFrameCache,
    MutableSnapshotCache,
    TeleopControlBridge,
    calibrated_degrees_to_radians,
    create_cached_app,
    gripper_percent_to_radians,
    integrate_body_odometry,
)


@dataclass
class Calibration:
    range_min: int
    range_max: int
    drive_mode: int = 0


class FakeBus:
    def __init__(self, names):
        self.motors = dict.fromkeys(names)
        self.calibration = {
            name: Calibration(1467, 2972) if name.endswith("gripper") else Calibration(0, 4095)
            for name in names
        }
        self.reads = []

    def sync_read(self, register, names, *, normalize, num_retry):
        assert normalize is False
        assert num_retry == 2
        self.reads.append(register)
        base = {
            "Present_Voltage": 121,
            "Present_Temperature": 35,
            "Present_Current": 12,
            "Present_Load": 8,
            "Torque_Enable": 1,
            "Operating_Mode": 0,
            "Moving": 0,
            "Status": 0,
        }[register]
        return dict.fromkeys(names, base)


def test_calibrated_arm_degrees_are_authoritative_radians():
    assert calibrated_degrees_to_radians("arm_shoulder_pan", 90) == pytest.approx(math.pi / 2)
    assert calibrated_degrees_to_radians("arm_shoulder_lift", -90) == pytest.approx(0)
    assert calibrated_degrees_to_radians("arm_elbow_flex", 90) == pytest.approx(0)
    assert calibrated_degrees_to_radians("arm_wrist_flex", -90) == pytest.approx(math.pi)


def test_gripper_uses_recorded_raw_span():
    calibration = Calibration(1467, 2972)
    expected_travel = (2972 - 1467) * 2 * math.pi / 4096
    assert gripper_percent_to_radians(0, calibration) == 0
    assert gripper_percent_to_radians(100, calibration) == pytest.approx(-expected_travel)
    assert gripper_percent_to_radians(50, calibration) == pytest.approx(-expected_travel / 2)


def test_body_odometry_rotates_body_velocity_into_world():
    pose = {"x": 0.0, "y": 0.0, "theta": math.pi / 2}
    result = integrate_body_odometry(pose, {"x.vel": 1.0, "y.vel": 0.0, "theta.vel": 90}, 1.0)
    assert result["x"] == pytest.approx(0.0, abs=1e-9)
    assert result["y"] == pytest.approx(1.0)
    assert result["theta"] == pytest.approx(math.pi)


def test_sampler_integrates_continuous_wheel_angle_and_publishes_joint_radians(monkeypatch):
    names = (
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
    bus = FakeBus(names)
    clock = iter([0.0, 0.01, 1.0, 1.01])
    monkeypatch.setattr("lerobot.robots.lekiwi.live_diagnostics.time.perf_counter", lambda: next(clock))
    sampler = LiveDiagnosticsSampler(bus, EmbeddedDiagnosticsConfig("follower", "/dev/test"))
    positions = dict.fromkeys(names[:5], 0.0) | {"arm_gripper": 50.0}
    sampler.sample(
        positions,
        wheel_velocity_raw=dict.fromkeys(names[6:], 4096),
        body_velocity={"x.vel": 0, "y.vel": 0, "theta.vel": 0},
    )
    sampler.sample(
        positions,
        wheel_velocity_raw=dict.fromkeys(names[6:], 4096),
        body_velocity={"x.vel": 0, "y.vel": 0, "theta.vel": 0},
    )
    state = sampler.snapshot()
    left = next(motor for motor in state["motors"] if motor["name"] == "base_left_wheel")
    assert left["joint_position_rad"] == pytest.approx(math.pi)  # dt is capped at 0.5 s
    gripper = next(motor for motor in state["motors"] if motor["name"] == "arm_gripper")
    assert gripper["joint_position_rad"] is not None
    assert state["schema_version"] == "2.0"
    assert state["joint_frame"] == JOINT_FRAME
    assert state["sample_mode"] == "embedded_control_loop"
    assert state["pose_interval_ms"] == pytest.approx(1000.0)
    assert state["max_pose_interval_ms"] == pytest.approx(1000.0)


def test_health_registers_are_staggered_not_burst(monkeypatch):
    names = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
    bus = FakeBus(names)
    current = -0.2

    def clock():
        nonlocal current
        current += 0.2
        return current

    monkeypatch.setattr("lerobot.robots.lekiwi.live_diagnostics.time.perf_counter", clock)
    sampler = LiveDiagnosticsSampler(bus, EmbeddedDiagnosticsConfig("leader", "/dev/test"))
    for _ in range(len(HEALTH_REGISTERS)):
        sampler.sample(dict.fromkeys(names, 0.0))
    assert bus.reads == [register for register, _field, _convert in HEALTH_REGISTERS]
    assert len(bus.reads) == len(HEALTH_REGISTERS)


def test_servo_rail_transition_is_reported_without_restarting(monkeypatch):
    names = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
    bus = FakeBus(names)
    current = 0.0

    def clock():
        nonlocal current
        current += 0.01
        return current

    monkeypatch.setattr("lerobot.robots.lekiwi.live_diagnostics.time.perf_counter", clock)
    sampler = LiveDiagnosticsSampler(bus, EmbeddedDiagnosticsConfig("leader", "/dev/test"))
    sampler.sample(dict.fromkeys(names, 0.0))
    assert sampler.snapshot()["counts"]["detected"] == 6
    sampler.mark_bus_unavailable(ConnectionError("motor status packet unavailable"))
    off = sampler.snapshot()
    assert off["connected"] is True  # embedded host/controller is still alive
    assert off["counts"]["detected"] == 0
    assert off["counts"]["unpowered"] == 6
    assert off["power"]["servo_rail"] == "no_power_detected"
    sampler.sample(dict.fromkeys(names, 1.0))
    assert sampler.snapshot()["counts"]["detected"] == 6


def test_cached_feed_goes_stale_after_two_seconds(monkeypatch):
    cache = MutableSnapshotCache("follower")
    cache.publish(
        {
            "last_update": "2026-08-09T00:00:00+00:00",
            "connected": True,
            "overall": "healthy",
            "counts": {"detected": 9},
            "motors": [{"severity": "healthy"}],
        }
    )
    monkeypatch.setattr("lerobot.robots.lekiwi.live_diagnostics.time.time", lambda: 1_786_233_605.0)
    state = cache.snapshot()
    assert state["stale"] is True
    assert state["connected"] is False
    assert state["motors"][0]["severity"] == "offline"


def test_odometry_reset_is_a_persistent_visualization_origin():
    cache = MutableSnapshotCache("follower")
    base = {
        "last_update": "2099-01-01T00:00:00+00:00",
        "connected": True,
        "overall": "healthy",
        "counts": {"detected": 9},
        "motors": [],
        "odometry": {"x": 2.0, "y": 3.0, "theta": 0.5, "estimated": True},
    }
    cache.publish(base)
    cache.reset_odometry()
    reset = cache.snapshot()["odometry"]
    assert reset["x"] == pytest.approx(0.0)
    assert reset["y"] == pytest.approx(0.0)
    assert reset["theta"] == pytest.approx(0.0)
    cache.publish(base | {"odometry": {"x": 3.0, "y": 3.0, "theta": 0.5, "estimated": True}})
    state = cache.snapshot()
    assert state["odometry"]["x"] == pytest.approx(math.cos(0.5))
    assert state["odometry"]["y"] == pytest.approx(-math.sin(0.5))


def test_sse_endpoint_delivers_cached_state_without_bus_access():
    cache = MutableSnapshotCache("follower")
    app = create_cached_app(cache)
    assert app.config["TEMPLATES_AUTO_RELOAD"] is True
    assert app.jinja_env.auto_reload is True
    response = app.test_client().get("/api/stream", buffered=False)
    first = next(response.response).decode()
    response.close()
    assert "event: state" in first
    assert '"sample_mode":"embedded_control_loop"' in first


def test_cached_dashboard_rejects_serial_connect():
    app = create_cached_app(MutableSnapshotCache("leader"))
    response = app.test_client().post("/api/connect", json={"port": "/dev/test"})
    assert response.status_code == 409
    assert "owned by teleoperation" in response.get_json()["error"]


def test_bus_lease_prevents_supported_concurrent_owner(tmp_path):
    port = str(tmp_path / "serial-device")
    first = BusLease(port, "teleoperation")
    second = BusLease(port, "standalone diagnostics")
    first.acquire()
    try:
        with pytest.raises(BusOwnedError, match="owned by teleoperation"):
            second.acquire()
    finally:
        first.release()


def test_protocol_mismatch_fails_clearly():
    client = LeKiwiClient.__new__(LeKiwiClient)
    with pytest.raises(ProtocolCompatibilityError, match="matching v0.6.1"):
        client._validate_protocol([json.dumps({"_protocol": "legacy-0.3.4"}).encode()])
    client._validate_protocol([json.dumps({"_protocol": PROTOCOL_VERSION}).encode()])


def test_camera_cache_is_latest_only_and_reports_staleness():
    cache = MutableCameraFrameCache(("front", "wrist"))
    cache.publish("front", b"jpeg-one")
    first, first_revision = cache.wait_for_frame("front")
    assert first == b"jpeg-one"
    cache.publish("front", b"jpeg-two")
    second, second_revision = cache.wait_for_frame("front", first_revision)
    assert second == b"jpeg-two"
    assert second_revision == first_revision + 1
    status = cache.status()
    assert status["front"]["available"] is True
    assert status["front"]["stale"] is False
    assert status["wrist"]["available"] is False


def test_client_publishes_transport_jpegs_to_dashboard_cache():
    client = LeKiwiClient.__new__(LeKiwiClient)
    client.diagnostics_cache = MutableSnapshotCache("follower")
    client.camera_cache = MutableCameraFrameCache(("front", "wrist"))
    header = {
        "_protocol": PROTOCOL_VERSION,
        "_diagnostics": {"last_update": "2099-01-01T00:00:00+00:00"},
        "_cams": ["front", "wrist"],
        "x.vel": 0.0,
    }
    parsed = client._parse_observation([json.dumps(header).encode(), b"front-jpeg", b"wrist-jpeg"])
    assert parsed["front"] == b"front-jpeg"
    assert client.camera_cache.wait_for_frame("wrist")[0] == b"wrist-jpeg"


def test_dashboard_base_controls_are_deadman_pulses():
    bridge = TeleopControlBridge(pulse_s=0.35)
    bridge.set_permitted(True, "ready")
    bridge.set_enabled(True)
    bridge.set_speed(1)
    bridge.pulse_base("z", True)
    arm = dict.fromkeys(
        (
            "arm_shoulder_pan.pos",
            "arm_shoulder_lift.pos",
            "arm_elbow_flex.pos",
            "arm_wrist_flex.pos",
            "arm_wrist_roll.pos",
            "arm_gripper.pos",
        ),
        0.0,
    )
    now = time.monotonic()
    _arm, base = bridge.apply(arm, {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}, arm, now=now)
    assert base == {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 50.0}
    _arm, expired = bridge.apply(
        arm,
        {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0},
        arm,
        now=now + 1.0,
    )
    assert expired["theta.vel"] == 0.0


def test_follower_host_browser_base_is_exclusive_and_stops_on_release():
    bridge = TeleopControlBridge(pulse_s=0.35, exclusive_base=True)
    bridge.set_permitted(True, "ready")
    bridge.set_enabled(True)
    arm = dict.fromkeys(
        (
            "arm_shoulder_pan.pos",
            "arm_shoulder_lift.pos",
            "arm_elbow_flex.pos",
            "arm_wrist_flex.pos",
            "arm_wrist_roll.pos",
            "arm_gripper.pos",
        ),
        0.0,
    )
    now = time.monotonic()
    _arm, stopped = bridge.apply(
        arm,
        {"x.vel": 0.25, "y.vel": 0.0, "theta.vel": 0.0},
        arm,
        now=now,
    )
    assert stopped == {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}
    bridge.pulse_base("w", True)
    _arm, moving = bridge.apply(arm, stopped, arm, now=now)
    assert moving["x.vel"] > 0
    _arm, expired = bridge.apply(arm, moving, arm, now=now + 1.0)
    assert expired == {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}


def test_arm_takeover_starts_from_follower_pose_and_jogs_gradually():
    bridge = TeleopControlBridge()
    bridge.set_permitted(True, "ready")
    bridge.set_enabled(True)
    bridge.set_arm_takeover(True)
    leader = dict.fromkeys(
        (
            "arm_shoulder_pan.pos",
            "arm_shoulder_lift.pos",
            "arm_elbow_flex.pos",
            "arm_wrist_flex.pos",
            "arm_wrist_roll.pos",
            "arm_gripper.pos",
        ),
        80.0,
    )
    follower = dict.fromkeys(leader, 10.0)
    now = time.monotonic()
    held, _base = bridge.apply(leader, {"x.vel": 0, "y.vel": 0, "theta.vel": 0}, follower, now=now)
    assert held["arm_elbow_flex.pos"] == 10.0
    bridge.pulse_joint("arm_elbow_flex.pos", 1, True)
    moved, _base = bridge.apply(
        leader,
        {"x.vel": 0, "y.vel": 0, "theta.vel": 0},
        follower,
        now=now + 0.1,
    )
    assert moved["arm_elbow_flex.pos"] == pytest.approx(12.4)
    assert moved["arm_shoulder_pan.pos"] == 10.0


def test_stop_latches_zero_base_and_observed_arm_pose():
    bridge = TeleopControlBridge()
    bridge.set_permitted(True, "ready")
    bridge.set_enabled(True)
    bridge.stop()
    leader = dict.fromkeys(
        (
            "arm_shoulder_pan.pos",
            "arm_shoulder_lift.pos",
            "arm_elbow_flex.pos",
            "arm_wrist_flex.pos",
            "arm_wrist_roll.pos",
            "arm_gripper.pos",
        ),
        60.0,
    )
    follower = dict.fromkeys(leader, 15.0)
    arm, base = bridge.apply(leader, {"x.vel": 0.2, "y.vel": 0, "theta.vel": 30}, follower)
    assert set(arm.values()) == {15.0}
    assert base == {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}
    assert bridge.status()["stop_latched"] is True


class CachedControlProvider:
    def __init__(self):
        self.controls = TeleopControlBridge()
        self.controls.set_permitted(True, "ready")
        self.cameras = MutableCameraFrameCache(("front",))

    def snapshot(self):
        return {"control": self.controls.status(), "sample_mode": "embedded_control_loop"}

    def reset_odometry(self):
        pass


def test_control_endpoint_requires_same_origin_json_header():
    provider = CachedControlProvider()
    app = create_cached_app(provider)
    rejected = app.test_client().post("/api/control/enable", json={"enabled": True})
    assert rejected.status_code == 409
    accepted = app.test_client().post(
        "/api/control/enable",
        json={"enabled": True},
        headers={"X-LeKiwi-Control": "dashboard-v1"},
    )
    assert accepted.status_code == 200
    assert provider.controls.status()["enabled"] is True


def test_camera_stream_serves_cached_jpeg_without_hardware_access():
    provider = CachedControlProvider()
    provider.cameras.publish("front", b"fake-jpeg")
    app = create_cached_app(provider)
    response = app.test_client().get("/api/cameras/front/stream", buffered=False)
    first = next(response.response)
    response.close()
    assert b"Content-Type: image/jpeg" in first
    assert b"fake-jpeg" in first


class StaticFollowerProvider:
    def snapshot(self):
        return {
            "schema_version": "2.0",
            "source": "follower",
            "connected": True,
            "stale": False,
            "counts": {
                "expected": 9,
                "detected": 9,
                "healthy": 9,
                "warning": 0,
                "critical": 0,
                "unpowered": 0,
            },
            "power": {"servo_rail": "powered"},
            "motors": [],
            "odometry": {"x": 0.0, "y": 0.0, "theta": 0.0},
        }

    def reset_odometry(self):
        pass


def test_follower_host_provider_allows_control_without_opening_a_leader_bus():
    controls = TeleopControlBridge(exclusive_base=True)
    provider = FollowerHostSnapshotProvider(
        StaticFollowerProvider(),
        MutableCameraFrameCache(("front", "wrist")),
        controls,
    )
    state = provider.snapshot()
    assert state["sample_mode"] == "embedded_host_control_loop"
    assert state["sources"]["leader"]["connected"] is False
    assert state["control"]["permitted"] is True
    assert state["control"]["exclusive_base"] is True
