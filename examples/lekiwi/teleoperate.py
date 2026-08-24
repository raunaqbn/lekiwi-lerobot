#!/usr/bin/env python
"""Low-latency LeKiwi teleoperation with the live diagnostics dashboard."""

from __future__ import annotations

import argparse
import atexit
import os
import select
import sys
import termios
import time
import tty

import rerun as rr
import rerun.blueprint as rrb

from lerobot.robots.lekiwi import LeKiwiClient, LeKiwiClientConfig
from lerobot.robots.lekiwi.live_diagnostics import (
    AggregateSnapshotProvider,
    BusLease,
    CachedDiagnosticsServer,
    EmbeddedDiagnosticsConfig,
    LiveDiagnosticsSampler,
    TeleopControlBridge,
)
from lerobot.teleoperators.keyboard.teleop_keyboard import KeyboardTeleop, KeyboardTeleopConfig
from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig
from lerobot.utils.visualization_utils import init_rerun, log_rerun_data

FPS = 30
DEFAULT_PI = os.getenv("LEKIWI_HOST", "lekiwi.local")
DEFAULT_LEADER_PORT = os.getenv("LEKIWI_LEADER_PORT")


class TerminalPulseKeyboard:
    """macOS Terminal key backend with release-by-expiry semantics."""

    def __init__(self, pulse_s: float = 0.35):
        if not sys.stdin.isatty():
            raise RuntimeError("Terminal keyboard control needs an interactive Terminal window")
        self.fd = sys.stdin.fileno()
        self.original = termios.tcgetattr(self.fd)
        self.expiry: dict[str, float] = {}
        self.controls = set("wasdzxrf")
        self.pulse_s = pulse_s
        self.connected = False

    def connect(self) -> None:
        tty.setcbreak(self.fd)
        self.connected = True

    def get_action(self) -> dict[str, None]:
        now = time.perf_counter()
        while select.select([self.fd], [], [], 0)[0]:
            chars = os.read(self.fd, 64).decode(errors="ignore").lower()
            for char in chars:
                if char in self.controls:
                    self.expiry[char] = now + self.pulse_s
        for key in [key for key, expiry in self.expiry.items() if expiry <= now]:
            del self.expiry[key]
        return dict.fromkeys(self.expiry)

    def disconnect(self) -> None:
        if self.connected:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.original)
            self.connected = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Teleoperate LeKiwi v0.6.1 with live diagnostics")
    parser.add_argument("--pi", default=DEFAULT_PI, help="Raspberry Pi address")
    parser.add_argument(
        "--leader-port",
        default=DEFAULT_LEADER_PORT,
        required=DEFAULT_LEADER_PORT is None,
        help="Leader arm serial port (or set LEKIWI_LEADER_PORT)",
    )
    parser.add_argument("--robot-id", default=os.getenv("LEKIWI_ROBOT_ID", "lekiwi"))
    parser.add_argument("--dashboard-host", default="127.0.0.1")
    parser.add_argument("--dashboard-port", type=int, default=8090)
    parser.add_argument("--no-rerun", action="store_true")
    parser.add_argument("--no-pynput", action="store_true", help="Use only focused-Terminal key pulses")
    parser.add_argument(
        "--latency-trace-dir",
        help="Batch session traces to local JSONL here; no live database writes",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    robot = LeKiwiClient(
        LeKiwiClientConfig(
            remote_ip=args.pi,
            id=args.robot_id,
            latency_trace_dir=args.latency_trace_dir,
        )
    )
    leader_arm = SO101Leader(
        SO101LeaderConfig(port=args.leader_port, id=args.robot_id, use_degrees=True, num_read_retries=2)
    )
    pynput_keyboard = None if args.no_pynput else KeyboardTeleop(KeyboardTeleopConfig(id="terminal_keyboard"))
    terminal_keyboard = TerminalPulseKeyboard(0.35)
    leader_lease = BusLease(args.leader_port, "LeKiwi v0.6.1 Mac teleoperation")
    diagnostics_server: CachedDiagnosticsServer | None = None
    dashboard_controls = TeleopControlBridge()

    try:
        leader_lease.acquire()
        robot.connect()
        leader_arm.connect()
        terminal_keyboard.connect()
        atexit.register(terminal_keyboard.disconnect)
        if pynput_keyboard is not None:
            pynput_keyboard.connect()

        leader_diagnostics = LiveDiagnosticsSampler(
            leader_arm.bus,
            EmbeddedDiagnosticsConfig(
                role="leader",
                serial_port=args.leader_port,
                num_read_retries=leader_arm.config.num_read_retries,
            ),
        )
        aggregate = AggregateSnapshotProvider(
            leader_diagnostics,
            robot.diagnostics_cache,
            cameras=robot.camera_cache,
            controls=dashboard_controls,
            latency=robot.latency,
        )
        diagnostics_server = CachedDiagnosticsServer(aggregate, args.dashboard_host, args.dashboard_port)
        diagnostics_server.start()

        if not args.no_rerun:
            init_rerun(session_name="lekiwi_v061_teleop")
            rr.send_blueprint(
                rrb.Blueprint(
                    rrb.Grid(
                        rrb.Spatial2DView(origin="/observation.front", name="Base camera"),
                        rrb.Spatial2DView(origin="/observation.wrist", name="Wrist camera"),
                        grid_columns=2,
                    )
                )
            )

        print(
            f"Teleoperation ready. Dashboard: http://{args.dashboard_host}:{args.dashboard_port}\n"
            "Controls: W/S forward/back · A/D strafe · Z/X rotate · R/F speed · Ctrl+C stop\n"
            "The dashboard now includes dead-man base controls, arm jogging, and both camera feeds.",
            flush=True,
        )

        while True:
            started_ns = time.perf_counter_ns()
            started = time.perf_counter()
            observation_start_ns = time.perf_counter_ns()
            observation = robot.get_observation()
            robot.latency.record_span(
                "observation_api",
                observation_start_ns,
                time.perf_counter_ns(),
                robot._latest_trace_context,
            )

            leader_start_ns = time.perf_counter_ns()
            leader_action = leader_arm.get_action()
            robot.latency.record_span(
                "leader_motor_read",
                leader_start_ns,
                time.perf_counter_ns(),
                robot._latest_trace_context,
            )
            leader_positions = {
                key.removesuffix(".pos"): float(value)
                for key, value in leader_action.items()
                if key.endswith(".pos")
            }
            leader_diagnostics.sample(leader_positions)
            arm_action = {f"arm_{key}": value for key, value in leader_action.items()}

            keyboard_keys: dict[str, None] = {}
            if pynput_keyboard is not None:
                keyboard_keys.update(pynput_keyboard.get_action())
            keyboard_keys.update(terminal_keyboard.get_action())
            base_action = robot._from_keyboard_to_base_action(keyboard_keys)
            arm_action, base_action = dashboard_controls.apply(
                arm_action,
                base_action,
                observation,
            )
            action = {**arm_action, **base_action}

            if not args.no_rerun:
                rerun_start_ns = time.perf_counter_ns()
                log_rerun_data(observation, action)
                robot.latency.record_span(
                    "rerun_log",
                    rerun_start_ns,
                    time.perf_counter_ns(),
                    robot._latest_trace_context,
                )
            robot.send_action(action)
            robot.latency.record_span(
                "teleop_loop",
                started_ns,
                time.perf_counter_ns(),
                robot._latest_trace_context,
            )
            time.sleep(max(1.0 / FPS - (time.perf_counter() - started), 0.0))
    except KeyboardInterrupt:
        print("\nStopping teleoperation cleanly…", flush=True)
    finally:
        if diagnostics_server is not None:
            diagnostics_server.stop()
        terminal_keyboard.disconnect()
        if pynput_keyboard is not None and pynput_keyboard.is_connected:
            pynput_keyboard.disconnect()
        if leader_arm.is_connected:
            leader_arm.disconnect()
        if robot.is_connected:
            robot.disconnect()
        leader_lease.release()


if __name__ == "__main__":
    main()
