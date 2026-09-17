# RCA Research Cluster

An agentic research system for infosec investigations — root-cause analysis of
breaches, security events, and deep-dive topics — built around a single
principle: **separation of retrieval from judgment**. Agents that gather
evidence are never the same agents that judge it.

Every claim in a final report carries provenance, an independence-checked
corroboration grade, and a clear split between *reported fact*, *analyst
inference*, and *vendor narrative*. The cluster's differentiator is adjudicating
competing post-incident narratives — not just repeating them.

---

## Status

| Sprint | Scope | State |
|--------|-------|-------|
| 1 | Plumbing round-trip (queue, state, artifact store, stub agent) | ✅ Complete |
| 2 | First real recon agent (live web retrieval, credibility grading) | 🚧 Next |
| 3 | Planner + hypothesis tree, gate-one interactive approval | Planned |
| 4 | Correlator (claims registry, timeline, hypothesis updating) | Planned |
| 5 | Adversarial verifier (rubric, verdicts, coverage matrix) | Planned |
| 6 | Synthesizer + report templates (technical report / exec summary) | Planned |
| 7 | Autonomous mode: trigger service, incident-stub resolver, revision policy | Deferred |

See `DECISIONS.md` for the rationale ledger behind every architectural choice.

---

## Architecture

Mode-agnostic state machine. Interactive and autonomous (future) modes share
the same graph; only the trigger layer and gate behavior differ:

```
INTAKE → PLAN → [gate 1] → RECON (parallel fan-out) → CORRELATE
       → [gate 2] → VERIFY → SYNTHESIZE → [gate 3] → DELIVER
```

**Roles**

| Role | Responsibility |
|------|----------------|
| Orchestrator | Sole stateful component. Decomposes questions, dispatches tasks, tracks state, enforces budget caps |
| Recon agents | Stateless collectors, one per source class (web, regulatory, technical, social...) |
| Correlator | Timeline assembly, causal chains, hypothesis updating, contradiction flagging |
| Adversarial verifier | Attacks the correlator's conclusions. Grades every claim |
| Synthesizer | Renders validated findings into deliverables |

**Core disciplines**

- *Claim verdicts* — five coarse states, never numeric confidence:
  `corroborated · single_source · contested · unsupported · inference`.
  Ties break downward: false "confirmed" costs more than false "needs more sources."
- *Independence checking* — sources sharing an origin collapse to one.
  Three outlets citing a company statement is one source, not three.
- *Hypothesis trees* — planner pre-registers confirming/disconfirming signals
  per branch; branches are killed or confirmed only by corroborated claims.
  Prior probabilities drive lazy evaluation to control token spend.
- *Full provenance* — every report claim traces: claim → verdict → sources →
  recon task → hypothesis → plan version. Checkpoints are append-only.

**Stack** — Python 3.12, Pydantic v2, Redis Streams, local Docker Compose.
No cloud services required; model and retrieval API calls egress from the
orchestrator and recon agents.

---

## Quick start

Prerequisites: Docker + Docker Compose.

```bash
git clone <repo-url> && cd rca-cluster
mkdir -p artifacts state
docker compose up --build
```

Expected output: the stub recon agent reports online, the orchestrator
dispatches a demo task, the stub fabricates a realistic result, and the
orchestrator ingests it and exits 0. Inspect afterwards:

```
state/<session-id>/state.json                  # live session document
state/<session-id>/checkpoints/NNNN_<node>.json  # append-only transition history
artifacts/<session-id>/                        # retrieved content, by content_ref
```

Re-running the orchestrator (`docker compose run --rm orchestrator`) creates a
new session; the stub agent keeps serving from its consumer group across
restarts.

## Configuration

Retrieval API keys and model provider credentials are injected via
environment variables at the container level (added in Sprint 2+):

```yaml
# docker-compose.override.yml (not committed)
services:
  stub-recon:
    environment:
      SEARCH_API_KEY: ...
```

## Repository layout

```
src/
├── common/
│   ├── models.py      # Intake, Task/Result contracts, SessionState — the spec, executable
│   ├── queue.py       # Redis Streams transport, consumer groups
│   └── store.py       # Artifact store (immutable, path-guarded) + session store/checkpoints
├── orchestrator/
│   └── main.py        # Run-once demo driver (Sprint 1); planner integration lands in Sprint 3
└── agents/
    └── stub_recon.py  # Round-trip proof; fabrication block replaced by real retrieval in Sprint 2
```

## Development protocol

- Every module carries a header docstring naming the contract it implements.
- `DECISIONS.md` is the decision log; append entries with date and rationale —
  no silent reversals.
- `ARCHITECTURE.md` holds the durable design detail; this README stays thin.
- Checkout of a sprint branch per sprint; acceptance criteria in the sprint's
  issue/notes before merging.

## Budget & operations

Designed for a ~$100/month envelope: local hosting (~$0), retrieval APIs
(~$15), tiered model tokens (~$70–85). Per-session hard caps (cost, recon
passes, replan cycles) are enforced by the orchestrator and carried in the
intake payload. Async revision cycles for stale-source correction (day-7 /
day-30 re-runs) arrive with autonomous mode.

## Roadmap

- **Sprint 2** — live retrieval, source-record grading, real incident smoke test
- **Sprint 3–6** — planner, correlator, verifier, synthesizer
- **Autonomous mode** — breach-drop triggers (CISA, OCR portal, SEC filings),
  policy gates, versioned revision briefs

## License

TBD — decide before any external visibility.
