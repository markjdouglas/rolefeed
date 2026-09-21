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

import re
import time
from datetime import datetime, timedelta, timezone
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
    posted_reliable: bool = False,
) -> dict:
    """The one shape every adapter returns. Keep this stable — everything depends on it.

    `posted_reliable` matters more than it looks. Lever, Ashby and SmartRecruiters
    return a genuine publication date. Greenhouse returns `updated_at`, which moves
    every time an employer fixes a typo, so a three-month-old role looks brand new.
    Treating those two as the same field is what made every "new" count identical.
    """
    return {
        "company": company,
        "ats": ats,
        "external_id": str(external_id),
        "title": (title or "").strip(),
        "location": (location or "").strip(),
        "url": url,
        "posted_at": posted_at,
        "posted_reliable": posted_reliable,
    }


# ---------------------------------------------------------------------------
# Greenhouse
# Docs: https://docs.greenhouse.io/job-board.html
# Roughly half of tech-sector employers. The cleanest of the four.
# ---------------------------------------------------------------------------

def fetch_greenhouse(token: str, company: str | None = None) -> list[dict]:
    # Greenhouse runs a separate EU-hosted estate for customers with data-residency
    # requirements, on its own API host. European employers frequently live there and
    # return 404 on the US host, so try both before concluding a token is wrong.
    hosts = ("boards-api.greenhouse.io", "boards-api.eu.greenhouse.io")
    payload = None
    for host in hosts:
        response = _get(f"https://{host}/v1/boards/{token}/jobs", params={"content": "false"})
        if response.status_code == 200:
            candidate = response.json()
            if candidate.get("jobs"):
                payload = candidate
                break
    if payload is None:
        return []
    return [
        _posting(
            company=company or token,
            ats="greenhouse",
            external_id=job["id"],
            title=job.get("title", ""),
            location=(job.get("location") or {}).get("name", ""),
            url=job.get("absolute_url", ""),
            # Greenhouse's board API exposes only updated_at, which changes on any
            # edit. Kept for reference, but not trusted for recency.
            posted_at=job.get("first_published") or job.get("updated_at"),
            posted_reliable=bool(job.get("first_published")),
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
                posted_reliable=posted_at is not None,
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
            posted_reliable=bool(job.get("publishedAt")),
        )
        for job in payload.get("jobs", [])
    ]


# ---------------------------------------------------------------------------
# SmartRecruiters
# More common among European enterprises than the other three.
# ---------------------------------------------------------------------------

def fetch_smartrecruiters(token: str, company: str | None = None) -> list[dict]:
    """SmartRecruiters caps a single response at 100 postings and expects you to page.

    This was silently losing roles. Sixt, Delivery Hero and Grab each reported exactly
    100 — the cap, not their true count. An employer landing precisely on a page
    boundary is the signature of un-paged collection, so treat any adapter returning a
    suspiciously round number as unpaged until proven otherwise.

    The response carries `totalFound`, so we page on `offset` until we have them all.
    PAGE_CAP stops a misreported total turning into an unbounded loop against an API
    nobody is charging us for.
    """
    url = f"https://api.smartrecruiters.com/v1/companies/{token}/postings"
    PAGE_CAP = 12
    raw_jobs: list[dict] = []
    offset = 0
    for _ in range(PAGE_CAP):
        response = _get(url, params={"limit": 100, "offset": offset})
        if response.status_code != 200:
            break
        payload = response.json()
        batch = payload.get("content") or []
        raw_jobs.extend(batch)
        total = payload.get("totalFound")
        offset += len(batch)
        # Stop on a short page, an exhausted total, or an empty page. Any one of the
        # three is sufficient; relying on `totalFound` alone trusts the server too much.
        if len(batch) < 100 or not batch:
            break
        if isinstance(total, int) and offset >= total:
            break
    if not raw_jobs:
        return []
    postings = []
    for job in raw_jobs:
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
                posted_reliable=bool(job.get("releasedDate")),
            )
        )
    return postings


# ---------------------------------------------------------------------------
# Teamtailor
#
# Added after finding it on IAG Cargo, having wrongly written it off as closed. Every
# Teamtailor career site publishes an open JSON Feed at /jobs.json — no key, no auth —
# and each item embeds a full schema.org JobPosting with a genuine `datePosted` and a
# structured address. That makes it the best-quality source of the six.
#
# It is also discoverable: sites live at {token}.teamtailor.com even when the employer
# fronts them with a custom domain, so discover.py can probe it like the others.
#
# Common among UK, Nordic and European employers — exactly the segment the original
# four adapters missed.
# ---------------------------------------------------------------------------

def fetch_teamtailor(token: str, company: str | None = None) -> list[dict]:
    # A pinned custom domain wins; otherwise derive the standard subdomain.
    base = token if token.startswith("http") else f"https://{token}.teamtailor.com"
    response = _get(f"{base}/jobs.json")
    if response.status_code != 200:
        return []
    try:
        payload = response.json()
    except ValueError:
        return []

    postings = []
    for item in payload.get("items", []):
        jp = item.get("_jobposting") or {}

        # Location comes from the embedded JobPosting's address, which is structured
        # rather than a free-text blob — locality plus ISO country code.
        location = ""
        places = jp.get("jobLocation") or []
        if isinstance(places, dict):
            places = [places]
        parts = []
        for place in places[:2]:
            addr = (place or {}).get("address") or {}
            bits = [addr.get("addressLocality"), addr.get("addressCountry")]
            joined = ", ".join(b for b in bits if b)
            if joined:
                parts.append(joined)
        location = " / ".join(parts)

        posted = jp.get("datePosted") or item.get("date_published")
        postings.append(
            _posting(
                company=company or token,
                ats="teamtailor",
                external_id=str((jp.get("identifier") or {}).get("value") or item.get("id", "")),
                title=item.get("title", ""),
                location=location,
                url=item.get("url", ""),
                posted_at=posted,
                posted_reliable=bool(posted),
            )
        )
    return postings


# ---------------------------------------------------------------------------
# Workday
#
# How most enterprise employers hire — airlines, airports, rail and bus operators,
# parcel majors, car rental groups. There is no public API and no documentation. What
# exists is the endpoint the career site's own front end calls, which returns clean JSON:
#
#   POST https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
#
# Three consequences worth understanding before relying on it:
#   1. It is undocumented, so it can change shape without notice. Treat a sudden drop to
#      zero roles as suspected breakage, not as an employer with no vacancies.
#   2. Tenant, Workday instance number and site name cannot be guessed reliably, so these
#      employers are configured by hand from their careers URL. Use add_workday.py.
#   3. It paginates in pages of 20, so a large employer costs several requests.
# ---------------------------------------------------------------------------

WORKDAY_REL = re.compile(r"(\d+)\+?\s+(day|week|month)s?\s+ago", re.IGNORECASE)


def workday_posted(text: str | None) -> tuple[str | None, bool]:
    """Workday returns prose: "Posted 3 Days Ago", "Posted 30+ Days Ago", "Posted Today".

    Converted to an approximate ISO date. Approximate is still far better than nothing
    for a 24-hour recency window, and "Posted Today" is exact.
    """
    if not text:
        return None, False
    now = datetime.now(timezone.utc)
    low = text.lower()
    if "today" in low:
        return now.isoformat(timespec="seconds"), True
    if "yesterday" in low:
        return (now - timedelta(days=1)).isoformat(timespec="seconds"), True
    m = WORKDAY_REL.search(low)
    if not m:
        return None, False
    n = int(m.group(1))
    days = {"day": 1, "week": 7, "month": 30}[m.group(2)] * n
    return (now - timedelta(days=days)).isoformat(timespec="seconds"), True


WORKDAY_URL = re.compile(
    r"https://(?P<tenant>[\w-]+)\.(?P<instance>wd\d+)\.myworkdayjobs\.com"
    r"/(?:[\w-]+/)?(?P<site>[\w-]+)"
)


def parse_workday_url(url: str) -> dict | None:
    """Turn a Workday careers URL into the config the adapter needs.

    Accepts either the human career site URL or the CXS endpoint:
      https://iag.wd3.myworkdayjobs.com/en-US/IAG_Careers
      https://iag.wd3.myworkdayjobs.com/IAG_Careers
    """
    match = WORKDAY_URL.match(url.strip())
    if not match:
        return None
    parts = match.groupdict()
    # A locale segment such as en-US is optional in the URL; the regex skips it, but if
    # the site group captured the locale itself the URL had no site, which is unusable.
    if re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts["site"]):
        return None
    return parts


def fetch_workday(config: dict | str, company: str | None = None) -> list[dict]:
    """Fetch a Workday board. `config` is the dict from parse_workday_url, or that URL."""
    if isinstance(config, str):
        parsed = parse_workday_url(config)
        if not parsed:
            return []
        config = parsed

    tenant = config["tenant"]
    instance = config["instance"]
    site = config["site"]
    base = f"https://{tenant}.{instance}.myworkdayjobs.com"
    endpoint = f"{base}/wday/cxs/{tenant}/{site}/jobs"

    postings: list[dict] = []
    offset = 0
    page = 20
    while offset < 400:  # cap: no employer needs more than 400 roles pulled per run
        response = requests.post(
            endpoint,
            headers={**HEADERS, "Content-Type": "application/json"},
            json={"appliedFacets": {}, "limit": page, "offset": offset, "searchText": ""},
            timeout=TIMEOUT,
        )
        if response.status_code != 200:
            break
        payload = response.json()
        batch = payload.get("jobPostings", [])
        if not batch:
            break
        for job in batch:
            external = job.get("externalPath", "")
            # bulletFields usually carries the employer's own requisition id.
            bullets = job.get("bulletFields") or []
            postings.append(
                _posting(
                    company=company or tenant,
                    ats="workday",
                    external_id=bullets[0] if bullets else external,
                    title=job.get("title", ""),
                    location=job.get("locationsText", ""),
                    url=f"{base}/en-US/{site}{external}",
                    **dict(zip(("posted_at", "posted_reliable"),
                               workday_posted(job.get("postedOn")))),
                )
            )
        if len(batch) < page:
            break
        offset += page
        time.sleep(PAUSE)

    return postings


# The registry every other script uses. Add a new adapter here and it is picked up
# by both discover.py and fetch.py with no further wiring.
#
# Workday is excluded from this registry deliberately: it cannot be probed by guessing a
# token, so discover.py must not try it. It is called directly by fetch.py for employers
# that carry a `workday_url`.
ADAPTERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "smartrecruiters": fetch_smartrecruiters,
    "teamtailor": fetch_teamtailor,
}
