# RoleFeed — original specification

> **Historical.** This is the specification as written on 19 September 2026, before the
> build. It is kept as a record of the starting assumptions, several of which changed —
> the Google Sheet interface was replaced by a static site, and the employer list grew
> from 169 to 211. For the current state see `README.md`; for what was learned, see the
> product brief at `site/prd.html`.

## What this is for, in priority order

1. **Learn to build and deploy properly.** Working knowledge of git, GitHub, CI/CD, APIs,
   secrets and scheduled automation, acquired by building something real.
2. **Find a role.** Useful, and secondary.

That ordering is load-bearing. When the two conflict, the build wins. Matching criteria
are cheap to change later and should not absorb effort now.

## The hypothesis under test

Can a useful feed of senior operations roles be assembled from public ATS endpoints
alone, without scraping, paid data or LinkedIn?

Phase 0 tests the data. The Alpha tests the product.

## Insight the design rests on

None of the public ATS APIs offer search. They are per-employer endpoints: you pass one
employer's board token and get that employer's jobs back.

The consequence is structural. **The curated employer list is the product.** The code is a
loop over that list, so coverage is bounded by who is on the list, not by matching
cleverness. Effort belongs in `companies.yaml`.

## Scope

**In**: technology and operations in moving people and goods — ride-hail, micromobility,
last-mile delivery, freight and forwarding, fulfilment and warehousing, EV charging,
fleet and telematics, public transport, aviation and space, autonomous vehicles.

Sector-agnostic within that boundary. The transferable capability is marketplace supply,
network operations and infrastructure programmes, not any one vertical.

**Out**: govtech, policy, charity, generic SaaS, fintech. Employers under roughly ten
people. Previous employers: Uber, Gett, Glue Home, Ontruck, ParkBee, Otto Car, POSTX,
Apolitical, Abercrombie & Fitch.

**Preference**: established companies over startups. Enterprise and large buckets are
printed first for that reason.

## Non-goals

Not to be added without a decision to change this spec:

- A framework or a build step. The front end is one hand-written static file, by
  decision: it deploys as static assets, costs nothing, and stays legible to a
  non-engineer. No React, no Next.js, no bundler.
- A database. The committed `site/data/jobs.json` is the store, and `git diff` is the
  history. Workers KV only if per-device sync is wanted.
- Google Sheets. It was the original plan for the interface and was dropped once the
  static page proved both cheaper and better.
- LinkedIn, Indeed, or any paid aggregator.
- Automated applications. RoleFeed surfaces; Mark applies.
- JSON-LD / schema.org parsing. Parked at Mark's request.

## Success criteria

**Phase 0** succeeds if it surfaces roles Mark would genuinely apply for that he had not
already seen. Five is the threshold.

**The Alpha** succeeds if Mark opens the Sheet instead of opening LinkedIn.

## Data model

One row per posting. Natural key is `ats:company:external_id`, which survives an employer
editing a title.

| Field | Source | Notes |
|---|---|---|
| `company` | employer list | display name, not the token |
| `ats` | resolved list | greenhouse / lever / ashby / smartrecruiters / workday |
| `external_id` | endpoint | the ATS's own id |
| `title` | endpoint | verbatim |
| `location` | endpoint | verbatim; shapes vary wildly between ATSs |
| `url` | endpoint | direct link to apply |
| `posted_at` | endpoint | often absent |
| `size` | employer list | enterprise / large / mid / scaleup |
| `sector` | employer list | one of ten |
| `first_seen` | RoleFeed | **the field that makes "new" meaningful** |
| `last_seen` | RoleFeed | absence for two runs means closed |
| `score` | RoleFeed | Phase 3 |
| `status` | Mark, by hand | blank / shortlisted / applied / dismissed |

A snapshot of open roles is not useful; the diff between snapshots is. `first_seen` is
what answers "what appeared since Tuesday".

## Matching

Three gates in order; a posting must pass all three. Deliberately provisional — the spec
expects these to be tuned once real volume is visible.

1. **Title include** — core ops leadership (Director/Head/VP of Operations, Operations
   Director, COO, General Manager, Managing Director, Country Manager), mobility phrasing
   for the same job (Head of Marketplace/Supply/Courier/Fleet/City/Charging Operations),
   launch and market-building (Head of Expansion, Director of New Markets, Regional GM,
   City Lead), and Head/Director of Partnerships.
2. **Title exclude** — engineering, DevOps, SRE, security and network operations, sales
   and marketing operations, clinical, warehouse, retail, and anything junior. Negative
   lookbehinds also strip Finance, People, Revenue, Talent, Business and Technical
   Operations Lead, which the bare `operations lead` pattern would otherwise catch.
3. **Location** — London, UK-wide, or genuinely remote. Guards against "London, Ontario",
   "New London" and remote roles pinned to another continent.

Verified against 39 sample titles with no failures.

Seniority resolves to one of three tiers rather than a single accept-or-reject rule,
because title inflation runs opposite to company size: a 30-person scaleup calls the job
Head of Operations and Deliveroo calls the same scope Senior Manager. "Operations
Manager" at a large employer is therefore mid-senior rather than noise, and is tagged
as such instead of being discarded.

## Failure modes designed against

- **Silent staleness.** An adapter returning `[]` because an endpoint changed is
  indistinguishable from an employer with no vacancies. Track roles-per-employer run on
  run and alarm when a previously-productive employer drops to zero. Acute for Workday.
- **Misattribution.** A guessed token can resolve to an unrelated company's board and
  silently present their jobs as the target's. Mitigated by refusing first-word tokens
  under six characters and flagging non-obvious matches `verify: true`.
- **Token rot.** Employers migrate ATS. Re-run `discover.py` monthly.
- **Rate limiting.** Free endpoints run by other people. Per-host locks, 0.25s pacing,
  one retry with backoff, a real User-Agent, and a capped variant list — the naive
  version would have fired 7,400 requests.
- **Over-filtering.** A tight filter returning nothing looks like broken code.
  `fetch.py --all` distinguishes the two.

## Build sequence

| Phase | Budget | Deliverable |
|---|---|---|
| 0 | 90 min | `discover.py` + `fetch.py` printing to terminal. Hypothesis tested. |
| 1 | 45 min | Static front end and Cloudflare Pages deployment. Replaced the Sheet. |
| 2 | 45 min | `.github/workflows/collect.yml`, first scheduled run. |
| 3 | 60 min | `first_seen` / `last_seen`, dedup persistence, staleness detection. |
| 4 | 60 min | Teamtailor adapter, trustworthy publication dates, seniority tiers. |
| — | open | Cloudflare Access, Workday employers, Workers KV for cross-device state. |

Phases 0 to 4 are done and deployed as v0.4.0. Phase 1 diverged from plan: the Google
Sheet was dropped for a static page, which removed a Google Cloud service account, a
set of credentials and an entire dependency from the design.

## Open questions

- How many of the 60 enterprise employers are reachable at all? Most run Workday,
  SuccessFactors, Taleo or iCIMS. Only Workday is supported, so enterprise coverage
  depends entirely on how many are on Workday — currently unknown.
- Is a weekly email digest worth building over simply opening the Sheet? Probably not.
- Does scoring earn its place, or is the volume low enough to read by eye?
