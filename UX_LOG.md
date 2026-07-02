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

---

## Pass 2 — Lens B: visual hierarchy & scanability (2026-06-14)

**Issue:** The Command Center had grown to ~12 stacked sections (screening,
approvals, experiments, pipeline, learnings, patterns, scoring, governance,
challenges, initiatives, demo studio, history) all at identical h3 weight —
a wall of content with no way to see where work is waiting or jump to it.

**Who it hurt, when:** The reviewer persona — the platform's most frequent
user — on every visit. Finding "are there ideas waiting for me?" required
scrolling the full page; the queues with live work were visually
indistinguishable from static configuration panels.

**Change:** Sticky jump-nav at the top of the Command Center with seven
section chips, the work queues carrying live counts (Screening 3 ·
Approvals 2 · Experiments 1 …). Smooth-scroll anchors with scroll-margin
so headings land below the sticky bar. No sections moved or redesigned.

**Files:** src/components/CommandCenter.tsx, src/index.css

**Also observed (below the fix bar this pass):** role picker still renders
above visible page content (minor); Overview stacking order is sound;
tables scan well. "Queue clear." copy remains a lens C candidate.

Verified: build clean, 43 tests green, dev server renders with nav mounted.

---

## Pass 3 — Lens C: microcopy & tone (2026-06-14)

**Issue:** System copy spoke developer, not human, at the two worst moments.
The offline banner printed a literal shell command ("Start it with: cd server
&& uvicorn app.main:app --port 8000") — which a client would see during any
serverless cold-start hiccup mid-presentation. And all four gate queues used
the same terse "Queue clear." regardless of context.

**Who it hurt, when:** A client or executive at the moment the product
stumbles — exactly when tone determines whether the stumble reads as "blip"
or "broken". Empty queues are also a reviewer's most common sight; identical
copy wasted the moment.

**Change:** Offline banner now reads "Reconnecting… The hub can't reach its
data service right now — this usually resolves in a few seconds" with a
Retry now button (recovery affordance instead of shell instructions). Each
gate's empty state now affirms in its own voice ("All caught up — every new
idea has been screened", "the AI is ready when they are").

**Files:** src/App.tsx, src/components/CommandCenter.tsx, src/index.css

**Also observed (below the fix bar):** "Observe now" button label is jargon
but tied to the evidence-observation concept (lens C candidate if it recurs);
generic "Loading…" placeholders are candidates for lens E skeletons.

Verified: build clean, 44 tests green, dev server renders.

---

## Pass 4 — Lens D: accessibility (2026-06-14)

**Issue:** The app's primary interactive surfaces were mouse-only: the
decision queue rows (Overview), expandable card headers (Ideas, Business
Cases, Portfolio findings), and opportunity table rows were plain divs/trs
with onClick — no role, no tabIndex, no key handling — and the stylesheet
had zero :focus-visible styling anywhere.

**Who it hurt, when:** Keyboard users and anyone driving a projected demo
from a keyboard: the executive decision queue — the product's centerpiece —
was unreachable without a mouse.

**Change:** All five surface types gained role="button"/tabIndex and
Enter/Space activation; a global :focus-visible ring (accent outline) now
covers buttons, role=button, rows, and form fields.

**Files:** Dashboard.tsx, Ideas.tsx, BusinessCases.tsx, Portfolio.tsx,
Opportunities.tsx, index.css

**Also observed (below the fix bar):** weight sliders lack aria-labels
(visible labels adjacent); vote button meaning relies on title attr.

Verified: build clean, 45 tests green.

---

## Pass 5 — Lens E: loading/error/feedback (2026-06-14)

**Issue:** The three primary views (Overview — the default tab, Command
Center, Pipeline) rendered a single dead "Loading…" text line while their
data loaded. On the deployed serverless instance, first load includes a
cold start plus the lazy automation pass — several seconds of what looked
like a broken page at the exact moment an executive opens the product.

**Who it hurt, when:** Anyone opening the app, worst on the deployment where
cold starts are real; executives judge products in that first second.

**Change:** Layout-preserving shimmer skeletons: the Overview shows ghost
hero-stat cards and content blocks in their final positions; Command Center
and Pipeline get card/column ghosts. aria-busy for assistive tech. Dead text
is gone.

**Files:** Dashboard.tsx, CommandCenter.tsx, PipelineView.tsx, index.css

**Also observed (below the fix bar):** action feedback via busy button
labels is adequate; error surfaces are inline and close to the action.

Verified: build clean, 45 tests green.
