# RoleFeed — project memory for Claude Code

Read this at the start of every session. It is the standing brief.

## What this is

A scheduled job-listings collector. It queries public applicant tracking system (ATS)
endpoints for a curated list of 169 transport, logistics, mobility and aviation
employers, filters for senior operations roles, groups them by company size, and writes
them to a Google Sheet that doubles as the interface.

Two goals, in order:
1. **Educational.** Mark is Director of Operations at Apolitical, product-focused and
   semi-technical, not an engineer. He is learning git, GitHub, CI/CD, APIs and
   deployment by building this. Explain what you are doing and why. Prefer boring,
   legible code over clever code.
2. **Useful.** He is on gardening leave until 04/11/2026 and needs a new role.

## How to work with Mark

- British English. Short declarative sentences. Verdict first, then reasoning.
- Explain esoteric terms on first use. He does not need elementary explanations, but he
  does need the vocabulary named.
- Attach confidence levels (high / moderate / low / unknown) to empirical claims,
  especially about undocumented endpoints.
- Do not agree reflexively. If a decision is wrong, say so and explain the mechanism.
- Never invent an API response shape. Probe the endpoint and read what comes back.

## Priority

The build matters more than the matching criteria. Mark has said explicitly: the main
hypothesis is whether this approach is viable, tested by pulling the data and getting an
Alpha standing up. Criteria are cheap to change later. Do not spend budget perfecting
filters or chasing the last few employer tokens while Phases 1 and 2 are unbuilt.

## Hard constraints

- **Total build budget: 5 hours.** Scope is cut to fit, not extended.
- **No custom front end.** The Google Sheet is the UI. No Next.js, no React, no Vercel.
- **No database.** Google Sheets is the store. Postgres only if writable state is needed
  later, which it currently is not.
- **No paid APIs.** No RapidAPI, Apify, Fantastic Jobs or similar aggregators.
- **No LinkedIn.** No public jobs search API exists, and scraping it is both against
  terms of service and actively defended. Do not attempt it.
- **No secrets in the repo.** Credentials live in GitHub Actions secrets and a local
  `.env` that `.gitignore` excludes.
- JSON-LD / schema.org JobPosting parsing is **explicitly parked** at Mark's request.
  Do not add it without being asked.

## Scope

**Sectors in**: ride-hail, micromobility, last-mile delivery, freight and forwarding,
fulfilment and warehousing, EV charging, fleet and telematics, public transport, aviation
and space, autonomous vehicles. Sector-agnostic within that — the transferable capability
is marketplace supply, network operations and infrastructure programmes.

**Out**: govtech, policy, charity, fintech, generic SaaS. Employers under ~50 people.

**Never targets** — previous employers: Uber, Gett, Glue Home, Ontruck, ParkBee, Otto Car,
POSTX, Apolitical, Abercrombie & Fitch.

**Company size** is tagged on every employer and every posting, and results print largest
bucket first. Mark prefers established companies and is not interested in startups.

**Geography**: London, or UK-wide remote.

**Seniority floor**: director level and above. "Operations Manager" is noise.

See SPEC.md for the full title include and exclude rules. They are provisional and
expected to be tuned once real volume is visible — do not treat them as settled.

## Architecture

```
companies.yaml          curated employer list (the core asset)
  ↓ discover.py         probes each candidate slug against 4 ATSs, resolves where the board lives
companies.resolved.yaml verified employer → ATS → board token mapping
  ↓ fetch.py            pulls postings, filters, dedupes, scores
data/jobs.json          committed snapshot (gives free history via git diff)
  ↓ sheets.py           writes new and changed rows to the Google Sheet
Google Sheet            Mark's interface: filter, sort, shortlist, dismiss
```

Scheduling runs on **GitHub Actions** (`.github/workflows/collect.yml`), not Vercel —
Vercel's Hobby plan caps cron jobs at once per day, which defeats the purpose.

## ATS endpoints

All four core adapters are public and need no authentication.

| ATS | Endpoint |
|---|---|
| Greenhouse | `https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` |
| Lever | `https://api.lever.co/v0/postings/{token}?mode=json` |
| Ashby | `https://api.ashbyhq.com/posting-api/job-board/{token}` |
| SmartRecruiters | `https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100` |

Two things learned the hard way, both now handled — do not regress them:
- Tokens are untidy. ShipBob is `shipbobinc`, Aurora Innovation is `aurorainnovation`,
  Neuron Mobility is `neuron`. discover.py generates variants.
- Greenhouse runs a separate EU estate at `boards-api.eu.greenhouse.io`. Try both hosts.

**Workday is the fifth adapter** and the only route to enterprise employers. No public
API — it calls the endpoint the career site's own front end uses. Tenant, instance and
site cannot be guessed, so those employers are hand-configured via `add_workday.py` from
a careers URL. It is undocumented and will break without notice, so a drop to zero roles
is suspected breakage, not an empty board.

Unsupported and not worth fighting: SuccessFactors, Taleo, iCIMS, Cornerstone, Bullhorn.
If a careers URL matches none of the five, note it and move on.

## Phase plan

- **Phase 0** (90 min) — `discover.py` + `fetch.py`. Prints matching roles grouped by
  company size. Purpose: prove the data is there. **Second pass ready to run.**
- **Phase 1** — Google Cloud service account, `sheets.py`, rows land in the Sheet.
- **Phase 2** — GitHub Actions workflow, secrets, first automated run. With Phase 1,
  this is the Alpha, and it is the priority.
- **Phase 3** — `first_seen` / `last_seen`, scoring, staleness alarm.
- **Phase 4** — Workday employers configured. Employer list corrected.

## Conventions

- Python 3.14 (Homebrew, at `/opt/homebrew/bin/python3`). Create the venv with that
  explicit path — plain `python3` resolves to Apple's 3.9.6 because macOS `path_helper`
  puts `/usr/bin` ahead of `/opt/homebrew/bin`.
- Dependencies pinned in `requirements.txt`.
- Every adapter is a function with the same signature returning the same dict shape.
  One adapter failing must never stop the run.
- Be polite to endpoints: a short delay between requests, a real User-Agent, and
  retry-with-backoff on 429 or 5xx.
- Commit messages: imperative mood, one line, explain why not what.

## Environment facts worth not rediscovering

- Neither the cloud sandbox nor the Cowork desktop Linux VM can reach ATS endpoints; both
  have restricted egress. Mark's own terminal can. Run `discover.py` and `fetch.py` there.
- git identity is the `markjdouglas@users.noreply.github.com` alias, deliberately, to keep
  his address off a public repo.
- GitHub account is `markjdouglas`; repo is `markjdouglas/rolefeed`, public.
