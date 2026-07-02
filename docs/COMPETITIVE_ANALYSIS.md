# Competitive assessment: Innovation Hub vs. ITONICS, Qmarkets, Brightidea, InnovationCast

*Prepared 2026-07-02. Competitor facts as of early 2026 — verify specific feature
claims before external use.*

## Executive summary

The four incumbents sell the same core promise — collect ideas from a crowd, run
them through configurable funnels, report engagement. Their differences are
emphasis: **ITONICS** leads with foresight (trend/tech radars feeding portfolio),
**Qmarkets** with deep workflow configurability for large enterprises,
**Brightidea** with breadth, maturity, and claimed cumulative ROI tracking,
**InnovationCast** with a lighter, collaboration-first experience for the
mid-market. All four share a structural weakness: **the value they report is
self-declared** — benefits typed into forms by idea owners, rolled up into
dashboards finance doesn't trust. That is the seam the Hub is built to attack.

## Where each incumbent beats us today

| Competitor | Their edge over the Hub | Weight |
|---|---|---|
| ITONICS | Foresight layer: trend/tech/startup radars feeding pipeline; roadmapping | High for corporate-strategy buyers |
| Qmarkets | Enterprise configurability at scale, multilingual crowds, gamification, mature RBAC | High for 10k+ employee deployments |
| Brightidea | 20-year track record, integrations (SSO, Teams/Slack, Jira), references, analytics depth | High — it's the safe choice |
| InnovationCast | Polished collaborative idea development (canvases, co-creation), low-friction engagement | Medium — UX bar to match |
| All four | SOC 2/ISO, SSO/SCIM, durable multi-tenant infra, mobile, i18n, services teams | **Disqualifying in procurement if absent** |

## What the Hub does that none of them do

1. **Verified value structurally separated from claimed value** — frozen-baseline
   metric bindings re-observed from the customer's own data. Their ROI is a
   survey; ours is a computation with an audit trail.
2. **Data-first pipeline origination** — we ingest the estate (CMDB/ERP/cloud/ITSM)
   and detect opportunities before anyone has an idea.
3. **AI that does the work** — auto-drafted business cases with measurement plans,
   auto-advancement on evidence, AI triage, grounded drafting assistance.
4. **Metered, evidence-gated funding** — VC-style tranches released against
   milestones.
5. **Kill-friendly economics** — experiments with mandatory learnings, a learnings
   library, submitters thanked for kills.
6. **Calibration loop** — forecast bias measured against actuals per category.

## Recommendations

### A. Close the disqualifiers (table stakes)

1. Durable infrastructure: Postgres, real multi-tenancy, backup/restore
   (ephemeral SQLite is fine for demo, fatal for sale).
2. Enterprise identity: SSO/SAML, SCIM, deeper RBAC atop the four roles; audit
   log export.
3. Compliance: SOC 2 Type II path; data residency options.
4. Capture integrations: Teams/Slack idea capture, Jira/ADO delivery handoff,
   ServiceNow bidirectional (finish existing connector scaffolding).
5. Reporting: exportable board packs, BI connector.

### B. Sharpen the wedge (differentiation)

1. **Position as "the innovation platform that proves ROI."** Make the Verified
   Value Ledger the brand; sell to the CFO as much as the CINO. Incumbent
   architectures assume typed-in benefits — they cannot follow quickly.
2. **Lead demos with detection, not ideation.** "Connect your data; we'll show
   you the pipeline you already have." Demo studio + lifecycle seeding =
   same-day proof-of-value vs. 3–6 month incumbent rollouts.
3. **Productize the funding gate** — "stage-gate governance that releases money
   like a VC."
4. **Own honest innovation accounting** — publish the methodology (claimed vs.
   verified, calibration, kill economics) as a standard incumbents can't adopt
   without indicting their own dashboards.
5. **Time-to-value as pricing leverage** — transparent pricing, self-serve tier.

### C. Sequencing

- **Now (0–3 mo):** Postgres + SSO + audit export; ServiceNow/Jira connectors;
  verified-value ledger polish; board-pack export.
- **Next (3–9 mo):** SOC 2 engagement; Teams/Slack capture; multilingual UI;
  benchmark library from calibration data.
- **Later (9–18 mo):** lightweight foresight/radar module (neutralize ITONICS in
  bake-offs) — only after the value wedge is winning deals; resource/roadmap
  views.

## Bottom line

Don't out-feature Qmarkets or out-tenure Brightidea — **out-prove them.** The
Hub's architecture already embodies the one claim none of them can make: *the
number on the dashboard is real.* Close the procurement disqualifiers, lead
with detection and verified value, and the incumbents' breadth becomes their
liability — a wider surface of unverifiable promises.
