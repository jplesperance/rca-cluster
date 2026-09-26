"""
Deterministic source grading for Sprint 2 — placeholder until the LLM-assisted
rubric lands with the verifier (Sprint 5). Tier assignment at collection time
per the verifier rubric's Layer-1 table; verifier may downgrade, never upgrade.

Heuristic order matters: most-specific patterns first. Unknown domains default
to 'secondary' for news-looking URLs (contains 'news'), else 'speculative'.
"""
from __future__ import annotations
import re
from urllib.parse import urlparse

# Domains whose content is presumptively primary-grade per the rubric table.
PRIMARY_DOMAINS = (
    "sec.gov", "hhs.gov", "ocrportal.hhs.gov", "justice.gov", "courtlistener.org",
    "psc.gov", "nist.gov", "cisa.gov", "us-cert.cisa.gov", "gdpr.eu",
    "ico.org.uk", "europa.eu", "gao.gov",
)
SECONDARY_DOMAINS = (
    "krebsonsecurity.com", "bleepingcomputer.com", "therecord.media",
    "darkreading.com", "threatpost.com", "securityweek.com", "thehackernews.com",
    "reuters.com", "apnews.com", "wsj.com", "ft.com", "bloomberg.com",
    "nytimes.com", "washingtonpost.com", "techcrunch.com", "arstechnica.com",
)
SPECULATIVE_PATTERNS = (
    re.compile(r"(twitter|x)\.com", re.I),
    re.compile(r"reddit\.com", re.I),
    re.compile(r"\.substack\.com$", re.I),
    re.compile(r"medium\.com", re.I),
    re.compile(r"(youtube|discord|telegram)", re.I),
)

def grade_source(url: str) -> tuple[str, str]:
    """Returns (credibility_tier, grader_note). Deterministic; no model call."""
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if any(host == d or host.endswith("." + d) for d in PRIMARY_DOMAINS):
        return "primary", "domain on primary allowlist"
    if any(host == d or host.endswith("." + d) for d in SECONDARY_DOMAINS):
        return "secondary", "domain on secondary (established press) allowlist"
    for pat in SPECULATIVE_PATTERNS:
        if pat.search(url):
            return "speculative", "social/aggregator platform pattern"
    if "news" in host:
        return "secondary", "unknown domain, news-signaling hostname"
    return "speculative", "unknown domain — defaulted speculative"
