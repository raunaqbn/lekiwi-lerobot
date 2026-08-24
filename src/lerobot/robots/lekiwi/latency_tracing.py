#!/usr/bin/env python

"""Non-blocking, session-scoped latency tracing for LeKiwi.

The control loop only puts compact dictionaries into a bounded in-memory queue.
A daemon thread writes newline-delimited JSON in batches.  Database loading and
percentile analysis intentionally happen after teleoperation has stopped.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import queue
import socket
import sqlite3
import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TRACE_SCHEMA_VERSION = "lekiwi-latency-v1"
logger = logging.getLogger(__name__)

AGGREGATE_STAGES = frozenset(
    {
        "client.command_to_observation_rtt",
        "client.observation_api",
        "client.remote_host_pipeline",
        "client.teleop_loop",
        "host.camera_encode_total",
        "host.control_loop",
        "host.follower_observation_total",
    }
)


def new_session_id() -> str:
    return f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"


def new_trace_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    session_id: str
    sequence: int | None = None

    def wire(self, **extra: Any) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "sequence": self.sequence,
            **extra,
        }


class LatencyTraceRecorder:
    """Bounded, non-blocking JSONL trace recorder.

    When ``directory`` is ``None``, all methods are cheap no-ops.  A full queue
    drops records instead of ever delaying control or camera work.
    """

    def __init__(
        self,
        directory: str | Path | None,
        *,
        role: str,
        node: str | None = None,
        session_id: str | None = None,
        queue_size: int = 8192,
        batch_size: int = 128,
        flush_interval_s: float = 1.0,
    ):
        self.role = role
        self.node = node or socket.gethostname()
        self.session_id = session_id or new_session_id()
        self.batch_size = max(1, int(batch_size))
        self.flush_interval_s = max(0.05, float(flush_interval_s))
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=max(1, queue_size))
        self._dropped = 0
        self._drop_lock = threading.Lock()
        self._closed = False
        self.path: Path | None = None
        self._thread: threading.Thread | None = None

        if directory is not None:
            output_dir = Path(directory).expanduser()
            output_dir.mkdir(parents=True, exist_ok=True)
            safe_node = "".join(char if char.isalnum() or char in "-_" else "-" for char in self.node)
            self.path = output_dir / f"{self.session_id}.{self.role}.{safe_node}.jsonl"
            self._thread = threading.Thread(
                target=self._writer,
                name=f"lekiwi-latency-{role}",
                daemon=True,
            )
            self._thread.start()
            self.mark("trace.session_start", attributes={"path": str(self.path)})

    @property
    def enabled(self) -> bool:
        return self.path is not None and not self._closed

    @property
    def dropped_records(self) -> int:
        with self._drop_lock:
            return self._dropped

    def context(self, sequence: int | None = None, *, session_id: str | None = None) -> TraceContext:
        return TraceContext(new_trace_id(), session_id or self.session_id, sequence)

    def _enqueue(self, record: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            with self._drop_lock:
                self._dropped += 1

    def mark(
        self,
        name: str,
        context: TraceContext | None = None,
        *,
        attributes: dict[str, Any] | None = None,
        monotonic_ns: int | None = None,
        wall_time_ns: int | None = None,
    ) -> None:
        if not self.enabled:
            return
        self._enqueue(
            {
                "schema_version": TRACE_SCHEMA_VERSION,
                "record_type": "event",
                "session_id": context.session_id if context else self.session_id,
                "trace_id": context.trace_id if context else None,
                "sequence": context.sequence if context else None,
                "node": self.node,
                "role": self.role,
                "name": name,
                "monotonic_ns": monotonic_ns if monotonic_ns is not None else time.perf_counter_ns(),
                "wall_time_ns": wall_time_ns if wall_time_ns is not None else time.time_ns(),
                "attributes": attributes or {},
            }
        )

    def record_span(
        self,
        name: str,
        start_ns: int,
        end_ns: int,
        context: TraceContext | None = None,
        *,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        self._enqueue(
            {
                "schema_version": TRACE_SCHEMA_VERSION,
                "record_type": "span",
                "session_id": context.session_id if context else self.session_id,
                "trace_id": context.trace_id if context else None,
                "sequence": context.sequence if context else None,
                "node": self.node,
                "role": self.role,
                "name": name,
                "start_monotonic_ns": int(start_ns),
                "end_monotonic_ns": int(end_ns),
                "duration_ns": max(0, int(end_ns) - int(start_ns)),
                "wall_time_ns": time.time_ns(),
                "attributes": attributes or {},
            }
        )

    def record_duration(
        self,
        name: str,
        duration_ns: int,
        context: TraceContext | None = None,
        *,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        end_ns = time.perf_counter_ns()
        self.record_span(name, end_ns - max(0, int(duration_ns)), end_ns, context, attributes=attributes)

    @contextlib.contextmanager
    def span(
        self,
        name: str,
        context: TraceContext | None = None,
        *,
        attributes: dict[str, Any] | None = None,
    ) -> Iterator[None]:
        start_ns = time.perf_counter_ns()
        try:
            yield
        finally:
            self.record_span(name, start_ns, time.perf_counter_ns(), context, attributes=attributes)

    def close(self, timeout_s: float = 3.0) -> None:
        if self.path is None or self._closed:
            return
        self.mark("trace.session_end", attributes={"dropped_records": self.dropped_records})
        self._closed = True
        # The writer also observes ``_closed`` after draining a batch.
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait(None)
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, timeout_s))

    def _writer(self) -> None:
        assert self.path is not None
        batch: list[dict[str, Any]] = []
        last_flush = time.monotonic()
        try:
            with self.path.open("a", encoding="utf-8", buffering=1) as output:
                while True:
                    timeout = max(0.0, self.flush_interval_s - (time.monotonic() - last_flush))
                    try:
                        item = self._queue.get(timeout=timeout)
                    except queue.Empty:
                        item = None if self._closed else {}

                    if item is None:
                        while True:
                            try:
                                remaining = self._queue.get_nowait()
                            except queue.Empty:
                                break
                            if remaining is not None:
                                batch.append(remaining)
                        if batch:
                            self._write_batch(output, batch)
                        return
                    if item:
                        batch.append(item)
                    if batch and (
                        len(batch) >= self.batch_size
                        or time.monotonic() - last_flush >= self.flush_interval_s
                    ):
                        self._write_batch(output, batch)
                        batch.clear()
                        last_flush = time.monotonic()
        except Exception:
            logger.exception("LeKiwi latency writer failed for %s", self.path)

    @staticmethod
    def _write_batch(output, batch: list[dict[str, Any]]) -> None:
        output.writelines(json.dumps(record, separators=(",", ":")) + "\n" for record in batch)
        output.flush()


class MotionResponseTracker:
    """Measure command-write to the next observed movement without extra reads.

    The result is an upper bound: motion may begin between two 30 Hz feedback
    samples. Repeated commands that do not materially change a target are
    ignored so steady movement does not manufacture response samples.
    """

    def __init__(self, recorder: LatencyTraceRecorder, timeout_s: float = 2.0):
        self.recorder = recorder
        self.timeout_ns = int(timeout_s * 1_000_000_000)
        self._pending: dict[str, Any] | None = None

    @staticmethod
    def _threshold(key: str) -> float:
        if key == "theta.vel":
            return 3.0
        if key.endswith(".vel"):
            return 0.01
        return 0.35

    def start(
        self,
        context: TraceContext,
        action: dict[str, float],
        observation: dict[str, Any],
        *,
        written_ns: int | None = None,
    ) -> bool:
        if not self.recorder.enabled:
            return False
        if self._pending is not None:
            return False
        expected: dict[str, dict[str, float]] = {}
        for key, target_value in action.items():
            if not (key.endswith(".pos") or key.endswith(".vel")):
                continue
            baseline_value = observation.get(key)
            if baseline_value is None:
                continue
            target = float(target_value)
            baseline = float(baseline_value)
            delta = target - baseline
            if abs(delta) < self._threshold(key):
                continue
            expected[key] = {
                "baseline": baseline,
                "target": target,
                "direction": 1.0 if delta > 0 else -1.0,
            }
        if not expected:
            return False
        self._pending = {
            "context": context,
            "written_ns": written_ns if written_ns is not None else time.perf_counter_ns(),
            "expected": expected,
        }
        return True

    def observe(self, observation: dict[str, Any], *, observed_ns: int | None = None) -> bool:
        if not self.recorder.enabled:
            return False
        if self._pending is None:
            return False
        now_ns = observed_ns if observed_ns is not None else time.perf_counter_ns()
        written_ns = int(self._pending["written_ns"])
        expected: dict[str, dict[str, float]] = self._pending["expected"]
        responding = []
        for key, target in expected.items():
            current_value = observation.get(key)
            if current_value is None:
                continue
            movement = (float(current_value) - target["baseline"]) * target["direction"]
            if movement >= self._threshold(key):
                responding.append(key)
        if responding:
            self.recorder.record_span(
                "command_to_observed_motion",
                written_ns,
                now_ns,
                self._pending["context"],
                attributes={
                    "responding_fields": responding,
                    "sampling_upper_bound": True,
                },
            )
            self._pending = None
            return True
        if now_ns - written_ns >= self.timeout_ns:
            self.recorder.mark(
                "command_motion_timeout",
                self._pending["context"],
                attributes={"expected_fields": sorted(expected)},
                monotonic_ns=now_ns,
            )
            self._pending = None
        return False


def trace_context_from_wire(value: Any) -> TraceContext | None:
    if not isinstance(value, dict) or not value.get("trace_id") or not value.get("session_id"):
        return None
    sequence = value.get("sequence")
    return TraceContext(
        str(value["trace_id"]), str(value["session_id"]), int(sequence) if sequence is not None else None
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def load_records(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        files = sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
        for file_path in files:
            with file_path.open(encoding="utf-8") as source:
                for line_number, line in enumerate(source, 1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"Invalid JSON in {file_path}:{line_number}") from exc
                    if record.get("schema_version") == TRACE_SCHEMA_VERSION:
                        records.append(record)
    return records


def summarize(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    durations: dict[str, list[float]] = defaultdict(list)
    trace_nodes: dict[str, set[str]] = defaultdict(set)
    dropped = 0
    for record in records:
        trace_id = record.get("trace_id")
        if trace_id:
            trace_nodes[str(trace_id)].add(str(record.get("role", "unknown")))
        if record.get("record_type") == "span":
            key = f"{record.get('role', 'unknown')}.{record.get('name', 'unknown')}"
            durations[key].append(float(record.get("duration_ns", 0)) / 1_000_000.0)
        if record.get("name") == "trace.session_end":
            dropped += int(record.get("attributes", {}).get("dropped_records", 0))

    stages = []
    for name, values in durations.items():
        stage = {
            "stage": name,
            "kind": "aggregate" if name in AGGREGATE_STAGES else "component",
            "count": len(values),
            "p50_ms": round(_percentile(values, 0.50), 3),
            "p95_ms": round(_percentile(values, 0.95), 3),
            "p99_ms": round(_percentile(values, 0.99), 3),
            "max_ms": round(max(values), 3),
            "mean_ms": round(sum(values) / len(values), 3),
        }
        stages.append(stage)
    stages.sort(key=lambda item: item["p95_ms"], reverse=True)
    rtt = next((stage for stage in stages if stage["stage"] == "client.command_to_observation_rtt"), None)
    if rtt and rtt["p95_ms"] > 0:
        for stage in stages:
            stage["p95_share_of_rtt_pct"] = round(100.0 * stage["p95_ms"] / rtt["p95_ms"], 1)
    complete = sum(1 for roles in trace_nodes.values() if {"client", "host"}.issubset(roles))
    components = [stage for stage in stages if stage["kind"] == "component"]
    return {
        "schema_version": TRACE_SCHEMA_VERSION,
        "span_count": sum(len(values) for values in durations.values()),
        "trace_count": len(trace_nodes),
        "cross_node_trace_count": complete,
        "dropped_records": dropped,
        "stages": stages,
        "likely_bottleneck": components[0]["stage"] if components else None,
    }


def export_sqlite(records: Iterable[dict[str, Any]], path: str | Path) -> Path:
    output = Path(path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(output) as database:
        database.execute(
            """
            CREATE TABLE IF NOT EXISTS latency_records (
                schema_version TEXT NOT NULL,
                record_type TEXT NOT NULL,
                session_id TEXT,
                trace_id TEXT,
                sequence INTEGER,
                node TEXT,
                role TEXT,
                name TEXT NOT NULL,
                wall_time_ns INTEGER,
                start_monotonic_ns INTEGER,
                end_monotonic_ns INTEGER,
                duration_ns INTEGER,
                attributes_json TEXT NOT NULL
            )
            """
        )
        database.execute("CREATE INDEX IF NOT EXISTS idx_latency_trace ON latency_records(trace_id)")
        database.execute("CREATE INDEX IF NOT EXISTS idx_latency_name ON latency_records(role, name)")
        database.executemany(
            """
            INSERT INTO latency_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    record.get("schema_version"),
                    record.get("record_type"),
                    record.get("session_id"),
                    record.get("trace_id"),
                    record.get("sequence"),
                    record.get("node"),
                    record.get("role"),
                    record.get("name"),
                    record.get("wall_time_ns"),
                    record.get("start_monotonic_ns"),
                    record.get("end_monotonic_ns"),
                    record.get("duration_ns"),
                    json.dumps(record.get("attributes", {}), separators=(",", ":")),
                )
                for record in records
            ],
        )
    return output


def _format_text(report: dict[str, Any]) -> str:
    lines = [
        "LeKiwi latency report",
        f"traces={report['trace_count']} cross-node={report['cross_node_trace_count']} "
        f"spans={report['span_count']} dropped={report['dropped_records']}",
        "",
        f"{'stage':48} {'kind':>9} {'count':>7} {'p50':>9} {'p95':>9} {'p99':>9} {'max':>9}",
    ]
    for stage in report["stages"]:
        lines.append(
            f"{stage['stage'][:48]:48} {stage['kind']:>9} {stage['count']:7d} {stage['p50_ms']:8.2f} "
            f"{stage['p95_ms']:8.2f} {stage['p99_ms']:8.2f} {stage['max_ms']:8.2f}"
        )
    if report["likely_bottleneck"]:
        lines.extend(["", f"Highest p95 stage: {report['likely_bottleneck']}"])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze completed LeKiwi latency trace sessions")
    parser.add_argument("paths", nargs="+", help="Trace JSONL files or directories")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--sqlite", help="Append all records to this SQLite database")
    args = parser.parse_args()
    records = load_records(args.paths)
    if args.sqlite:
        export_sqlite(records, args.sqlite)
    report = summarize(records)
    print(json.dumps(report, indent=2) if args.json else _format_text(report))


if __name__ == "__main__":
    main()
