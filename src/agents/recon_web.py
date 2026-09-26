"""
Recon agent, source class: general web (Tavily). Stateless consumer for role
'recon.web'. Implements the contract: directive -> search -> graded sources ->
ResultMessage with artifact-store content_refs.

Failure taxonomy: provider hard-failure after retries -> status 'failed', no
sources, error in notes. Partial degradation (some results unusable) -> status
'partial'. Normal completion -> 'complete'.

Token accounting is ESTIMATED (len/4 heuristic) — flag for correction when
model-calling agents land in Sprint 4+. Cost is tracked in Tavily API calls
plus an operator-configurable per-call rate.
"""
from __future__ import annotations
import os
import time
from datetime import datetime, timezone
from src.common.models import TaskMessage, ResultMessage, SourceRecord
from src.common.queue import Bus, task_stream
from src.common.store import ArtifactStore
from src.common.grading import grade_source
from src.common.retrieval import RetrievalProvider

ROLE = "recon.web"
MAX_RESULTS = 8
# Update to match your plan's per-query cost; placeholder default, verify
# against your Tavily billing page before trusting ledger figures.
PER_CALL_COST_USD = float(os.environ.get("TAVILY_PER_CALL_USD", "0.01"))

def _slugify(text: str, maxlen: int = 48) -> str:
    s = "".join(c if c.isalnum() or c in "-_" else "-" for c in text.lower()).strip("-")
    return s[:maxlen] or "result"

def handle(bus: Bus, artifacts: ArtifactStore, provider: RetrievalProvider,
           task_body: dict) -> None:
    task = TaskMessage(**task_body)
    print(f"[{ROLE}] received {task.task_id[:8]}: {task.directive}")

    try:
        raw_results = provider.search(task.directive, max_results=MAX_RESULTS)
    except RuntimeError as exc:
        result = ResultMessage(
            session_id=task.session_id,
            task_id=task.task_id,
            status="failed",
            notes=f"retrieval failure: {exc}",
        )
        bus.publish("stream:results", result.model_dump())
        print(f"[{ROLE}] FAILED {task.task_id[:8]}: {exc}")
        return

    sources: list[SourceRecord] = []
    skipped = 0
    tokens_est = 0
    for i, r in enumerate(raw_results, start=1):
        url = r.get("url", "")
        content = r.get("content") or ""
        if not url or not content:
            skipped += 1
            continue
        sid = f"S-{i:03d}-{task.task_id[:4]}"
        rel = f"web/{_slugify(task.directive)}-{i:02d}.txt"
        header = (
            f"source_url: {url}\n"
            f"title: {r.get('title', '')}\n"
            f"retrieved_via: tavily query='{task.directive}'\n"
            f"retrieved_at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
            f"---\n"
        )
        full_text = header + content
        tokens_est += len(full_text) // 4
        content_ref = artifacts.write_content(task.session_id, rel, full_text)
        tier, note = grade_source(url)
        sources.append(SourceRecord(
            source_id=sid,
            url=url,
            source_class="general_web",
            content_ref=content_ref,
            credibility_tier=tier,
            excerpt=content[:300],
        ))

    status = "complete" if not skipped else "partial"
    result = ResultMessage(
        session_id=task.session_id,
        task_id=task.task_id,
        status=status,
        sources=sources,
        tokens_used=tokens_est,
        cost_usd=PER_CALL_COST_USD,
        notes=(f"tavily: {len(sources)} graded, {skipped} skipped (empty). "
               f"tokens are len/4 estimates."),
    )
    bus.publish("stream:results", result.model_dump())
    print(f"[{ROLE}] {status}: {len(sources)} sources for {task.task_id[:8]}")

def main() -> None:
    bus = Bus()
    artifacts = ArtifactStore()
    provider = RetrievalProvider()
    print(f"[{ROLE}] online, consuming {task_stream(ROLE)}")
    bus.consume_forever(
        task_stream(ROLE),
        f"group-{ROLE}",
        lambda body: handle(bus, artifacts, provider, body),
    )

if __name__ == "__main__":
    main()
