# RoleFeed — specification

## Problem


Public job boards are noisy, LinkedIn alerts are unreliable, and the roles he wants are
scattered across a few hundred employers' own careers pages. Checking those by hand
does not scale.

## Insight the design rests on

None of the public ATS APIs offer search. They are per-employer endpoints: you pass one
employer's board token and get that employer's jobs back. There is no way to ask
Greenhouse for "all Director of Operations roles".

The consequence is structural. **The curated employer list is the product.** The code is
a loop over that list. Coverage is bounded by who is on the list, not by how clever the
matching is. Effort therefore belongs in `companies.yaml`, not in the fetcher.

## Non-goals

Explicitly out of scope, and not to be added without a decision to change the spec:

- Any custom web front end. The Google Sheet is the interface.
- A database. Sheets is the store.
- LinkedIn, Indeed, or any paid aggregator.
- Automated applications. Mark applies by hand; the tool only surfaces.
- JSON-LD / schema.org parsing. Parked at Mark's request.

## Success criteria

Phase 0 succeeds if it surfaces **at least five roles Mark would genuinely apply for**
that he had not already seen. Below that, the hypothesis is weak and the build stops.

Steady state succeeds if Mark opens the Sheet instead of opening LinkedIn.

## Data model

One row per posting. The natural key is `ats:company:external_id`, which survives an
employer editing a title.

| Field | Source | Notes |
|---|---|---|
| `company` | employer list | display name, not the token |
| `ats` | resolved list | greenhouse / lever / ashby / smartrecruiters |
| `external_id` | endpoint | the ATS's own id |
| `title` | endpoint | verbatim |
| `location` | endpoint | verbatim; shapes vary wildly between ATSs |
| `url` | endpoint | direct link to apply |
| `posted_at` | endpoint | when the employer published it; often absent |
| `first_seen` | RoleFeed | first run in which this key appeared — **this is what makes "new" meaningful** |
| `last_seen` | RoleFeed | last run in which it appeared; absence for 2 runs means closed |
| `score` | RoleFeed | see below |
| `status` | Mark, by hand | blank / shortlisted / applied / dismissed |

`first_seen` is the important one. A snapshot of open roles is not useful; the diff
between snapshots is. That is how the feed answers "what appeared since Tuesday".

## Matching

Three gates, applied in order. A posting must pass all three.

1. **Title include** — operations leadership and small-org general management. Director
   of Operations, Operations Director, Head of Operations, VP Operations, Director of
   Business Operations, COO, General Manager, Managing Director, Director of Strategy
   and Operations. Comma forms ("Vice President, Operations") must match too.
2. **Title exclude** — drops titles sharing keywords but not the job: anything
   engineering, DevOps, SRE, security or network operations, sales or marketing
   operations, clinical, warehouse, retail, and anything junior (Manager with no
   director scope, Coordinator, Assistant, Analyst, Graduate, Intern).
3. **Location** — London, UK-wide, or genuinely remote. Guards against "London,
   Ontario", "New London" and remote roles pinned to another continent.

"Operations Manager" is deliberately excluded. It is one rung below the target and
would dominate the results.

## Scoring

Deferred to Phase 3, and kept simple when it arrives. Rank on: title seniority
(COO/Director above Head above Lead), sector proximity to Mark's background (govtech,
policy, energy and mobility rank above generic SaaS), and recency of `first_seen`.
Resist building a clever relevance model — with a good employer list the volume is low
enough to read by eye.

## Failure modes to design against

- **Silent staleness.** An adapter that returns `[]` because an endpoint changed looks
  identical to an employer with no open roles. Mitigation: track roles-per-employer run
  on run and alarm when a previously-productive employer drops to zero.
- **Token rot.** Employers migrate ATS. `discover.py` re-run monthly catches this.
- **Rate limiting.** These are free endpoints run by other people. 0.4s between
  requests, one retry with backoff, and a real User-Agent.
- **Over-filtering.** A filter too tight returns nothing and looks like broken code.
  `fetch.py --all` exists to distinguish the two.

## Build sequence

| Phase | Budget | Deliverable |
|---|---|---|
| 0 | 90 min | `discover.py` resolves employer → ATS. `fetch.py` prints matching roles. Hypothesis tested. |
| 1 | 45 min | Google Cloud service account, `sheets.py`, rows in the Sheet. |
| 2 | 45 min | `.github/workflows/collect.yml`, secrets, first scheduled run. |
| 3 | 60 min | `first_seen` / `last_seen`, dedup persistence, scoring, staleness alarm. |
| 4 | 60 min | Employer list corrected and expanded. Sheet conditional formatting. |

Total: 5 hours.

## Open questions

- Which unresolved employers are worth fixing by hand? Depends entirely on
  `discover.py`'s hit rate, which is unknown until first run.
- Is Workday worth an adapter? Only if the four core adapters leave obvious gaps among
  employers Mark cares about.
- Does a weekly email digest add anything over opening the Sheet? Probably not.
