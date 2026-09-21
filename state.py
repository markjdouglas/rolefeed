"""
Turn a snapshot of open roles into a feed with history.

A single fetch tells you what is open right now. That is much less useful than knowing
what is *new*, and "new" only exists if something remembers what it saw last time.

This module does that remembering. It merges a fresh fetch into the previous published
feed, so every role carries:

    first_seen   the first run in which RoleFeed saw it — this is what "new" means
    last_seen    the most recent run in which it was still listed
    missing_runs consecutive runs in which it has disappeared

`posted_at` from the ATS is not a substitute. Greenhouse returns `updated_at`, which
changes when an employer edits a description. Lever gives a creation timestamp, Ashby
sometimes gives nothing, and Workday's format varies. `first_seen` is ours, consistent
across all five adapters, and monotonic.

A role that has been missing for two consecutive runs is treated as closed and dropped.
Two rather than one, because a single flaky response from an endpoint should not delete
a live role from the feed.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone

# The published feed. Lives under site/ because that directory is what gets deployed —
# on a private repo the page cannot fetch its data from GitHub, so the JSON has to ship
# as part of the site itself.
FEED = pathlib.Path("site/data/jobs.json")

# Consecutive misses before a role is considered closed.
MISSING_LIMIT = 2

# The collector's schedule, used to tell the page when to expect the next run.
RUN_INTERVAL_HOURS = 2


def effective_date(job: dict) -> tuple[str, str]:
    """The date recency should be judged on, and where it came from.

    Prefers the employer's real publication date when the adapter vouches for it
    (Lever, Ashby, SmartRecruiters, Teamtailor and Workday all provide one). Falls back
    to `first_seen` otherwise — which is every Greenhouse role, because Greenhouse's
    board API exposes only `updated_at` and that moves on any edit.

    This distinction is the reason the counts were previously identical: with
    `first_seen` as the only clock and history starting on day one, every role was
    simultaneously new, hot and new-this-week. A real posted date spreads them out.
    """
    posted = job.get("posted_at")
    if posted and job.get("posted_reliable"):
        return posted, "posted"
    return job.get("first_seen", ""), "first_seen"


def load_previous(path: pathlib.Path = FEED) -> dict[str, dict]:
    """Previous feed, keyed for merging. Returns {} on a first run or unreadable file."""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        # A corrupt feed should not stop a collection. We lose history, which is bad,
        # but a failed run would be worse — and the next run rebuilds from here.
        return {}
    return {job["key"]: job for job in payload.get("jobs", []) if "key" in job}


def merge(
    fresh: list[dict],
    previous: dict[str, dict],
    *,
    now: datetime | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """Fold a fresh fetch into the previous feed.

    Returns (jobs, counts). `jobs` is the new feed contents; `counts` reports what
    changed, which is what the run summary and the staleness alarm are built from.
    """
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="seconds")

    merged: list[dict] = []
    new_count = 0

    seen_keys = set()
    for job in fresh:
        key = f"{job['ats']}:{job['company']}:{job['external_id']}"
        seen_keys.add(key)
        prior = previous.get(key)

        entry = dict(job)
        entry["key"] = key
        entry["last_seen"] = stamp
        entry["missing_runs"] = 0

        if prior:
            # Keep the original sighting. This is the whole point of the module.
            entry["first_seen"] = prior.get("first_seen", stamp)
        else:
            entry["first_seen"] = stamp
            new_count += 1

        # Resolved once here so the page never has to reason about which clock to use.
        entry["effective_date"], entry["date_basis"] = effective_date(entry)
        merged.append(entry)

    # Roles that were in the previous feed but not this fetch. Give them grace before
    # deleting, so one bad response does not wipe live roles.
    closed_count = 0
    for key, prior in previous.items():
        if key in seen_keys:
            continue
        misses = prior.get("missing_runs", 0) + 1
        if misses >= MISSING_LIMIT:
            closed_count += 1
            continue
        carried = dict(prior)
        carried["missing_runs"] = misses
        merged.append(carried)

    # Newest first. That is the order Mark actually wants to read in, because the
    # 48-hour application window is the thing that matters.
    merged.sort(key=lambda j: (j.get("effective_date") or j.get("first_seen", ""),
                               j.get("company", "")), reverse=True)

    counts = {
        "total": len(merged),
        "new_this_run": new_count,
        "closed_this_run": closed_count,
        "carried_missing": sum(1 for j in merged if j.get("missing_runs", 0) > 0),
    }
    return merged, counts


def recent_count(jobs: list[dict], hours: int = 48) -> int:
    """How many roles are newer than `hours`, judged on the effective date."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    count = 0
    for job in jobs:
        raw = job.get("effective_date") or job.get("first_seen")
        if not raw:
            continue
        try:
            when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when >= cutoff:
            count += 1
    return count


def write_feed(
    jobs: list[dict],
    counts: dict[str, int],
    *,
    employers_queried: int,
    employers_total: int | None = None,
    failures: list[str] | None = None,
    total_roles_seen: int,
    coverage: list[dict] | None = None,
    path: pathlib.Path = FEED,
) -> dict:
    """Write the published feed, including the metadata the page's header needs."""
    now = datetime.now(timezone.utc)
    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        # Advisory only. GitHub Actions scheduled runs are frequently late under load,
        # so the page must present this as "due", never as a promise.
        "next_due_at": (now + timedelta(hours=RUN_INTERVAL_HOURS)).isoformat(
            timespec="seconds"
        ),
        "run_interval_hours": RUN_INTERVAL_HOURS,
        # Two different numbers, and conflating them overstates coverage:
        # `queried` is the boards we can actually reach, `total` is the employer
        # list. The gap between them is the unresolved pile.
        "employers_queried": employers_queried,
        "employers_total": employers_total or employers_queried,
        "employers_failed": len(failures or []),
        "failures": (failures or [])[:20],
        "total_roles_seen": total_roles_seen,
        "matching_roles": counts["total"],
        "new_this_run": counts["new_this_run"],
        "closed_this_run": counts["closed_this_run"],
        "new_last_24h": recent_count(jobs, 24),
        "new_last_48h": recent_count(jobs, 48),
        "new_last_7d": recent_count(jobs, 24 * 7),
        "new_last_30d": recent_count(jobs, 24 * 30),
        # How much of the feed carries a real publication date rather than a fallback.
        # Worth surfacing: a low number means the recency figures are soft.
        "dated_from_source": sum(1 for j in jobs if j.get("date_basis") == "posted"),
        # Every employer on the list, reachable or not, with the system it was reached
        # through. Publishing the unreachable pile matters more than it looks: an
        # employer that is silently absent is indistinguishable from an employer with
        # no vacancies, and 149 of 211 absent is the difference between "the market is
        # quiet" and "we cannot see most of the market". Without this the feed's own
        # coverage is an unmeasured assumption.
        "coverage": coverage or [],
        "jobs": jobs,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload
