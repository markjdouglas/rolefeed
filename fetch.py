"""
Pull every open role from the resolved employer list, filter it down to roles worth
applying for, and print the survivors.

    python fetch.py                  # matching roles only
    python fetch.py --all            # every role, so you can sanity-check the filter
    python fetch.py --json           # write data/jobs.json as well

This is Phase 0. There is no Google Sheet and no scheduling yet. The only question it
exists to answer is whether the endpoints surface roles Mark would actually apply for.
If the answer is no, the rest of the project is not worth building.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
from datetime import datetime, timezone

import yaml

from ats import ADAPTERS, fetch_workday
from state import FEED, load_previous, merge, write_feed

RESOLVED = "companies.resolved.yaml"

# Company size buckets, largest first — results are grouped and ordered by these.
SIZE_ORDER = ("enterprise", "large", "mid", "scaleup")
SIZE_LABELS = {
    "enterprise": "ENTERPRISE  (5,000+)",
    "large": "LARGE  (1,000-5,000)",
    "mid": "MID  (250-1,000)",
    "scaleup": "SCALEUP  (50-250)",
}


# ---------------------------------------------------------------------------
# Matching rules. These are the product. Everything else is plumbing.
# ---------------------------------------------------------------------------

# Titles worth looking at. Ops leadership plus small-org general management.
TITLE_INCLUDE = re.compile(
    r"""
    \b(
      # Core operations leadership
        (director|head|vp|vice\s+president)[\s,]+(of\s+)?
        (global\s+|business\s+|commercial\s+|central\s+)?operations
      # Bare "Operations Director/Lead", but NOT when a qualifier in front makes it a
      # different job. Without this guard, "Finance Operations Lead" and "People
      # Operations Lead" both match.
      | (?<!finance\s)(?<!people\s)(?<!revenue\s)(?<!sales\s)(?<!talent\s)
        (?<!business\s)(?<!security\s)(?<!technical\s)(?<!clinical\s)
        \boperations\s+(director|lead(er)?)
      | (chief\s+operating\s+officer|coo)
      | (general\s+manager|managing\s+director|country\s+manager)
      | (director|head)[\s,]+(of\s+)?strategy\s+(and|&)\s+operations

      # Mobility and marketplace phrasing for the same job — the Gett role verbatim
      | (director|head|vp)[\s,]+(of\s+)?
        (marketplace|supply|driver|courier|rider|fleet|partner|city|regional|
         market|network|delivery|logistics|charging)\s+operations
      | (marketplace|supply|fleet|partner|network)\s+operations\s+(director|lead)

      # Launch, expansion and market-building — the Otto Car and Uber city work
      | (director|head|vp)[\s,]+(of\s+)?(expansion|launch|new\s+markets?|
         market\s+development|city\s+operations)
      | (regional|city|market)\s+(director|general\s+manager|lead)

      # Partner and programme leadership with an infrastructure flavour
      | (director|head)[\s,]+(of\s+)?(strategic\s+)?partnerships
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Titles that contain the right words but are the wrong job. Checked after the include,
# so anything matching here is dropped even if the include matched.
TITLE_EXCLUDE = re.compile(
    r"""
    \b(
        engineer(ing)? | developer | devops | sre | platform
      | security\s+operations | network\s+operations | it\s+operations
      | trading\s+operations | clinical | nurse | nursing
      | sales | account\s+(executive|manager) | marketing | recruit
      | warehouse | driver | retail\s+store | restaurant | kitchen
      | intern | apprentice | graduate | placement
      | assistant | coordinator | administrator | executive\s+assistant
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Locations that count. London, UK-wide, or genuinely remote.
LOCATION_INCLUDE = re.compile(
    r"\b(london|united\s+kingdom|uk|england|remote|hybrid|anywhere)\b",
    re.IGNORECASE,
)

# Locations that look UK-ish but are not. Guards against "New London", "UKraine" and
# remote roles pinned to another continent.
LOCATION_EXCLUDE = re.compile(
    r"""
    \b(
        new\s+london | london,\s*(on|ontario|ky|kentucky) | ukraine
      | united\s+states | usa | u\.s\.a? | us          # bare "US" catches
      | north\s+america | latam | apac                   # "Remote - Central US"
      | canada | india | singapore | australia | new\s+zealand
      | germany | france | spain | netherlands | poland | portugal
      | brazil | mexico | japan | china | israel | uae | dubai
      | sweden | denmark | norway | finland | ireland | switzerland
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def matches_title(title: str) -> bool:
    if TITLE_EXCLUDE.search(title):
        return False
    return bool(TITLE_INCLUDE.search(title))


def matches_location(location: str) -> bool:
    if not location:
        return True  # no location given is not a reason to discard; flag it instead
    if LOCATION_EXCLUDE.search(location):
        return False
    return bool(LOCATION_INCLUDE.search(location))


def dedupe_key(posting: dict) -> str:
    """Stable identity for a posting, so the same role is never counted twice.

    ATS plus external id is unique and survives a title being edited, which a hash of
    the title would not.
    """
    return f"{posting['ats']}:{posting['company']}:{posting['external_id']}"


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

def collect(companies: list[dict]) -> tuple[list[dict], list[str]]:
    """Fetch every employer. Returns (postings, names that failed).

    Each posting is tagged with the employer's size and sector from the list, so results
    can be grouped by company type rather than arriving as one undifferentiated pile.
    """
    postings: list[dict] = []
    failures: list[str] = []

    for index, company in enumerate(companies, start=1):
        name = company["name"]
        ats_name = company.get("ats")

        try:
            if ats_name == "workday":
                url = company.get("workday_url")
                if not url or url == "TODO":
                    failures.append(f"{name} (workday_url not set)")
                    continue
                found = fetch_workday(url, company=name)
            else:
                fetcher = ADAPTERS.get(ats_name)
                if not fetcher:
                    failures.append(f"{name} (unknown ats: {ats_name})")
                    continue
                found = fetcher(company["slug"], company=name)
        except Exception as exc:  # noqa: BLE001 - one employer must not stop the run
            failures.append(f"{name} ({type(exc).__name__})")
            print(f"  [{index:3}] {name:34} failed: {exc}", file=sys.stderr)
            continue

        for posting in found:
            posting["size"] = company.get("size", "unknown")
            posting["sector"] = company.get("sector", "unknown")
        postings.extend(found)
        print(f"  [{index:3}] {name:34} {len(found):4} roles", file=sys.stderr)
        time.sleep(0.4)

    return postings, failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect and filter job postings.")
    parser.add_argument("--all", action="store_true", help="show every role, unfiltered")
    parser.add_argument("--json", action="store_true",
                        help="merge into site/data/jobs.json, preserving first_seen")
    parser.add_argument("--size", help="one bucket only: enterprise, large, mid, scaleup")
    parser.add_argument("--sector", help="one sector only")
    args = parser.parse_args()

    try:
        with open(RESOLVED) as handle:
            config = yaml.safe_load(handle)
    except FileNotFoundError:
        print(f"{RESOLVED} not found. Run `python discover.py` first.", file=sys.stderr)
        return 1

    companies = config.get("companies", [])
    if args.size:
        companies = [c for c in companies if c.get("size") == args.size]
    if args.sector:
        companies = [c for c in companies if c.get("sector") == args.sector]
    if not companies:
        print(f"No resolved employers in {RESOLVED}.", file=sys.stderr)
        return 1

    print(f"Fetching {len(companies)} employers.\n", file=sys.stderr)
    postings, failures = collect(companies)

    # Deduplicate, keeping the first occurrence of each key.
    seen: dict[str, dict] = {}
    for posting in postings:
        seen.setdefault(dedupe_key(posting), posting)
    unique = list(seen.values())

    # Everything in the right geography goes into the feed. `priority` records whether
    # it also passes the title filter.
    #
    # Publishing the wider set deliberately: it makes the title filter tunable in the
    # browser instead of in Python, so refining it costs a click rather than a code
    # change and a twenty-minute re-run. It also makes the rejected pile visible, which
    # is the only way to tell an over-tight filter from a genuinely empty market.
    in_scope = [p for p in unique if matches_location(p["location"])]
    for posting in in_scope:
        posting["priority"] = matches_title(posting["title"])

    published = in_scope
    results = in_scope if args.all else [p for p in in_scope if p["priority"]]

    # Group by company size, largest employers first. Mark is less interested in small
    # companies, so the ordering puts the relevant buckets at the top of the output.
    for bucket in SIZE_ORDER:
        rows = [p for p in results if p.get("size") == bucket]
        if not rows:
            continue
        rows.sort(key=lambda p: (p["sector"], p["company"], p["title"]))
        print()
        print("=" * 104)
        print(f"  {SIZE_LABELS[bucket]}  —  {len(rows)} role(s)")
        print("=" * 104)
        for posting in rows:
            print(
                f"{posting['company'][:21]:22} "
                f"{posting['title'][:46]:47} "
                f"{posting['location'][:20]:21} "
                f"{posting['sector']}"
            )
            print(f"{'':22} {posting['url']}")

    unbucketed = [p for p in results if p.get("size") not in SIZE_ORDER]
    if unbucketed:
        print(f"\n  Unbucketed — {len(unbucketed)} role(s)")
        for posting in unbucketed:
            print(f"    {posting['company']:22} {posting['title']}")

    print()
    print(
        f"{len(results)} shown / {len(in_scope)} in scope (UK or remote) "
        f"from {len(unique)} total across {len(companies) - len(failures)} employers."
    )
    counts = {b: sum(1 for p in results if p.get("size") == b) for b in SIZE_ORDER}
    print("By size: " + ", ".join(f"{b} {n}" for b, n in counts.items() if n))
    if failures:
        print(f"\n{len(failures)} employers unavailable: {', '.join(failures[:10])}")
        if len(failures) > 10:
            print(f"  ...and {len(failures) - 10} more")

    if args.json:
        # Merge into the previous feed so first_seen survives, then publish.
        previous = load_previous()
        jobs, counts = merge(published, previous)
        write_feed(
            jobs,
            counts,
            employers_queried=len(companies),
            failures=failures,
            total_roles_seen=len(unique),
        )
        priority_total = sum(1 for j in jobs if j.get("priority"))
        print(
            f"\nFeed written to {FEED}: {counts['total']} UK/remote roles "
            f"({priority_total} title-matched), "
            f"{counts['new_this_run']} new this run, "
            f"{counts['closed_this_run']} closed."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
