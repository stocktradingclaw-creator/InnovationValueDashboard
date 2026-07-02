
---

## Pass 6 — Lens F: responsive & small screens (2026-07-02)

**Issue:** Below 760px the sidebar switched to `position: fixed` but kept
whatever width its expand state dictated — 218px for anyone who hadn't
collapsed it (i.e., every first-time visitor). Content only reserved 78px,
so the fixed panel physically covered the left half of every tab on a phone.

**Who it hurt, when:** Anyone opening the hub on a phone or narrow window —
an exec tapping the demo link from email sees half the dashboard hidden.

**Change:** On ≤760px the sidebar always renders as a compact 62px glyph
rail regardless of stored expand state: labels, brand wordmark, and the
(now-pointless) collapse toggle are hidden, glyphs centered, and content
padding matched to the rail. Nav buttons keep title tooltips as labels.

**Files:** index.css

**Also observed (below the fix bar):** wide tables (opps-table, kpi-table)
can still overflow horizontally on very narrow screens — candidate for a
scroll wrapper on a later pass.

Verified: build clean, 50 tests green.
