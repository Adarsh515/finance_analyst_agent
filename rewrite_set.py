# rewrite_set.py
# Phase 6.4 - the rewriter's own eval set. 22 conversations, scored MECHANICALLY.
#
# NO JUDGE, ON PURPOSE. "Did the rewrite resolve the pronoun to the right entity and period?"
# is a substring question, and this project has spent a whole phase learning what a judge
# costs: it needs its own calibration, its own mutation suite and its own regression before
# any number it produces can be trusted (lesson: a judge is part of the system under test).
# A rewriter can be graded with `in` and `not in`, so it is.
#
# HOW AN ITEM IS SCORED. Each carries `must_have` (every string must appear, case-insensitive)
# and `must_not` (none may appear). `must_not` is the half that catches the failure that
# matters most: carrying an entity forward into a question that switched topic. A set with
# only `must_have` would score a rewriter that appends every company it has ever seen at 100%.
#
# THE BUCKETS, and what each one is for:
#   pronoun        "its", "uska" - the classic case, and the easy one
#   elided         "and AMD?" - the metric and period must survive, the company must change
#   period         "and the previous year?" - the company survives, the period must change
#   switch         a genuinely new topic - NOTHING may be carried over. The dangerous bucket.
#   standalone     already complete - the rewrite must NOT invent detail. The other dangerous
#                  one, and the one a rewriter graded only on follow-ups would never fail.
#   noise          history that is real but irrelevant to the new message
#
# Hinglish items are deliberate: the learner asks follow-ups that way ("aur uska net income?"),
# and an eval written only in the English the corpus uses would measure a system nobody uses.
#
# GROUND TRUTH DISCIPLINE. Every expected company and period below is a string that appears in
# the index (see the corpus list in PROJECT_TRACKER). An item whose ground truth is not clean
# is reported and excluded, never quietly graded.

# EVERY FIGURE BELOW IS CHECKED against golden_set.py / cross_set.py by the self-test at the
# bottom. Three of the figures in the first draft of this file were wrong - I typed them from
# memory when the repo already held verified values - so the check is mechanical now. See
# corpus_facts.py for what that cost.

# Shorthands for the conversation turns, so an item reads as a conversation.
def U(text):
    return ("user", text)


def A(text):
    return ("assistant", text)


REWRITE_SET = [
    # --- pronoun -----------------------------------------------------------------------------
    {"id": "rw01", "bucket": "pronoun",
     "history": [U("What was NVIDIA's total revenue for fiscal year 2026?"),
                 A("NVIDIA's total revenue for fiscal year 2026 was $215,938 million.")],
     "question": "And what was its net income?",
     "must_have": ["nvidia", "net income"], "must_not": ["amd", "intel"],
     "why": "pronoun 'its' must resolve to the company just discussed"},

    {"id": "rw02", "bucket": "pronoun",
     "history": [U("What was AMD's total revenue for fiscal year 2025?"),
                 A("AMD's total revenue for fiscal year 2025 was $34,639 million.")],
     "question": "aur uska net income kya tha?",
     "must_have": ["amd", "net income"], "must_not": ["nvidia", "intel"],
     "why": "Hinglish possessive - the learner's actual phrasing"},

    {"id": "rw03", "bucket": "pronoun",
     "history": [U("What was Intel's total revenue for fiscal year 2025?"),
                 A("Intel's total revenue for fiscal year 2025 was $52,853 million.")],
     "question": "How did that compare with the prior year?",
     "must_have": ["intel"], "must_not": ["nvidia", "amd"],
     "why": "'that' refers to the metric, not the company - both must survive"},

    {"id": "rw04", "bucket": "pronoun",
     "history": [U("What was NVIDIA's gross margin in fiscal year 2026?"),
                 A("NVIDIA's gross margin was 71.1% in fiscal year 2026.")],
     "question": "Why did it move?",
     "must_have": ["nvidia", "gross margin"], "must_not": ["amd", "intel"],
     "why": "a bare 'it' with no noun anywhere in the new message"},

    # --- elided entity -------------------------------------------------------------------------
    {"id": "rw05", "bucket": "elided",
     "history": [U("What was NVIDIA's total revenue for fiscal year 2026?"),
                 A("NVIDIA's total revenue for fiscal year 2026 was $215,938 million.")],
     "question": "And AMD?",
     "must_have": ["amd", "revenue"], "must_not": ["nvidia"],
     "why": "THE case that breaks naive rewriters: the metric carries, the company REPLACES"},

    {"id": "rw06", "bucket": "elided",
     "history": [U("What was AMD's net income for fiscal year 2025?"),
                 A("AMD's net income for fiscal year 2025 was $4,335 million.")],
     "question": "aur Intel ka?",
     "must_have": ["intel", "net income"], "must_not": ["amd"],
     "why": "same replacement, in Hinglish"},

    {"id": "rw07", "bucket": "elided",
     "history": [U("What was NVIDIA's total revenue for fiscal year 2026?"),
                 A("NVIDIA's total revenue for fiscal year 2026 was $215,938 million.")],
     "question": "What about total assets?",
     "must_have": ["nvidia", "total assets"], "must_not": ["amd", "intel"],
     "why": "the METRIC is replaced and the company carries - the mirror of rw05"},

    {"id": "rw08", "bucket": "elided",
     "history": [U("Compare NVIDIA and AMD gross margin for the latest fiscal year."),
                 A("NVIDIA's gross margin was 71.1%; AMD's was 50%.")],
     "question": "And Intel?",
     "must_have": ["intel", "gross margin"], "must_not": [],
     "why": "two companies in history, a third in the new message - no must_not, because a "
            "comparison question may legitimately keep the others"},

    # --- period carry-over -----------------------------------------------------------------------
    {"id": "rw09", "bucket": "period",
     "history": [U("What was NVIDIA's total revenue for fiscal year 2026?"),
                 A("NVIDIA's total revenue for fiscal year 2026 was $215,938 million.")],
     "question": "And the previous year?",
     "must_have": ["nvidia", "2025"], "must_not": [],
     "why": "the period must be RESOLVED to a year, not left as 'the previous year'"},

    {"id": "rw10", "bucket": "period",
     "history": [U("What was AMD's total revenue for fiscal year 2025?"),
                 A("AMD's total revenue for fiscal year 2025 was $34,639 million.")],
     "question": "aur pichhle saal?",
     "must_have": ["amd"], "must_not": ["nvidia", "intel"],
     "why": "Hinglish period reference. The company must survive; 2024 is outside the corpus, "
            "so the year itself is NOT required - a correct refusal downstream is the right "
            "outcome and the rewriter's job is only to make the question askable"},

    {"id": "rw11", "bucket": "period",
     "history": [U("What was NVIDIA's revenue in the third quarter of fiscal year 2026?"),
                 A("NVIDIA's revenue in Q3 FY2026 was $57,006 million.")],
     "question": "And for the full year?",
     "must_have": ["nvidia", "2026"], "must_not": [],
     "why": "quarter to annual, same company - the period changes SHAPE, not just value"},

    # --- topic switch: the dangerous bucket ---------------------------------------------------------
    {"id": "rw12", "raw_ok": True, "bucket": "switch",
     "history": [U("What was NVIDIA's total revenue for fiscal year 2026?"),
                 A("NVIDIA's total revenue for fiscal year 2026 was $215,938 million.")],
     "question": "What was Intel's total assets at the end of fiscal year 2025?",
     "must_have": ["intel", "total assets", "2025"], "must_not": ["nvidia"],
     "why": "a fully standalone question after unrelated history. Carrying NVIDIA forward "
            "here would corrupt a question the user got right"},

    {"id": "rw13", "raw_ok": True, "bucket": "switch",
     "history": [U("What was AMD's gross margin for fiscal year 2025?"),
                 A("AMD's gross margin for fiscal year 2025 was 50%.")],
     "question": "Which companies are covered in this corpus?",
     "must_have": [], "must_not": ["50%", "gross margin"],
     "why": "a meta question with no entity at all - the rewriter must not glue a metric to it"},

    {"id": "rw14", "raw_ok": True, "bucket": "switch",
     "history": [U("What was NVIDIA's net income for fiscal year 2026?"),
                 A("NVIDIA's net income for fiscal year 2026 was $120,067 million.")],
     "question": "Now tell me about AMD's three reportable segments.",
     "must_have": ["amd", "segment"], "must_not": ["nvidia", "net income"],
     "why": "explicit switch, explicit new topic - nothing may survive"},

    # --- already standalone: must NOT be 'improved' ---------------------------------------------------
    {"id": "rw15", "raw_ok": True, "bucket": "standalone",
     "history": [U("What was NVIDIA's total revenue for fiscal year 2026?"),
                 A("NVIDIA's total revenue for fiscal year 2026 was $215,938 million.")],
     "question": "What was AMD's total revenue for fiscal year 2025?",
     "must_have": ["amd", "total revenue", "2025"], "must_not": ["nvidia", "2026"],
     "why": "complete on its own. A rewriter that appends context here has damaged it"},

    {"id": "rw16", "raw_ok": True, "bucket": "standalone",
     "history": [U("Hello"), A("Hello. Ask me about the filings in the corpus.")],
     "question": "What was Intel's total revenue for fiscal year 2025?",
     "must_have": ["intel", "total revenue", "2025"], "must_not": [],
     "why": "irrelevant history plus a complete question - the baseline case"},

    {"id": "rw17", "raw_ok": True, "bucket": "standalone",
     "history": [U("What was NVIDIA's total revenue for fiscal year 2026?"),
                 A("NVIDIA's total revenue for fiscal year 2026 was $215,938 million.")],
     "question": "Compare NVIDIA and AMD gross margin for the latest fiscal year.",
     "must_have": ["nvidia", "amd", "gross margin"], "must_not": [],
     "why": "standalone AND overlaps the history - the tempting case to over-edit"},

    # --- noise: real history, irrelevant to the new message --------------------------------------------
    {"id": "rw18", "bucket": "noise",
     "history": [U("What was NVIDIA's total revenue for fiscal year 2026?"),
                 A("NVIDIA's total revenue for fiscal year 2026 was $215,938 million."),
                 U("Thanks"), A("You're welcome.")],
     "question": "And its total assets?",
     "must_have": ["nvidia", "total assets"], "must_not": ["amd", "intel"],
     "why": "the referent is two turns back, behind a courtesy exchange"},

    {"id": "rw19", "bucket": "noise",
     "history": [U("What was AMD's total revenue for fiscal year 2025?"),
                 A("AMD's total revenue for fiscal year 2025 was $34,639 million."),
                 U("What about Intel's?"),
                 A("Intel's total revenue for fiscal year 2025 was $52,853 million.")],
     "question": "And NVIDIA's?",
     "must_have": ["nvidia", "revenue"], "must_not": [],
     "why": "three companies deep - the rewriter must take the METRIC from the thread and the "
            "company from the new message"},

    {"id": "rw20", "raw_ok": True, "bucket": "noise",
     "history": [U("Can you explain what a 10-K is?"),
                 A("A 10-K is an annual report filed with the SEC.")],
     "question": "And NVIDIA's revenue for fiscal year 2026?",
     "must_have": ["nvidia", "revenue", "2026"], "must_not": ["10-k is an annual"],
     "why": "history is a definition, not a data point - nothing to carry"},

    {"id": "rw21", "bucket": "noise",
     "history": [U("What was NVIDIA's total revenue for fiscal year 2026?"),
                 A("Not stated in the filing.")],
     "question": "And AMD?",
     "must_have": ["amd", "revenue"], "must_not": [],
     "why": "the previous answer was a REFUSAL. The topic still carries; a rewriter that reads "
            "the refusal as the subject will produce nonsense"},

    {"id": "rw22", "raw_ok": True, "bucket": "noise",
     "history": [U("What was NVIDIA's total revenue for fiscal year 2026?"),
                 A("NVIDIA's total revenue for fiscal year 2026 was $215,938 million.")],
     "question": "ok",
     "must_have": [], "must_not": ["total revenue", "fiscal year"],
     "must_be": "ok",
     "why": "NOT A QUESTION. Measured 2026-08-18: the rewriter turned \"ok\" into \"What was "
            "NVIDIA's total revenue for fiscal year 2026?\" - it re-asked the previous "
            "question, which in the product means the user types \"ok\" and pays for an "
            "answer they already have. The item originally asserted nothing and scored it as "
            "a pass. Fixed in CODE (rewriter.is_acknowledgement), not in the prompt, so the "
            "right answer is now exact: the message comes back unchanged."},

    # --- Phase 6.8: a period that does not exist for the company being switched to ----------
    # THE LIVE DEFECT THIS SET COULD NOT SEE. rw05 already covers "And AMD?" after an NVIDIA
    # fiscal-2026 question, and it checks that AMD REPLACES NVIDIA - but it never looked at the
    # PERIOD, so "AMD's revenue for fiscal year 2026" has passed it for four phases. AMD has no
    # fiscal 2026 filing. Neither does Tesla.
    #
    # Before Tesla was indexed this cost nothing: the answer was a refusal either way, and the
    # tracker recorded carrying the period as faithful-but-limited. With Tesla in the corpus
    # the SAME rewrite turns a question the filings CAN answer into "Not stated in the filing."
    # Measured live in the product on 2026-08-19, not inferred.
    {"id": "rw23", "bucket": "period",
     "history": [U("What was NVIDIA's total revenue for fiscal year 2026?"),
                 A("NVIDIA's total revenue for fiscal year 2026 was $215,938 million.")],
     "question": "And Tesla?",
     "must_have": ["tesla", "revenue"], "must_not": ["nvidia", "2026"],
     "why": "the company replaces AND the period must not follow it - Tesla's fiscal year is "
            "2025, so 'Tesla ... fiscal year 2026' names a filing that does not exist and "
            "refuses a question the corpus can answer"},

    {"id": "rw24", "bucket": "period",
     "history": [U("What was NVIDIA's total revenue for fiscal year 2026?"),
                 A("NVIDIA's total revenue for fiscal year 2026 was $215,938 million.")],
     "question": "And AMD?",
     "must_have": ["amd", "revenue"], "must_not": ["nvidia", "2026"],
     "why": "rw05 with its blind spot closed. rw05 passes as long as AMD replaces NVIDIA and "
            "never noticed the carried fiscal 2026; AMD's fiscal 2025 is the only AMD filing "
            "in this corpus"},

    # 🔑 THE CONTROL ARM. Without this item, "drop every period" passes rw23 and rw24 and looks
    # like a fix. It is not: NVIDIA DOES have a fiscal 2026 filing, so here the period must be
    # CARRIED. The pair is what is legal or illegal, never the period on its own - the same
    # rule plan_node already enforces in code, and the same reason the timing test in 6.2
    # needed a known-vs-known arm before its ratio meant anything.
    {"id": "rw25", "bucket": "period",
     "history": [U("What was NVIDIA's total revenue for fiscal year 2026?"),
                 A("NVIDIA's total revenue for fiscal year 2026 was $215,938 million.")],
     "question": "And what was its net income?",
     "must_have": ["nvidia", "net income", "2026"], "must_not": [],
     "why": "CONTROL for rw23/rw24: the period must survive when the company genuinely has "
            "that filing. A fix that strips periods indiscriminately passes those two and "
            "breaks this one"},
]

BUCKETS = sorted({i["bucket"] for i in REWRITE_SET})


def score(item, rewritten):
    """Return (passed, notes). Pure string work - no model, no cost, no judgement."""
    # `must_be` is for the items where the correct output is EXACT rather than merely
    # containing the right things. Only an acknowledgement qualifies today: there is one
    # right answer ("give it back untouched") and any rewrite at all is wrong.
    if item.get("must_be") is not None:
        exact = (rewritten or "").strip() == item["must_be"]
        return exact, ("" if exact else f"MUST BE {item['must_be']!r}, got {rewritten!r}")
    low = (rewritten or "").lower()
    missing = [s for s in item["must_have"] if s.lower() not in low]
    present = [s for s in item["must_not"] if s.lower() in low]
    notes = []
    if missing:
        notes.append(f"MISSING {missing}")
    if present:
        notes.append(f"CARRIED OVER {present}")
    return (not missing and not present), "; ".join(notes)


if __name__ == "__main__":
    # The set checks itself before it is ever used to check anything else.
    ids = [i["id"] for i in REWRITE_SET]
    assert len(ids) == len(set(ids)), "duplicate id in REWRITE_SET"
    for i in REWRITE_SET:
        assert i["history"] and i["question"] and i["why"], i["id"]
        # an item cannot demand and forbid the same string - that is unpassable by
        # construction, and it would look like a rewriter defect forever
        clash = {s.lower() for s in i["must_have"]} & {s.lower() for s in i["must_not"]}
        assert not clash, f"{i['id']} both requires and forbids {clash}"
        # Every item declares whether its RAW question already passes, and BOTH directions
        # are checked. An item that is supposed to test the rewrite must fail on the raw
        # question, or it would score 100% against a function that returns its input. An item
        # marked do-no-harm must PASS on the raw question, or the label is a lie.
        #
        # This is per-item and explicit because my first version exempted whole BUCKETS, which
        # was wrong twice over: it silently excused rw18-rw21, which are genuine follow-ups
        # that do fail on the raw question, and it hid rw20, which is already standalone and
        # was sitting in the wrong bucket. A blanket exemption is how a suite stops testing
        # without anyone noticing.
        passed, _ = score(i, i["question"])
        if i.get("raw_ok"):
            assert passed, (
                f"{i['id']} is marked raw_ok but FAILS on its own raw question - "
                f"either the label or the assertion is wrong")
        else:
            assert not passed, (
                f"{i['id']} passes on the raw question - it tests nothing about the "
                f"rewriter. Mark it raw_ok if that is intended.")

    # The two halves measure different things and both are reported, because a rewriter can
    # be excellent at one and destructive at the other - and "22/22" would hide which.
    rewrite_items = [i for i in REWRITE_SET if not i.get("raw_ok")]
    harm_items = [i for i in REWRITE_SET if i.get("raw_ok")]
    assert len(rewrite_items) >= 12, (
        f"only {len(rewrite_items)} items actually test a rewrite")
    assert len(harm_items) >= 5, (
        f"only {len(harm_items)} items test that the rewriter does no harm - that direction "
        f"is where a rewriter damages questions the user already got right")
    print(f"  {len(rewrite_items)} items test the REWRITE, "
          f"{len(harm_items)} test DO-NO-HARM")

    # No figure in this file may be one the repo has never verified. The histories are
    # supposed to read like real conversations, and a made-up number in a "real" conversation
    # is a fact this project would be asserting to its own instructor.
    import json as _json
    from corpus_facts import unverified
    bad = unverified(_json.dumps(REWRITE_SET, ensure_ascii=False))
    assert not bad, (f"unverified figures in REWRITE_SET: {bad} - take them from "
                     f"golden_set.py / cross_set.py rather than from memory")

    counts = {b: sum(1 for i in REWRITE_SET if i["bucket"] == b) for b in BUCKETS}
    print(f"rewrite_set.py: {len(REWRITE_SET)} items, buckets {counts}, all self-checks passed")
