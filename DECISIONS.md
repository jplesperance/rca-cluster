# DECISIONS.md

- 2026-09-17: Hand-rolled orchestrator over framework-heavy abstraction (debuggability > framework affordances at this scale). Revisit at Sprint 3+.
- 2026-09-17: Local Docker Compose hosting; ~$100/mo budget allocated to retrieval APIs (~$15) and tiered model tokens (~$70–85).
- 2026-09-17: Redis Streams, one stream per addressee role — avoids read-filter on shared stream; consumer groups for at-least-once delivery.
- 2026-09-17: Verifier rubric: two layers (source-class tier presumption, claim-level verdict procedure); independence collapse for shared origins; recency-dominates on intra-tier conflict; anonymous sources cap at single_source/speculative and route to leads channel; absence of evidence is not evidence of absence.
- 2026-09-17: Hypothesis tree: pre-registered confirming/disconfirming signals; prior_probability drives lazy-eval (full/light/deferred); mandatory exhaustive-outcome sibling; kill/confirm require corroborated grade; separate causal-chain from co-factor branches.
- 2026-09-17: Replans use FULL TREE RE-EMISSION with changelog, not deltas. Two-cycle cap makes re-emit token cost acceptable; consistency over patch complexity.
- 2026-09-17: Synthesizer verdict mapping: corroborated/contested -> report body; single_source -> labeled section; inference -> commentary; unsupported -> debug log only.
Sprint 2 accepted: Tavily integration functional; domain-heuristic grading deployed (placeholder for LLM rubric); cost placeholder calibrated against provider billing.
