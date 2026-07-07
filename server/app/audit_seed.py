"""Seed data for the Innovation Management Audit (Governance tab).
All methodology content lives HERE — editing this file changes the product.
Anchor texts seed from the global stage rubric; replace any question's
'anchors' dict with bespoke texts at will (see spec for authoritative copy)."""

GLOBAL_RUBRIC = {
    0: "Lacking/absent", 1: "Basic/informal & person-dependent",
    2: "Emerging/defined but partially adopted",
    3: "Managed/consistently practiced & resourced",
    4: "Advanced/optimized, data-driven, continuously improved"}

BANDS = [(0, 39, "Lacking"), (40, 59, "Developing"), (60, 79, "Emerging"), (80, 100, "Ready")]
READINESS_THRESHOLD = 80
PERCEPTION_GAP_THRESHOLD = 15
MIN_SEGMENT_N = 3
VALUE_QUADRANT_THRESHOLD = 60

DIMENSIONS = [
    ("D1", "Strategy & Ambition", ["4 Context", "5 Leadership", "6 Planning"]),
    ("D2", "Portfolio & Resource Allocation", ["6 Planning", "8 Operations"]),
    ("D3", "Process & Pipeline", ["8 Operations"]),
    ("D4", "Governance & Organizational Architecture", ["5 Leadership", "7 Support"]),
    ("D5", "Culture & Talent", ["7 Support"]),
    ("D6", "Ecosystem & Partnerships", ["8 Operations (partnerships, intelligence)"]),
    ("D7", "Enablers: Funding, Data & Technology", ["7 Support"]),
    ("D8", "Measurement & Value Realization", ["9 Performance evaluation", "10 Improvement"]),
]
WEIGHTS = {d[0]: 1.0 for d in DIMENSIONS}

E, M, P = "executive", "management", "practitioner"
QUESTIONS = [
    ("D1.Q1", "D1", [E, M, P], "Our organization has an explicit innovation strategy linked to overall business strategy."),
    ("D1.Q2", "D1", [E, M], "Innovation-led growth targets are quantified and cascaded to business units."),
    ("D1.Q3", "D1", [E, M, P], "Leadership visibly sponsors and resources innovation."),
    ("D1.Q4", "D1", [E, M], "We have defined where we will and will not play (innovation domains / opportunity spaces)."),
    ("D2.Q1", "D2", [E, M], "We manage innovation initiatives as a balanced portfolio across core, adjacent, and transformational horizons."),
    ("D2.Q2", "D2", [E, M], "Resource allocation is dynamic — funding shifts to validated opportunities and weak projects are stopped."),
    ("D2.Q3", "D2", [E, M, P], "Portfolio decisions use transparent criteria (risk, timing, value) rather than sponsorship politics."),
    ("D3.Q1", "D3", [E, M, P], "We have a defined end-to-end process from idea capture through experimentation to scaling."),
    ("D3.Q2", "D3", [M, P], "Ideas are tested with customers or users early, via structured experiments, before major investment."),
    ("D3.Q3", "D3", [M, P], "Stage/gate decision points exist with clear evidence requirements and cycle-time expectations."),
    ("D3.Q4", "D3", [E, M, P], "Successful pilots have a defined, resourced path to scale."),
    ("D4.Q1", "D4", [E, M], "Roles, decision rights, and accountability for innovation are clearly defined."),
    ("D4.Q2", "D4", [E, M, P], "Innovation governance balances control with speed — approvals do not strangle experiments."),
    ("D4.Q3", "D4", [E, M], "Dedicated structures (teams, labs, funds) exist with mandates distinct from run-the-business units."),
    ("D5.Q1", "D5", [E, M, P], "People at all levels feel safe to propose ideas, challenge the status quo, and report failed experiments."),
    ("D5.Q2", "D5", [E, M, P], "Time, incentives, and recognition support participation in innovation."),
    ("D5.Q3", "D5", [M, P], "We deploy strong talent — not just available talent — to priority innovation initiatives and build innovation skills."),
    ("D6.Q1", "D6", [E, M], "We systematically source ideas and capabilities externally (customers, startups, academia, suppliers)."),
    ("D6.Q2", "D6", [M, P], "We have repeatable mechanisms for partnering (pilots, ventures, licensing) with clear IP practices."),
    ("D6.Q3", "D6", [E, M, P], "External insight (market, technology, trends) regularly informs our innovation choices."),
    ("D7.Q1", "D7", [E, M], "Innovation has protected, multi-horizon funding distinct from annual operating budgets."),
    ("D7.Q2", "D7", [E, M, P], "Teams can access the data, tools, and technology platforms needed to experiment quickly."),
    ("D7.Q3", "D7", [M, P], "Knowledge and learnings from past initiatives are captured and reusable."),
    ("D8.Q1", "D8", [E, M], "We track a balanced set of innovation metrics across inputs, activities, outputs, and outcomes."),
    ("D8.Q2", "D8", [E, M, P], "Realized value from innovation is measured and attributed."),
    ("D8.Q3", "D8", [E, M], "Metrics drive decisions — portfolio rebalancing, funding, and improvement of the innovation system itself."),
]

# (id, dim, band_lo, band_hi, title, effort S/M/L, impact H/M/L, horizon)
RECOMMENDATION_TEMPLATES = [
    ("R-D1-1", "D1", 0, 39, "Draft and ratify an innovation strategy", "M", "H", "now"),
    ("R-D1-2", "D1", 40, 59, "Quantify and cascade the innovation growth target", "M", "H", "now"),
    ("R-D1-3", "D1", 60, 79, "Define or refresh innovation domains", "S", "M", "next"),
    ("R-D2-1", "D2", 0, 39, "Stand up a single portfolio view", "S", "H", "now"),
    ("R-D2-2", "D2", 40, 59, "Set balance targets and a quarterly rebalancing cadence", "M", "H", "next"),
    ("R-D2-3", "D2", 60, 79, "Adopt metered, evidence-based funding", "M", "H", "next"),
    ("R-D3-1", "D3", 0, 39, "Define a minimum viable idea-to-scale process", "M", "H", "now"),
    ("R-D3-2", "D3", 40, 59, "Institute evidence-based gates", "M", "H", "next"),
    ("R-D3-3", "D3", 60, 79, "Build a scaling playbook and handoff contract", "M", "H", "next"),
    ("R-D4-1", "D4", 0, 39, "Assign accountable innovation ownership", "S", "H", "now"),
    ("R-D4-2", "D4", 40, 59, "Right-size governance for experiments", "S", "M", "now"),
    ("R-D4-3", "D4", 60, 79, "Clarify explore/exploit interfaces", "M", "M", "later"),
    ("R-D5-1", "D5", 0, 39, "Run a leadership listening and safety reset", "S", "H", "now"),
    ("R-D5-2", "D5", 40, 59, "Create time and recognition mechanisms", "M", "M", "next"),
    ("R-D5-3", "D5", 60, 79, "Build innovation skill paths and deploy top talent", "L", "H", "later"),
    ("R-D6-1", "D6", 0, 39, "Open the aperture in one domain", "S", "M", "next"),
    ("R-D6-2", "D6", 40, 59, "Standardize partnering playbooks and IP templates", "M", "M", "next"),
    ("R-D6-3", "D6", 60, 79, "Formalize strategic intelligence into the governance cadence", "M", "M", "later"),
    ("R-D7-1", "D7", 0, 39, "Ring-fence seed funding", "S", "H", "now"),
    ("R-D7-2", "D7", 40, 59, "Provide experimentation infrastructure", "M", "H", "next"),
    ("R-D7-3", "D7", 60, 79, "Introduce multi-vehicle funding", "L", "H", "later"),
    ("R-D8-1", "D8", 0, 39, "Define the metric chain v1", "S", "H", "now"),
    ("R-D8-2", "D8", 40, 59, "Agree value attribution rules with Finance", "M", "H", "next"),
    ("R-D8-3", "D8", 60, 79, "Close the loop on the innovation system", "S", "M", "next"),
]

GAP_TEMPLATE = ("R-GAP", "Close the perception gap on {dimension_name}",
                "Scores on {dimension_name} diverge by {gap} points between {level_a} and "
                "{level_b}. Run structured listening sessions, then communicate the changes made.",
                "S", "H", "now")


def anchors_for(statement: str):
    return {str(k): f"{v} — with respect to: {statement.rstrip('.')}"
            for k, v in GLOBAL_RUBRIC.items()}
