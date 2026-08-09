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
from .lekiwi import LeKiwi
from .live_diagnostics import (
    PROTOCOL_VERSION,
    BusLease,
    CachedDiagnosticsServer,
    EmbeddedDiagnosticsConfig,
    LiveDiagnosticsSampler,
    ProtocolCompatibilityError,
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
    if cfg.host.diagnostics_enabled:
        diagnostics_server = CachedDiagnosticsServer(
            diagnostics, cfg.host.diagnostics_host, cfg.host.diagnostics_port
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
    logging.info("Waiting for commands...")
    try:
        # Business logic
        start = time.perf_counter()
        duration = 0
        while host.connection_time_s <= 0 or duration < host.connection_time_s:
            loop_start_time = time.time()
            try:
                msg = host.zmq_cmd_socket.recv_string(zmq.NOBLOCK)
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
                _action_sent = robot.send_action(envelope["action"])
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

            try:
                last_observation = robot.get_observation()
                diagnostics.sample(
                    robot.last_arm_position,
                    wheel_velocity_raw=robot.last_base_wheel_velocity,
                    body_velocity=robot.last_body_velocity,
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

            # Send one multipart message: a JSON header frame (state + camera
            # order) followed by one raw JPEG frame per camera. Raw JPEG avoids
            # the 33% base64 inflation of embedding binary data in JSON.
            cam_keys = list(robot.cameras.keys())
            observation_to_send = dict(last_observation)
            jpeg_frames = []
            for cam_key in cam_keys:
                ret, jpeg = cv2.imencode(
                    ".jpg", observation_to_send.pop(cam_key), [int(cv2.IMWRITE_JPEG_QUALITY), 90]
                )
                jpeg_frames.append(jpeg if ret else b"")
            header = {
                "_protocol": PROTOCOL_VERSION,
                "_diagnostics": diagnostics.snapshot(),
                "_cams": cam_keys,
                **observation_to_send,
            }

            # Send the observation to the remote agent
            try:
                host.zmq_observation_socket.send_multipart(
                    [json.dumps(header).encode()] + jpeg_frames, flags=zmq.NOBLOCK
                )
            except zmq.Again:
                logging.info("Dropping observation, no client connected")

            # Ensure a short sleep to avoid overloading the CPU.
            elapsed = time.time() - loop_start_time

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
