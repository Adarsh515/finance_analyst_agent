"""
probe_tesla.py - Phase 6.8. Did the sixth filing land, and did it damage the other five?

WHY THIS RUNS BEFORE THE GATE. A full gate costs about Rs 21 and 20-30 minutes. The two ways
adding Tesla could go wrong are both visible in RETRIEVAL alone, which needs no generation
model at all:

    1. Tesla is indexed but unreachable - the planner cannot filter to a company the alias
       table has never heard of. (It is derived from the index, so this should work by
       itself; "should" is not a measurement.)
    2. Tesla IS reachable and 498 new chunks now out-compete the right ones for questions
       about the other five filings. This is the expensive failure: nothing errors, the
       answers just quietly get worse, and the first evidence would be a gate that moved for
       reasons nobody can attribute.

Cost: embedding a handful of short queries. gemini-embedding-001 is $0.15 per 1M input
tokens and these queries total a few hundred, so this is a fraction of a paisa - call it
free. NO generation model is called: there is no plan step, no answer step, no judge.

Free-ish, and it answers the question the gate would answer 30 minutes and Rs 21 later.
"""

import warnings

warnings.filterwarnings("ignore")

import rag  # noqa: E402  - reads the index at import; that is the point

# (query, the company whose chunks must dominate). The first six are the NEW capability.
# The rest are the OLD capability, and they are the reason this probe exists: a regression
# here is worth more than a success above.
CASES = [
    ("What was Tesla's total revenue for fiscal year 2025?",              "Tesla"),
    ("What were Tesla's total liabilities?",                              "Tesla"),
    ("How many people does Tesla employ?",                                "Tesla"),
    ("Tesla energy generation and storage segment revenue",               "Tesla"),
    ("Tesla net income attributable to common stockholders",              "Tesla"),
    ("Tesla provision for income taxes",                                  "Tesla"),

    ("What was NVIDIA's total revenue for fiscal year 2026?",             "NVIDIA"),
    ("What was NVIDIA's Data Center revenue?",                            "NVIDIA"),
    ("What was AMD's net revenue for fiscal year 2025?",                  "AMD"),
    ("What was AMD's Data Center segment revenue?",                       "AMD"),
    ("What was Intel's net revenue for fiscal year 2025?",                "Intel"),
    ("Intel research and development expense",                            "Intel"),
    ("What was NVIDIA's revenue for the three months ended October 26, 2025?", "NVIDIA"),
]

# The trap the new corpus creates. Tesla's filing says "data centers" seven times - in risk
# factors, capex guidance, R&D cost composition and the lease note - and never as segment
# revenue. A query about Data Center revenue must NOT come back full of Tesla.
TRAPS = [
    ("Data Center segment revenue", "Tesla", 1,
     "Tesla mentions data centres only as COSTS; it must not dominate a Data Center query"),
    ("gross margin percentage", "Tesla", 3,
     "Tesla has the lowest gross margin but no special claim on the phrase"),
]


def main():
    if not rag.COMPANY_ALIASES:
        raise SystemExit("  the index reports no companies - run build_index.py first")

    print(f"\n  companies the index reports: {sorted(rag.COMPANY_ALIASES)}")
    assert "Tesla" in rag.COMPANY_ALIASES, \
        "Tesla is not in the alias table - the index does not know about it"
    print("  ok   Tesla is in the alias table, derived from the index (rag.py untouched)")

    assert rag.detect_companies("What was Tesla's revenue?") == ["Tesla"], \
        rag.detect_companies("What was Tesla's revenue?")
    # ...and it must not fire on a question that merely rhymes
    assert rag.detect_companies("What was NVIDIA's revenue?") == ["NVIDIA"]
    print("  ok   detect_companies resolves Tesla, and does not over-fire\n")

    ok = fail = 0
    print(f"  {'query':58} {'want':7} {'top-4 companies'}")
    print(f"  {'-'*58} {'-'*7} {'-'*34}")
    for q, want in CASES:
        docs = rag.vectorstore.similarity_search(q, k=4)
        got = [d.metadata.get("company", "?") for d in docs]
        good = got and got[0] == want
        ok, fail = (ok + 1, fail) if good else (ok, fail + 1)
        print(f"  {'ok  ' if good else 'FAIL'} {q[:53]:53} {want:7} {got}")

    print()
    for q, must_not_dominate, limit, why in TRAPS:
        docs = rag.vectorstore.similarity_search(q, k=6)
        got = [d.metadata.get("company", "?") for d in docs]
        n = got.count(must_not_dominate)
        good = n <= limit
        ok, fail = (ok + 1, fail) if good else (ok, fail + 1)
        print(f"  {'ok  ' if good else 'FAIL'} trap: {q[:40]:40} "
              f"{must_not_dominate} appears {n}/6 (limit {limit})")
        print(f"         {why}")

    print(f"\n{'=' * 86}")
    print(f"  {ok} passed, {fail} failed, out of {len(CASES) + len(TRAPS)}")
    if fail:
        print("  DO NOT RUN THE GATE YET. Retrieval is wrong and the gate would only tell you")
        print("  the same thing 30 minutes and ~Rs 21 later.")
    else:
        print("  Retrieval is intact for all six filings. The gate is now worth paying for.")
    print(f"{'=' * 86}")
    print("  No generation model was called. Cost: a few hundred embedding tokens.")


if __name__ == "__main__":
    main()
