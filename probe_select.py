# probe_select.py
# Verify the per-job round-robin selection on the questions the global re-ranker broke,
# BEFORE paying for a full gate run.
#
# This runs the real agent end to end - plan, retrieve, answer, reflect - but no judges.
# Judging is the expensive half of run_eval.py, and it is not needed to answer the only
# question that matters right now: does the needed figure reach the context, and does the
# answer stop saying "not stated".
#
# Nine of the twenty Phase 4.4 failures, plus two canaries that were passing and must
# still pass. A fix verified only on what it was built to fix is not verified.
#
# needles are the stored form of the figures: the index holds them WITHOUT thousands
# separators, so "76926", never "76,926".
#
# A needle set must cover every entity the ANSWER will talk about, not just the ones the
# reference answer names. x28 asks about AMD vs "the other chipmaker", so its needles were
# AMD and NVIDIA - and the run came back ALL PRESENT while the answer quietly claimed
# Intel's total assets were $2,762M. The corpus has three companies, so the system
# volunteers all three whether the question asked for them or not. Under-specified needles
# report a pass on an answer with a fabricated figure in it, which is worse than no test.

import agent

agent.VERBOSE = True

CASES = [
    # --- broken by the global re-ranker -------------------------------------
    ("x26", "How much bigger was NVIDIA's gross profit than the other chipmaker's in these filings?",
     {"NVDA gross profit 153,463": "153463", "AMD gross profit 17,152": "17152",
      "Intel gross profit 18,375": "18375"}),

    ("x28", "How much smaller were AMD's total assets than the other chipmaker's in these filings?",
     {"AMD total assets 76,926": "76926", "NVDA total assets 206,803": "206803",
      "Intel total assets 211,429": "211429"}),

    ("x13", "Both NVIDIA and AMD report a Gaming segment. What was Gaming revenue for each?",
     {"NVDA Gaming 16,042": "16042", "AMD Gaming 3,910": "3910"}),

    ("x24", "How many times more cash did the highest-revenue company generate from operations "
            "than the lowest-revenue one?",
     {"NVDA op CF 102,718": "102718", "AMD op CF 7,709": "7709",
      "Intel op CF 9,697": "9697", "NVDA revenue 215,938": "215938",
      "AMD revenue 34,639": "34639", "Intel revenue 52,853": "52853"}),

    ("x20", "For the company with the highest revenue in these filings, what was its gross margin, "
            "and how does that compare with the lowest-revenue company's?",
     {"NVDA revenue 215,938": "215938", "AMD revenue 34,639": "34639",
      "Intel revenue 52,853": "52853", "AMD gross profit 17,152": "17152"}),

    # The tax needle is "(103)" WITH the parentheses. A bare "103" is three digits and
    # matches almost any table on the page - a needle that cannot fail is not a test.
    ("x30", "For whichever company in these filings reported an income tax benefit rather than "
            "an expense, what were its total liabilities at fiscal year end?",
     # "(103)" failed while the answer correctly said "income tax benefit of $103 million",
     # so the figure was there in a form this needle could not see. Chasing the exact
     # rendering of one parenthesised number is not worth another round; the two balance
     # sheet figures are what the second hop actually has to fetch.
     {"AMD total assets 76,926": "76926", "AMD equity 62,999": "62999"}),

    ("w02", "Which company reported the largest total assets, and how does that ranking compare "
            "with the revenue ranking?",
     {"Intel total assets 211,429": "211429", "NVDA total assets 206,803": "206803",
      "AMD total assets 76,926": "76926",
      "NVDA revenue 215,938": "215938", "Intel revenue 52,853": "52853",
      "AMD revenue 34,639": "34639"}),

    ("d08", "What is the combined revenue of all the companies in these filings for their latest "
            "fiscal years, and what share of that combined figure is AMD's?",
     {"NVDA revenue 215,938": "215938", "Intel revenue 52,853": "52853",
      "AMD revenue 34,639": "34639"}),

    ("qq2", "What was NVIDIA's revenue for the nine months ended October 26, 2025, and how much of "
            "full-year fiscal 2026 revenue did the remaining quarter contribute?",
     {"9-month revenue 147,811": "147811", "FY2026 revenue 215,938": "215938"}),

    ("x29", "Among the companies in these filings, which one leads on gross margin, which leads "
            "on R&D as a share of revenue, and which leads on cash generated from operations?",
     {"NVDA revenue 215,938": "215938", "Intel R&D 13,774": "13774",
      "AMD R&D 8,091": "8091", "NVDA op CF 102,718": "102718",
      "Intel op CF 9,697": "9697", "AMD op CF 7,709": "7709"}),

    ("r01", "Which company generated LESS cash from operations than the net income it reported, "
            "and what were the two figures?",
     {"NVDA op CF 102,718": "102718", "NVDA net income 120,067": "120067",
      "AMD op CF 7,709": "7709", "AMD net income 4,335": "4335",
      "Intel op CF 9,697": "9697"}),

    # --- canaries: these were PASSING, and a fix that breaks them is not a fix ---
    ("x01", "What was AMD's net revenue for fiscal year 2025?",
     {"AMD revenue 34,639": "34639"}),

    ("g01", "What was NVIDIA's total revenue in fiscal year 2026?",
     {"NVDA revenue 215,938": "215938"}),
]

# Everything below runs only as a script. Without this guard, "from probe_select import
# CASES" would execute all thirteen paid questions as an import side effect - which is
# exactly what nearly happened when probe_depth.py wanted to reuse this list. A module
# that costs money to import is a trap.
def main():
  # One question must never be able to destroy the other twelve. A transient API error in
  # the embedding call once killed this probe at question 7 and threw away six paid answers;
  # agent.py now retries that call, and this catch is the second line of defence.
  rows, broken = [], []
  for qid, question, needles in CASES:
      print("\n" + "=" * 78)
      print(f"{qid}: {question}")
      try:
          out = agent.run_agent(question)
      except Exception as e:
          broken.append(qid)
          print(f"  ERROR, skipped: {type(e).__name__}: {str(e)[:120]}")
          continue
      ctx = out["context"]
      misses = [label for label, n in needles.items() if n not in ctx]
      for label, n in needles.items():
          print(f"    {label:30} present={n in ctx}")
      print(f"  rounds={out['rounds']}  chunks={len(out['chunks'])}  ctx={len(ctx)} chars")
      print(f"  ANSWER: {out['answer'][:400]}")
      rows.append((qid, len(ctx), len(out["chunks"]), out["rounds"], misses, out["answer"]))

  print("\n" + "=" * 78)
  print("SUMMARY")
  print("=" * 78)
  print(f"  {'id':5} {'chunks':>6} {'rounds':>6} {'chars':>7}  needles")
  for qid, chars, nch, rnds, misses, ans in rows:
      flag = "ALL PRESENT" if not misses else "MISSING: " + ", ".join(misses)
      print(f"  {qid:5} {nch:>6} {rnds:>6} {chars:>7}  {flag}")

  # "Not stated" in an answer whose context HAS the figure is a generation problem.
  # "Not stated" in an answer whose context LACKS it is a retrieval problem. Separating
  # those two is the whole reason this probe prints both columns.
  refusals = [r for r in rows if any(m in r[5].lower() for m in agent.INCOMPLETE_MARKERS)]
  print(f"\n  answers still admitting a gap: {[r[0] for r in refusals] or 'none'}")
  if broken:
      print(f"  NOT SCORED (errors, re-run these): {broken}")
  chars = sorted(r[1] for r in rows)
  print(f"  context chars: median {chars[len(chars)//2]:,}  max {chars[-1]:,}")


if __name__ == "__main__":
    main()
