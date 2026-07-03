# Conversion Teardown — Innovation Hub

*Two passes. Pass 1: the designer who ships $10M ARR products rips apart the
visual decisions. Pass 2: a first-time end user clicks through and reports
where they got confused or wanted to leave. Sorted by Critical / High impact /
Nice to have. Written 2026-07-02 against the live deployment.*

---

## Pass 1 — The designer

### CRITICAL

**C1. Your hero metric is $0 in the demo. Fire everything else, fix this first.**
The entire pitch is "verified value, computed from data." The seeded demo shows
**Verified: $0** on the Overview, the P&L, and the Value Ledger (4 ledger
entries, all zero delta). A prospect reads that as *"this product's flagship
feature doesn't work."* The seeder mutates the cloud dataset for a case whose
bindings track a different metric, so no delta ever lands. Every pixel of
polish is wasted until the demo's verified number is green and six figures.

**C2. There is no landing moment. The app assumes you already bought it.**
A visitor hits a dashboard — either skeletons resolving into someone else's
numbers or an empty grid of cards. No one-sentence value claim, no "watch it
work in 60 seconds" path above the fold, no trial CTA anywhere. Linear's
homepage converts because the first screen sells; ours audits.

**C3. Unicode glyphs as icons is the #1 "vibe-coded AI project" tell.**
⌂ ★ ☑ ≫ ◎ ▤ ✓ ▦ ⚙ ⛁ render with different optical weights, per-OS
substitution (⛁ becomes emoji or tofu), and zero brand. A 16-glyph inline SVG
icon set is a day of work and the single fastest way to stop looking
AI-generated from 50 feet.

**C4. 'Segoe UI' first in the font stack.**
That's Windows-2015 enterprise, not premium SaaS. Also the type scale is
whispering: h2 is 1.15rem against 0.92rem body — hierarchy at a 1.25 ratio,
where Linear/Vercel run display sizes at 2–3× body with tight tracking and
`tabular-nums` on every metric (our money columns wiggle).

**C5. Six accent hues with no owner.**
Green means: brand wordmark, primary buttons, chips, progress bars, *and*
"verified money." When the sacred color also paints a Cancel-adjacent chip,
the semantic asset — green = real dollars — is destroyed. One brand accent;
verified-green reserved for verified value only; everything else neutral.

### HIGH IMPACT

**H1. Everything is the same card.** One border-radius, one border, one
surface, stacked N-deep on every tab (Overview stacks 8+ sections). No
elevation system, no focal point per screen. The eye has nowhere to land, so
it lands nowhere.

**H2. Button system doesn't exist.** One size, hover inverts to bright green
with dark text (a jarring value flip), no pressed state, paddings drift
between 0.3 and 0.6rem. Primary/secondary/destructive/quiet with a size scale
would remove 80% of the visual noise.

**H3. Empty states are paragraphs.** "No data loaded yet. Go to Data
Sources…" is documentation, not design. Each empty state is a conversion
moment begging for one illustration + one button that does the thing.

**H4. Motion budget is zero.** Toasts pop, cards blink in, accordion snaps,
the board reflows synchronously after every decide. 150–200ms ease transforms
on enter/exit and layout changes is the cheapest premium signal there is.

**H5. Hand-rolled charts don't share a language.** Gauge, slope lines, matrix
dots, funnel bars: different stroke weights, padding, and label styles.
Tooltips via `title` attribute = 800ms browser delay, unstylable, invisible
on touch and keyboard.

**H6. Login screen has no brand moment** — a bare card whose helper text
("first sign-in creates the admin account") reads alarming to a trial user,
not welcoming.

**H7. Wizard steps look like filter chips.** Step indicators need progress
semantics — numbered dots with a connecting line, "Step 1 of 3" — not the
same pill used for source filters elsewhere.

### NICE TO HAVE

- **N1.** Border-radius roulette: 4 / 8 / 10 / 12 / 999 across components.
- **N2.** No favicon/OG/meta — sharing the URL shows a naked link.
- **N3.** Unstyled scrollbars flash white on Windows dark mode.
- **N4.** Brand is an `h1` with a green `<span>`; the collapse toggle is
  ASCII («/»). No mark, no logotype.
- **N5.** Shadows exist only on popovers; pick one elevation language.
- **N6.** `aging-flag` orange and `warn` orange are the same hue doing two
  jobs (urgency vs. category).

---

## Pass 2 — The first-time user

### CRITICAL

**U1. "I didn't know what to do first, and nobody told me."**
Landed on Overview. Numbers, a funnel, a P&L bar, a genome. I clicked four
tabs looking for "where do I put my idea" before noticing the green button.
Nothing greeted me, nothing sequenced my first five minutes. I nearly left at
minute one — and I'm a motivated evaluator.

**U2. "Whose data is this?"**
The dashboard was full of ideas from priya and jordan. Nothing said "this is
sample data — reset it or make it yours." I didn't trust anything I saw, and
worse, I wondered if I was seeing another customer's data. One dismissible
banner ("You're looking at a demo portfolio — Reset / Start fresh") fixes an
actual trust breach.

**U3. "I approved something and the whole board moved."**
Clicked Pass gate → toast said "applying in a few seconds" → I kept reading →
the card vanished and every section reflowed under my cursor. Twice I nearly
clicked the wrong button on a card that had shifted up. Decisions should
animate the one card out, not re-deal the table.

**U4. "It let me do everything — which made it feel like nothing was real."**
I opened Hub Settings as an anonymous visitor and could edit the workflow,
delete objectives, reseed the database. Open-mode is invisible: there's no
"demo mode — everything is editable, nothing is precious" framing, so instead
of feeling powerful it felt like a prototype with no rules.

**U5. "Why am I typing my name to approve things?"**
The Approvals tab has an "Acting as…" field. I'd already entered my name on
My Submissions. Then login exists too? Three identity surfaces
(login, localStorage name, actor field) leak into the UI as one confusing
question: *does this app know who I am or not?*

### HIGH IMPACT

**U6. "Verified $0 told me the product doesn't work."** (Same as C1, from the
other side of the glass — I looked at the big green promise, saw zero, and
mentally filed the whole dashboard under "aspirational.")

**U7. "The AI draft was the best moment — and I almost missed it."** The one
genuinely magic interaction (draft my description from a title) is a small
secondary button below the textarea. It should be impossible to miss the
first time a title is typed.

**U8. "Submit succeeded… now what?"** After submitting, a green sentence told
me to visit My Submissions. Why didn't it take me there, or show my idea's
chain right here? Dead-end success states waste the happiest click in the app.

**U9. "The amber banner scolded me before I did anything."** Cost-of-delay
yelled $250K burned the moment I opened Approvals — about seeded ideas I'd
never seen. Urgency without context reads as noise; I dismissed it mentally,
which trains me to ignore the one metric you want executives to feel.

**U10. "Search moved me to a tab but didn't show me the thing."** I searched
"invoice," clicked the result, landed at the top of Business Cases, and had
to find it again by eye. Deep-link to the item, expanded and highlighted.

**U11. "Run 2,000 futures gave me numbers with no verdict."** p10/p50/p90 —
fine, I know stats — but no sentence saying *"even pessimistically this
portfolio pays for itself."* Numbers without narrative don't persuade.

**U12. "On my phone the icons are hieroglyphs."** The rail collapses to
glyphs with no labels; ⛁ got me Data Sources when I wanted Settings. Tooltips
don't exist on touch.

### NICE TO HAVE

- **U13.** Drag-to-pass-a-gate: learned it existed from header text after I'd
  used the buttons; on iPad it does nothing (fine — but say so or hide it).
- **U14.** Notifications for feedback on my idea only surfaced when I went
  looking on My Submissions; no ambient indicator anywhere.
- **U15.** "Board pack" exported a `.md` file — executives expect PDF; my
  phone didn't know what to do with it.
- **U16.** The lifecycle map's hover-tooltips hide the gate criteria on
  touch devices entirely.
- **U17.** After Demo revert, my scroll position and open accordions reset —
  small, but it made the app feel amnesiac.

---

## The verdict

The bones are genuinely differentiated — verified value, red team, P&L — but
the demo *contradicts the pitch* (C1/U6) and the first five minutes have no
choreography (C2/U1/U2). Fix the seeded verified number, add a first-run
"make it yours in 60 seconds" moment, replace the glyphs, and enforce one
accent — those four changes do more for trial conversion than everything
else on this list combined.

---
---

# Round 2 — post-fix re-audit (2026-07-02, same day)

*Round 1's critical list is confirmed fixed on the live deployment: verified
value is real ($10K computed), sample-data banner greets visitors, SVG icons
shipped, accent discipline enforced, undo/confirm on decisions, mobile
search/labels/touch targets landed. This round judges what's left — and what
the fixes exposed.*

## Pass 1 — The designer, round 2

### CRITICAL

**R2-C1. There is still nothing to convert TO.** My only goal is trial
starts, and this product has no trial: no sign-up path, no pricing page, no
"Start free" button, no workspace-creation flow. The demo converts interest
into… more demo. Every fix so far polishes the museum; there's still no gift
shop. Ship a `/start` moment: name + email → fresh workspace (the state
export/import and open-mode plumbing already make this a day of work).

**R2-C2. The verified story is real but timid.** $10,080 verified against
$131,700 claimed reads as "8% of what people promise is real" — technically
honest, emotionally weak. The seed should verify six figures across 2–3
cases so the hero band leads with a number that sells the wedge.

**R2-C3. "Make it yours" evaporates after the banner.** Dismiss the
sample-data banner and the only path to a personalized demo (Demo Studio —
the single best sales weapon in the product) is buried behind a gear icon a
contributor would never open. Promote "Generate MY company's portfolio" to
the Overview empty/demo state permanently.

### HIGH IMPACT

**R2-H1. Charts still speak four dialects.** Gauge, slope, funnel, and
matrix have different stroke weights, paddings, and label styles (Round 1
H5, carried). One chart language = one afternoon with shared SVG constants.

**R2-H2. The rise animation replays on unchanged cards.** Every decide →
refresh → full remount → every card re-rises. What softened one reflow now
reads as whole-board flicker on busy gates. Key-stable rendering or animate
only entering cards.

**R2-H3. Type scale is still flat.** h2 1.15rem vs body 0.92rem. The
tracking fix helped texture, not hierarchy. Display numbers (hero band,
P&L) deserve 1.6–2rem with the new tabular figures.

**R2-H4. Wizard lets you jump to step 3 with an empty title** and the Next
button disables silently — disabled states without explanations are dead
ends (why can't I click this?). Inline "add a title first" beats a greyed
button.

**R2-H5. Phone first-viewport is crowded:** banner + mobile search + profile
fab + headline stack before any content. Collapse the banner to one line on
small screens.

### NICE TO HAVE

- **R2-N1.** Border-radius roulette persists (4/6/8/10/12/999).
- **R2-N2.** aging-orange vs warn-orange still share one hue for two meanings.
- **R2-N3.** Print board pack lacks the brand mark its login screen now has.
- **R2-N4.** Toasts and profile popover can overlap at z-100 vs z-40.
- **R2-N5.** Similar-idea "join" confirms via toast only — the chip itself
  should flip to "✓ joined".

## Pass 2 — The first-time user, round 2

### CRITICAL

**R2-U1. "I finished exploring and had nowhere to go."** I got it — the
numbers are real, the red team is cool. Then I looked for "sign up," found
nothing, and closed the tab. That's the whole funnel leaking at the last
step.

**R2-U2. "I dismissed the sample banner and couldn't find my way back to
'try it with MY data.'"** The one thing that would have hooked me — seeing
my own company's portfolio — I only found because someone told me it was
under Hub Settings.

### HIGH IMPACT

**R2-U3. "The undo toast made me confident — then the whole gate blinked."**
After the timer fired, every remaining card re-animated and I lost my scroll
position mid-review. (Same root cause as R2-H2.)

**R2-U4. "Search found my business case but landed me on ROI Tracking above
the fold — the case was two screens down under a section I didn't know."**
The flash works when the target is near; it should also expand the target's
section.

**R2-U5. "Step 2 asked who benefits — I'd already written that in the
description the AI drafted."** The wizard doesn't notice the AI draft
already contains beneficiary/pain, so it nags for what it has. Parse the
draft's sections into the step-2 fields.

### NICE TO HAVE

- **R2-U6.** The genome bar collapsed says "top trait: Tagged to a strategic
  objective (1.8×)" — cryptic before you know what the genome is.
- **R2-U7.** Attachments only appear after expanding a card — no paperclip
  count on the collapsed row.
- **R2-U8.** After using search once, I expected ⌘K. Muscle memory from
  every tool I use daily.

## Round 2 verdict

The product no longer looks vibe-coded — it looks designed, and the demo
finally proves its own pitch. The remaining conversion gap is structural,
not cosmetic: **there is no trial to start and no self-serve "my data"
moment on the main path.** R2-C1 and R2-C3 are the whole ballgame; R2-H2 is
the one polish item users physically feel. Everything else is tuning.

---
---

# Round 3 (2026-07-02)

*Round 2's structural criticals are shipped: a real trial flow exists, Demo
Studio is on the main path, the board stopped flickering. Round 3 judges the
funnel that now exists.*

## Pass 1 — The designer, round 3

### CRITICAL

**R3-C1. "Start free" lives only inside a dismissible banner.** Click "Got
it" once and the trial CTA is gone forever (localStorage ack). The single
most important button in the product must be permanent — sidebar footer and
profile menu, always visible until a workspace is claimed.

**R3-C2. The moment after conversion is empty.** Create a workspace → land
on a blank dashboard. Highest commitment, zero choreography. Ship a 3-step
first-run checklist on the empty Overview: 1) Connect data (or load
samples), 2) Submit your first idea, 3) Add your team — with progress ticks.

**R3-C3. No email capture.** Workspace creation takes name/company/password
— no email. The growth loop dead-ends: no way to recover an abandoned
trial, no way to follow up. One field.

### HIGH IMPACT

- **R3-H1.** The orientation banner now has three buttons — choice overload
  at the one moment attention is guaranteed. One primary ("Start free"),
  one quiet text link, dismiss as ✕.
- **R3-H2.** Verified $10K vs claimed $131K (carried from R2-C2): seed a
  second bound case on the ERP duplicate-invoice measure to verify six
  figures honestly.
- **R3-H3.** Still no ⌘K; still no wizard jump-validation; type scale still
  flat (all carried).

### NICE TO HAVE

- **R3-N1.** The workspace name the user types never appears in the UI —
  brand the sidebar with it after claiming.
- **R3-N2.** Start screen lacks the brand mark the login screen got.
- **R3-N3.** Radius roulette, orange hue collision, print-pack brand mark
  (all carried).

## Pass 2 — The first-time user, round 3

### CRITICAL

**R3-U1. "I made a workspace and landed on… nothing."** After the best
click of my visit, an empty dashboard with no "do this first." I sat there
for ten seconds, then went back to poking tabs.

**R3-U2. "I dismissed the banner earlier — later I wanted to start a
workspace and couldn't find the button anywhere."**

### HIGH IMPACT

- **R3-U3.** "Nobody asked for my email. As a buyer that read as 'this
  isn't actually a product yet.'"
- **R3-U4.** "Three buttons in the banner — I read it twice before picking."

### NICE TO HAVE

- **R3-U5.** "I named my company Acme and never saw the word Acme again."

## Round 3 verdict

The funnel exists; now it leaks at its two ends — a CTA that can be
dismissed out of existence (R3-C1) and a post-conversion void (R3-C2).
Those plus email capture are a half-day of work and complete the story:
land → orient → try with your data → claim → be led to first value.

---
---

# Round 4 — user-only pass, whole-app click-through (2026-07-02)

*Every tab, anonymous first, then signed in. Reporting only where I got
confused or wanted to leave.*

### CRITICAL

**R4-U1. "Two green buttons — which one is THE button?"** The sidebar now
has "New idea" and "Start free" both in accent green, stacked in the same
rail. My eye bounced between them; the one that makes you money (Start
free) loses to the one above the fold (New idea). One accent CTA per
surface — demote New idea to neutral until the workspace is claimed.

**R4-U2. "Pipeline and Approvals show the same stages in two places."** I
opened Pipeline, saw gates with counts, tried to click an idea to approve
it — nothing is clickable. Then found Approvals does that. Two tabs, one
mental model, only one of them acts. Either make Pipeline rows deep-link
into Approvals or merge them; as-is I felt lost in a hall of mirrors.

**R4-U3. "I voted on a similar idea as 'anonymous' before the app knew my
name."** On wizard step 1 I clicked join on a similar idea — the toast
thanked me, but my name field was still empty (that's step 2). My vote is
now from "anonymous," forever. Sequence identity before social actions, or
ask my name in the join moment.

### HIGH IMPACT

- **R4-U4.** "Business Cases made me write a description by hand — the
  Ideas tab had AI drafting. Same job, one tab is magic, the other is
  homework." Inconsistent superpowers read as broken promises.
- **R4-U5.** "The rubric button was greyed out and never told me why"
  (needs an actor; hint only on hover — invisible on touch).
- **R4-U6.** "'Observe now' on ROI Tracking — observe what? I clicked it
  scared." Label it "Re-measure from data."
- **R4-U7.** "Portfolio tab = a CSV-upload diagnostic AND a Monte Carlo
  simulator sharing one page. I couldn't tell what the tab was FOR."
- **R4-U8.** "The signal radar created a live challenge instantly — no
  preview, no undo. I made a junk challenge ('test') that now shows on
  Idea Submission for everyone."
- **R4-U9.** "No help, no docs, no support link anywhere in the app. When I
  got stuck there was no rope to grab."

### NICE TO HAVE

- **R4-N1.** Red-team memo bullets can run long enough to dwarf the case
  they critique — clamp to two lines with expand.
- **R4-N2.** "Frozen baseline" jargon is everywhere the ledger goes;
  one-line tooltip glossary would ease first contact.
- **R4-N3.** ⌘K still missing (third round in a row I reached for it).
- **R4-N4.** After demo revert, my open accordions and scroll reset
  (carried from R1).

## Round 4 verdict

The funnel is sound; the confusion now lives in **role boundaries between
tabs** (Pipeline vs Approvals, Portfolio's split personality) and
**inconsistent magic** (AI drafts here but not there, identity asked after
it's needed). Fix R4-U1/U2/U3 and a first-timer can no longer get lost —
everything else is comfort.

---
---

# Round 5 — end-user pass (2026-07-02)

*Post-R4 click-through. Shorter list — the app now mostly explains itself.
What's left:*

### CRITICAL

**R5-U1. "My teammate hit a locked door."** Once a workspace is claimed,
anyone else visiting gets the sign-in screen with no path forward: no "ask
your admin for an account," no request-access button, no way to even see
what the product is. For a tool whose funnel is submitter-driven, the
second user's first experience is a wall.

**R5-U2. "The radar still publishes instantly."** (Carried from R4-U8.) It
remains the only click in the app that creates public content — a live
challenge on the submission page — with no preview, confirm, or undo. Every
other risky action got an undo window; this one still fires blind.

### HIGH IMPACT

- **R5-U3.** Wizard still allows jumping to step 3 with an empty title, and
  Next still disables without explaining (carried R2-H4 — third sighting).
- **R5-U4.** On a phone, the first viewport stacks orientation banner +
  search box + profile icon + headline before content; the banner should
  collapse to a single line under 760px.
- **R5-U5.** ⌘K — fourth round reaching for it. At this point its absence
  is itself a finding about who this product thinks its users are.

### NICE TO HAVE

- **R5-N1.** "Frozen baseline" jargon still unexplained at first contact.
- **R5-N2.** Red-team memos still run long unclamped.
- **R5-N3.** Accordion/scroll state resets on data refresh (carried).

## Round 5 verdict

One genuine hole (the second user's locked door), one carried risk (radar),
and polish. The single-player journey is now clean end to end; the
multi-player journey needs its first five minutes designed.

---
---

# Round 6 — end-user pass: the senior enterprise leader (2026-07-02)

*Persona: SVP with a 90-second attention budget, board-level accountability,
and a healthy distrust of dashboards. Clicked through on a laptop, then an
iPad before a steering meeting.*

### CRITICAL

**R6-U1. "Where is my strategy?"** I set strategic objectives — the thing I
personally own — and the only place to see how they're performing is buried
in Hub Settings next to the demo studio. Ideas and value roll up per
objective in the API, but there is no first-class "How is my strategy
performing?" view on the main path. For my level, that view *is* the
product; everything else is operations.

**R6-U2. "You say 'verified' — prove it where you say it."** The verified
number is the pitch, but next to it there's no 'how is this computed?'
affordance. The methodology exists (docs, ledger), yet at the moment of
skepticism — my finger on the number — there's no one-click path from claim
to method. An ⓘ that opens the ledger entry trail would close the loop.

**R6-U3. "Every number is a snapshot. I manage deltas."** Nothing shows
movement: no verified-value trend vs last month, no pipeline
week-over-week, no 'since your last visit.' A leader decides on
trajectories; the trajectory chart exists on Overview but the P&L, ledger,
and board pack are all timeless. The board pack especially needs 'vs prior
period' columns or it can't survive a CFO meeting.

### HIGH IMPACT

- **R6-U4.** "The Innovation P&L — the one thing I came for — is folded
  into a one-line bar I almost scrolled past." Progressive disclosure
  optimized for contributors traded away the executive's landing moment.
  Fold it for contributors, open it for executives (role-aware default).
- **R6-U5.** "Who approved this?" Case cards don't show accountability —
  approver name and date live in a history feed, not on the artifact. In an
  enterprise, decisions wear name tags.
- **R6-U6.** "I can approve or reject — I can't *delegate*." Half my job is
  routing decisions to the right owner; there's no 'assign to' anywhere.
- **R6-U7.** "No fiscal framing." Annualized numbers with no FY/quarter
  boundaries, one hardcoded currency. Global enterprises will ask in the
  first demo.
- **R6-U8.** "I'd present this at steering — but there's no presentation
  mode." Sidebar, banners, and profile chrome all visible; one 'clean
  screen' toggle would make the Overview boardroom-safe.

### NICE TO HAVE

- **R6-N1.** Data freshness ('observed 3d ago') should sit beside the
  verified hero, not only inside the ledger.
- **R6-N2.** Board pack lacks the workspace/brand name in its header.
- **R6-N3.** Praise where due: calibration discounts, low-sample flags on
  the genome, and claimed-vs-verified separation all read as *designed for
  my skepticism* — keep that voice everywhere.

## Round 6 verdict

The operational journey is solid; the *executive* journey stops one floor
short. R6-U1 (strategy view on the main path) and R6-U3 (deltas, not
snapshots) are the two that decide whether a senior leader opens this
weekly or delegates it forever. R6-U2 is the cheapest trust win in the
whole backlog.

---
---

# Round 7 — three-persona pass (2026-07-03)

*Contributor, reviewer, and senior leader each walked their full journey on
the live app. The journeys are now clean in the middle; both loose ends are
loops that don't close.*

### CRITICAL

**R7-C1 (contributor). "They asked for more info — and I have no way to
give it."** Feedback arrives ("Which reports, and what decision do they
drive?"), My Submissions flags it, the badge counts it… and then nothing:
there is no way to *revise* a submitted idea. No edit, no formal respond
action. The core feedback loop — the moment the hub asked for collaboration
— dead-ends at a read-only card. The contributor's only move is to submit a
duplicate.

**R7-C2 (reviewer). "The backlog is where ideas go to be forgotten."** Hold
sends an idea to the backlog with a one-line count at the bottom of
Approvals. There is no resume/reactivate action, no review date, no
visibility of what's parked. 'Hold (backlog)' is currently a polite
synonym for decline — which corrupts the meaning of every backlog metric.

### HIGH IMPACT

- **R7-H1 (leader).** Day-one deltas render "+$0 since 2026-07-03" — delta
  noise when since == as_of; suppress until there's an actual prior day.
- **R7-H2 (reviewer).** Rubric shows count and average only; reviewers
  can't see each other's per-criterion scores or comments, so calibration
  conversations can't happen.
- **R7-H3 (leader).** Delegation still missing (carried R6-U6) — the most
  requested exec action after approve.
- **R7-H4 (all).** Notifications remain scattered: badge on My
  Submissions, feed on Ideas, webhook outbound — no single "what happened
  since I was last here" surface.

### NICE TO HAVE

- **R7-N1.** Fiscal framing/currency (carried).
- **R7-N2.** "Frozen baseline" tooltip glossary (carried, third sighting).
- **R7-N3.** Backlog/held ideas could show *why* they were held (the
  comment exists in events, unused).

## Round 7 verdict

Every persona now completes their happy path. What's broken is the two
*unhappy* paths: feedback with no reply channel (R7-C1) and hold with no
resume (R7-C2). Both are loop-closing fixes, not features — and both
corrupt trust in the process if left open: one teaches submitters that
feedback is rejection, the other teaches reviewers that hold is a lie.
