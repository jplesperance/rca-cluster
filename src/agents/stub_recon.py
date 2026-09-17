"""
Stub recon agent — long-running consumer for role 'recon.stub'.
Fabricates a realistic ResultMessage (two graded sources with content refs
written to the artifact store) so the round-trip exercises every field of
the contract. Sprint 2 deletes the fabrication block and inserts a real
retrieval tool call; the consume/publish envelope stays identical.
"""
from __future__ import annotations
import time
from src.common.models import TaskMessage, ResultMessage, SourceRecord
from src.common.queue import Bus, task_stream
from src.common.store import ArtifactStore

ROLE = "recon.stub"


def handle(bus: Bus, artifacts: ArtifactStore, task_body: dict) -> None:
    task = TaskMessage(**task_body)
    print(f"[{ROLE}] received {task.task_id[:8]}: {task.directive}")

    time.sleep(1)  # pretend to search

    fabricated = [
        ("articles/press-release.txt",
         "PRIMARY-TIER FICTION: Fictioncorp disclosed a security incident "
         "on 2026-08-30 affecting approximately 4 million records. Initial "
         "access attributed by the vendor to credential stuffing.",
         "https://example.com/fictioncorp-pr", "secondary", "trade_press"),
        ("articles/forum-thread.txt",
         "SPECULATIVE FICTION: forum poster claims insider involvement and "
         "missing MFA on a legacy VPN appliance. Unverified.",
         "https://example.com/forum-thread", "speculative", "social"),
    ]

    sources: list[SourceRecord] = []
    for i, (rel, text, url, tier, cls) in enumerate(fabricated, start=1):
        sid = f"S-{i:03d}"
        content_ref = artifacts.write_content(task.session_id, rel, text)
        sources.append(SourceRecord(
            source_id=sid, url=url, source_class=cls,
            content_ref=content_ref, credibility_tier=tier,
            excerpt=text[:120],
        ))

    result = ResultMessage(
        session_id=task.session_id,
        task_id=task.task_id,
        status="complete",
        sources=sources,
        tokens_used=1850,
        cost_usd=0.003,
        notes="STUB RESULT — fabricated content, no real retrieval performed.",
    )
    bus.publish("stream:results", result.model_dump())
    print(f"[{ROLE}] published result for {task.task_id[:8]}")


def main() -> None:
    bus = Bus()
    artifacts = ArtifactStore()
    print(f"[{ROLE}] online, consuming {task_stream(ROLE)}")
    bus.consume_forever(task_stream(ROLE), f"group-{ROLE}", lambda body: handle(bus, artifacts, body))


if __name__ == "__main__":
    main()
