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

import atexit
import contextlib
import json
import logging
import time
from dataclasses import dataclass, field

import cv2
import draccus
import zmq

from .config_lekiwi import LeKiwiConfig, LeKiwiHostConfig
from .latency_tracing import (
    LatencyTraceRecorder,
    MotionResponseTracker,
    TraceContext,
    trace_context_from_wire,
)
from .lekiwi import LeKiwi
from .live_diagnostics import (
    PROTOCOL_VERSION,
    BusLease,
    CachedDiagnosticsServer,
    EmbeddedDiagnosticsConfig,
    FollowerHostSnapshotProvider,
    LiveDiagnosticsSampler,
    MutableCameraFrameCache,
    ProtocolCompatibilityError,
    TeleopControlBridge,
)


@dataclass
class LeKiwiServerConfig:
    """Configuration for the LeKiwi host script."""

    robot: LeKiwiConfig = field(default_factory=LeKiwiConfig)
    host: LeKiwiHostConfig = field(default_factory=LeKiwiHostConfig)


class LeKiwiHost:
    def __init__(self, config: LeKiwiHostConfig):
        self.zmq_context = zmq.Context()
        self.zmq_cmd_socket = self.zmq_context.socket(zmq.PULL)
        self.zmq_cmd_socket.setsockopt(zmq.CONFLATE, 1)
        self.zmq_cmd_socket.bind(f"tcp://*:{config.port_zmq_cmd}")

        self.zmq_observation_socket = self.zmq_context.socket(zmq.PUSH)
        # CONFLATE does not support multipart messages; a 2-deep send queue keeps
        # near-latest-only semantics and sheds stale observations during stalls.
        self.zmq_observation_socket.setsockopt(zmq.SNDHWM, 2)
        self.zmq_observation_socket.bind(f"tcp://*:{config.port_zmq_observations}")

        self.connection_time_s = config.connection_time_s
        self.watchdog_timeout_ms = config.watchdog_timeout_ms
        self.max_loop_freq_hz = config.max_loop_freq_hz

    def disconnect(self):
        self.zmq_observation_socket.close()
        self.zmq_cmd_socket.close()
        self.zmq_context.term()


@draccus.wrap()
def main(cfg: LeKiwiServerConfig):
    logging.info("Configuring LeKiwi")
    robot = LeKiwi(cfg.robot)
    latency = LatencyTraceRecorder(cfg.host.latency_trace_dir, role="host")
    motion_response = MotionResponseTracker(latency)

    lease = BusLease(cfg.robot.port, "LeKiwi v0.6.1 teleoperation host")
    lease.acquire()

    logging.info("Connecting LeKiwi")
    try:
        robot.connect()
    except Exception:
        lease.release()
        raise

    diagnostics_server = None
    host = None
    cleaned_up = False

    def cleanup() -> None:
        nonlocal cleaned_up
        if cleaned_up:
            return
        cleaned_up = True
        if diagnostics_server is not None:
            diagnostics_server.stop()
        with contextlib.suppress(Exception):
            robot.disconnect()
        if host is not None:
            with contextlib.suppress(Exception):
                host.disconnect()
        lease.release()
        latency.close()

    # Also covers failures while binding the HTTP/ZMQ ports after the motor
    # connection has enabled torque.
    atexit.register(cleanup)

    diagnostics = LiveDiagnosticsSampler(
        robot.bus,
        EmbeddedDiagnosticsConfig(
            role="follower",
            serial_port=cfg.robot.port,
            num_read_retries=cfg.robot.num_read_retries,
        ),
    )
    camera_cache = MutableCameraFrameCache(tuple(robot.cameras))
    dashboard_controls = TeleopControlBridge(exclusive_base=True)
    if cfg.host.diagnostics_enabled:
        dashboard = FollowerHostSnapshotProvider(
            diagnostics, camera_cache, dashboard_controls, latency=latency
        )
        diagnostics_server = CachedDiagnosticsServer(
            dashboard, cfg.host.diagnostics_host, cfg.host.diagnostics_port
        )
        diagnostics_server.start()
        logging.info(
            "Follower cached diagnostics available on http://%s:%s",
            cfg.host.diagnostics_host,
            cfg.host.diagnostics_port,
        )

    logging.info("Starting HostAgent")
    host = LeKiwiHost(cfg.host)

    last_cmd_time = time.time()
    watchdog_active = False
    last_observation = None
    last_client_action = None
    last_control_revision = dashboard_controls.status()["revision"]
    host_sequence = 0
    logging.info("Waiting for commands...")
    try:
        # Business logic
        start = time.perf_counter()
        duration = 0
        while host.connection_time_s <= 0 or duration < host.connection_time_s:
            loop_start_ns = time.perf_counter_ns()
            loop_start_time = time.time()
            client_action_pending = False
            cycle_trace: TraceContext | None = None
            host_receive_ns: int | None = None
            try:
                msg = host.zmq_cmd_socket.recv_string(zmq.NOBLOCK)
                host_receive_ns = time.perf_counter_ns()
                envelope = dict(json.loads(msg))
                received_protocol = envelope.get("_protocol")
                if received_protocol != PROTOCOL_VERSION:
                    raise ProtocolCompatibilityError(
                        "Incompatible LeKiwi host/client protocol: "
                        f"host requires {PROTOCOL_VERSION!r}, client sent {received_protocol!r}. "
                        "Start the matching v0.6.1 Mac client and Pi host together."
                    )
                if envelope.get("_kind") != "action" or not isinstance(envelope.get("action"), dict):
                    raise RuntimeError("Invalid LeKiwi command envelope")
                last_client_action = dict(envelope["action"])
                cycle_trace = trace_context_from_wire(envelope.get("_trace"))
                client_action_pending = True
                last_cmd_time = time.time()
                watchdog_active = False
            except zmq.Again:
                if not watchdog_active:
                    logging.warning("No command available")
            except ProtocolCompatibilityError:
                # A mixed v0.3.4/v0.6.1 pair must fail closed instead of
                # accepting an action with incompatible semantics.
                raise
            except Exception as e:
                logging.error("Message fetching failed: %s", e)

            host_sequence += 1
            if cycle_trace is None:
                dashboard_trace = dashboard_controls.take_trace_context()
                cycle_trace = dashboard_trace or latency.context(host_sequence)
            if host_receive_ns is not None:
                latency.mark(
                    "command_received",
                    cycle_trace,
                    monotonic_ns=host_receive_ns,
                    attributes={"source": "zmq_client"},
                )

            now = time.time()
            if (now - last_cmd_time > host.watchdog_timeout_ms / 1000) and not watchdog_active:
                logging.warning(
                    f"Command not received for more than {host.watchdog_timeout_ms} milliseconds. Stopping the base."
                )
                watchdog_active = True
                try:
                    robot.stop_base()
                except Exception as exc:
                    logging.warning("Could not stop an unavailable base bus: %s", exc)

            observation_start_ns = time.perf_counter_ns()
            try:
                last_observation = robot.get_observation()
                observation_end_ns = time.perf_counter_ns()
                latency.record_span(
                    "follower_observation_total",
                    observation_start_ns,
                    observation_end_ns,
                    cycle_trace,
                )
                motion_response.observe(last_observation, observed_ns=observation_end_ns)
                for stage, duration_ns in robot.last_performance_ns.items():
                    latency.record_duration(stage, duration_ns, cycle_trace)
                diagnostics_start_ns = time.perf_counter_ns()
                diagnostics.sample(
                    robot.last_arm_position,
                    wheel_velocity_raw=robot.last_base_wheel_velocity,
                    body_velocity=robot.last_body_velocity,
                )
                latency.record_span(
                    "diagnostics_sample",
                    diagnostics_start_ns,
                    time.perf_counter_ns(),
                    cycle_trace,
                )
            except Exception as exc:
                # The USB controller may remain online while the servo rail is
                # switched off. Keep the host alive so recovery requires no
                # process restart and expose the transition in cached telemetry.
                logging.warning("Follower motor sample unavailable: %s", exc)
                diagnostics.mark_bus_unavailable(exc)

            if last_observation is None:
                time.sleep(max(1 / host.max_loop_freq_hz, 0.01))
                duration = time.perf_counter() - start
                continue

            observed_arm = {
                key: float(value)
                for key, value in last_observation.items()
                if key.startswith("arm_") and key.endswith(".pos")
            }
            zero_base = {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}
            client_is_fresh = (
                last_client_action is not None
                and time.time() - last_cmd_time <= host.watchdog_timeout_ms / 1000
            )
            baseline = dict(last_client_action) if client_is_fresh else {**observed_arm, **zero_base}
            arm_action = {key: value for key, value in baseline.items() if key.endswith(".pos")}
            base_action = {key: value for key, value in baseline.items() if key.endswith(".vel")}
            control_status = dashboard_controls.status()
            control_changed = control_status["revision"] != last_control_revision
            control_active = control_status["enabled"] or control_status["stop_latched"]
            if client_action_pending or control_active or control_changed:
                control_start_ns = time.perf_counter_ns()
                arm_action, base_action = dashboard_controls.apply(
                    arm_action,
                    base_action,
                    last_observation,
                )
                latency.record_span(
                    "control_merge",
                    control_start_ns,
                    time.perf_counter_ns(),
                    cycle_trace,
                    attributes={
                        "dashboard_active": control_active,
                        "client_action_pending": client_action_pending,
                    },
                )
                motor_write_start_ns = time.perf_counter_ns()
                applied_action = {**arm_action, **base_action}
                robot.send_action(applied_action)
                motor_write_end_ns = time.perf_counter_ns()
                latency.record_span(
                    "motor_write",
                    motor_write_start_ns,
                    motor_write_end_ns,
                    cycle_trace,
                )
                motion_response.start(
                    cycle_trace,
                    applied_action,
                    last_observation,
                    written_ns=motor_write_end_ns,
                )
                last_control_revision = dashboard_controls.status()["revision"]
                if control_active:
                    last_cmd_time = time.time()
                    watchdog_active = False

            # Send one multipart message: a JSON header frame (state + camera
            # order) followed by one raw JPEG frame per camera. Raw JPEG avoids
            # the 33% base64 inflation of embedding binary data in JSON.
            cam_keys = list(robot.cameras.keys())
            observation_to_send = dict(last_observation)
            jpeg_frames = []
            encode_start_ns = time.perf_counter_ns()
            for cam_key in cam_keys:
                camera_encode_start_ns = time.perf_counter_ns()
                ret, jpeg = cv2.imencode(
                    ".jpg", observation_to_send.pop(cam_key), [int(cv2.IMWRITE_JPEG_QUALITY), 90]
                )
                encoded = bytes(jpeg) if ret else b""
                jpeg_frames.append(encoded)
                if encoded:
                    camera_cache.publish(cam_key, encoded)
                latency.record_span(
                    f"camera_encode.{cam_key}",
                    camera_encode_start_ns,
                    time.perf_counter_ns(),
                    cycle_trace,
                    attributes={"jpeg_bytes": len(encoded)},
                )
            latency.record_span(
                "camera_encode_total", encode_start_ns, time.perf_counter_ns(), cycle_trace
            )
            host_send_start_ns = time.perf_counter_ns()
            host_pipeline_ns = (
                host_send_start_ns - host_receive_ns if host_receive_ns is not None else None
            )
            header = {
                "_protocol": PROTOCOL_VERSION,
                "_diagnostics": diagnostics.snapshot(),
                "_cams": cam_keys,
                "_trace": cycle_trace.wire(
                    host_pipeline_ns=host_pipeline_ns,
                    host_send_wall_ns=time.time_ns(),
                ),
                **observation_to_send,
            }

            # Send the observation to the remote agent
            try:
                host.zmq_observation_socket.send_multipart(
                    [json.dumps(header).encode()] + jpeg_frames, flags=zmq.NOBLOCK
                )
            except zmq.Again:
                logging.info("Dropping observation, no client connected")
            latency.record_span(
                "observation_serialize_send",
                host_send_start_ns,
                time.perf_counter_ns(),
                cycle_trace,
                attributes={"camera_count": len(jpeg_frames)},
            )

            # Ensure a short sleep to avoid overloading the CPU.
            elapsed = time.time() - loop_start_time

            latency.record_span("control_loop", loop_start_ns, time.perf_counter_ns(), cycle_trace)

            time.sleep(max(1 / host.max_loop_freq_hz - elapsed, 0))
            duration = time.perf_counter() - start
        print("Cycle time reached.")

    except KeyboardInterrupt:
        print("Keyboard interrupt received. Exiting...")
    finally:
        print("Shutting down Lekiwi Host.")
        cleanup()

    logging.info("Finished LeKiwi cleanly")


if __name__ == "__main__":
    main()
