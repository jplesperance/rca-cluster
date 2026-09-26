"""
Retrieval provider wrapper. Isolates Tavily specifics behind one interface so
the recon agents never import the SDK directly — provider stays swappable
(DECISIONS: Exa evaluated later for technical-analysis source class).

Also centralizes the two cross-cutting concerns every retrieval provider needs:
retry-with-backoff on transient errors, and egress isolation (this is the only
module besides the queue that opens outbound connections in recon agents).
"""
from __future__ import annotations
import os
import time
from typing import Any

class RetrievalProvider:
    """Thin wrapper over Tavily. Raises RuntimeError after exhausting retries
    so callers translate it into a failed ResultMessage rather than crashing."""

    MAX_ATTEMPTS = 3

    def __init__(self):
        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            raise RuntimeError("TAVILY_API_KEY not set")
        from tavily import TavilyClient
        self._client = TavilyClient(api_key=api_key)

    def search(self, query: str, max_results: int = 8) -> list[dict[str, Any]]:
        last_exc: Exception | None = None
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                resp = self._client.search(
                    query=query,
                    search_depth="advanced",
                    max_results=max_results,
                    include_raw_content=False,
                )
                return list(resp.get("results", []))
            except Exception as exc:  # transient provider errors: back off and retry
                last_exc = exc
                if attempt < self.MAX_ATTEMPTS:
                    time.sleep(2 ** attempt)
        raise RuntimeError(f"Tavily retrieval failed after {self.MAX_ATTEMPTS} attempts: {last_exc}")
