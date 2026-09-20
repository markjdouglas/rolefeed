"""
Work out where each employer's job board actually lives.

companies.yaml holds a candidate board token per employer. Real tokens are frequently
untidy — ShipBob is `shipbobinc`, Aurora Innovation is `aurorainnovation`, Neuron
Mobility is just `neuron` — so probing the tidy name alone has a poor hit rate. This
script generates variants of each candidate and probes them against all four ATS
endpoints, stopping at the first that returns actual jobs.

    python discover.py                # probe everything unpinned
    python discover.py --workers 12   # more concurrency (default 8)
    python discover.py --only freight # one sector

Output is companies.resolved.yaml, which fetch.py reads.

Employers with `ats:` already set in companies.yaml are verified rather than probed,
costing one request instead of forty. Pin every token you confirm by hand — it makes
every subsequent run faster and stops the hit rate regressing.
"""

from __future__ import annotations

import argparse
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml

from ats import ADAPTERS, fetch_workday

SOURCE = "companies.yaml"
OUTPUT = "companies.resolved.yaml"

# Suffixes that employers commonly append to a board token. Kept short deliberately:
# every extra suffix multiplies the request count across four endpoints, and tokens that
# do not match in the first handful of forms almost never match at all.
SUFFIXES = ("inc", "hq", "io")

# One lock per host, so concurrency across employers never means hammering one endpoint.
_host_locks = {name: threading.Lock() for name in ADAPTERS}


def variants(name: str, slug: str) -> list[str]:
    """Candidate tokens for one employer, most likely first, no duplicates.

    Derived from both the given slug and the display name, because which one matches
    varies: 'Neuron Mobility' resolves on `neuron`, 'Aurora Innovation' on the full
    `aurorainnovation`.
    """
    words = re.findall(r"[a-z0-9]+", name.lower())
    joined = "".join(words)
    hyphenated = "-".join(words)
    first = words[0] if words else ""

    # Bare forms first — these catch the large majority of real tokens.
    ordered = [slug, joined, hyphenated]

    # The first word alone is a genuine pattern ('Neuron Mobility' → `neuron`), but a
    # short generic word risks landing on an unrelated company's board and silently
    # attributing their jobs to this employer. Six characters is the cutoff: it keeps
    # `neuron` and drops `free`, `cargo`, `via` and `snap`.
    if first != joined and len(first) >= 6:
        ordered.append(first)

    # Then suffixed forms of the two most likely bases only.
    for suffix in SUFFIXES:
        for base in (slug, joined):
            if base and not base.endswith(suffix):
                ordered.append(f"{base}{suffix}")

    out: list[str] = []
    for candidate in ordered:
        if candidate and candidate not in out:
            out.append(candidate)
    return out


def token_forms(ats_name: str, token: str) -> list[str]:
    """SmartRecruiters tokens are case-sensitive and usually capitalised; the rest are not."""
    if ats_name != "smartrecruiters":
        return [token]
    forms = [token, token.capitalize(), token.upper(), token.title().replace("-", "")]
    seen: list[str] = []
    for form in forms:
        if form not in seen:
            seen.append(form)
    return seen


def call(ats_name: str, token: str, company: str) -> list[dict]:
    """One probe, serialised per host and paced."""
    fetcher = ADAPTERS[ats_name]
    with _host_locks[ats_name]:
        try:
            result = fetcher(token, company=company)
        except Exception:  # noqa: BLE001 - a dead endpoint must not stop the sweep
            result = []
        time.sleep(0.25)
    return result


def resolve(company: dict) -> dict:
    """Probe one employer. Returns the entry with `ats`, `slug` and `open_roles` set."""
    name = company["name"]
    pinned = company.get("ats")

    # Workday employers are configured by hand from a careers URL, never probed — there
    # is no token to guess. Pass them straight through so fetch.py still sees them, and
    # count an unconfigured one as resolved-but-empty rather than a discovery failure.
    if pinned == "workday":
        url = company.get("workday_url")
        if not url or url == "TODO":
            return {**company, "open_roles": 0, "needs_config": True}
        postings = fetch_workday(url, company=name)
        return {**company, "open_roles": len(postings)}

    if pinned:
        for token in token_forms(pinned, company["slug"]):
            found = call(pinned, token, name)
            if found:
                return {**company, "ats": pinned, "slug": token, "open_roles": len(found)}
        return {**company, "open_roles": 0}

    for token in variants(name, company["slug"]):
        for ats_name in ADAPTERS:
            for form in token_forms(ats_name, token):
                found = call(ats_name, form, name)
                if found:
                    entry = {
                        **company,
                        "ats": ats_name,
                        "slug": form,
                        "open_roles": len(found),
                    }
                    # A hit on anything other than the obvious forms is worth a human
                    # glance — it may be the right board, or another company entirely.
                    words = re.findall(r"[a-z0-9]+", name.lower())
                    if form.lower() not in (company["slug"], "".join(words), "-".join(words)):
                        entry["verify"] = True
                    return entry
    return {**company, "open_roles": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve employer job boards.")
    parser.add_argument("--workers", type=int, default=8, help="concurrent employers")
    parser.add_argument("--only", help="limit to one sector")
    args = parser.parse_args()

    with open(SOURCE) as handle:
        companies = yaml.safe_load(handle).get("companies", [])

    if args.only:
        companies = [c for c in companies if c.get("sector") == args.only]

    if not companies:
        print("No employers to probe.", file=sys.stderr)
        return 1

    print(
        f"Probing {len(companies)} employers across {len(ADAPTERS)} ATS endpoints "
        f"with {args.workers} workers. Pinned entries are verified, not probed.\n"
    )
    started = time.time()

    resolved: list[dict] = []
    unresolved: list[dict] = []
    done = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(resolve, company): company for company in companies}
        for future in as_completed(futures):
            entry = future.result()
            done += 1
            if entry.get("open_roles"):
                resolved.append(entry)
                print(
                    f"[{done:3}/{len(companies)}] ✓ {entry['name']:26} "
                    f"{entry['ats']:16} {entry['slug']:24} {entry['open_roles']:4} roles"
                )
            elif entry.get("needs_config"):
                unresolved.append(entry)
                print(
                    f"[{done:3}/{len(companies)}] · {entry['name']:26} "
                    "workday — needs a careers URL (add_workday.py)"
                )
            else:
                unresolved.append(entry)
                print(f"[{done:3}/{len(companies)}] ✗ {entry['name']}")

    resolved.sort(key=lambda c: -c["open_roles"])
    unresolved.sort(key=lambda c: c["name"])

    with open(OUTPUT, "w") as handle:
        yaml.safe_dump(
            {"companies": resolved, "unresolved": unresolved},
            handle,
            sort_keys=False,
            allow_unicode=True,
        )

    total = len(companies)
    roles = sum(c["open_roles"] for c in resolved)
    elapsed = time.time() - started
    print(
        f"\nResolved {len(resolved)} of {total} ({len(resolved) / total:.0%}), "
        f"covering {roles} open roles, in {elapsed / 60:.1f} minutes."
    )
    print(f"Written to {OUTPUT}.")

    if resolved:
        by_ats: dict[str, int] = {}
        for entry in resolved:
            by_ats[entry["ats"]] = by_ats.get(entry["ats"], 0) + 1
        print("By ATS: " + ", ".join(f"{k} {v}" for k, v in sorted(by_ats.items())))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
