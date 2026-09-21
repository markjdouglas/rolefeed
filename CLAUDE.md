# RoleFeed — project memory for Claude Code

Read this at the start of every session. It is the standing brief.

## What this is

A scheduled job-listings collector with a static web front end. It queries public
applicant tracking system (ATS) endpoints for a curated list of ~211 transport,
logistics, mobility and aviation employers, filters for senior operations roles, groups
them by employer size, and publishes them as a single JSON file that a static page
renders.

Live at `https://rolefeed.pages.dev`. Currently v0.4.0, alpha.

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
- Never put a `#` comment on a line in a block he will paste. He uses zsh, which does
  not enable `interactive_comments` by default, so the comment is parsed as code and
  the whole block fails.

## Priority

The build matters more than the matching criteria. Mark has said explicitly: the main
hypothesis is whether this approach is viable, tested by pulling real data and getting
an alpha standing up. Criteria are cheap to change later. Do not spend budget
perfecting filters while something structural is unbuilt.

## Hard constraints

- **Scope is cut to fit the time, not extended.** The original budget was 5 hours.
- **No framework and no build step.** `site/index.html` is one hand-written file with
  inline CSS and JS. No React, no Next.js, no Vercel, no bundler. This is deliberate:
  it deploys as static files, costs nothing, and stays readable to a non-engineer.
- **No database.** State lives in `site/data/jobs.json`, committed to the repo, which
  gives free history via `git diff`. Workers KV only if per-device sync is wanted.
- **No paid APIs.** No RapidAPI, Apify, Fantastic Jobs or similar aggregators.
- **No LinkedIn.** No public jobs search API exists, and scraping it is both against
  terms of service and actively defended. Do not attempt it.
- **No Indeed.** No public API. The partner Developer Agreement explicitly prohibits
  scraping and algorithmic querying. Checked and ruled out.
- **No secrets in the repo.** The collector needs none — every adapter is keyless.
- JSON-LD / schema.org JobPosting parsing of arbitrary career sites is **parked** at
  Mark's request. Do not add it without being asked. (Teamtailor is different: it
  publishes a JSON feed that happens to embed JobPosting. That is a supported adapter.)

## Scope

**Sectors in**: ride-hail, micromobility, last-mile delivery, freight and forwarding,
fulfilment and warehousing, EV charging, fleet and telematics, public transport,
aviation and space, autonomous vehicles. Sector-agnostic within that — the transferable
capability is marketplace supply, network operations and infrastructure programmes.

**Out**: govtech, policy, charity, fintech, generic SaaS.

**Never targets** — previous employers: Uber, Gett, Glue Home, Ontruck, ParkBee,
Otto Car, POSTX, Apolitical, Abercrombie & Fitch.

**Company size** is tagged on every employer and posting, in five buckets: enterprise,
large, mid, scaleup, startup. Largest first. Startups above roughly ten people are in
scope as of v0.4.0; Mark still prefers established employers.

**Geography**: UK, or remote within GMT ±3. An impostor guard rejects London Ontario,
Birmingham Alabama and Manchester New Hampshire before the UK pattern can match.

**Seniority**: three tiers — exec, director, mid-senior — not a single threshold.
Title inflation runs opposite to company size, so one rule cannot fit both a 30-person
startup and Deliveroo. See `title_tier()` in `fetch.py`.

See SPEC.md for the title include and exclude rules. They are provisional.

## Architecture

```
companies.yaml          curated employer list (the core asset)
  ↓ discover.py         probes token variants against 5 ATSs, resolves where each board lives
companies.resolved.yaml verified employer → ATS → board token mapping
  ↓ fetch.py            pulls postings, filters, dedupes, tiers   ← the matching rules live here
  ↓ state.py            merges with the previous feed so first_seen survives
site/data/jobs.json     committed snapshot; the only thing the front end loads
  ↓ git push            a commit to main triggers a Cloudflare Pages rebuild
site/index.html         the interface: filter, sort, hot, shortlist, dismiss
site/changelog.html     version history, written for a human reader
```

Scheduling runs on **GitHub Actions** (`.github/workflows/collect.yml`), not Vercel —
Vercel's Hobby plan caps cron at once per day, which defeats the purpose.

Hosting is **Cloudflare Pages**, free, and it serves private repositories, which is why
GitHub Pro was not needed.

## Two different costs — do not confuse them

- `discover.py` is a **build step**. It guesses: up to ten token variants across five
  endpoints per unresolved employer, serialised behind per-host locks with a 0.25s
  pace. Ten to twenty minutes for 211 employers. Run it only when `companies.yaml`
  changes, and commit `companies.resolved.yaml` so the runner never has to re-guess.
- `fetch.py` is the **runtime step**. One request per resolved employer, about two
  minutes. This is what the schedule runs.
- The front end fetches nothing but one static JSON file. It is instant.

## ATS endpoints

Six adapters. All keyless. All in `ats.py`, one signature, one returned dict shape.

| ATS | Endpoint |
|---|---|
| Greenhouse | `https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` |
| Lever | `https://api.lever.co/v0/postings/{token}?mode=json` |
| Ashby | `https://api.ashbyhq.com/posting-api/job-board/{token}` |
| SmartRecruiters | `https://api.smartrecruiters.com/v1/companies/{token}/postings` |
| Teamtailor | `https://{token}.teamtailor.com/jobs.json` |
| Workday | `POST https://{tenant}.wdN.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` |

Hard-won, do not regress:

- **Tokens are untidy.** ShipBob is `shipbobinc`, Neuron Mobility is `neuron`, GXO is
  `gxologisticsinc`. `discover.py` generates variants.
- **Greenhouse runs a separate EU estate** at `boards-api.eu.greenhouse.io`. Try both
  hosts. Missing this was half of the first pass's 25% resolve rate.
- **Teamtailor was wrongly written off as closed without being tested.** It publishes an
  open JSON Feed 1.1 at `/jobs.json` with an embedded schema.org JobPosting, giving a
  genuine `datePosted` and a structured address — the best-quality source of the six.
  Sites live at `{token}.teamtailor.com` even behind a custom domain, so it is
  probeable. Common among UK, Nordic and European employers. The lesson generalises:
  probe before ruling a source out.
- **SmartRecruiters pages at 100.** An employer reporting exactly 100 roles is hitting
  the cap, not reporting its true count. The adapter now pages on `offset` against
  `totalFound`. Treat any suspiciously round count as unpaged until proven otherwise.
- **`posted_reliable` is not decoration.** Lever, Ashby, SmartRecruiters and Teamtailor
  return a real publication date. Greenhouse returns `updated_at`, which moves whenever
  an employer fixes a typo. Conflating the two is what made the hot, 48-hour and 7-day
  counts identical. `state.effective_date()` falls back to `first_seen` when the source
  cannot be trusted.
- **Workday** is the only route to enterprise employers and cannot be guessed — tenant
  and site are arbitrary. Hand-configure via `add_workday.py` from a careers URL. It is
  undocumented, so a drop to zero roles is suspected breakage, not an empty board.
- **British Airways cannot be covered.** No JSON-LD, `robots.txt` disallows
  `/search-jobs/`, sitemap is category pages only. Do not build a route around this.

Unsupported and not worth fighting: SuccessFactors, Taleo, iCIMS, Cornerstone,
Bullhorn. That is most of the enterprise bucket, and it is the known ceiling on
coverage. If a careers URL matches none of the six, note it and move on.

## Working on the repo

**A bot pushes to `main` every two hours.** The scheduled workflow commits a fresh
`jobs.json` under the identity `rolefeed-bot`. So any push made more than two hours
after your last pull will be rejected as non-fast-forward. Always:

```
git pull --rebase
```

before committing. Rebase, not merge, or the history fills with merge commits at the
rate of twelve a day.

- The cron is `37 */2 * * *`, deliberately off the hour. Measured over 14 runs, an
  on-the-hour schedule fired 11–17 minutes late every time, because `0 * * * *` is the
  most common expression on the platform and the shared queue is deepest then.
- GitHub guarantees nothing about scheduled start times. The UI says "due", never "in".
- **`.gitignore` came from the stock Python template and contained `/site`**, which
  silently excluded the entire deployed application. It is commented out with a note.
  Check `git status` actually lists what you expect before trusting a commit.

## Conventions

- Python 3.14 (Homebrew, at `/opt/homebrew/bin/python3`). Create the venv with that
  explicit path — plain `python3` resolves to Apple's 3.9.6, because macOS `path_helper`
  puts `/usr/bin` ahead of `/opt/homebrew/bin`.
- Dependencies pinned in `requirements.txt`.
- One adapter failing must never stop the run. Failures are surfaced in the UI instead.
- Be polite to endpoints: a short delay between requests, a real User-Agent, and
  retry-with-backoff on 429 or 5xx.
- Commit messages: imperative mood, one line, explain why not what.
- Front-end comments explain *why*, at length, because this file is a teaching artefact
  as much as an application. Do not strip them.

## Design

Dark only. Base indigo `#14102b`. Depth comes from borders, hard offset shadows and
contrast — never blurred box-shadows. Purple `#8b6cff` is an accent, used sparingly;
warm cream `#f4eddf` carries primary actions. Habbo Hotel pixel-art register with
art-deco display type. A pixel cream goose in the header performs one of fifteen
weighted acts every five seconds.

The checkerboard floor tile lives in the page gutters only, behind no text — it was
originally across the whole body and made prose hard to read.

## Environment facts worth not rediscovering

- **Neither the Claude cloud sandbox nor the Cowork desktop Linux VM can reach ATS
  endpoints.** Both have restricted egress; the container proxy returns 403 and the
  desktop VM exits 56. Mark's own terminal can. `discover.py` and `fetch.py` run there.
- The Cowork bridge cannot delete files, so git commands run through it leave lock
  files behind. Use `GIT_OPTIONAL_LOCKS=0` for read-only inspection, and use a local terminal for
  anything that writes.
- `.github/workflows/` is protected from the remote file-write tool. Edit it through the
  device shell.
- git identity is the `markjdouglas@users.noreply.github.com` alias, deliberately, to
  keep his address out of the commit history.
- GitHub account is `markjdouglas`. Repo is `markjdouglas/rolefeed`, **private**.

## State, as of v0.4.0

Done: collector, six adapters, token discovery, state merge (verified across 14
unattended runs), scheduled collection, static front end, Cloudflare Pages deployment,
version history page.

Open, roughly in value order:
- **Cloudflare Access.** The site is currently readable by anyone with the URL.
- **Workday employers.** IAG and others sit at `workday_url: TODO`. This is the only
  lever on enterprise coverage.
- **Workers KV via a Pages Function.** Shortlist and dismiss are localStorage only, so
  they do not follow him to his phone.
- Judge the title filter against the wider-scope pile now that real volume exists.
