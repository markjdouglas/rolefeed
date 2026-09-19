"""
Adapters for public applicant tracking system (ATS) job board endpoints.

Every adapter has the same contract:

    fetch_<ats>(token: str) -> list[dict]

It returns a list of postings in a single normalised shape, so everything downstream
stops caring which ATS a job came from. If the token is unknown or the board is empty,
it returns an empty list. If the endpoint itself is broken it raises, and the caller
decides what to do — one employer failing must never stop the whole run.

All four endpoints below are public and require no API key.
"""

from __future__ import annotations

import time
from typing import Any

import requests

# A real User-Agent is basic courtesy and stops some endpoints refusing us outright.
HEADERS = {
    "User-Agent": "RoleFeed/0.1 (personal job search; +https://github.com/markjdouglas/rolefeed)",
    "Accept": "application/json",
}

TIMEOUT = 20  # seconds before we give up on a single request
PAUSE = 0.4   # seconds between requests, so we are a polite client


def _get(url: str, **kwargs: Any) -> requests.Response:
    """GET with a timeout, our headers, and one retry on a transient failure.

    429 means "too many requests", 5xx means the server is having a bad time.
    Both are worth retrying once after a pause. Anything else we return as-is and
    let the caller inspect the status code.
    """
    for attempt in (1, 2):
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT, **kwargs)
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == 1:
                time.sleep(2)
                continue
        return response
    return response  # pragma: no cover - unreachable, satisfies type checkers


def _posting(
    *,
    company: str,
    ats: str,
    external_id: str,
    title: str,
    location: str,
    url: str,
    posted_at: str | None = None,
) -> dict:
    """The one shape every adapter returns. Keep this stable — everything depends on it."""
    return {
        "company": company,
        "ats": ats,
        "external_id": str(external_id),
        "title": (title or "").strip(),
        "location": (location or "").strip(),
        "url": url,
        "posted_at": posted_at,
    }


# ---------------------------------------------------------------------------
# Greenhouse
# Docs: https://docs.greenhouse.io/job-board.html
# Roughly half of tech-sector employers. The cleanest of the four.
# ---------------------------------------------------------------------------

def fetch_greenhouse(token: str, company: str | None = None) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    response = _get(url, params={"content": "false"})
    if response.status_code != 200:
        return []
    payload = response.json()
    return [
        _posting(
            company=company or token,
            ats="greenhouse",
            external_id=job["id"],
            title=job.get("title", ""),
            location=(job.get("location") or {}).get("name", ""),
            url=job.get("absolute_url", ""),
            posted_at=job.get("updated_at"),
        )
        for job in payload.get("jobs", [])
    ]


# ---------------------------------------------------------------------------
# Lever
# Docs: https://github.com/lever/postings-api
# ---------------------------------------------------------------------------

def fetch_lever(token: str, company: str | None = None) -> list[dict]:
    url = f"https://api.lever.co/v0/postings/{token}"
    response = _get(url, params={"mode": "json"})
    if response.status_code != 200:
        return []
    payload = response.json()
    if not isinstance(payload, list):
        return []
    postings = []
    for job in payload:
        categories = job.get("categories") or {}
        # Lever gives createdAt in milliseconds since the epoch, not seconds.
        created = job.get("createdAt")
        posted_at = None
        if isinstance(created, (int, float)):
            posted_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(created / 1000))
        postings.append(
            _posting(
                company=company or token,
                ats="lever",
                external_id=job.get("id", ""),
                title=job.get("text", ""),
                location=categories.get("location", ""),
                url=job.get("hostedUrl", ""),
                posted_at=posted_at,
            )
        )
    return postings


# ---------------------------------------------------------------------------
# Ashby
# Common among companies founded after roughly 2020.
# ---------------------------------------------------------------------------

def fetch_ashby(token: str, company: str | None = None) -> list[dict]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    response = _get(url)
    if response.status_code != 200:
        return []
    payload = response.json()
    return [
        _posting(
            company=company or token,
            ats="ashby",
            external_id=job.get("id", ""),
            title=job.get("title", ""),
            location=job.get("location", ""),
            url=job.get("jobUrl", ""),
            posted_at=job.get("publishedAt"),
        )
        for job in payload.get("jobs", [])
    ]


# ---------------------------------------------------------------------------
# SmartRecruiters
# More common among European enterprises than the other three.
# ---------------------------------------------------------------------------

def fetch_smartrecruiters(token: str, company: str | None = None) -> list[dict]:
    url = f"https://api.smartrecruiters.com/v1/companies/{token}/postings"
    response = _get(url, params={"limit": 100})
    if response.status_code != 200:
        return []
    payload = response.json()
    postings = []
    for job in payload.get("content", []):
        loc = job.get("location") or {}
        city = loc.get("city") or ""
        country = loc.get("country") or ""
        if loc.get("remote"):
            city = f"{city} (remote)".strip()
        postings.append(
            _posting(
                company=company or token,
                ats="smartrecruiters",
                external_id=job.get("id", ""),
                title=job.get("name", ""),
                location=", ".join(p for p in (city, country.upper()) if p),
                url=(job.get("ref") or "").replace(
                    "api.smartrecruiters.com/v1/companies", "jobs.smartrecruiters.com"
                ) or f"https://jobs.smartrecruiters.com/{token}/{job.get('id', '')}",
                posted_at=job.get("releasedDate"),
            )
        )
    return postings


# The registry every other script uses. Add a new adapter here and it is picked up
# by both discover.py and fetch.py with no further wiring.
ADAPTERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "smartrecruiters": fetch_smartrecruiters,
}
