"""
Sprint 1 orchestrator — run-once demo proving the round-trip:
  INTAKE -> PLAN(stub) -> dispatch task to recon.stub -> await result
  -> ingest into session state -> checkpoint -> report ledger.

Sprint 3 replaces the hardcoded task emission with the planner's hypothesis-
tree fan-out. Everything else (dispatch, ingestion, checkpointing) survives
unchanged — that is the point of Sprint 1.
"""
from __future__ import annotations
import sys
import argparse
from src.common.models import IntakePayload, TaskMessage, ResultMessage, SessionState
from src.common.queue import Bus, task_stream
from src.common.store import SessionStore, ArtifactStore

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--question", required=True)
    p.add_argument("--entity", required=True)
    p.add_argument("--role", default="recon.web")
    p.add_argument("--directive", default=None, help="Defaults to the question text")
    p.add_argument("--source-class", default="general_web")
    return p.parse_args()

def demo_intake() -> IntakePayload:
    return IntakePayload(
        question="Root cause analysis of the Sprint-1 fictional entity breach",
        subject={
            "entity": "Fictioncorp",
            "incident_type": "breach",
            "known_facts": ["Disclosure 2026-08-30", "Claimed 4M records"],
            "claimed_narratives": [
                {"claim": "credential stuffing", "source_class": "vendor", "confidence": "low"}
            ],
        },
    )


def main() -> int:
    bus = Bus()
    sessions = SessionStore()
    artifacts = ArtifactStore()

    intake = demo_intake()
    state = SessionState(intake=intake)
    sessions.save(state, "intake")

    task = TaskMessage(
        session_id=intake.session_id,
        addressee_role=args.role,
        directive=args.directive or args.question,
        source_class=args.source_class,
        parent_hypothesis="H0",
    )
    state.graph_node = "RECON_PENDING"
    state.tasks_dispatched[task.task_id] = "dispatched"
    sessions.save(state, "recon_dispatch")
    bus.publish(task_stream(task.addressee_role), task.model_dump())

    print(f"[orchestrator] dispatched {task.task_id[:8]} to {task.addressee_role}; awaiting result")
    try:
        _id, body = bus.read_results(intake.session_id, timeout_ms=30000)
    except TimeoutError:
        state.graph_node = "FAILED_TIMEOUT"
        sessions.save(state, "fail_timeout")
        print("[orchestrator] TIMEOUT: no result received")
        return 1

    result = ResultMessage(**body)
    sessions.ingest_result(state, result)
    state.graph_node = "RECON_COMPLETE"
    sessions.save(state, "recon_ingest")

    print(f"[orchestrator] result {result.status}: {len(result.sources)} sources, "
          f"ledger now {state.ledger['tokens_used']} tokens / ${state.ledger['cost_usd']:.2f}")
    print(f"[orchestrator] source index: {list(state.source_index.keys())}")
    print(f"[orchestrator] session {intake.session_id} — inspect state/{intake.session_id}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
