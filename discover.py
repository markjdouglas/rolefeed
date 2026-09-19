"""
Work out where each employer's job board actually lives.

companies.yaml holds guessed board tokens. This script probes each guess against all
four ATS endpoints and records which combination returns real jobs. The output,
companies.resolved.yaml, is what fetch.py reads.

Run it whenever you add employers to companies.yaml:

    python discover.py

It is deliberately slow — roughly four requests per employer with a pause between
each. Around 500 requests for a 125-employer list, so expect four or five minutes.
Politeness matters more than speed here; these are free endpoints run by other people.

Expect a hit rate of somewhere between a third and a half on first run. The misses are
not failures — they are employers whose token differs from their name, or who use one
of the other dozen ATSs. Fix those by hand: open the careers page, read the URL, and
pin `ats:` and `slug:` on that entry in companies.yaml.
"""

from __future__ import annotations

import sys
import time

import yaml

from ats import ADAPTERS

SOURCE = "companies.yaml"
OUTPUT = "companies.resolved.yaml"


def probe(name: str, slug: str) -> tuple[str, int] | None:
    """Try every ATS for this slug. Return the first that yields jobs, and how many."""
    for ats_name, fetcher in ADAPTERS.items():
        try:
            postings = fetcher(slug, company=name)
        except Exception as exc:  # noqa: BLE001 - a broken endpoint must not stop the sweep
            print(f"    {ats_name:16} error: {type(exc).__name__}", file=sys.stderr)
            continue
        finally:
            time.sleep(0.4)
        if postings:
            return ats_name, len(postings)
    return None


def main() -> int:
    with open(SOURCE) as handle:
        config = yaml.safe_load(handle)

    companies = config.get("companies", [])
    resolved: list[dict] = []
    unresolved: list[dict] = []

    print(f"Probing {len(companies)} employers across {len(ADAPTERS)} ATS endpoints.\n")

    for index, company in enumerate(companies, start=1):
        name = company["name"]
        slug = company["slug"]
        pinned = company.get("ats")

        print(f"[{index:3}/{len(companies)}] {name}")

        if pinned:
            # Already known — verify it still works rather than probing all four.
            try:
                postings = ADAPTERS[pinned](slug, company=name)
            except Exception as exc:  # noqa: BLE001
                print(f"    pinned {pinned} raised {type(exc).__name__}")
                postings = []
            if postings:
                print(f"    ✓ {pinned} ({len(postings)} open roles, pinned)")
                resolved.append({**company, "ats": pinned, "open_roles": len(postings)})
            else:
                print("    ✗ pinned token returned nothing — check it by hand")
                unresolved.append(company)
            time.sleep(0.4)
            continue

        hit = probe(name, slug)
        if hit:
            ats_name, count = hit
            print(f"    ✓ {ats_name} ({count} open roles)")
            resolved.append({**company, "ats": ats_name, "open_roles": count})
        else:
            print("    ✗ no match on any endpoint")
            unresolved.append(company)

    with open(OUTPUT, "w") as handle:
        yaml.safe_dump(
            {"companies": resolved, "unresolved": unresolved},
            handle,
            sort_keys=False,
            allow_unicode=True,
        )

    total = len(companies)
    found = len(resolved)
    roles = sum(c.get("open_roles", 0) for c in resolved)
    print(
        f"\nResolved {found} of {total} employers "
        f"({found / total:.0%}), covering {roles} open roles."
    )
    print(f"Written to {OUTPUT}.")
    if unresolved:
        print(
            f"\n{len(unresolved)} unresolved. Fix the highest-value ones by hand — open "
            "their careers page, read the ATS and token out of the URL, and pin them in "
            f"{SOURCE}."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
