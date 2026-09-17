# ARCHITECTURE.md
Research agent cluster for infosec RCA. Mode-agnostic state machine:
INTAKE -> PLAN -> [gate] -> RECON (fan-out) -> CORRELATE -> [gate] -> VERIFY -> SYNTHESIZE -> [gate] -> DELIVER.
Modes differ only in trigger layer and gate behavior; agents never branch on mode.

Roles: orchestrator (sole stateful component), recon workers (stateless, per
source class), correlator, adversarial verifier, synthesizer.

Communication: Redis Streams, one task stream per role, single results stream.
Messages carry content_ref pointers; bodies live in the artifact store.

Claim discipline: verdict vocabulary is {corroborated, single_source,
contested, unsupported, inference} — never numeric confidence. Ties break
downward. Reports: corroborated/contested in body, single_source quarantined
section, inference commentary, unsupported debug-log only.

Status: Sprint 1 (plumbing round-trip). See DECISIONS.md for rationale ledger.
