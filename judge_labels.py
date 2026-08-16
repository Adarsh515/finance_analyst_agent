# judge_labels.py
# Human labels for the judge calibration set (Phase 4.5.1).
#
# Source: the 40-item stratified sample of eval_44_gate2.jsonl - every flagged item, every
# question in a hard bucket (derived, three-way, red-flag, refusal, duplicate-source,
# quarterly), plus an evenly-spaced sample of the rest. Sampling only PASSING items would
# make false positives structurally invisible, which is the x28 lesson.
#
# WHO LABELLED THIS, AND THE BIAS THAT CREATES
# The labels were written by the same author as the system under test. That is a real
# conflict of interest and it is not hidden. Two things contain it:
#   1. Every label cites the verified corpus fact it was decided from - the figures in the
#      tracker, hand-checked against the filings. A label is auditable, not an opinion.
#   2. Borderline calls are marked, not smoothed over. A calibration set that pretends every
#      call is crisp hides exactly the region where a judge's variance lives.
# Anything the judge and this file disagree on should be read by a second person.
#
# THE RULE APPLIED, STATED ONCE SO IT IS APPLIED CONSISTENTLY
#   correct = 1  if every figure or claim the REFERENCE presents as the answer appears in
#                the system answer and is right. Extra correct detail is fine. A missing
#                part of a multi-part answer is 0.
#   grounded = 1 if every claim in the answer is supported by the context, INCLUDING claims
#                made by structure - a heading, an ordering, or a list membership is a claim.
#
# label: (correct, grounded, borderline, why)

LABELS = {
    # --- derived -------------------------------------------------------------
    "d01": (1, 1, False, "Intel 26.1% highest, AMD 23.36% next, gap 2.74pp; reference says Intel by ~2.7pp"),
    "d02": (1, 1, False, "three segments 16,635 + 14,550 + 3,454 = 34,639, all correct"),
    "d03": (1, 1, False, "NVIDIA 55.60%, Intel -0.51%, gap 56.11pp; reference 56.1pp"),
    "d04": (0, 0, False, "AMD 3,345/7,546 and Intel 400/2,762 are acquisition-note figures, not the "
                         "consolidated balance sheet; concludes Intel lowest, reference says AMD. "
                         "grounded=0 too: the figures exist in the context but the answer labels "
                         "them 'total liabilities/total assets' for the COMPANY, which they are not"),
    "d05": (1, 1, False, "NVIDIA 89.7% and AMD 48.0% both present and correct; the Intel refusal is "
                         "extra and honest - the reference does not ask for Intel"),
    "d06": (1, 1, False, "85.55% vs reference 85.6%"),
    "d07": (1, 1, False, "90,307 and 4.03x"),
    "d08": (1, 1, False, "303,430 combined and 11.42% share"),
    "d09": (1, 1, False, "6,493 continuing-operations figure and 18.74%"),
    "d10": (1, 1, True,  "62.5% correct, but derived by subtracting two ROUNDED percentages "
                         "(71.1 - 8.6) rather than the underlying figures. Right answer, fragile method"),

    # --- duplicate-source ----------------------------------------------------
    "p01": (1, 1, False, "130,497, sources agree, both named"),
    "p02": (1, 1, False, "27 December 2025; AMD 34,639 and Intel 52,853"),

    # --- regression (NVIDIA only) -------------------------------------------
    "q01": (1, 1, False, "215,938"),
    "q05": (1, 1, False, "4.93 basic"),
    "q09": (1, 1, False, "10,605"),
    "q13": (1, 1, False, "competition may adversely affect market share and financial results"),
    "q17": (1, 1, False, "78,551 increase, 115,186 -> 193,737"),
    "q21": (1, 1, False, "75.0% -> 71.1%, attributed to the Hopper-to-Blackwell transition; the "
                         "extra H20 charge and inventory factors are also in the filing"),
    "q25": (1, 1, False, "correct refusal - no FY2027 projection exists in the 10-K"),
    "q29": (1, 1, False, "47,187 and 65%"),
    "q33": (1, 1, False, "9,812"),
    "q37": (1, 1, False, "3.91 from 125,605 / 32,163; reference ~3.9"),

    # --- quarterly -----------------------------------------------------------
    "qq1": (1, 1, False, "57,006"),
    "qq2": (1, 1, False, "147,811 and the 68,127 remainder"),
    "qq3": (1, 1, False, "66,530 nine-month and 102,718 full-year"),

    # --- red-flag ------------------------------------------------------------
    "r01": (1, 0, True,
            "correct=1: NVIDIA plus 102,718 and 120,067 are all present and right. "
            "grounded=0 and this is a DISAGREEMENT with the judge: the answer lists "
            "'Intel (fiscal year 2023): net income 1,675 / operating cash flow 11,471' under a "
            "heading that reads 'generated LESS cash from operations than the net income they "
            "reported', which its own two numbers contradict. A parenthetical later corrects it. "
            "This is the same self-contradiction shape the judge DID catch on w02 and scored 0 - "
            "so the judge is not applying its own standard consistently"),
    "r02": (1, 1, False, "Intel, operating loss 2,214 and income before taxes 1,557"),
    "r03": (1, 1, False, "26, 293 and (267) all present with the 293 difference stated - the "
                         "figures that were missing at 3 slots/job now reach the context"),

    # --- three-way -----------------------------------------------------------
    "w01": (1, 1, False, "215,938 > 52,853 > 34,639, correctly ordered"),
    "w02": (1, 1, False, "Intel 211,429 ranked first, NVIDIA 206,803 second, AMD third - the "
                         "ordering that was self-contradictory at 3 slots/job is now right"),
    "w03": (1, 1, False, "102,718 > 9,697 > 7,709"),

    # --- cross-company / single-company / trend -----------------------------
    "x02": (1, 1, False, "4,335"),
    "x06": (1, 1, False, "181,299 difference, both figures right; the reference's 6.2x multiple is "
                         "absent but the difference the question asks for is present"),
    "x10": (1, 1, True,
            "BORDERLINE, and it is the mirror image of the old r03 failure. Both figures "
            "(193,737 and 16,635) are right, but the reference's 'roughly 11.6 times larger' "
            "comparison is never made. The judge scored the old r03 answer 0 for giving the "
            "comparison without the figures, and scores this 1 for giving the figures without "
            "the comparison. Labelled 1 because the question says 'compare' and two figures side "
            "by side are a comparison - but the judge reaching opposite verdicts on the two "
            "shapes is the finding, not this label"),
    "x14": (1, 1, False, "27 December 2025 and 25 January 2026"),
    "x17": (1, 1, False, "correct refusal - no AI accelerator market share is disclosed"),
    "x19": (1, 1, False, "NVIDIA 18,497 > Intel 13,774 > AMD 8,091"),
    "x23": (1, 1, False, "124,135 from 120,067 + 4,335 + (267)"),
    "x27": (1, 1, False, "Intel lowest gross margin 34.8%, R&D 26.1% of revenue"),
    "t01": (1, 1, False, "75.0% -> 71.1%, a fall of 3.9 percentage points"),
}
