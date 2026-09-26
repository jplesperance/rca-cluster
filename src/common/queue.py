"""
Redis Streams transport. One stream per addressee role (tasks:{role}), one
results stream read by the orchestrator. Consumer groups give at-least-once
delivery; message IDs are ACKed only after the handler completes.
"""
from __future__ import annotations
import json
from typing import Callable
import redis

REDIS_HOST = "redis"
RESULTS_STREAM = "stream:results"


def task_stream(role: str) -> str:
    return f"stream:tasks:{role}"


class Bus:
    def __init__(self, host: str = REDIS_HOST, port: int = 6379):
        self.r = redis.Redis(host=host, port=port, decode_responses=True)
        self.r.ping()

    def publish(self, stream: str, payload: dict) -> str:
        return self.r.xadd(stream, {"body": json.dumps(payload)})

    def read_results(self, session_id: str, timeout_ms: int = 120000):
        """Blocking read of the results stream, returning the first message
        belonging to the given session. Raises TimeoutError on silence.
        Scans from last-read position so prior sessions' results are skipped."""
        import time
        last_id = "0"
        deadline = time.monotonic() + timeout_ms / 1000.0
        while True:
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                raise TimeoutError(f"No results for {session_id} within {timeout_ms}ms")
            resp = self.r.xread(
                {RESULTS_STREAM: last_id},
                count=10,
                block=max(min(remaining_ms, 5000), 1),
            )
            if not resp:
                raise TimeoutError(f"No results for {session_id} within {timeout_ms}ms")
            entries = resp[0][1]
            last_id = entries[-1][0]
            for _id, fields in entries:
                body = json.loads(fields["body"])
                if body.get("session_id") == session_id:
                    return _id, body
            # No match in this batch — loop and keep scanning from last_id.

    def consume_forever(self, stream: str, group: str, handler: Callable[[dict], None]):
        """Worker-side loop: consumer-group read -> handler -> ack."""
        try:
            self.r.xgroup_create(stream, group, id="0", mkstream=True)
        except redis.exceptions.ResponseError:
            pass  # group exists
        while True:
            resp = self.r.xreadgroup(group, "worker-1", {stream: ">"}, count=1, block=5000)
            if not resp:
                continue
            for _stream, entries in resp:
                for _id, fields in entries:
                    handler(json.loads(fields["body"]))
                    self.r.xack(stream, group, _id)
