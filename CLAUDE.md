# RoleFeed — project memory for Claude Code

Read this at the start of every session. It is the standing brief.

## What this is

A scheduled job-listings collector. It queries public applicant tracking system (ATS)
endpoints for a curated list of employers, filters for roles Mark would actually apply
for, and writes them to a Google Sheet that doubles as the interface.

Two goals, in order:
1. **Educational.** This is a learning project.
   Mark is learning git, GitHub, CI/CD, APIs and
   deployment by building this. Explain what you are doing and why. Prefer boring,
   legible code over clever code.
2. **Useful.** A working job search.

## How to work with Mark

- British English. Short declarative sentences. Verdict first, then reasoning.
- Explain esoteric terms on first use. He does not need elementary explanations, but he
  does need the vocabulary named.
- Attach confidence levels (high / moderate / low / unknown) to empirical claims,
  especially about undocumented endpoints.
- Do not agree reflexively. If a decision is wrong, say so and explain the mechanism.
- Never invent an API response shape. Probe the endpoint and read what comes back.

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

## Search criteria

**Titles to match** — operations leadership and small-org general management:
Director of Operations, Operations Director, Head of Operations, VP Operations,
Director of Business Operations, COO, Chief Operating Officer, General Manager,
Managing Director.

**Titles to exclude** — these share keywords but are the wrong job:
anything containing Engineer, Engineering, Developer, Sales, Account, Marketing,
Warehouse, Driver, Retail Store, Restaurant, Nurse, Clinical, Security Operations,
Network Operations, DevOps, SRE, Trading Operations, Intern, Apprentice, Graduate.

**Geography**: London, or UK-wide remote. Exclude non-UK locations unless the posting
is explicitly remote and UK-eligible.

**Seniority floor**: director level and above. A "Operations Manager" with no director
scope is noise.

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

Unverified candidates, in rough priority order if coverage proves thin: Workable,
Recruitee, Personio, Teamtailor, Pinpoint, Applied, Breezy HR, Polymer.

**Workday** is how most large employers hire. It has no public API; its career sites
call `POST /wday/cxs/{tenant}/{site}/jobs`. Undocumented, so it will break without
notice. Only add it with a loud failure alarm, and not before the four core adapters
are stable.

## Phase plan

- **Phase 0** (90 min) — `discover.py` + `fetch.py`. Prints matching roles to the
  terminal. Purpose: prove the hypothesis before building infrastructure. If it surfaces
  nothing worth applying for, stop here.
- **Phase 1** — Google Cloud service account, `sheets.py`, rows land in the Sheet.
- **Phase 2** — GitHub Actions workflow, secrets, first automated run.
- **Phase 3** — Dedup key, `first_seen` timestamps, scoring, staleness alarm.
- **Phase 4** — Employer list to ~120. Sheet formatting.

## Conventions

- Python 3.14 (Homebrew, at `/opt/homebrew/bin/python3`). Use a virtual environment.
- Dependencies pinned in `requirements.txt`.
- Every adapter is a function with the same signature returning the same dict shape.
  One adapter failing must never stop the run.
- Be polite to endpoints: a short delay between requests, a real User-Agent, and
  retry-with-backoff on 429 or 5xx.
- Commit messages: imperative mood, one line, explain why not what.
