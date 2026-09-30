"""
General-purpose planner. Deterministic templater, not LLM-driven. Takes the
intake payload (question, entity, incident_type) and produces a fixed-topology
tree with 5–7 branches. Rationale for deterministic: Sprint 3 debugging wants
one new variable (tree mechanics), not two (tree mechanics + prompt tuning).
Swap to LLM-backed planner in Sprint 4+ if templated output proves limiting.

Output: HypothesisTree instance and fan_out_manifest = [(directive, source_class,
parent_node_id), ...] for the orchestrator to dispatch as TaskMessages.

Gate: auto-approved — no interactive pause; dispatcher fires immediately after
tree emission.
"""
from __future__ import annotations
from typing import Tuple, List
from src.common.tree import HypothesisTree, Node, Disposition, EvalPriority

# Template configuration — these are the fixed branches that map across any
# breach-type investigation. Adjust prior probabilities per incident_type
# if needed later (APT vs. ransomware vs. vuln-disclosure have different priors).
BRANCH_TEMPLATES = [
    # External initial access variants (depth-1)
    ("H1", None, "External initial access", 0.60),
    ("H1.1", "H1", "Credential compromise via phishing/info-stealer", 0.35),
    ("H1.2", "H1", "Exploited internet-facing vulnerability (CVE chain)", 0.40),
    ("H1.3", "H1", "Supply chain / third-party compromise", 0.15),
    # Insider-mediated (lower prior for ransomware)
    ("H2", None, "Insider-mediated access", 0.15),
    # Detection & response failures (co-factors)
    ("H3", None, "Detection & response failure (amplification factor)", 0.50),
    # Exhaustive outcome catch-all (MANDATORY per design)
    ("H4", None, "Other / unknown vector", 0.10),
]

SOURCE_CLASS_QUERY_HINTS = {
    "regulatory": "SEC filing regulatory disclosure congressional testimony",
    "vendor_advisory": "CISA advisory vendor security bulletin patch",
    "cve_db": "CVE exploited in the wild advisory",
    "threat_intel": "threat intelligence report indicators of compromise",
    "technical": "technical analysis root cause post-mortem forensics",
    "audit_report": "post-incident audit control failures findings",
    "legal_docs": "lawsuit class action court filing testimony",
    "internal_audit": "internal controls governance failure",
    "general_web": "",
}


def _build_branch(
    node_id: str, parent_id: Optional[str], hypothesis: str, prior: float,
    incident_type: str,
) -> Node:
    """Factory for branch nodes. Confirming/disconfirming signals are templated
    per branch type; adjust them empirically as you collect calibration data.
    Incident-type overrides can be added later (e.g., APT increases supply-chain prior)."""
    base_dir = f"Research the {hypothesis.lower()} for the {incident_type} incident"
    
    confirming_templates = {
        "External initial access": [
            "IR firm post-mortem identifying initial access vector",
            "Vendor advisory naming affected systems and CVE",
            "Regulatory filing disclosing specific technical details",
        ],
        "Credential compromise": [
            "Threat intel linking entity to known info-stealer campaign",
            "Credential dump tied to entity domain on paste site",
            "Vendor report of MFA fatigue or credential stuffing indicators",
        ],
        "Internet-facing vulnerability": [
            "CVE exploitation timeline matching incident date range",
            "IOC overlap with known vulnerability exploitation campaign",
            "Vendor advisory explicitly naming entity as victim",
        ],
        "Supply chain": [
            "Third-party vendor admission of compromise",
            "CI/CD pipeline audit revealing unauthorized changes",
            "Software bill of materials (SBOM) anomalies",
        ],
        "Insider-mediated": [
            "HR/termination records coinciding with incident timeline",
            "Privileged access logs showing anomalous internal activity",
            "Whistleblower or insider testimony",
        ],
        "Detection & response failure": [
            "Dwell time exceeding industry baseline (>90 days)",
            "Alert suppression or SIEM blind spots documented",
            "Post-breach audit identifying control gaps",
        ],
        "Other / unknown": [
            "All other branches definitively killed by corroborated evidence",
            "Insufficient public disclosure despite regulatory filings",
        ],
    }
    
    disconfirming_templates = {
        "External initial access": [
            "Forensic post-mortem ruling out external vectors",
            "Evidence pointing exclusively to insider activity",
        ],
        "Credential compromise": [
            "MFA logs showing no bypass attempts",
            "Absence of credential dump tied to entity",
        ],
        "Internet-facing vulnerability": [
            "Patch deployment records predating exploit availability",
            "Network segmentation isolating vulnerable system from exposure",
        ],
        "Supply chain": [
            "Vendor attestation of no compromise",
            "Code signing validation passing on all delivered artifacts",
        ],
        "Insider-mediated": [
            "No privileged account abuse detected",
            "Physical access controls and badge logs clean",
        ],
        "Detection & response failure": [
            "Detection occurred within SLA (<48 hours)",
            "Automated containment executed per runbook",
        ],
        "Other / unknown": [],
    }
    
    # Source-class targeting varies by branch type; external branches need
    # technical/vendor/regulatory sources, insider branches need forensic/legal.
    source_classes = {
        "External initial access": ["general_web", "technical", "vendor_advisory", "regulatory"],
        "Credential compromise": ["general_web", "technical", "threat_intel"],
        "Internet-facing vulnerability": ["technical", "vendor_advisory", "cve_db"],
        "Supply chain": ["general_web", "vendor_advisory", "regulatory"],
        "Insider-mediated": ["legal_docs", "internal_audit", "regulatory"],
        "Detection & response failure": ["technical", "audit_report", "regulatory"],
        "Other / unknown": ["general_web"],
    }
    
    # Handle parent-less node_id cases (depth-1 nodes)
    display_hypothesis = hypothesis
    for key in confirming_templates:
        if key.lower() in hypothesis.lower():
            confirming = confirming_templates[key]
            disconfirming = disconfirming_templates[key]
            classes = source_classes[key]
            break
    else:
        # Fallback: use first template or defaults
        confirming = [f"Evidence supporting {hypothesis.lower()}"]
        disconfirming = [f"Evidence refuting {hypothesis.lower()}"]
        classes = ["general_web"]
    
    return Node(
        node_id=node_id,
        parent_id=parent_id,
        path=f"{parent_id}.{node_id}" if parent_id else node_id,
        hypothesis=hypothesis,
        rationale=f"Branch evaluates whether {hypothesis.lower()} contributed to {incident_type}",
        prior_probability=prior,
        disposition=Disposition.ACTIVE,
        eval_priority=EvalPriority.FULL if prior > 0.25 else EvalPriority.LIGHT,
        source_class_targets=classes,
        confirming_signals=confirming,
        disconfirming_signals=disconfirming,
    )

def build_tree(session_id: str, question: str, entity: str, incident_type: str) -> HypothesisTree:
    """Emits a fresh v1 tree for the given session. Prior probabilities can be
    adjusted per incident_type here (APT vs. ransomware vs. vuln-disclosure have
    different base rates). For now, static priors per template."""
    
    # Adjust priors for incident type — ransomware favors external access; APT favors supply chain.
    priors_adjustment = {
        "ransomware": {"External initial access": 0.0, "Insider-mediated": -0.05},
        "apt": {"Supply chain": 0.1, "Insider-mediated": 0.05},
        "vuln-disclosure": {"Internet-facing vulnerability": 0.1},
    }
    adjustments = priors_adjustment.get(incident_type, {})
    
    nodes: dict[str, Node] = {}
    # Root node H0
    root = Node(
        node_id="H0",
        parent_id=None,
        path="H0",
        hypothesis="Root cause investigation scope",
        rationale=f"Investigate {entity} {incident_type}: {question}",
        prior_probability=1.0,
        disposition=Disposition.ACTIVE,
        source_class_targets=[],  # Root doesn't generate tasks
        confirming_signals=[f"Adequate coverage of all child branches"],
        disconfirming_signals=["Critical branches untested due to budget"],
    )
    nodes[root.node_id] = root
    
    for node_id, parent_id, hypothesis, prior in BRANCH_TEMPLATES:
        node = _build_branch(node_id, parent_id, hypothesis, prior, incident_type)
        # Apply incident-type adjustment to prior
        for keyword, delta in adjustments.items():
            if keyword.lower() in hypothesis.lower():
                node.prior_probability = min(1.0, max(0.0, node.prior_probability + delta))
                break
        # Set priority based on adjusted prior
        node.eval_priority = EvalPriority.FULL if node.prior_probability > 0.25 else EvalPriority.LIGHT
        nodes[node_id] = node
    
    tree = HypothesisTree(
        session_id=session_id,
        root=root,
        nodes=nodes,
        change_log=[f"v1: initial tree emission, {len(nodes)-1} branches"],
    )
    
    return tree

def fan_out_manifest(tree: HypothesisTree) -> List[Tuple[str, str, str]]:
    """Returns the cross-product of (directive, source_class, parent_node_id)
    for all active, non-DEFERRED branches. Directive text derived from the
    branch's hypothesis + entity for query specificity. This is the manifest
    the orchestrator turns into TaskMessages."""
    manifest = []
    for node in tree.nodes.values():
        if node.disposition == Disposition.DEFERRED:
            continue
        for source_class in node.source_class_targets:
            directive = f"{node.hypothesis} in {entity_context(tree.session_id)}"  # TODO: fix entity lookup
            manifest.append((directive, source_class, node.node_id))
    return manifest

def entity_context(session_id: str) -> str:
    """Placeholder — in practice, load the session's intake.subject.entity
    from SessionStore. For Sprint 3, assume the caller passes this in."""
    return "[entity]"  # FIXME: replace with actual lookup from session store

def fan_out_manifest_with_entity(tree: HypothesisTree, entity: str) -> List[Tuple[str, str, str]]:
    """Same as fan_out_manifest but injects the entity name into directives."""
    manifest = []
    for node in tree.nodes.values():
        if node.disposition == Disposition.DEFERRED:
            continue
        for source_class in node.source_class_targets:
            directive = f"{node.hypothesis} in the {entity} incident".strip()
            hint = SOURCE_CLASS_QUERY_HINTS.get(source_class, "")
            if hint:
                directive = f"{directive} {hint}"

            manifest.append((directive, source_class, node.node_id))
    return manifest
