# Innovation Hub — Product Review

*Prepared 2026-07-16 (supersedes 2026-07-06 review) · Live at
https://innovation-value-dashboard.vercel.app ·
Repo: stocktradingclaw-creator/InnovationValueDashboard*

## 1. What the product is

An end-to-end innovation lifecycle platform spanning **detect → ideate →
decide → fund → build → validate → verify**: opportunities are detected in
the customer's own operational data before anyone types an idea; a full
ideation studio (futures, competitive, maturity, workshops, Ten Types)
generates and funnels concepts; a configurable stage-gate engine qualifies
and prioritizes; AI drafts CFO-grade business cases; executives review with
an adversarial red-team memo beside the advocate's case; funding releases in
milestone-gated tranches; an MVP workflow carries approved cases through
design/build/test/deploy/validate; and value is **verified by re-observing
frozen baselines against the customer's own data** — never typed in. The
core thesis: innovation platforms fail on trust, and trust is won by
computing value rather than collecting claims.

## 2. Capability inventory

**Context engine** — set a company or industry once (Overview or Hub
Settings) and every tab populates with subject-relevant artifacts:
competitive reports against real named peers, futures chains, maturity
reads, Ten Types concepts. Demo data is two-layer: a static base lifecycle
plus an incremental context layer; clearing removes only the increment.

**Ideate suite (ribbon group)** — *Detect*: weighted opportunity
prioritization from ingested CMDB/ERP/cloud/ITSM data, top-3 focus
highlighting. *Futures*: Frank Diana-style signal→implication→reimagine
chains across timeframes, pre-populated and click-explainable. *Competitive*:
one-field intake (company or industry, the rest auto-populated) producing a
structured company-vs-company report — matrix, positioning, SWOT,
confidence-labeled recommendations — plus a competitor watchlist with
re-scan deltas; reports persist across navigation. *Maturity*: McKinsey-grade
assessment module — editable framework with rubrics, assessment waves,
calibration, benchmark deltas, gaps with value-at-stake, impact/effort 2×2,
sequenced roadmap, executive readout. *Workshops*: Mural-style
design-thinking sessions with sticky-note ingestion straight into triaged
ideas. *Ten Types*: combinatorial innovation — AI combines 3+ Keeley types
into net-new breakthrough concepts with revenue logic and experiments, not
one idea per type. *Funnel*: every promoted ideate concept lands on a
Christensen disruption map with triage scores; endorsement pushes it into
the formal stage gates. Promote-to-opportunity works identically from every
studio.

**Intake & decisioning** — guided wizard with autosave, AI
draft/review of descriptions and audience/value sections (grounded in
detected opportunities), similar-idea surfacing with join-by-vote,
multi-objective tagging, benefit-range dropdowns, campaigns as a
first-class tab. Configurable workflow steps (custom gates become
first-class statuses; removed gates migrate stranded ideas); Approvals board
with per-gate accordions, rubric scoring, drag-to-pass, fast-track lane,
undo via event-replay (holds, rejects, and advances all revert faithfully),
two-tap decline, revise-and-rescore, backlog-with-reason and resume; an
"in motion" section where approvers manage tranches against milestones.

**Value engine & CFO surface** — frozen-baseline metric bindings; Verified
Value Ledger (per-dollar traceability, CSV, auto re-measure of stale
bindings); calibration loop learning realization factors from actuals;
CFO-grade per-case financial model (ROI, TCV, NPV, payback) computed from
the customer's own data with every assumption sourced and the benefit basis
labeled (verified / detected / submitter estimate); AI-built P&L and
cumulative-return visuals from key approver inputs; Innovation P&L;
cost-of-delay; Monte Carlo simulator; innovation genome.

**MVP Studio** — post-approval delivery workflow per case: Design → Build →
Test → Deploy → Validate. AI drafts each stage's working pack (PRD, build
plan, test suite, deploy runbook, GTM/validation advice) grounded in that
case's financial model; stages complete in order behind honest gates (no
advance without an artifact); Validate measures against the claimed benefit
and routes realized value through metric bindings.

**Portfolio & telemetry** — McKinsey-style advisory window: horizon balance
vs strategy-context targets (one balance story platform-wide), funnel
conversion with PoC-purgatory detection, funding gate queue and kill
economics, pool→gap→realized value rollup, digital-core readiness; peer
reference ranges clearly labeled as external; recommended actions with
**Execute** buttons that perform the action in-app (mass actions preview
scope and require confirmation).

**Governance** — four-role access model with login/password (PBKDF2),
sessions, request-access flow, last-admin guard; **Innovation Management
Audit**: 8 dimensions / ISO 56001-anchored question bank with role-specific
variants per level, anonymity with small-segment suppression, perception-gap
detection (e.g. exec optimism deltas), deterministic prioritized roadmap,
innovation value index, Maturity×Value quadrant; audit trail; state
export/import.

**Executive surface** — strategy rollups, verified-hero proof affordance
(ⓘ → ledger), presentation mode (Esc/button exit), print-ready board pack
with prior-period deltas, portfolio diagnostic for PMO exports, AI red team,
signal radar.

**Learning system** — experiments with mandatory success criteria; kills
require learnings; learning dividends credit cited kills; pattern library
for replicating proven wins.

## 3. Quality posture

- **91 automated tests**, run before every commit: unit, e2e data-integrity,
  UAT persona journeys, negative paths, and per-feature endpoint coverage
  including audit anonymity/suppression, role curation, undo replay,
  telemetry, MVP workflow gates, token-authenticated exports, and cache
  invalidation.
- **Ten documented review rounds**: seven conversion/persona teardowns
  (docs/CONVERSION_TEARDOWN.md) plus three parallel-agent user-journey
  audits (maker + steward consultants) — 31 findings raised, 31 fixed, each
  round's fixes verified by the next round's auditors. Every patch is
  grep-verified as applied before commit.
- **Nine-lens UX loop** completed (UX_LOG.md).
- **Performance instrumented**: p50/p95 on capture, decide, queue, and
  ledger paths via /api/perf; measured before/after on flow optimizations.
- **Honesty invariants held throughout**: claimed and verified value never
  blended; verified value only from re-observed data; every AI output
  labeled with its provenance (claude vs template); low-confidence signals
  flagged, not hidden.

## 4. Strengths (differentiated)

1. Verified value with an auditable ledger — no incumbent (ITONICS,
   Qmarkets, Brightidea, InnovationCast) computes value from source data.
2. Data-first pipeline origination — opportunities detected before ideas.
3. Breadth with one spine: the same case object travels from detected
   opportunity to funded MVP to verified P&L — no hand-offs between modules.
4. AI that does work (drafting, triage, red team, competitive reports,
   combinatorial concepts, stage packs, executable portfolio actions) with
   honest labeled fallbacks when AI is unavailable.
5. Metered, evidence-gated funding; released tranches are the ROI cost basis.
6. Kill-friendly economics with learning dividends.
7. Governance depth unusual at this stage: management audit with
   role-specific instruments and perception-gap analytics.
8. A demo that proves the pitch: full-lifecycle two-layer seeding with
   genuinely computed verified value, protected from overwriting real work.

## 5. Known limitations (material, disclosed)

- **Ephemeral storage.** SQLite in /tmp on Vercel: deploys and instance
  churn reset all data, including claimed workspaces. Postgres migration is
  the single highest-priority engineering item before any real customer use.
- **Identity is demo-grade.** No SSO/SAML/SCIM; sessions are bearer tokens;
  role model is sound but not enterprise IdP.
- **AI is credit-blocked on prod as of this writing.** The API key is
  configured and was verified working; the account's credit balance is
  exhausted, so all AI paths currently degrade to labeled templates.
  Topping up restores full generation with no redeploy. This also means the
  platform's honest-fallback posture has now been production-tested.
- **Verified seed is modest** ($10K/yr): honest — the sample data doesn't
  contain more idle-cloud value. A second ERP-bound case is needed for a
  six-figure demo number.
- **No delegation, fiscal-year framing, or multi-currency** — top remaining
  executive asks.
- **Deferred backlog:** audit-campaign invite UI (API exists), Mural API
  integration, saved futures scenarios, workshop harvest preview-edit,
  opportunity-weight percentage display, i18n, mobile apps, SOC 2.

## 6. Verdict

Since the last review the product closed its two biggest scope gaps — the
front of the funnel (a full ideation studio with context-aware competitive,
futures, maturity, and combinatorial-concept capabilities) and the back
(CFO-grade financials, an MVP delivery workflow, portfolio telemetry, and a
governance audit). The lifecycle story is now genuinely end-to-end: detect
an opportunity in your own data, ideate around it, gate it, fund it in
tranches, build the MVP with AI at every stage, and verify the value
against the original claim. Differentiation remains structural (verified
value, calibration, kill economics, one-spine data model) rather than
cosmetic, and three consecutive audit rounds converging on seam-level
findings indicate the surface quality has caught up with the architecture.
What separates it from sellable is unchanged and infrastructural: durable
storage, enterprise identity, a funded AI account, and a compliance story.
Recommended next investments, in order: Postgres, SSO, API credits as an
operational line item, six-figure verified seed, delegation and fiscal
framing.
