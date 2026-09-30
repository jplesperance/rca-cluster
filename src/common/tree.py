"""
Hypothesis-tree data structure and utility functions. Versioned per-session;
checkpointed alongside session state. Covers are the verifier's audit anchor
in Sprint 5 — the tree's confirm/disconfirm signals are the ground truth for
"was branch adequately tested?".

Versioning: each replan produces a new `version` and `change_log` entry. Full
re-emit per DESIGN DECISION (no delta compression; simplicity over patch
complexity).
"""
from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

class Disposition(str, Enum):
    ACTIVE = "active"
    LIGHT = "light"
    DEFERRED = "deferred"
    KILLED = "killed"
    CONFIRMED = "confirmed"
    PARKED = "parked"

class EvalPriority(str, Enum):
    FULL = "full"
    LIGHT = "light"
    DEFERRED = "deferred"

class Node(BaseModel):
    """Single tree node. Leaf nodes are disconfirmable by evidence. Every leaf
    has pre-registered signals that define what counts as confirming vs.
    disconfirming — this is the planning discipline we borrowed from clinical
    trials (pre-registration defeats confirmation bias)."""
    node_id: str                    # e.g. "H1.1.a"
    parent_id: Optional[str]        # "H0" for depth-1 nodes
    path: str                       # "H0.H1.1.a"
    hypothesis: str                 # Must be testable (yes/no per evidence)
    rationale: str
    prior_probability: float        # 0.0–1.0; drives eval_priority
    disposition: Disposition = Disposition.ACTIVE
    eval_priority: EvalPriority = EvalPriority.FULL
    source_class_targets: list[str] = Field(default_factory=lambda: ["general_web"])
    confirming_signals: list[str] = Field(default_factory=list)
    disconfirming_signals: list[str] = Field(default_factory=list)
    verdict_links: list[str] = Field(default_factory=list)  # claim IDs
    budget_state: dict = Field(default_factory=lambda: {"tokens_spent": 0, "passes": 0})
    created_at: str = Field(default_factory=_now)

class HypothesisTree(BaseModel):
    """Versioned tree document. Planners re-emit the full tree on replan, appending
    changelog entries; checkpointed alongside session state."""
    tree_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    version: int = 1
    session_id: str
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    root: Node                      # H0, the frame node
    nodes: dict[str, Node] = Field(default_factory=dict)  # keyed by node_id
    change_log: list[str] = Field(default_factory=list)
    
    def get(self, node_id: str) -> Optional[Node]:
        return self.nodes.get(node_id) if node_id != self.root.node_id else self.root
    
    def to_dict(self) -> dict:
        return {
            "tree_id": self.tree_id,
            "version": self.version,
            "session_id": self.session_id,
            "root": self.root.model_dump(),
            "nodes": {k: v.model_dump() for k, v in self.nodes.items()},
            "change_log": self.change_log,
        }
