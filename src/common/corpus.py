"""
Dedup layer. Collapses retrieval events into a distinct-document corpus keyed
by sha256(normalized URL). Each document accumulates its retrieval context —
which hypotheses and source classes surfaced it — which is signal, not noise:
core-corpus docs (multiple branches) vs class-specific color. Full-text cache
is stored under artifacts/{session}/fulltext/{doc_hash}.txt; extraction reads
cached text when present, excerpt otherwise.
"""
from __future__ import annotations
import hashlib
from urllib.parse import urlparse, urlunparse

def normalize_url(url: str) -> str:
    p = urlparse(url.strip().lower())
    return urlunparse((p.scheme, p.netloc, p.path.rstrip("/"), "", "", ""))

def doc_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()[:16]

def build_corpus(source_index: dict[str, dict]) -> dict[str, dict]:
    """source_index (from SessionState) -> {doc_hash: {...}} with merged
    retrieval events."""
    corpus: dict[str, dict] = {}
    for sid, meta in source_index.items():
        h = doc_hash(meta["url"])
        if h not in corpus:
            corpus[h] = {
                "doc_hash": h,
                "url": meta["url"],
                "source_class": meta["source_class"],
                "credibility_tier": meta["credibility_tier"],
                "source_ids": [],
                "source_classes": set(),
                "content_ref": meta["content_ref"],
            }
        corpus[h]["source_ids"].append(sid)
        corpus[h]["source_classes"].add(meta["source_class"])
        # every source_index entry is task-derived; task -> hypothesis mapping
        # comes from state.tasks_dispatched via the from_task field if wired,
        # otherwise pass tree separately
    for d in corpus.values():
        d["source_classes"] = sorted(d["source_classes"])
    return corpus
