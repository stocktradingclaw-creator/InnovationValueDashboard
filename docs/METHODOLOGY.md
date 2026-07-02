# Honest Innovation Accounting — the Hub's methodology

Published as an open standard. Competing platforms report what idea owners
type in; the Hub reports what the data shows. The difference is auditable.

## 1. Claimed vs. verified — never blended
- **Claimed value** is self-reported (savings entries typed by case owners).
  Always labeled, never summed into verified totals.
- **Verified value** is computed: a metric binding freezes a baseline query
  against the customer's own data at case creation; later observations re-run
  the same query; the annualized delta is the verified value. No typing.

## 2. The Verified Value Ledger
Every verified dollar is traceable to: the case, the metric definition, the
frozen baseline value and date, each observation value and date, and the data
source. Export: `/api/value-ledger?format=csv`.

## 3. Calibration
Forecast bias is measured per category (claimed vs. eventually verified) and
the resulting realization factor is applied to future prioritization —
learned from actuals, never assumed. Exposed at `/api/benchmarks`.

## 4. Metered funding
Approval releases nothing. Funding moves in tranches gated on milestones;
released tranches — not estimates — form the cost basis of realized ROI.

## 5. Kills are tuition
Experiments require explicit success criteria; kills require recorded
learnings, which enter a searchable library. A killed idea with a learning is
a return on investment, and the platform treats it that way.
