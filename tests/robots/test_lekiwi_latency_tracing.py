from __future__ import annotations

import json
import sqlite3
import time
from collections import OrderedDict

from lerobot.robots.lekiwi.latency_tracing import (
    TRACE_SCHEMA_VERSION,
    LatencyTraceRecorder,
    MotionResponseTracker,
    TraceContext,
    export_sqlite,
    load_records,
    summarize,
    trace_context_from_wire,
)
from lerobot.robots.lekiwi.lekiwi_client import LeKiwiClient
from lerobot.robots.lekiwi.live_diagnostics import (
    PROTOCOL_VERSION,
    MutableCameraFrameCache,
    MutableSnapshotCache,
    TeleopControlBridge,
    create_cached_app,
)


def test_trace_context_round_trips_over_wire():
    context = TraceContext("trace-1", "session-1", 42)
    parsed = trace_context_from_wire(context.wire(client_send_wall_ns=123))
    assert parsed == context


def test_recorder_batches_jsonl_and_closes_cleanly(tmp_path):
    recorder = LatencyTraceRecorder(
        tmp_path,
        role="client",
        node="test-node",
        session_id="session-1",
        batch_size=32,
        flush_interval_s=60,
    )
    context = TraceContext("trace-1", "session-1", 1)
    with recorder.span("leader_motor_read", context):
        time.sleep(0.001)
    recorder.close()

    records = load_records([tmp_path])
    assert {record["name"] for record in records} >= {
        "trace.session_start",
        "leader_motor_read",
        "trace.session_end",
    }
    span = next(record for record in records if record["name"] == "leader_motor_read")
    assert span["record_type"] == "span"
    assert span["duration_ns"] > 0


def test_report_identifies_highest_p95_stage_and_exports_sqlite(tmp_path):
    def span(name: str, duration_ms: float, trace_id: str, role: str) -> dict:
        return {
            "schema_version": TRACE_SCHEMA_VERSION,
            "record_type": "span",
            "session_id": "session-1",
            "trace_id": trace_id,
            "sequence": 1,
            "node": role,
            "role": role,
            "name": name,
            "wall_time_ns": 1,
            "start_monotonic_ns": 1,
            "end_monotonic_ns": 1 + int(duration_ms * 1_000_000),
            "duration_ns": int(duration_ms * 1_000_000),
            "attributes": {},
        }

    records = [
        span("camera_encode.front", 20, "shared", "host"),
        span("camera_encode.front", 30, "host-only", "host"),
        span("camera_decode", 5, "shared", "client"),
    ]
    report = summarize(records)
    assert report["likely_bottleneck"] == "host.camera_encode.front"
    assert report["cross_node_trace_count"] == 1

    database_path = export_sqlite(records, tmp_path / "latency.sqlite")
    with sqlite3.connect(database_path) as database:
        assert database.execute("SELECT COUNT(*) FROM latency_records").fetchone()[0] == 3


def test_dashboard_trace_is_consumed_once_by_owner_loop():
    bridge = TeleopControlBridge()
    bridge.note_trace({"trace_id": "browser-1", "session_id": "browser-session", "sequence": 7})
    assert bridge.take_trace_context() == TraceContext("browser-1", "browser-session", 7)
    assert bridge.take_trace_context() is None


def test_client_correlates_command_with_host_pipeline_and_network_residual(tmp_path):
    client = LeKiwiClient.__new__(LeKiwiClient)
    client.latency = LatencyTraceRecorder(tmp_path, role="client", node="test-client", session_id="session-1")
    client.diagnostics_cache = MutableSnapshotCache("follower")
    client.camera_cache = MutableCameraFrameCache(())
    client._latest_trace_context = None
    context = TraceContext("trace-1", "session-1", 1)
    sent_ns = time.perf_counter_ns() - 10_000_000
    client._latency_outstanding = OrderedDict({context.trace_id: (sent_ns, context)})
    header = {
        "_protocol": PROTOCOL_VERSION,
        "_diagnostics": {},
        "_cams": [],
        "_trace": context.wire(host_pipeline_ns=4_000_000),
        "x.vel": 0.0,
    }
    assert (
        client._parse_observation([json.dumps(header).encode()], received_monotonic_ns=sent_ns + 10_000_000)
        is not None
    )
    client.latency.close()
    names = {record["name"] for record in load_records([tmp_path])}
    assert {
        "command_to_observation_rtt",
        "remote_host_pipeline",
        "network_queue_residual",
    }.issubset(names)


def test_loader_rejects_malformed_trace_json(tmp_path):
    trace_path = tmp_path / "bad.jsonl"
    trace_path.write_text(json.dumps({"schema_version": TRACE_SCHEMA_VERSION}) + "\nnot-json\n")
    try:
        load_records([trace_path])
    except ValueError as exc:
        assert "bad.jsonl:2" in str(exc)
    else:
        raise AssertionError("malformed JSONL should fail with a line number")


def test_motion_response_is_measured_from_existing_feedback_only(tmp_path):
    recorder = LatencyTraceRecorder(tmp_path, role="host", node="test-host", session_id="session-1")
    tracker = MotionResponseTracker(recorder)
    context = TraceContext("motion-1", "session-1", 1)
    baseline = {"arm_elbow_flex.pos": 10.0, "x.vel": 0.0}
    assert tracker.start(
        context,
        {"arm_elbow_flex.pos": 20.0, "x.vel": 0.0},
        baseline,
        written_ns=1_000_000_000,
    )
    assert not tracker.observe({"arm_elbow_flex.pos": 10.1, "x.vel": 0.0}, observed_ns=1_010_000_000)
    assert tracker.observe({"arm_elbow_flex.pos": 10.5, "x.vel": 0.0}, observed_ns=1_020_000_000)
    recorder.close()
    span = next(
        record for record in load_records([tmp_path]) if record["name"] == "command_to_observed_motion"
    )
    assert span["duration_ns"] == 20_000_000
    assert span["attributes"]["sampling_upper_bound"] is True


def test_motion_probe_ignores_an_unchanged_target(tmp_path):
    recorder = LatencyTraceRecorder(tmp_path, role="host")
    tracker = MotionResponseTracker(recorder)
    assert not tracker.start(
        TraceContext("motion-2", recorder.session_id, 1),
        {"arm_elbow_flex.pos": 10.1, "x.vel": 0.0},
        {"arm_elbow_flex.pos": 10.0, "x.vel": 0.0},
    )
    recorder.close()


def test_browser_round_trip_is_flushed_on_the_next_control_request(tmp_path):
    class Provider:
        def __init__(self):
            self.controls = TeleopControlBridge()
            self.controls.set_permitted(True, "ready")
            self.latency = LatencyTraceRecorder(
                tmp_path, role="host", node="test-host", session_id="host-session"
            )

        def snapshot(self):
            return {"control": self.controls.status()}

        def reset_odometry(self):
            pass

    provider = Provider()
    app = create_cached_app(provider)
    previous = {"trace_id": "browser-1", "session_id": "browser-session", "sequence": 1}
    current = {
        "trace_id": "browser-2",
        "session_id": "browser-session",
        "sequence": 2,
        "previous_control": {**previous, "rtt_ms": 42.5},
    }
    response = app.test_client().post(
        "/api/control/enable",
        json={"enabled": True, "_trace": current},
        headers={"X-LeKiwi-Control": "dashboard-v1"},
    )
    assert response.status_code == 200
    provider.latency.close()
    span = next(record for record in load_records([tmp_path]) if record["name"] == "browser_control_rtt")
    assert span["trace_id"] == "browser-1"
    assert span["duration_ns"] == 42_500_000
