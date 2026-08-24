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

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

pytest.importorskip("flask")

from lerobot.robots.lekiwi.diagnostics import (
    EXPECTED_MOTORS,
    LeKiwiDiagnostics,
    RemoteDiagnosticsProxy,
    assess_motor,
    combine_snapshots,
    create_app,
    estimate_battery,
)


def test_demo_snapshot_exposes_full_expected_topology():
    state = LeKiwiDiagnostics(demo=True).snapshot()

    assert state["connected"] is True
    assert state["demo"] is True
    assert state["read_only"] is True
    assert state["counts"] == {
        "expected": 9,
        "detected": 8,
        "healthy": 7,
        "warning": 1,
        "critical": 1,
        "unpowered": 0,
    }
    assert [motor["id"] for motor in state["motors"]] == list(range(1, 10))
    assert state["motors"][7]["severity"] == "critical"


def test_assess_motor_flags_thermal_warning():
    severity, findings = assess_motor(
        {
            "detected": True,
            "model_mismatch": False,
            "read_error": None,
            "temperature_c": 58,
            "voltage_v": 12.1,
            "status_raw": 0,
            "torque_enabled": True,
        }
    )

    assert severity == "warning"
    assert findings == ["Temperature is elevated"]


def test_state_endpoint_works_without_hardware():
    app = create_app(LeKiwiDiagnostics(demo=True))
    client = app.test_client()

    response = client.get("/api/state")

    assert response.status_code == 200
    assert response.get_json()["counts"]["expected"] == 9


def test_standalone_sse_endpoint_streams_cached_demo_state_without_hardware():
    app = create_app(LeKiwiDiagnostics(demo=True))
    response = app.test_client().get("/api/stream", buffered=False)

    first = next(response.response).decode()
    response.close()

    assert "event: state" in first
    assert '"sources"' in first


def test_combined_snapshot_keeps_overlapping_leader_and_follower_ids_distinct():
    leader = LeKiwiDiagnostics()
    leader.connected = True
    leader.latest_motors = []
    follower = LeKiwiDiagnostics()
    follower.connected = True
    follower.latest_motors = []

    for expected in EXPECTED_MOTORS:
        leader_motor = leader._empty_motor(expected)
        if expected.id <= 6:
            leader_motor.update(
                detected=True,
                model_number=777,
                model="STS3215",
                voltage_v=5.3,
                temperature_c=26,
                status_raw=0,
                torque_enabled=False,
            )
        leader.latest_motors.append(leader_motor)

        follower_motor = follower._empty_motor(expected)
        follower_motor.update(
            detected=True,
            model_number=777,
            model="STS3215",
            voltage_v=10.5,
            temperature_c=30,
            status_raw=0,
            torque_enabled=False,
        )
        follower.latest_motors.append(follower_motor)

    state = combine_snapshots(leader.snapshot(), follower.snapshot(), "http://192.0.2.10:8091/api/state")

    assert state["connected_sources"] == 2
    assert state["system_counts"]["expected"] == 15
    assert state["system_counts"]["detected"] == 15
    assert len(state["all_motors"]) == 15
    assert state["sources"]["leader"]["motors"][0]["source"] == "leader"
    assert state["sources"]["leader"]["motors"][0]["voltage_v"] == 5.3
    assert state["sources"]["leader"]["battery"]["available"] is False
    assert state["sources"]["follower"]["motors"][0]["source"] == "follower"
    assert state["sources"]["follower"]["motors"][0]["voltage_v"] == 10.5
    assert state["battery"]["voltage_v"] == 10.5
    assert state["battery"]["percent_max"] == 20


def test_offline_source_motors_keep_their_source_identity():
    state = combine_snapshots(LeKiwiDiagnostics(demo=True).snapshot())

    offline_role = "follower" if state["sources"]["leader"]["connected"] else "leader"
    assert all(motor["source"] == offline_role for motor in state["sources"][offline_role]["motors"])


def test_remote_follower_url_is_normalized():
    assert RemoteDiagnosticsProxy.normalize_url("192.0.2.10:8091") == "http://192.0.2.10:8091/api/state"


def test_remote_proxy_does_not_present_cached_data_as_live_after_feed_failure():
    proxy = RemoteDiagnosticsProxy()
    proxy.url = "http://192.0.2.10:8091/api/state"
    proxy.latest = LeKiwiDiagnostics(demo=True).snapshot()
    proxy.error = "Follower diagnostics endpoint did not respond in time"

    state = proxy.snapshot()

    assert state["connected"] is False
    assert state["counts"]["detected"] == 0
    assert state["error"] == "Follower diagnostics endpoint did not respond in time"
    assert (
        RemoteDiagnosticsProxy.normalize_url("http://192.0.2.10:8091/api/state")
        == "http://192.0.2.10:8091/api/state"
    )


def test_autodetect_endpoint_starts_a_background_attempt():
    service = LeKiwiDiagnostics(demo=True)
    service.start_autodetect = lambda: True
    client = create_app(service).test_client()

    response = client.post("/api/autodetect")

    assert response.status_code == 202
    assert response.get_json()["ok"] is True


def test_disconnect_clears_the_automatic_connection_label():
    service = LeKiwiDiagnostics()
    service.autodetect_status = "connected"
    service.autodetect_source = "remembered"

    service.disconnect()

    assert service.autodetect_status == "idle"
    assert service.autodetect_source is None


def test_complete_five_volt_arm_uses_the_leader_profile():
    service = LeKiwiDiagnostics()
    service.connected = True
    service.latest_motors = []
    for expected in EXPECTED_MOTORS:
        motor = service._empty_motor(expected)
        if expected.id <= 6:
            motor.update(
                detected=True,
                model_number=777,
                model="STS3215",
                voltage_v=5.3,
                temperature_c=26,
                status_raw=0,
                torque_enabled=False,
            )
        service.latest_motors.append(motor)

    state = service.snapshot()

    assert state["profile"]["key"] == "so101_leader_5v"
    assert state["counts"] == {
        "expected": 6,
        "detected": 6,
        "healthy": 6,
        "warning": 0,
        "critical": 0,
        "unpowered": 0,
    }
    assert all(motor["severity"] == "not_applicable" for motor in state["motors"][6:])
    assert state["findings"][0]["title"] == "No faults detected"
    assert state["findings"][0]["detail"].startswith("All 6 expected motors")


def test_partial_five_volt_arm_is_not_allowed_to_mask_a_follower_fault():
    service = LeKiwiDiagnostics()
    service.connected = True
    service.latest_motors = []
    for expected in EXPECTED_MOTORS:
        motor = service._empty_motor(expected)
        if expected.id <= 5:
            motor.update(
                detected=True,
                model_number=777,
                model="STS3215",
                voltage_v=5.3,
                temperature_c=26,
                status_raw=0,
                torque_enabled=False,
            )
        service.latest_motors.append(motor)

    state = service.snapshot()

    assert state["profile"]["key"] == "lekiwi_follower_12v"
    assert state["counts"]["expected"] == 9
    assert state["counts"]["critical"] == 9


def test_silent_connected_bus_is_reported_as_unpowered_not_nine_faults():
    service = LeKiwiDiagnostics()
    service.connected = True

    state = service.snapshot()

    assert state["power"]["usb_controller"] == "online"
    assert state["power"]["servo_rail"] == "no_power_detected"
    assert state["power"]["confidence"] == "inferred"
    assert state["counts"]["critical"] == 0
    assert state["counts"]["unpowered"] == 9
    assert {motor["severity"] for motor in state["motors"]} == {"unpowered"}
    assert state["findings"] == [
        {
            "severity": "warning",
            "title": "No servo power detected",
            "detail": "The USB controller is online, but none of the servos responded. This usually means the servo rail is switched off or disconnected; check the shared data cable too.",
        }
    ]


def test_voltage_only_battery_estimate_is_broad_and_explicitly_uncalibrated():
    estimate = estimate_battery(10.5)

    assert estimate["available"] is True
    assert (estimate["percent_min"], estimate["percent_max"]) == (0, 20)
    assert estimate["confidence"] == "low"
    assert estimate["calibrated"] is False
    assert estimate["runtime_available"] is False
    assert estimate["pack"]["capacity_wh"] == 57.72


def test_connect_endpoint_requires_a_serial_port():
    app = create_app(LeKiwiDiagnostics())
    client = app.test_client()

    response = client.post("/api/connect", json={"port": ""})

    assert response.status_code == 400
    assert "Select a serial port" in response.get_json()["error"]


def test_deep_scan_reports_a_motor_on_the_wrong_baudrate():
    service = LeKiwiDiagnostics()
    service.connected = True
    service.baudrate = 1_000_000
    service.scan_results = {500_000: [4]}
    service.scan_models = {500_000: {4: 777}}

    motor = service._read_motor(next(motor for motor in EXPECTED_MOTORS if motor.id == 4))

    assert motor["detected"] is True
    assert motor["wrong_baudrate"] is True
    assert motor["severity"] == "critical"


def test_deep_scan_polls_the_baudrate_with_the_most_expected_motors():
    selected = LeKiwiDiagnostics._choose_baudrate(
        {1_000_000: [1], 500_000: [2, 3, 4, 5, 6, 7, 8, 9]},
        preferred=1_000_000,
    )

    assert selected == 500_000


def test_poll_rescans_bus_after_servo_power_is_switched_on():
    class PoweredBus:
        def broadcast_ping(self, num_retry=1):
            return {motor.id: 777 for motor in EXPECTED_MOTORS}

    service = LeKiwiDiagnostics()
    service.connected = True
    service.bus = PoweredBus()
    service._read_motor = lambda expected: service._empty_motor(expected)

    service.poll_once()

    assert set(service.discovered_models) == set(range(1, 10))
    assert service.scan_results[1_000_000] == list(range(1, 10))


def test_successful_bus_preferences_are_remembered():
    with TemporaryDirectory() as directory:
        settings_path = Path(directory) / "settings.json"
        service = LeKiwiDiagnostics(settings_path=settings_path)

        service._save_preferences("/dev/ttyUSB7", 500_000)
        restored = LeKiwiDiagnostics(settings_path=settings_path)

        assert json.loads(settings_path.read_text())["serial_port"] == "/dev/ttyUSB7"
        assert restored.remembered_port == "/dev/ttyUSB7"
        assert restored.remembered_baudrate == 500_000


def test_autodetect_tries_remembered_bus_with_its_saved_baudrate_first():
    candidates = LeKiwiDiagnostics._autodetect_candidates(
        [
            {"device": "/dev/ttyUSB0", "plausible": True},
            {"device": "/dev/ttyACM0", "plausible": True},
        ],
        remembered_port="/dev/ttyUSB0",
        remembered_baudrate=500_000,
    )

    assert candidates[0] == {
        "device": "/dev/ttyUSB0",
        "baudrate": 500_000,
        "source": "remembered",
    }
    assert candidates[1]["device"] == "/dev/ttyACM0"


def test_autodetect_uses_the_only_plausible_usb_serial_port():
    candidates = LeKiwiDiagnostics._autodetect_candidates(
        [
            {"device": "/dev/cu.Bluetooth-Incoming-Port", "plausible": False},
            {"device": "/dev/ttyACM0", "plausible": True},
        ],
        remembered_port=None,
    )

    assert candidates == [{"device": "/dev/ttyACM0", "baudrate": 1_000_000, "source": "single_port"}]


def test_autodetect_requires_a_choice_when_multiple_unknown_adapters_exist():
    candidates = LeKiwiDiagnostics._autodetect_candidates(
        [
            {"device": "/dev/ttyUSB0", "plausible": True},
            {"device": "/dev/ttyUSB1", "plausible": True},
        ],
        remembered_port=None,
    )

    assert candidates == []
