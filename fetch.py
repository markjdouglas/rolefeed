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

from ats import ADAPTERS

RESOLVED = "companies.resolved.yaml"
SNAPSHOT = pathlib.Path("data/jobs.json")

# ---------------------------------------------------------------------------
# Matching rules. These are the product. Everything else is plumbing.
# ---------------------------------------------------------------------------

# Titles worth looking at. Ops leadership plus small-org general management.
TITLE_INCLUDE = re.compile(
    r"""
    \b(
        (director|head|vp|vice\s+president)[\s,]+(of\s+)?(global\s+|business\s+)?operations
      | operations\s+(director|lead(er)?)
      | (chief\s+operating\s+officer|coo)
      | (general\s+manager|managing\s+director)
      | (director|head)[\s,]+(of\s+)?strategy\s+(and|&)\s+operations
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
    r"\b(new\s+london|london,\s*(on|ontario|ky|kentucky)|ukraine"
    r"|united\s+states|usa|u\.s\.|canada|india|singapore|australia"
    r"|germany|france|spain|netherlands|poland|brazil|japan|remote\s*-\s*us)\b",
    re.IGNORECASE,
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
    """Fetch every employer. Returns (postings, names that failed)."""
    postings: list[dict] = []
    failures: list[str] = []

    for index, company in enumerate(companies, start=1):
        name = company["name"]
        ats_name = company["ats"]
        slug = company["slug"]
        fetcher = ADAPTERS.get(ats_name)
        if not fetcher:
            failures.append(f"{name} (unknown ats: {ats_name})")
            continue
        try:
            found = fetcher(slug, company=name)
        except Exception as exc:  # noqa: BLE001 - one employer must not stop the run
            failures.append(f"{name} ({type(exc).__name__})")
            print(f"  [{index:3}] {name:34} failed: {exc}", file=sys.stderr)
            continue
        postings.extend(found)
        print(f"  [{index:3}] {name:34} {len(found):4} roles", file=sys.stderr)
        time.sleep(0.4)

    return postings, failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect and filter job postings.")
    parser.add_argument("--all", action="store_true", help="show every role, unfiltered")
    parser.add_argument("--json", action="store_true", help="also write data/jobs.json")
    args = parser.parse_args()

    try:
        with open(RESOLVED) as handle:
            config = yaml.safe_load(handle)
    except FileNotFoundError:
        print(f"{RESOLVED} not found. Run `python discover.py` first.", file=sys.stderr)
        return 1

    companies = config.get("companies", [])
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

    if args.all:
        results = unique
    else:
        results = [
            p for p in unique
            if matches_title(p["title"]) and matches_location(p["location"])
        ]

    results.sort(key=lambda p: (p["company"], p["title"]))

    print()
    print("=" * 108)
    print(f"{'COMPANY':22} {'TITLE':48} {'LOCATION':22} ATS")
    print("=" * 108)
    for posting in results:
        print(
            f"{posting['company'][:21]:22} "
            f"{posting['title'][:47]:48} "
            f"{posting['location'][:21]:22} "
            f"{posting['ats']}"
        )
        print(f"{'':22} {posting['url']}")
    print("=" * 108)

    print(
        f"\n{len(results)} matching roles from {len(unique)} total "
        f"across {len(companies) - len(failures)} employers."
    )
    if failures:
        print(f"{len(failures)} employers failed: {', '.join(failures[:8])}")

    if args.json:
        SNAPSHOT.parent.mkdir(exist_ok=True)
        snapshot = {
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "employers_queried": len(companies),
            "total_roles": len(unique),
            "matching_roles": len(results),
            "failures": failures,
            "jobs": results,
        }
        SNAPSHOT.write_text(json.dumps(snapshot, indent=2) + "\n")
        print(f"Snapshot written to {SNAPSHOT}.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
