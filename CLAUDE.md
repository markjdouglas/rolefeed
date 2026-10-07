# RoleFeed — project brief for Claude Code

Read this at the start of every session.

## What this is

A scheduled job-listings collector with a static web front end. It queries the public
job-board APIs of applicant tracking systems (ATS) for a curated list of 211 transport,
logistics, mobility and aviation employers, filters for senior operations roles in the
UK or remote within GMT ±3, groups them by employer size, and publishes the result as
one JSON file that a static page renders.

Live at `https://rolefeed.pages.dev`. Alpha, v0.4.7. The repository is **public**.

It served two purposes: a working education in git, CI/CD, APIs and deployment, and a
test of whether a curated ATS pipeline could beat LinkedIn for a narrow search. The test
concluded that it cannot — coverage is capped at 62 of 211 employers by which ATS each
one uses. The product brief (`site/prd.html`) records the result. Treat the project as
maintained, not expanding.

## How to work on this project

- British English. Short declarative sentences. Verdict first, then reasoning.
- Name technical vocabulary on first use rather than assuming it.
- Attach confidence levels (high / moderate / low / unknown) to empirical claims,
  especially about undocumented endpoints.
- Do not agree reflexively. If a decision is wrong, say so and explain the mechanism.
- Never invent an API response shape. Probe the endpoint and read what comes back.
- **Verify against the artefact, not a copy.** Read a file immediately before writing it,
  and check the published output after a change. A whole-file write from a copy taken
  earlier silently reverts anything that changed since — this is how the duplicate
  publishing bug of 21 September came back thirteen minutes after it was fixed.
- No `#` comments inside shell blocks meant for pasting. zsh does not enable
  `interactive_comments` by default, so the comment is parsed as a command.

## Hard constraints

- **No framework and no build step.** Each page in `site/` is one hand-written file with
  inline CSS and JS. Deploys as static files, costs nothing, stays readable.
- **No database.** State lives in `site/data/jobs.json`, committed to the repo.
- **No paid APIs** and no aggregators.
- **No LinkedIn and no Indeed.** Neither has a public jobs API, and both prohibit
  scraping. Ruled out, not attempted.
- **No secrets.** Every adapter is keyless; the workflow uses only the built-in token.
- JSON-LD parsing of arbitrary career sites is out of scope. Teamtailor's JSON feed is a
  supported adapter, which is different.

## Scope

**Sectors**: ride-hail, micromobility, last-mile delivery, freight and forwarding,
fulfilment and warehousing, EV charging, fleet and telematics, public transport,
aviation and space, autonomous vehicles.

**Company size**: five buckets — enterprise, large, mid, scaleup, startup — largest
first. Excluded employers are listed in `companies.yaml`.

**Geography**: UK, or remote within GMT ±3. An impostor guard rejects London Ontario,
Birmingham Alabama and Manchester New Hampshire. The location test is known to leak:
see Open issues.

**Seniority**: three tiers — exec, director, mid-senior. Title inflation runs opposite
to company size, so one threshold cannot fit both a 30-person startup and Deliveroo.
See `title_tier()` in `fetch.py`.

## Architecture

```
companies.yaml          curated employer list
  ↓ discover.py         probes token variants against the ATSs, resolves each board
companies.resolved.yaml verified employer → ATS → board token
  ↓ fetch.py            pulls postings, dedupes, applies location and title rules
  ↓ state.py            merges with the previous feed so first_seen survives
site/data/jobs.json     the only thing the front end loads
  ↓ git push            a commit to main triggers a Cloudflare Pages rebuild
site/*.html             feed, coverage, product brief, version history, outages
```

Scheduling is GitHub Actions (`.github/workflows/collect.yml`), every two hours at :37.
Hosting is Cloudflare Pages.

## Two different costs

- `discover.py` is a **build step**: up to ten token variants across several endpoints
  per employer, rate-limited per host. About 23 minutes for 211 employers. Run it only
  when `companies.yaml` changes, and commit the result.
- `fetch.py` is the **runtime step**: one request per resolved employer, about a minute.
- The front end fetches one static JSON file.

## ATS endpoints

Six adapters in `ats.py`, one signature, one returned shape. All keyless.

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
- **Greenhouse runs a separate EU estate** at `boards-api.eu.greenhouse.io`. Try both.
- **Probe before ruling a source out.** Teamtailor was wrongly written off and turned out
  to publish the best-quality data of the six.
- **SmartRecruiters pages at 100.** A count of exactly 100 is a cap, not a total. The
  adapter pages on `offset` against `totalFound`.
- **`posted_reliable` matters.** Greenhouse returns `updated_at`, not a publication date.
  `state.effective_date()` falls back to `first_seen` when the source date is unreliable.
- **Workday** cannot be guessed; configure by hand with `add_workday.py`. It is
  undocumented, so a drop to zero roles means suspected breakage.
- **British Airways cannot be covered**: no JSON-LD, `robots.txt` disallows
  `/search-jobs/`. Do not build a route around this.

Unsupported: SuccessFactors, Taleo, iCIMS, Cornerstone, Bullhorn — most of the
enterprise bucket, and the known ceiling on coverage.

## Working on the repo

**A bot pushes to `main` every two hours** as `rolefeed-bot`. Always
`git pull --rebase` before pushing.

- The commit step retries a failed push three times, reconciling last-write-wins. The
  bot's `jobs.json` replaces whatever is on `main`, including one regenerated by hand.
- GitHub does not guarantee scheduled start times, and under load it skips scheduled
  runs entirely — on 3–4 October it never started 11 of about 24.
- `.gitignore` came from a template that excluded `/site`. It is commented out.
- `.github/workflows/` cannot be written through the remote file tool; edit it through
  the device shell.

## Conventions

- Python 3.14 locally (Homebrew); CI uses 3.13. Dependencies pinned.
- One adapter failing must never stop the run.
- A short delay between requests, a real User-Agent, timeouts on every call.
- Commit messages: imperative mood, explain why not what.
- Front-end comments explain *why*, at length. Do not strip them.

## Design

Dark only. Base indigo `#14102b`. Depth from borders and hard offset shadows, never
blurred ones. Purple `#8b6cff` is a sparing accent; cream `#f4eddf` carries primary
actions. Pixel-art register with art-deco display type, and a pixel goose in the header.

## Open issues, in value order

From the audit of 7 October 2026:

1. **Failed employers' roles churn.** An HTTP error is read as an empty board, and
   `state.merge()` does not know which employers failed, so two failed runs close an
   employer's roles and recovery re-adds them as new.
2. **The location test leaks both ways.** Some US-remote roles pass as "remote,
   unspecified"; "Sydney, New South Wales" passes as UK on "Wales"; "Hybrid – Berlin"
   passes; Liverpool and Croydon are rejected.
3. **The reliability figure cannot see runs GitHub never started.** It counts runs that
   happened, not runs that should have. Measure feed age against the schedule instead.
4. "Newest first" sorts timestamps as text across mixed offsets.
5. Every run commits, because `last_seen` changes each time.
6. The filter toggles are not keyboard-reachable.
7. `actions/checkout@v4` and `setup-python@v5` run on Node 20.
