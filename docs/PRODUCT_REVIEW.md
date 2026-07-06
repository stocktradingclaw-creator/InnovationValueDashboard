# Innovation Hub — Product Review

*Prepared 2026-07-06 · Live at https://innovation-value-dashboard.vercel.app ·
Repo: stocktradingclaw-creator/InnovationValueDashboard*

## 1. What the product is

An end-to-end innovation lifecycle platform: ideas enter through guided,
AI-assisted submission; a configurable stage-gate engine qualifies and
prioritizes them; AI drafts business cases with measurement plans; executives
review with an adversarial red-team memo alongside the advocate's case;
funding releases in milestone-gated tranches; and value is **verified by
re-observing frozen baselines against the customer's own data** — never
typed in. The product's core thesis: innovation platforms fail on trust, and
trust is won by computing value rather than collecting claims.

## 2. Capability inventory

**Intake & ideation** — guided 3-step wizard with autosaved drafts; AI
description drafting/review (grounded in detected opportunities, honest
template fallback); as-you-type similar-idea surfacing with join-by-vote;
multi-objective tagging; challenges/campaigns; attachments; votes, comments,
build-ons; bulk CSV; generic capture webhook (Teams/Slack/email middleware).

**Decisioning** — configurable workflow steps (visual editor; custom gates
become first-class statuses); Approvals board with per-gate accordions,
rubric scoring (1–5 per criterion, upserted per reviewer), drag-to-pass,
undo-window decisions, two-tap decline; feedback loop closes via
revise-and-rescore; hold loop closes via backlog-with-reason and resume.

**Value engine** — data ingestion (CMDB/ERP/cloud/ITSM) → detected
opportunities with weighted prioritization; frozen-baseline metric bindings;
Verified Value Ledger (per-dollar traceability, CSV export); calibration
loop learning realization factors from actuals; Innovation P&L; cost-of-delay
ticker; portfolio Monte Carlo simulator with plain-language verdicts;
innovation genome (learned success predictors, low-sample flagged); daily
metric snapshots with deltas.

**Executive surface** — strategy performance rollups on the Overview;
verified-hero proof affordance (ⓘ → ledger); presentation mode; print-ready
board pack with prior-period comparison; portfolio diagnostic for ingested
PMO exports; AI red team per case; signal radar (research → draft challenge
→ explicit launch).

**Governance & identity** — four-role access model (contributor/reviewer/
executive/admin), open until profiles exist; login/password (PBKDF2) with
sessions; workspace claiming ("Start free": wipe samples, capture email,
bootstrap admin); teammate request-access; per-area governance assignments;
audit trail with CSV export; state export/import snapshots.

**Learning system** — experiments with mandatory success criteria; kills
require learnings; learning library with dividends (cited kills credit the
original team); pattern library for scaling proven wins.

## 3. Quality posture

- **63 automated tests**, run before every commit: unit, e2e data-integrity
  (referential + arithmetic checks across all phases), e2e UAT persona
  journeys, negative-path scenarios (illegal transitions, auth failures,
  stale data), and endpoint coverage for every major feature.
- **Seven documented review rounds** (docs/CONVERSION_TEARDOWN.md): two
  designer passes, four end-user passes (incl. senior-leader persona), one
  three-persona pass. All critical and high-impact findings closed.
- **UX log** (UX_LOG.md): nine-lens refinement loop completed (first-run,
  hierarchy, microcopy, accessibility, feedback, responsive, consistency,
  data-viz, flow friction).
- **Honesty invariants held throughout:** claimed and verified value are
  never blended; verified value only ever comes from re-observed data (the
  demo seeder mutates the dataset before observing — it cannot fake value);
  calibration and genome flag low confidence rather than hiding it.

## 4. Strengths (differentiated)

1. Verified value with an auditable ledger — no incumbent (ITONICS,
   Qmarkets, Brightidea, InnovationCast) computes value from source data.
2. Data-first pipeline origination — opportunities detected before ideas.
3. AI that does work (drafting, triage, red team, radar) with honest
   template fallbacks when no key is configured.
4. Metered, evidence-gated funding; released tranches are the ROI cost basis.
5. Kill-friendly economics with learning dividends.
6. A demo that proves the pitch: full-lifecycle seeding with genuinely
   computed verified value, protected from overwriting real work.

## 5. Known limitations (material, disclosed)

- **Ephemeral storage.** SQLite in /tmp on Vercel: every deploy/cold start
  resets all data, including claimed workspaces. Postgres migration is the
  single highest-priority engineering item before any real customer use.
- **Identity is demo-grade.** No SSO/SAML/SCIM; sessions are bearer tokens;
  the admin token guard and role model are sound but not enterprise IdP.
- **Verified seed is modest** ($10K/yr): honest — the sample data doesn't
  contain more idle-cloud value. A second ERP-bound seeded case is needed
  for a six-figure demo number.
- **No delegation, fiscal-year framing, or multi-currency** — top remaining
  executive asks.
- **AI features run in template mode on the live deployment** (no API key
  configured on Vercel); full Claude generation works locally.
- **Deferred backlog:** rubric detail visibility, unified chart language,
  glossary tooltips, scroll-state restoration, i18n, mobile apps, SOC 2.

## 6. Verdict

The product now tells one coherent story end to end — land, orient, explore
real numbers, demo with your own company's data, claim a workspace, be led
to first value, and bring your team — with every persona's happy *and*
unhappy path closing its loop. Its differentiation is structural (verified
value, calibration, kill economics) rather than cosmetic, and its demo is
its best salesperson. What separates it from sellable is infrastructure,
not product: durable storage, enterprise identity, and a compliance story.
Recommended next investments, in order: Postgres, SSO, six-figure verified
seed, delegation, fiscal framing.
