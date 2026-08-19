"""
probe_rewrite_stability.py - does the SAME follow-up rewrite to the SAME text as a thread grows?

WHY THIS EXISTS. The learner typed "And how does that compare to Intel?" three times in one
conversation and paid three times. `inspect_cache.py` showed why: two of those turns produced
different standalone questions nineteen seconds apart -

    How do AMD's   R&D expenses for FY2025 compare to Intel's R&D expenses for FY2025?
    How do Intel's R&D expenses for FY2025 compare to AMD's?

Same meaning, different text, and the operands SWAPPED. The cache is keyed on the rewrite by
design - keying on the raw follow-up would make "And AMD?" a global key, which is the
catastrophic case Phase 6.5 named in writing - so two texts are two questions and the second
one pays.

This is not model randomness: temperature is 0. The INPUT differs, because each turn adds its
own question and answer to the history the rewriter reads.

WHAT IS MEASURED. One fixed follow-up, replayed against a history that grows turn by turn, and
a count of how many DISTINCT rewrites come out. A perfectly stable rewriter scores 1. This is
run BEFORE the prompt is touched, so the improvement can be a measurement rather than a claim.

COST. One rewrite call per depth per case: 4 cases x 5 depths = 20 calls at ~$0.00005 each,
so about $0.001 - call it Rs 0.10. No retrieval, no generation, no judge.
"""

import os
import sys
from collections import Counter

# Each case: the fixed follow-up, and a thread of (question, answer) turns that grows under it.
# The answers are short and realistic; what matters is that the history CHANGES, not that it
# is verbatim from a real run.
CASES = [
    {
        "name": "R&D comparison - the one the learner hit",
        "followup": "And how does that compare to Intel?",
        "thread": [
            ("What were AMD's research and development expenses for fiscal year 2025?",
             "AMD spent $8,091 million on research and development in fiscal year 2025."),
            ("And how does that compare to Intel?",
             "Intel spent $13,774 million versus AMD's $8,091 million."),
            ("Which of them spent a larger share of revenue?",
             "Intel, at about 26.1% of revenue versus AMD's 23.4%."),
            ("What about NVIDIA?",
             "NVIDIA spent $18,497 million, about 8.6% of its revenue."),
            ("And Tesla?",
             "Tesla spent $6,411 million, about 6.8% of its revenue."),
        ],
    },
    {
        "name": "pronoun carry - its",
        "followup": "And what was its net income?",
        "thread": [
            ("What was NVIDIA's total revenue for fiscal year 2026?",
             "NVIDIA's total revenue for fiscal year 2026 was $215,938 million."),
            ("And what was its net income?",
             "NVIDIA's net income for fiscal year 2026 was $120,067 million."),
            ("What were its total assets?",
             "NVIDIA's total assets were $206,803 million."),
            ("And its total liabilities?",
             "NVIDIA's total liabilities were $49,510 million."),
            ("What was its operating cash flow?",
             "NVIDIA generated $102,718 million from operating activities."),
        ],
    },
    {
        "name": "entity swap - a bare company name",
        "followup": "And Tesla?",
        "thread": [
            ("What was NVIDIA's total revenue for fiscal year 2026?",
             "NVIDIA's total revenue for fiscal year 2026 was $215,938 million."),
            ("And Tesla?",
             "Tesla's total revenue for fiscal year 2025 was $94,827 million."),
            ("How many people does NVIDIA employ?",
             "NVIDIA reported about 42,000 employees across 38 countries."),
            ("And Tesla?",
             "Tesla's employee headcount was 134,785 as of December 31, 2025."),
            ("Which of them has more total assets?",
             "NVIDIA, with $206,803 million against Tesla's $137,806 million."),
        ],
    },
    {
        "name": "already standalone - must never change at all",
        "followup": "What was Tesla's total revenue for fiscal year 2025?",
        "thread": [
            ("What was NVIDIA's total revenue for fiscal year 2026?",
             "NVIDIA's total revenue for fiscal year 2026 was $215,938 million."),
            ("And what was its net income?",
             "NVIDIA's net income for fiscal year 2026 was $120,067 million."),
            ("What were AMD's total assets?",
             "AMD's total assets were $76,926 million."),
            ("And Intel's?",
             "Intel's total assets were $211,429 million."),
            ("Which of them is larger?",
             "Intel, by $134,503 million."),
        ],
    },
]


def main():
    import agent
    import cache
    import judges
    import rewriter
    import telemetry

    # 🔴 THE FIRST VERSION OF THIS SCRIPT PRINTED "spent this run: $0.000000" AND IT WAS FALSE.
    # rewriter.py does `from judges import log_cost`, which binds the function into ITS
    # namespace. telemetry.capture() only sees calls routed through the tracked version, and
    # nothing here had re-pointed rewriter - so the sink stayed empty while the per-call lines
    # printed real money above it. Lesson 125's trap, walked into by the person who wrote
    # lesson 125. install() first; unpatched() proves it took.
    telemetry.install(judges, rewriter)
    assert not telemetry.unpatched(rewriter), \
        "cost capture never reached rewriter - this run would under-report to zero"

    label = sys.argv[1] if len(sys.argv) > 1 else "before"
    print(f"\n  run label: {label!r}   (pass one on the command line to name the run)")
    print(f"  {len(CASES)} follow-ups x {len(CASES[0]['thread'])} history depths\n")

    spent = 0.0
    worst = 0
    rows = []
    for case in CASES:
        outs = []
        with telemetry.capture() as calls:
            for depth in range(1, len(case["thread"]) + 1):
                history = []
                for q, a in case["thread"][:depth]:
                    history.append(("user", q))
                    history.append(("assistant", a))
                # filings=, or this probe measures the PRE-6.8 rewriter - a harness
                # measuring a system nobody runs. The first 'after' run was missing
                # this and came back byte-identical to 'before', which is exactly what
                # a probe pointed at the wrong code looks like: a confident no-change.
                out, _note = rewriter.rewrite(case["followup"], history,
                                              filings=agent.FILINGS)
                outs.append(out)
        spent += telemetry.usd(calls)

        # The cache key is what actually decides whether the user pays, so count DISTINCT KEYS,
        # not distinct strings: normalise() folds case, punctuation and the FY spellings, and
        # two rewrites that differ only there would still hit.
        keys = Counter(cache.normalise(o) for o in outs)
        worst = max(worst, len(keys))
        rows.append((case["name"], len(keys), len(outs), keys))

        print(f"  {case['name']}")
        print(f"    typed: {case['followup']!r}")
        print(f"    {len(keys)} distinct cache key(s) across {len(outs)} history depths")
        for text, n in keys.most_common():
            print(f"      x{n}  {text[:96]}")
        print()

    print("=" * 92)
    print(f"  distinct keys per case : " + ", ".join(f"{n}/{t}" for _nm, n, t, _k in rows))
    print(f"  worst case: {worst} different keys from one typed question.")
    print(f"  spent this run: ${spent:.6f}")
    print("=" * 92)
    # 🔴 THE FIRST VERSION OF THIS SUMMARY SAID "would be PAID FOR 10 times instead of 4",
    # which treats every distinct key as waste. That is FALSE and it pointed at the wrong fix.
    # "And how does that compare to Intel?" genuinely MEANS something different after each
    # turn, because "that" points at the most recent thing said. Cases 1 and 3 move the
    # referent on purpose and SHOULD produce different questions; cases 2 and 4 hold it still
    # and are the ones whose score has to be 1.
    print("  READ THIS BEFORE ACTING ON THE NUMBERS ABOVE.")
    print("  A high count is not automatically waste. Two of these cases move what the")
    print("  follow-up REFERS TO on every turn - after \"which of them spent a larger share\",")
    print("  the word \"that\" means a share, not an expense - so a different standalone")
    print("  question is the CORRECT output, and collapsing them into one cache key would")
    print("  serve a wrong answer rather than save a rupee.")
    print()
    print("  The cases that must score 1 are the ones where the referent does NOT move:")
    for name, n, t, _k in rows:
        if "must never change" in name or "pronoun carry" in name:
            print(f"    {'ok  ' if n == 1 else 'FAIL'} {name}: {n}/{t}")
    print()
    print("  Spurious variance looks different from this: the SAME meaning phrased two ways,")
    print("  e.g. operands swapped between 'A compared to B' and 'B compared to A'. That is")
    print("  what inspect_cache.py found in the real conversation, and it is the only part")
    print("  of this a prompt change should try to remove.")
    print()
    print("  STABILITY only. Whether a rewrite is CORRECT is rewrite_eval.py's job, and any")
    print("  change here has to keep that at 25/25 to be allowed to ship.")


if __name__ == "__main__":
    main()
