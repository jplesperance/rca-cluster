"""
Sprint 1 orchestrator — run-once demo proving the round-trip:
  INTAKE -> PLAN(stub) -> dispatch task to recon.stub -> await result
  -> ingest into session state -> checkpoint -> report ledger.

Sprint 3 replaces the hardcoded task emission with the planner's hypothesis-
tree fan-out. Everything else (dispatch, ingestion, checkpointing) survives
unchanged — that is the point of Sprint 1.
"""
from __future__ import annotations

# Replace the entire main() function in src/orchestrator/main.py with this
import argparse
import sys
from src.common.models import IntakePayload, Subject, Constraints, TaskMessage, ResultMessage, SessionState
from src.common.queue import Bus, task_stream
from src.common.store import SessionStore, ArtifactStore

def parse_args():
    p = argparse.ArgumentParser(description="Sprint 2: parameterized intake + dispatch")
    p.add_argument("--question", required=True)
    p.add_argument("--entity", required=True)
    p.add_argument("--role", default="recon.stub", help="Agent role to target")
    p.add_argument("--directive", default=None, help="Search directive; defaults to question")
    p.add_argument("--source-class", default="general_web", help="Source class for task")
    return p.parse_args()

def main() -> int:
    args = parse_args()
    bus = Bus()
    sessions = SessionStore()
    artifacts = ArtifactStore()

    # Build intake from CLI args
    intake = IntakePayload(
        question=args.question,
        subject=Subject(
            entity=args.entity,
            incident_type="breach",  # could make this a CLI arg later
        ),
        constraints=Constraints(max_cost_usd=15.0, max_recon_passes=3, replan_cycles_allowed=2),
    )
    state = SessionState(intake=intake)
    sessions.save(state, "intake")

    directive = args.directive if args.directive else args.question

    task = TaskMessage(
        session_id=intake.session_id,
        addressee_role=args.role,                     # <-- respects --role
        directive=directive,                          # <-- uses --directive or question
        source_class=args.source_class,               # <-- uses --source-class
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
          f"ledger now {state.ledger['tokens_used']} tokens / ${state.ledger['cost_usd']:.4f}")
    print(f"[orchestrator] source index: {list(state.source_index.keys())}")
    print(f"[orchestrator] session {intake.session_id} — inspect state/{intake.session_id}/")
    return 0

if __name__ == "__main__":
    sys.exit(main())
