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

    def read_results(self, session_id: str, timeout_ms: int, last_id: str = "0"):
        """Blocking read for session results. Returns (_id, body, last_id) so caller
        threads the cursor through successive calls. Quiet windows are tolerated;
        raises TimeoutError only after full deadline elapses."""
        import time
        deadline = time.monotonic() + timeout_ms / 1000.0
        cursor = last_id
        while True:
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                raise TimeoutError(f"No results for {session_id} within {timeout_ms}ms")
        
            resp = self.r.xread(
                {RESULTS_STREAM: cursor},
                count=10,
                block=max(min(remaining_ms, 5000), 1),
            )
            if not resp:
                continue  # quiet window — keep waiting
        
            entries = resp[0][1]
            cursor = entries[-1][0]  # advance cursor even if no match for our session
        
            for _id, fields in entries:
                body = json.loads(fields["body"])
                if body.get("session_id") == session_id:
                    return _id, body, cursor  # pass cursor back
        
            # No match for this session in this batch — continue scanning from cursor

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
