# UX Refinement Log — Innovation Hub

Rotating-lens refinement loop. One highest-impact fix per pass.
Lenses: A first-run/empty · B hierarchy · C microcopy · D accessibility ·
E loading/error/feedback · F responsive · G consistency · H data-viz · I flow friction

---

## Pass 1 — Lens A: first-run & empty states (2026-06-14)

**Issue:** The Overview first-run state was a dead end: one line of muted text
with a tiny inline link. The product's "aha" moment (a fully lit dashboard with
opportunities, auto-drafts, and the value funnel) required three hops — navigate
to Data Sources, find the Load sample data button, navigate back.

**Who it hurt, when:** An executive or first-time evaluator in their first 30
seconds — exactly the moment the product must earn credibility. Also anyone
opening the fresh Vercel deployment before the lazy seeding kicks in.

**Change:** Empty Overview became a centered first-run hero with a primary
"Load sample data" button (seeds all five sources in place and refreshes —
one click to the full experience) plus a secondary "Connect your data" path.
Added seeding progress feedback.

**Files:** src/components/Dashboard.tsx, src/App.tsx, src/index.css

**Also observed (below the fix bar this pass):** role picker renders above a
visible dashboard (slight first-run noise — candidate for lens B); Command
Center "Queue clear." copy is terse but serviceable (lens C candidate).

Verified: build clean, 41 tests green, seed CTA exercised against the dev server.
