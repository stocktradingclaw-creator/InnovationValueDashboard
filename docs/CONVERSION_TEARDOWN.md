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
