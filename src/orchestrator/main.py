"""
Sprint 3: planner + hypothesis tree integration. Orchestrator now parses CLI args,
runs the general-purpose templated planner, persists the tree, and dispatches
the fan-out manifest. No interactive gate — auto-approved per design decision.

Importantly: all source classes route through recon.web until additional
recon agents are implemented.
"""
from __future__ import annotations
import argparse
import json
import sys
from src.common.models import IntakePayload, Subject, Constraints, TaskMessage, ResultMessage, SessionState
from src.common.queue import Bus, task_stream
from src.common.store import SessionStore, ArtifactStore
from src.planner.general_planner import build_tree, fan_out_manifest_with_entity

# Route all source classes through existing recon.web agent (Sprint 3)
AGENT_ROLE_MAP = {
    "general_web": "recon.web",
    "technical": "recon.web",
    "vendor_advisory": "recon.web",
    "cve_db": "recon.web",
    "threat_intel": "recon.web",
    "internal_audit": "recon.web",
    "regulatory": "recon.web",
    "audit_report": "recon.web",
    "legal_docs": "recon.web",
}

def parse_args():
    p = argparse.ArgumentParser(description="Sprint 3: planner + tree dispatch")
    p.add_argument("--question", required=True)
    p.add_argument("--entity", required=True)
    p.add_argument("--role", default="recon.web")
    p.add_argument("--directive", default=None)
    p.add_argument("--source-class", default="general_web")
    return p.parse_args()

def main() -> int:
    args = parse_args()
    bus = Bus()
    sessions = SessionStore()
    artifacts = ArtifactStore()

    intake = IntakePayload(
        question=args.question,
        subject=Subject(entity=args.entity, incident_type="breach"),
    )
    state = SessionState(intake=intake)
    sessions.save(state, "intake")

    # === PLANNER PHASE ===
    tree = build_tree(
        session_id=intake.session_id,
        question=args.question,
        entity=args.entity,
        incident_type="breach",
    )
    # Persist tree version 1
    tree_path = sessions.save_tree(intake.session_id, tree.to_dict())
    state.graph_node = "TREE_EMITTED"
    sessions.save(state, "tree_emitted")

    # === DISPATCH FAN-OUT ===
    manifest = fan_out_manifest_with_entity(tree, args.entity)
    tasks_count = 0
    for idx, (directive, source_class, parent_hyp) in enumerate(manifest, start=1):
        addressee_role = AGENT_ROLE_MAP.get(source_class, "recon.web")
        task = TaskMessage(
            session_id=intake.session_id,
            addressee_role=addressee_role,
            directive=directive,
            source_class=source_class,
            parent_hypothesis=parent_hyp,
            budget_tokens=40000,
            timeout_seconds=300,
        )
        state.tasks_dispatched[task.task_id] = "dispatched"
        bus.publish(task_stream(addressee_role), task.model_dump())
        tasks_count += 1

    state.graph_node = f"RECON_FAN_OUT_{tasks_count}_TASKS"
    sessions.save(state, "fan_out_dispatch")

    print(f"[orchestrator] emitted tree v1 with {len(tree.nodes)} nodes")
    print(f"[orchestrator] dispatched {tasks_count} tasks to {set(m[1] for m in manifest)}")
    print(f"[orchestrator] awaiting results (timeout 30s)...")

    # === WAIT FOR RESULTS (first one only for Sprint 3; aggregate in Sprint 4) ===
    # Replace the single-read block in main() with:
        # Replace the aggregation block in src/orchestrator/main.py
    pending = set(state.tasks_dispatched.keys())
    completed = 0
    cursor = "0"
    
    import time as _t
    deadline = _t.monotonic() + 600  # 20 sequential Tavily calls need minutes
    
    try:
        while pending and _t.monotonic() < deadline:
            remaining_ms = int((deadline - _t.monotonic()) * 1000)
            _id, body, cursor = bus.read_results(
                intake.session_id,
                timeout_ms=min(remaining_ms, 60000),
                last_id=cursor
            )
            if body["task_id"] not in pending:
                continue  # Already processed or stale
            
            result = ResultMessage(**body)
            sessions.ingest_result(state, result)
            pending.discard(result.task_id)
            completed += 1
            print(f"[orchestrator] ingested {completed}/{len(state.tasks_dispatched)} "
                  f"({result.status}, {len(result.sources)} sources)")
    except TimeoutError:
        print(f"[orchestrator] TIMEOUT: {completed} of {len(state.tasks_dispatched)} "
              f"completed; {len(pending)} tasks unaccounted")
        state.graph_node = "PARTIAL_TIMEOUT"

    state.graph_node = "RECON_COMPLETE"
    sessions.save(state, "recon_ingest_all")

    print(f"[orchestrator] fan-out complete: {completed}/{len(state.tasks_dispatched)} results, "
          f"ledger {state.ledger['tokens_used']} tokens / ${state.ledger['cost_usd']:.4f}, "
          f"{len(state.source_index)} sources indexed")    
    return 0

if __name__ == "__main__":
    sys.exit(main())
