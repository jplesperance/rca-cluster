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
| 2 | First real recon agent (Tavily retrieval, deterministic credibility grading) | ✅ Complete |
| 3 | General-purpose planner + hypothesis tree, auto-approved fan-out | ✅ Complete |
| 4 | Correlator: document dedup, claims registry, timeline, hypothesis updates | 🔜 Next |
| 5 | Adversarial verifier: rubric encoding, verdicts, coverage matrix | Planned |
| 6 | Synthesizer + report templates (technical report / exec summary) | Planned |
| 7 | Autonomous mode: trigger service, incident-stub resolver, revision policy | Deferred |

Current capability: point the orchestrator at a breach investigation, and the
system emits a 7-branch hypothesis tree, fans out 20 hypothesis-traced retrieval
tasks, aggregates all results with cursor-based resumable reads, and checkpointed
session state records the full audit trail. Full-session retrieval cost to date:
~$0.16 (~81k corpus tokens, 160 retrieval events).

See `DECISIONS.md` for the rationale ledger behind every architectural choice.

---

## Architecture

Mode-agnostic state machine. Interactive and autonomous (future) modes share
the same graph; only the trigger layer and gate behavior differ:

```
INTAKE → PLAN → [gate 1] → RECON (parallel fan-out) → CORRELATE
       → [gate 2] → VERIFY → SYNTHESIZE → [gate 3] → DELIVER
```

Plan gates are currently **auto-approved** (design decision; interactive
approval deferred). Document dedup, claims extraction, and verdicts are
Sprint 4–5 work.

**Roles**

| Role | Implementation | Responsibility |
|------|----------------|----------------|
| Orchestrator | ✅ `src/orchestrator/main.py` | Intake, tree emission, fan-out dispatch, result aggregation, ledger, checkpoints |
| Recon agents | ⚠️ `recon.web` only | Stateless retrieval workers per source class |
| Planner | ✅ `src/planner/general_planner.py` | Deterministic template: 7 fixed branches with pre-registered signals, prior-adjusted priorities |
| Correlator | 🔜 Sprint 4 | Claims registry, timeline, hypothesis updating |
| Adversarial verifier | 🔜 Sprint 5 | Grades every claim per the two-layer rubric |
| Synthesizer | 🔜 Sprint 6 | Renders validated findings into deliverables |

**Core disciplines**

- *Claim verdicts* (Sprint 5) — five coarse states, never numeric confidence:
  `corroborated · single_source · contested · unsupported · inference`.
  Ties break downward.
- *Deterministic source grading* (Sprint 2 interim) — domain-heuristic tier
  assignment (primary/secondary/speculative) via allowlists; placeholder for
  the LLM-assisted rubric.
- *Hypothesis trees* — planner pre-registers confirming/disconfirming signals
  per branch; versions are full re-emissions with changelog. Tasks trace to
  branches via `parent_hypothesis`.
- *Full provenance* — every retrieval traces: source → task → hypothesis →
  tree version. Checkpoints are append-only.

**Stack** — Python 3.12, Pydantic v2, Redis Streams (consumer groups,
at-least-once delivery, idempotent ingestion as the dedup boundary),
Tavily search API, local Docker Compose.

---

## Quick start

Prerequisites: Docker + Docker Compose, a Tavily API key.

```bash
git clone <repo-url> && cd rca-cluster
echo "TAVILY_API_KEY=tvly-..." > .env      # gitignored
mkdir -p artifacts state
docker compose up -d redis recon-web
docker compose run --rm orchestrator python -u -m src.orchestrator.main \
  --question "Root cause analysis of the Change Healthcare ransomware breach" \
  --entity "Change Healthcare / UnitedHealth Group"
```

Expected: tree v1 emitted (8 nodes), ~20 tasks dispatched, results
aggregated over 3–8 minutes, ending with a summary line like
`fan-out complete: 20/20 results, ledger ~80k tokens / $0.16, 160 sources indexed`.

Inspect afterwards:

```
state/<session-id>/state.json                    # live session document
state/<session-id>/checkpoints/NNNN_<node>.json   # append-only transition history
state/<session-id>/hypothesis_tree_v1.json        # versioned hypothesis tree
artifacts/<session-id>/web/                       # retrieved content with headers
```

## Configuration

Environment variables via `.env` (gitignored) or
`docker-compose.override.yml`:

| Variable | Purpose | Default |
|----------|---------|---------|
| `TAVILY_API_KEY` | Search provider credential | required for recon-web |
| `TAVILY_PER_CALL_USD` | Per-query cost for ledger accounting | 0.01 |

Per-session constraints (`max_cost_usd`, `max_recon_passes`,
`replan_cycles_allowed`) ride in the intake payload. Note: ledger currently
*records* spend; hard cap enforcement lands with Sprint 4.

## Repository layout

```
src/
├── common/
│   ├── models.py      # Intake, Task/Result contracts, SessionState — the spec, executable
│   ├── queue.py       # Redis Streams transport; cursor-based session reads
│   ├── store.py       # Artifact store + session store (append-only checkpoints)
│   ├── retrieval.py   # Tavily wrapper: retry/backoff, provider isolation
│   └── grading.py     # Deterministic domain-heuristic credibility tiers (interim)
├── planner/
│   └── general_planner.py  # Template tree builder + fan-out manifest
├── orchestrator/
│   └── main.py        # CLI-driven: intake → plan → dispatch → aggregate
└── agents/
    ├── recon_web.py   # Tavily-backed retrieval agent (role: recon.web)
    └── stub_recon.py  # Offline integration harness (keep for testing)
```

## Known limitations (honest inventory)

- **Single physical agent** — all source classes (`regulatory`, `technical`,
  `cve_db`, ...) route through `recon.web` via `AGENT_ROLE_MAP`. Query hints
  differentiate directives, but per-class tooling (EDGAR, NVD APIs) is
  Sprint 4+ work. Expect substantial URL duplication across the 160
  retrieval events (~60–90 distinct documents).
- **Token estimates only** — corpus tokens are len/4 heuristics; real model
  token accounting begins in Sprint 4 with the first LLM calls.
- **In-memory aggregation window** — result ingestion is checkpointed only
  after the aggregation loop completes; a kill mid-loop discards ingested
  state (results remain recoverable from the Redis stream). Per-result
  checkpointing is queued as an immediate fix.
- **Auto-approved gates** — no interactive plan pruning yet (deliberate;
  interactive approval re-enters with real replan cycles).
- **Excerpt granularity** — Tavily summaries, not full text; full-page
  fetch with URL-hash caching is a Sprint 4 prerequisite for attribution
  chains.
- **Timeout math** — fan-out deadline is a flat 600s; per-task timeouts and
  stuck-task recovery (XAUTOCLAIM/PEL) are deferred to Sprint 4.

## Budget & operations

Designed for a ~$100/month envelope: local hosting (~$0), retrieval
(~$3–5/month at current session velocity and pricing), remainder reserved
for model tokens from Sprint 4 onward. Empirical session cost to date:
**$0.16 retrieval, ~81k corpus tokens** for a full 20-task fan-out.

## Development protocol

- Every module carries a header docstring naming the contract it implements.
- `DECISIONS.md` is the decision log; append entries with date and rationale —
  no silent reversals.
- Full-file replacements over fragment splices; commit working states before
  applying changes so `git diff` catches stale lines.
- Each sprint has written acceptance criteria checked against real runs
  before it's marked complete.

## Roadmap

- **Sprint 4** — URL-keyed document dedup, full-text fetch with cache,
  claims registry (first LLM calls), timeline, hypothesis updates,
  dispatch-time cost caps
- **Sprint 5–6** — verifier rubric, coverage matrix, synthesizer templates
- **Autonomous mode** — breach-drop triggers (CISA, OCR portal, SEC filings),
  policy gates, versioned revision briefs

## License

TBD — decide before any external visibility.
