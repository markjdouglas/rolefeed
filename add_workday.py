"""
Configure a Workday employer from its careers URL.

Workday tenant names, instance numbers and site names cannot be guessed, so these
employers are set up by hand — once each, permanently. This makes that a ten-second job.

    python add_workday.py "https://iag.wd3.myworkdayjobs.com/en-US/IAG_Careers"

It parses the URL, calls the endpoint to prove the configuration works, reports how many
roles are live, and prints the exact YAML line to paste into companies.yaml.

Finding the URL: open the employer's careers page, click through to the job search, and
look at the address bar. If it contains `myworkdayjobs.com`, that is the URL you want.
If it does not, the employer is on SuccessFactors, Taleo or iCIMS, none of which RoleFeed
supports — note it and move on rather than fighting it.

    python add_workday.py --check          # re-verify every configured Workday employer
"""

from __future__ import annotations

import argparse
import sys

import yaml

from ats import fetch_workday, parse_workday_url

SOURCE = "companies.yaml"


def show(url: str) -> int:
    config = parse_workday_url(url)
    if not config:
        print("That is not a Workday careers URL.", file=sys.stderr)
        print(
            "Expected something like "
            "https://tenant.wd3.myworkdayjobs.com/en-US/Site_Name",
            file=sys.stderr,
        )
        return 1

    print(f"tenant   {config['tenant']}")
    print(f"instance {config['instance']}")
    print(f"site     {config['site']}")
    print("\nCalling the endpoint to verify...")

    postings = fetch_workday(config)
    if not postings:
        print(
            "\nNo roles came back. Either the site name is wrong, or this board is empty. "
            "Open the careers page and check the URL again.",
            file=sys.stderr,
        )
        return 1

    print(f"✓ {len(postings)} roles found. First three:\n")
    for posting in postings[:3]:
        print(f"    {posting['title']}  —  {posting['location']}")

    print("\nPaste this into companies.yaml, adjusting name, sector and size:\n")
    print(
        f"  - {{ name: NAME, slug: {config['tenant']}, sector: SECTOR, size: SIZE, "
        f"ats: workday, workday_url: \"{url}\" }}"
    )
    return 0


def check() -> int:
    with open(SOURCE) as handle:
        companies = yaml.safe_load(handle).get("companies", [])

    configured = [
        c for c in companies
        if c.get("ats") == "workday" and c.get("workday_url") not in (None, "TODO")
    ]
    todo = [
        c for c in companies
        if c.get("ats") == "workday" and c.get("workday_url") in (None, "TODO")
    ]

    if not configured:
        print("No Workday employers configured yet.")
    for company in configured:
        postings = fetch_workday(company["workday_url"], company=company["name"])
        mark = "✓" if postings else "✗"
        print(f"  {mark} {company['name']:32} {len(postings):4} roles")

    if todo:
        print(f"\n{len(todo)} awaiting a URL:")
        for company in todo:
            print(f"    {company['name']}")
        print("\nRun: python add_workday.py \"<careers URL>\" for each.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure a Workday employer.")
    parser.add_argument("url", nargs="?", help="the employer's Workday careers URL")
    parser.add_argument("--check", action="store_true", help="verify configured employers")
    args = parser.parse_args()

    if args.check:
        return check()
    if not args.url:
        parser.print_help()
        return 1
    return show(args.url)


if __name__ == "__main__":
    raise SystemExit(main())
