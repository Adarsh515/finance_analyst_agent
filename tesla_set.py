"""
Phase 6.8 - the Tesla question set.

WHY A THIRD SET RATHER THAN MORE ROWS IN cross_set.py.

Every gate this project has run reports two denominators: regression 40 and capability 54.
"Median gen_in 3,736 - the same number as the 6.0 gate" is the kind of sentence that only
means something while the denominators hold still. Dropping eight Tesla questions into
CROSS_SET would silently turn 54 into 62 and make every future comparison against every past
gate an argument about which rows were in the set.

So Tesla gets its own set and its own line on the scoreboard. Regression and capability stay
byte-comparable with 6.0, 6.4 and 6.7; the sixth filing is measured beside them, not inside
them. This is the same two-scoreboard discipline the project already uses, extended by one.

WHAT THESE QUESTIONS ARE FOR. A corpus that grows while the question set stands still is a
corpus whose new part is untested - the index would hold 498 Tesla chunks that nothing ever
checks. Each item below exists for a stated reason, and four of them guard a claim made in the
6.8 impact analysis:

    ts03 guards  d04 - Tesla STATES total liabilities; AMD does not and must be derived
    ts04 guards  d05 - Tesla has no Data Center segment, and the filing mentions data centres
                       only as costs, which is exactly the trap
    ts07 guards  x30 - the income tax BENEFIT must stay uniquely AMD's
    ts08 guards  p02 - Tesla's year-end must not collide with Intel's and AMD's

Every figure here was read out of data/tesla_10k_fy2025.htm on 2026-08-19, from the parsed
consolidated statements. None of it was typed from memory - see corpus_facts.py's header for
what that costs.
"""

TESLA_SET = [
    # --- single-company extraction ---------------------------------------------------------
    {"id": "ts01",
     "companies": ["Tesla"],
     "question": "What was Tesla's total revenue for fiscal year 2025?",
     "reference_answer": "$94,827 million.",
     "evidence": "Tesla consolidated statements of income: Total revenues 94,827 (FY2025), "
                 "made up of total automotive revenues 69,526, energy generation and storage "
                 "12,771 and services and other 12,530.",
     "difficulty": "easy",
     "section": "single-company extraction",
     "answer_type": "number"},

    # The NCI trap, deliberately mirroring Intel's r03. Tesla has BOTH figures and they differ
    # by 61 - small, same sign, and therefore much easier to conflate than Intel's sign flip.
    {"id": "ts02",
     "companies": ["Tesla"],
     "question": "What was Tesla's net income attributable to common stockholders in fiscal "
                 "year 2025?",
     "reference_answer": "$3,794 million. Total net income was $3,855 million; $61 million of "
                         "that was attributable to noncontrolling interests.",
     "evidence": "Tesla income statement: Net income 3,855; net income attributable to "
                 "noncontrolling interests and redeemable noncontrolling interests 61; "
                 "Net income attributable to common stockholders 3,794.",
     "difficulty": "medium",
     "section": "single-company extraction, definition trap",
     "answer_type": "number"},

    # The companion to d04. AMD's balance sheet has no total-liabilities line and the figure
    # must be derived; Tesla's states it outright. Same question, two document shapes.
    {"id": "ts03",
     "companies": ["Tesla"],
     "question": "What were Tesla's total liabilities at the end of fiscal year 2025?",
     "reference_answer": "$54,941 million, stated directly on the balance sheet.",
     "evidence": "Tesla consolidated balance sheets, December 31, 2025: Total liabilities "
                 "54,941. Total assets 137,806; total stockholders' equity 82,137.",
     "difficulty": "easy",
     "section": "single-company extraction",
     "answer_type": "number"},

    # 🔴 THE ATTRACTIVE NUISANCE. Tesla reports no Data Center segment - but the filing says
    # "data centers" seven times, in capital-expenditure and cost contexts ("investments in
    # compute infrastructure and data centers", "facilities costs such as data center
    # depreciation"). A system that pattern-matches the phrase will find text and invent a
    # share. The correct answer is that the segment does not exist.
    {"id": "ts04",
     "companies": ["Tesla"],
     "question": "What share of Tesla's total revenue came from its Data Center segment in "
                 "fiscal year 2025?",
     "reference_answer": "Tesla does not report a Data Center segment. It has two reportable "
                         "segments: automotive, and energy generation and storage. Data "
                         "centres appear in the filing only as costs and planned capital "
                         "expenditure, not as a source of revenue.",
     "evidence": "Tesla Note 16, Segment Reporting: 'two operating and reportable segments: "
                 "(i) automotive and (ii) energy generation and storage'. The phrase 'data "
                 "centers' appears only in risk factors, capital-expenditure guidance, R&D "
                 "cost composition and the lease note - never as segment revenue.",
     "difficulty": "hard",
     "section": "absent segment - must decline rather than derive",
     "answer_type": "short-text"},

    {"id": "ts05",
     "companies": ["Tesla"],
     "question": "How many people did Tesla employ at the end of fiscal year 2025?",
     "reference_answer": "134,785 as of December 31, 2025.",
     "evidence": "Tesla Human Capital Resources: 'As of December 31, 2025, our employee "
                 "headcount worldwide was 134,785'.",
     "difficulty": "easy",
     "section": "single-company extraction",
     "answer_type": "number"},

    # Guards x30: the income tax BENEFIT must stay uniquely AMD's. Tesla booked an expense in
    # FY2025 - though note it recorded a large BENEFIT in 2023, which is in the same table.
    {"id": "ts06",
     "companies": ["Tesla"],
     "question": "Did Tesla report an income tax expense or an income tax benefit in fiscal "
                 "year 2025, and how much?",
     "reference_answer": "An expense of $1,423 million.",
     "evidence": "Tesla income statement: Provision for (benefit from) income taxes 1,423 "
                 "(2025), 1,837 (2024), (5,001) (2023). The 2025 figure is a provision, i.e. "
                 "an expense; the 2023 figure in the same row was a benefit.",
     "difficulty": "medium",
     "section": "single-company extraction, sign trap",
     "answer_type": "short-text"},

    # --- cross-company -----------------------------------------------------------------------
    # The first comparison in this corpus that is NOT chipmaker versus chipmaker.
    {"id": "ts07",
     "companies": ["Tesla", "NVIDIA"],
     "question": "How did Tesla's gross margin compare with NVIDIA's in their most recent "
                 "fiscal years?",
     "reference_answer": "Tesla's was about 18.0% ($17,094M of $94,827M, FY2025) against "
                         "NVIDIA's about 71.1% (FY2026) - roughly 53 percentage points lower.",
     "evidence": "Tesla gross profit 17,094 on total revenues 94,827 = 18.0%. NVIDIA MD&A "
                 "gross margin 71.1% (FY2026). The fiscal years are not identical periods.",
     "difficulty": "hard",
     "section": "cross-company derived ratio",
     "answer_type": "short-text"},

    # Guards p02. Tesla's year-end is FOUR DAYS from Intel's and AMD's, which is exactly close
    # enough for a careless answer to call them the same.
    {"id": "ts08",
     "companies": ["Tesla", "Intel", "AMD"],
     "question": "On what date did Tesla's most recent fiscal year end, and did any other "
                 "company in these filings end its fiscal year on that same date?",
     "reference_answer": "31 December 2025. No other company shares it: Intel and AMD both "
                         "ended their fiscal years on 27 December 2025, and NVIDIA's ended on "
                         "25 January 2026.",
     "evidence": "Tesla 10-K cover page: fiscal year ended December 31, 2025. Intel and AMD "
                 "both ended December 27, 2025. NVIDIA FY2026 ended January 25, 2026.",
     "difficulty": "hard",
     "section": "cross-company, near-miss dates",
     "answer_type": "short-text"},
]


def bucket(example):
    return "cross-company" if len(example["companies"]) >= 2 else "single-company"


if __name__ == "__main__":
    import corpus_facts

    ok = 0
    ids = [e["id"] for e in TESLA_SET]
    assert len(set(ids)) == len(ids), "duplicate id"

    # 🔴 THE CHECK THIS FILE SHIPPED WITHOUT, AND THE BUG IT LET THROUGH.
    # The first version numbered these t01..t08 and asserted the ids were unique - WITHIN THIS
    # FILE. cross_set.py already had t01, t02 and t03, where `t` means TREND. Three ids
    # collided. Scoring was unaffected, because each set runs its own list, but `--ids t01`
    # became ambiguous and an analysis keyed on id silently merged rows from two different
    # questions. Same shape as corpus_facts.py reading two sets when there were three:
    # A CHECK IS ONLY AS WIDE AS WHAT IT LOOKS AT.
    from cross_set import CROSS_SET
    from golden_set import GOLDEN_SET
    others = {e["id"] for e in CROSS_SET} | {e["id"] for e in GOLDEN_SET}
    clash = sorted(set(ids) & others)
    assert not clash, (f"id collision with the existing sets: {clash}. Ids must be unique "
                       f"ACROSS all three sets, because --ids selects by id alone.")
    for e in TESLA_SET:
        for field in ("id", "companies", "question", "reference_answer", "evidence",
                      "difficulty", "section", "answer_type"):
            assert e.get(field), f"{e['id']} is missing {field}"
        assert "Tesla" in e["companies"], e["id"]
    ok += 1

    # Every figure in a REFERENCE must also appear in the EVIDENCE, so no reference asserts a
    # number that no quoted line supports. This is the mechanical version of "show your work".
    import re
    FIG = re.compile(r"\b\d{1,3}(?:,\d{3})+\b")
    for e in TESLA_SET:
        ref = set(FIG.findall(e["reference_answer"]))
        ev = set(FIG.findall(e["evidence"]))
        missing = ref - ev
        assert not missing, f"{e['id']}: reference cites {missing} with nothing in evidence"
    ok += 1

    # ...and the reverse direction of the same discipline: these are NEW figures, so they are
    # not in the old verified sets yet. This asserts they are new rather than silently
    # colliding with a figure that means something else.
    fresh = {"94,827", "3,794", "3,855", "54,941", "137,806", "82,137", "134,785",
             "1,423", "17,094", "69,526", "12,771", "12,530", "5,001", "1,837"}
    known = {f for f in fresh if corpus_facts.is_verified(f)}
    print(f"tesla_set.py: {len(TESLA_SET)} items, {ok}/{ok} checks passed, $0.00 spent")
    print(f"  buckets: " + ", ".join(f"{b}={sum(1 for e in TESLA_SET if bucket(e)==b)}"
                                     for b in ("single-company", "cross-company")))
    print(f"  figures already present in golden/cross before this file: "
          f"{sorted(known) if known else 'none - all eight items are new evidence'}")
