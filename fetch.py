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
SIZE_ORDER = ("enterprise", "large", "mid", "scaleup", "startup")
SIZE_LABELS = {
    "enterprise": "ENTERPRISE  (5,000+)",
    "large": "LARGE  (1,000-5,000)",
    "mid": "MID  (250-1,000)",
    "scaleup": "SCALEUP  (50-250)",
    "startup": "STARTUP  (10-50)",
}


# ---------------------------------------------------------------------------
# Matching rules. These are the product. Everything else is plumbing.
# ---------------------------------------------------------------------------

# Titles, classified into three tiers rather than accepted or rejected.
#
# Title inflation runs opposite to company size: "Head of Operations" at a 30-person
# startup is a hands-on job, while at Deliveroo it runs a department. A single
# accept/reject rule cannot express that, so each posting gets a tier and the UI
# filters on it. This also fixed the yield problem — 4 matches from 319 was the
# filter, not the market.

TIER_EXEC = re.compile(
    r"""
    \b(
        chief\s+\w+\s+officer | coo\b | cfo\b | cco\b
      | (vp|vice\s+president)[\s,]+(of\s+)?\w+
      | managing\s+director | general\s+manager | country\s+(manager|lead|director)
      | (svp|evp)\b
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

TIER_DIRECTOR = re.compile(
    r"""
    \b(
        director | head[\s,]+of | (^|\s)head\b
      | (global|group|regional|market|city)\s+(lead|manager)
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

TIER_MID = re.compile(
    r"""
    \b(
        senior\s+(manager|lead|programme|program|project)
      | (lead|principal|staff)\s+\w+
      | \w+\s+lead\b | manager\b | \blead\b
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# The domain has to be right whatever the tier. This is the "is it an operations job"
# test, kept separate from the "how senior is it" test.
DOMAIN = re.compile(
    r"""
    \b(
        operations | operational | ops\b
      | marketplace | supply | logistics | fulfil?ment | freight | fleet
      | courier | rider | driver\s+(experience|supply) | dispatch
      | expansion | launch | new\s+markets? | market\s+development
      | partnerships? | commercial | programme|program\s+management
      | charging | network | depot | hub | last\s+mile | city | regional | region
      | chief\s+operating\s+officer | coo\b
      | general\s+manager | managing\s+director | country\s+manager
      | strategy\s+(and|&)\s+operations | business\s+operations
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Wrong job despite the right words. Checked before anything else.
TITLE_EXCLUDE = re.compile(
    r"""
    \b(
        engineer(ing)? | developer | devops | sre | architect | scientist | analyst
      | security\s+operations | network\s+engineer | it\s+operations | infrastructure
      | trading\s+operations | clinical | nurse | nursing | pharmac
      | account\s+(executive|manager) | sales\s+(rep|development|manager|director)
      | marketing | recruit(er|ment) | talent\s+(acquisition|partner)
      | people\s+operations | hr\b | finance\s+(manager|director|lead)
      | sales\s+operations | revenue\s+operations | marketing\s+operations
      # These only ever matched when followed by manager/director/lead, so
      # "Finance Operations Lead" passed the domain test on the word
      # "operations" and was then caught by the mid tier. Same shape as the
      # sales/people/revenue cases above, which were already handled.
      | (finance|financial|legal|payroll|procurement|talent|hr)\s+operations
      | warehouse\s+(operative|associate) | picker | packer
      # Courier, rider and driver are the jobs being managed — unless the title is
      # about managing them, which the lookahead allows through.
      | (driver|rider|courier)(?!\s+(operations|experience|supply|network|strategy|
         acquisition|engagement|partnerships?))\b
      | retail\s+store | restaurant | kitchen | barista
      | intern(ship)? | apprentice | graduate | placement | trainee
      | assistant | coordinator | administrator | receptionist | advisor
      | customer\s+(service|support)\s+(agent|advisor|representative)
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def title_tier(title: str) -> str | None:
    """Return 'exec', 'director', 'mid', or None if this is not an operations role.

    Order matters: exclusions first, then the domain test, then seniority from the top
    down so "VP Operations" is exec rather than being caught by the mid-tier pattern.
    """
    if not title or TITLE_EXCLUDE.search(title):
        return None
    if not DOMAIN.search(title):
        return None
    if TIER_EXEC.search(title):
        return "exec"
    if TIER_DIRECTOR.search(title):
        return "director"
    if TIER_MID.search(title):
        return "mid"
    return None


def matches_title(title: str) -> bool:
    """Kept for the tests and the terminal view: any tier counts as a match."""
    return title_tier(title) is not None


# ---------------------------------------------------------------------------
# Geography. Two ways in, and only two:
#   1. The role is in the UK.
#   2. The role is remote AND the region it is remote *within* is inside GMT ±3.
#
# A Berlin office role is neither, so it is out. "Remote - Europe" is in. This is
# stricter than the previous rule, which admitted any role whose location mentioned
# "remote" regardless of where that remote was anchored.
# ---------------------------------------------------------------------------

UK = re.compile(
    r"\b(london|united\s+kingdom|u\.k\.|uk|england|scotland|wales|"
    r"northern\s+ireland|britain|gb\b|manchester|birmingham|leeds|bristol|glasgow|"
    r"edinburgh|cardiff|belfast|cambridge|oxford|reading|hatfield|milton\s+keynes)\b",
    re.IGNORECASE,
)

REMOTE = re.compile(r"\b(remote|anywhere|distributed|work\s+from\s+home|wfh|hybrid)\b",
                    re.IGNORECASE)

# Regions whose standard offset sits within three hours of GMT/BST. A three-hour
# spread is the practical limit for a shared working day: it still leaves a five-hour
# overlap with UK hours.
TZ_OK = re.compile(
    r"""
    \b(
        emea | europe | european | eu\b | uk\b | gmt | bst | cet | cest | wet | eet
      | ie\b | de\b | fr\b | es\b | pt\b | nl\b | be\b | se\b | dk\b | no\b | fi\b
      | ireland | dublin | portugal | lisbon | spain | madrid | barcelona
      | france | paris | germany | berlin | munich | netherlands | amsterdam
      | belgium | brussels | luxembourg | switzerland | zurich | geneva
      | italy | rome | milan | austria | vienna | denmark | copenhagen
      | sweden | stockholm | norway | oslo | finland | helsinki | iceland
      | poland | warsaw | krakow | czech | prague | slovakia | hungary | budapest
      | romania | bucharest | bulgaria | sofia | greece | athens | croatia | serbia
      | estonia | tallinn | latvia | riga | lithuania | vilnius
      | turkey | istanbul | israel | tel\s+aviv
      | south\s+africa | cape\s+town | johannesburg | nigeria | lagos | ghana | accra
      | kenya | nairobi | egypt | cairo | morocco | casablanca | tunisia
      | brazil | s[aã]o\s+paulo | argentina | buenos\s+aires | cape\s+verde
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Regions definitively outside GMT ±3. Checked first, because a posting reading
# "Remote - US, UK" should not qualify on the strength of the word remote.
TZ_BAD = re.compile(
    r"""
    \b(
        united\s+states | usa | u\.s\.a? | us\b | americas | latam | nam\b
      | north\s+america | south\s+america | canada | toronto | vancouver
      | mexico | chile | colombia | peru
      | apac | asia | india | bengaluru | bangalore | mumbai | delhi | hyderabad
      | pakistan | philippines | manila | vietnam | thailand | indonesia | jakarta
      | singapore | malaysia | hong\s+kong | china | shanghai | beijing | shenzhen
      | japan | tokyo | korea | seoul | taiwan | australia | sydney | melbourne
      | new\s+zealand | auckland
      | uae | dubai | abu\s+dhabi | saudi | riyadh | qatar | doha
      | new\s+london | london,\s*(on|ontario|ky|kentucky) | ukraine
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


# Places that contain a UK place name but are not in the UK. Checked before anything
# else, because "London, Ontario" would otherwise match the UK pattern and win.
UK_IMPOSTORS = re.compile(
    r"\b(new\s+london|london,\s*(on|ontario|ky|kentucky|oh|ohio)|"
    r"londonderry,\s*(nh|vt)|birmingham,\s*(al|alabama|mi)|"
    r"manchester,\s*(nh|ct|new\s+hampshire)|cambridge,\s*(ma|massachusetts)|"
    r"bristol,\s*(ct|ri|tn)|boston,\s*(ma|massachusetts))\b",
    re.IGNORECASE,
)


def location_verdict(location: str) -> tuple[bool, str]:
    """Return (in_scope, reason). The reason is kept on the posting so a surprising
    inclusion or exclusion can be explained later without re-deriving it."""
    if not location:
        # No location given. Keep it rather than silently dropping a possible London
        # role, but label it so it can be filtered in the UI.
        return True, "unstated"

    # Impostors first. A UK place name in another country must not qualify.
    if UK_IMPOSTORS.search(location):
        return False, "uk-impostor"

    bad = bool(TZ_BAD.search(location))
    uk = bool(UK.search(location))

    # A posting naming both the UK and somewhere far away is usually a genuinely
    # multi-site role, so the UK mention wins.
    if uk:
        return True, "uk"
    if bad:
        return False, "outside-tz"
    if REMOTE.search(location):
        if TZ_OK.search(location):
            return True, "remote-in-tz"
        # Bare "Remote" with no region at all. Keep, flagged: it is frequently a
        # UK or European employer being lazy, and dropping them loses real roles.
        return True, "remote-unspecified"
    return False, "not-uk"


def matches_location(location: str) -> bool:
    return location_verdict(location)[0]


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
    unresolved = config.get("unresolved", [])
    employers_total = len(companies) + len(unresolved)

    # Build the coverage record before any --size or --sector filter narrows the run,
    # so the published picture is always the whole employer list rather than whatever
    # slice this invocation happened to ask for.
    coverage = [
        {
            "name": c.get("name"),
            "size": c.get("size"),
            "sector": c.get("sector"),
            "ats": c.get("ats"),
            "open_roles": c.get("open_roles", 0),
        }
        for c in companies
    ] + [
        {
            "name": c.get("name"),
            "size": c.get("size"),
            "sector": c.get("sector"),
            "ats": None,
            "open_roles": 0,
        }
        for c in unresolved
    ]
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
    in_scope = []
    for posting in unique:
        ok, reason = location_verdict(posting["location"])
        if not ok:
            continue
        # The verdict's reason is why this location was accepted — "London",
        # "UK remote" and so on. The front end reads it for the match-reason line
        # under each role; it was being computed and thrown away, so every card
        # fell back to the generic "Location accepted".
        posting["geo"] = reason
        tier = title_tier(posting["title"])
        if tier is None:
            posting["tier"] = None
            posting["priority"] = False
        else:
            posting["tier"] = tier
            # "Priority" is the shortlist-worthy set: leadership scope, not every
            # operations role. Mid-tier stays in the feed and gets its own filter.
            posting["priority"] = tier in ("exec", "director")
        in_scope.append(posting)

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
        word = "employer" if len(failures) == 1 else "employers"
        print(f"\n{len(failures)} {word} unavailable: {', '.join(failures[:10])}")
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
            employers_total=employers_total,
            failures=failures,
            total_roles_seen=len(unique),
            coverage=coverage,
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
