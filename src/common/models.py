"""
Contract models — single source of truth for inter-agent messages and session state.

Implements the intake payload schema and task/result message contracts ratified in
design sessions (see ARCHITECTURE.md §Contracts). Verdict vocabulary: five coarse
states, never numeric confidence. Mode field is a gate-behavior hint only; agents
must never branch on it.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _uuid() -> str:
    return str(uuid.uuid4())


class IncidentType(str, Enum):
    BREACH = "breach"
    OUTAGE = "outage"
    MALWARE_CAMPAIGN = "malware-campaign"
    APT = "apt"
    VULN_DISCLOSURE = "vuln-disclosure"
    OTHER = "other"


class ClaimedNarrative(BaseModel):
    """What someone SAID happened — kept separate from what is known."""
    claim: str
    source_class: str
    confidence: str = "low"


class Constraints(BaseModel):
    """Per-session hard limits. Enforced by orchestrator, not vibes."""
    max_cost_usd: float = 15.0
    max_recon_passes: int = 3
    replan_cycles_allowed: int = 2


class Subject(BaseModel):
    entity: str
    incident_type: IncidentType
    date_range: Optional[dict[str, str]] = None
    known_facts: list[str] = Field(default_factory=list)
    claimed_narratives: list[ClaimedNarrative] = Field(default_factory=list)


class IntakePayload(BaseModel):
    """Entry point into the graph, identical for interactive and (future)
    autonomous modes. Trigger layer differs; this structure does not."""
    session_id: str = Field(default_factory=_uuid)
    mode: str = "interactive"          # "interactive" | "autonomous" — gate hint only
    created_at: str = Field(default_factory=_now)
    question: str
    subject: Subject
    constraints: Constraints = Field(default_factory=Constraints)


class SourceRecord(BaseModel):
    """One retrieved artifact, graded at collection time. credibility_tier:
    primary | secondary | speculative. Verifier may downgrade, never upgrade
    unilaterally."""
    source_id: str
    url: str
    source_class: str
    retrieved_at: str = Field(default_factory=_now)
    content_ref: str
    credibility_tier: str
    excerpt: str


class TaskMessage(BaseModel):
    """Orchestrator -> worker. Every task traces to a hypothesis via
    parent_hypothesis — this is the 'why did we fetch this' audit link."""
    msg_type: str = "task"
    session_id: str
    task_id: str = Field(default_factory=_uuid)
    addressee_role: str               # e.g. "recon.stub"
    directive: str
    source_class: str
    parent_hypothesis: Optional[str] = None
    budget_tokens: int = 40000
    timeout_seconds: int = 300


class ResultMessage(BaseModel):
    """Worker -> orchestrator. Content lives in artifact store; messages carry
    content_ref pointers only. tokens_used/cost_usd feed the session ledger."""
    msg_type: str = "result"
    session_id: str
    task_id: str
    status: str                       # complete | partial | failed
    sources: list[SourceRecord] = Field(default_factory=list)
    tokens_used: int = 0
    cost_usd: float = 0.0
    notes: str = ""


class SessionState(BaseModel):
    """
    Single JSON document per session, checkpointed after every transition.
    Spine of the audit trail: claims registry, source index, task registry,
    and the token/cost ledger all live here. Graph node state is minimal —
    Sprint 3 adds the hypothesis tree reference.
    """
    intake: IntakePayload
    graph_node: str = "INTAKE"
    ledger: dict = Field(
        default_factory=lambda: {"tokens_used": 0, "cost_usd": 0.0}
    )
    tasks_dispatched: dict[str, str] = Field(default_factory=dict)   # task_id -> status
    source_index: dict[str, dict] = Field(default_factory=dict)      # source_id -> metadata
    source_counter: int = 0
    checkpoint_seq: int = 0
    updated_at: str = Field(default_factory=_now)
