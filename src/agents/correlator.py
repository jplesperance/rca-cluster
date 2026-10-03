"""
Correlator — role 'correlator'. Stateful-in-artifact, stateless-in-memory:
loads session state + tree from the shared volume, builds the deduped corpus,
fetches full text for distinct docs (Tavily extract, URL-hash cached), runs
batched claims extraction, merges/dedupes claims, emits prior-update PROPOSALS
(applied only after Sprint 5 verification — never auto-applies), writes the
claims registry artifact, publishes a result.

Pipeline: CORRELATE task -> corpus build -> fulltext fetch -> extract batches
-> claims merge -> prior proposals -> artifacts -> result.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from src.common.models import TaskMessage, ResultMessage, ClaimRecord, ClaimsRegistry, PriorUpdateProposal
from src.common.queue import Bus, task_stream
from src.common.store import SessionStore, ArtifactStore
from src.common.corpus import build_corpus
from src.common.model import ModelAdapter
from src.common.retrieval import RetrievalProvider

ROLE = "correlator"
BATCH_DOCS = 6
DOC_CHAR_LIMIT = 4000

SYSTEM_EXTRACT = (
    "You extract discrete, attributable claims from security-incident documents. "
    "Rules: one claim per assertion; classify each as 'reported_fact' (entity/observer "
    "stated X happened), 'attribution' (someone claims Y caused Z), or 'inference' "
    "(analyst reasoning, clearly the author's interpretation). Capture 'stated_by' — "
    "never lose WHO made the assertion; a claim without an attributor is useless. "
    "Include dates where present. Mark which hypothesis IDs (given per document) "
    "the claim bears on. Output ONLY a JSON array of claim objects with keys: "
    "text, claim_type, stated_by, date_of_event, date_published, relevant_hypotheses, "
    "doc_hash. Quote precisely; do not paraphrase the core assertion."
)

def _load_tree(sessions: SessionStore, session_id: str) -> dict:
    d = sessions.root / session_id
    return json.loads((d / "hypothesis_tree_v1.json").read_text())

def _doc_fulltext(bus_artifacts: ArtifactStore, session_id: str, doc: dict,
                  provider: RetrievalProvider) -> str:
    h = doc["doc_hash"]
    cache = f"fulltext/{h}.txt"
    ref = f"artifacts/{session_id}/{cache}"
    try:
        return bus_artifacts.read_content(ref)
    except FileNotFoundError:
        pass
    try:
        resp = provider.client.extract(urls=[doc["url"]])
        text = (resp.get("results") or [{}])[0].get("raw_content") or ""
    except Exception:
        text = ""
    if not text:  # fall back to stored excerpt artifact
        try:
            text = bus_artifacts.read_content(doc["content_ref"])[:DOC_CHAR_LIMIT]
        except FileNotFoundError:
            text = ""
    bus_artifacts.write_content(session_id, cache, text)
    return text

def handle(bus: Bus, sessions: SessionStore, artifacts: ArtifactStore,
           model: ModelAdapter, provider: RetrievalProvider, task_body: dict) -> None:
    task = TaskMessage(**task_body)
    sid = task.session_id
    print(f"[{ROLE}] received {task.task_id[:8]} for session {sid[:8]}")
    state = sessions.load(sid)
    tree = _load_tree(sessions, sid)

    # Task -> hypothesis map (the join fix from corpus design notes)
    hyp_by_task = {}  # built from checkpoints: task IDs map to tree dispatch
    # Cheapest reliable source: recompute from fan-out checkpoint manifest
    fan_cp = sessions.root / sid / "checkpoints"
    for cp in sorted(fan_cp.glob("*fan_out_dispatch.json")):
        st = json.loads(cp.read_text())
        for tid, tmeta in st.get("_task_hypotheses", {}).items():  # see orchestrator note
            hyp_by_task[tid] = tmeta

    corpus = build_corpus(state.source_index)
    # annotate docs with retrieving hypotheses
    for doc in corpus.values():
        doc["hypotheses"] = sorted({
            hyp_by_task[meta.get("from_task")] if isinstance(hyp_by_task.get(meta.get("from_task")), str)
            else hid
            for meta in [next(m for m in state.source_index.values() if doc_hash(m["url"]) == doc["doc_hash"])]
            for hid in (hyp_by_task.get(meta["from_task"], []) if isinstance(hyp_by_task.get(meta["from_task"]), list) else [hyp_by_task.get(meta["from_task"])])
        })
    print(f"[{ROLE}] corpus: {len(corpus)} distinct docs from {len(state.source_index)} retrieval events")

    registry = ClaimsRegistry(session_id=sid)
    batches = [list(corpus.values())[i:i+BATCH_DOCS] for i in range(0, len(corpus), BATCH_DOCS)]
    for bi, batch in enumerate(batches, 1):
        doc_blocks = []
        for doc in batch:
            text = _doc_fulltext(artifacts, sid, doc, provider)[:DOC_CHAR_LIMIT]
            if not text:
                continue
            doc_blocks.append(
                f"DOCUMENT doc_hash={doc['doc_hash']}\ntier={doc['credibility_tier']}\n"
                f"hypotheses={[n['node_id'] for n in tree['nodes'].values()] and doc['hypotheses']}\n"
                f"url={doc['url']}\n---\n{text}"
            )
        if not doc_blocks:
            continue
        user = f"Incident question: {state.intake.question}\n\n" + "\n\n".join(doc_blocks)
        try:
            claims_raw, usage = model.complete_json(SYSTEM_EXTRACT, user)
        except Exception as exc:
            print(f"[{ROLE}] batch {bi} extraction failed: {exc}")
            continue
        registry.extraction_usage["tokens_in"] += usage["tokens_in"]
        registry.extraction_usage["tokens_out"] += usage["tokens_out"]
        registry.extraction_usage["cost_usd"] += usage["cost_usd"]
        for c in claims_raw:
            registry.claims.append(ClaimRecord(
                claim_id=f"C-{len(registry.claims)+1:03d}",
                text=c["text"], claim_type=c.get("claim_type", "reported_fact"),
                stated_by=c.get("stated_by", "unknown"),
                doc_hash=c.get("doc_hash", ""),
                source_ids=[],
                relevant_hypotheses=c.get("relevant_hypotheses", []),
                date_of_event=c.get("date_of_event"),
                date_published=c.get("date_published"),
            ))
            registry.docs_processed += 1
        print(f"[{ROLE}] batch {bi}/{len(batches)}: +{len(claims_raw)} claims "
              f"(${registry.extraction_usage['cost_usd']:.4f} cumulative)")

    # Tie claims to source_ids via doc_hash (post-merge provenance join)
    hash_to_sids = {d["doc_hash"]: d["source_ids"] for d in corpus.values()}
    for c in registry.claims:
        c.source_ids = hash_to_sids.get(c.doc_hash, [])

    artifacts.write_content(sid, "claims_registry.json", registry.model_dump_json(indent=2))

    # Prior-update proposals (NOT applied — stored for Sprint 5 ratification)
    tree_summary = "\n".join(
        f"{nid}: prior={n['prior_probability']} :: {n['hypothesis']}"
        for nid, n in tree["nodes"].items()
    )
    claims_summary = "\n".join(f"{c.claim_id} [{c.claim_type}] {c.text[:160]}" for c in registry.claims)
    try:
        proposals_raw, usage = model.complete_json(
            "You propose prior-probability adjustments for hypothesis-tree branches "
            "given extracted claims. Proposals only — nothing is final. Output JSON array: "
            "{node_id, suggested_prior, rationale, evidence_claim_ids}. Be conservative; "
            "single-source claims barely move priors.",
            f"TREE:\n{tree_summary}\n\nCLAIMS:\n{claims_summary}",
        )
        proposals = [PriorUpdateProposal(**p) for p in proposals_raw]
        artifacts.write_content(sid, "prior_proposals.json",
                               json.dumps([p.model_dump() for p in proposals], indent=2))
    except Exception as exc:
        print(f"[{ROLE}] proposal pass failed: {exc}")

    result = ResultMessage(
        session_id=sid, task_id=task.task_id, status="complete",
        tokens_used=registry.extraction_usage["tokens_in"] + registry.extraction_usage["tokens_out"],
        cost_usd=registry.extraction_usage["cost_usd"],
        notes=(f"correlate: {len(registry.claims)} claims from {len(corpus)} docs "
               f"({len(batch and batches)} batches); proposals in prior_proposals.json"),
    )
    bus.publish("stream:results", result.model_dump())
    print(f"[{ROLE}] done: {len(registry.claims)} claims, ${result.cost_usd:.4f} model spend")

def main() -> None:
    bus = Bus(); sessions = SessionStore(); artifacts = ArtifactStore()
    model = ModelAdapter(); provider = RetrievalProvider()
    print(f"[{ROLE}] online")
    bus.consume_forever(task_stream(ROLE), f"group-{ROLE}",
                        lambda b: handle(bus, sessions, artifacts, model, provider, b))

if __name__ == "__main__":
    main()
