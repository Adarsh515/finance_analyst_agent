# probe_depth.py
# PER_JOB_FLOOR is now the only knob left that decides Phase 4.4's accuracy/cost trade,
# and r03 proved 3 slots is not always enough: Intel's "(267)" line sits deep in its own
# job's results, reaches the context only at 5 slots per job, and with it present the
# answer is complete and both judges agree.
#
# Raising the knob for one question would be tuning on n=1. So measure the WHOLE trade
# curve instead, over every question with a known needle set, at every candidate depth -
# retrieval only. One plan per question, no generation, no judges. Roughly two cents for
# the whole sweep, against a paid run per setting.
#
# Read two columns together:
#   needles found   - does the evidence reach the context (accuracy ceiling)
#   context chars   - what that costs on the questions that are already fine
# The right depth is the smallest one where the needle column stops improving.

import agent
from agent import plan_node, _chroma_filter, _search, _select, MIN_CHUNKS
from probe_select import CASES as SELECT_CASES

agent.VERBOSE = False

# r03 is the reason this probe exists, and it is not in probe_select's list.
CASES = list(SELECT_CASES) + [
    ("r03", "For which company does reported net income depend on whether non-controlling "
            "interests are included, and by how much do the two figures differ?",
     {"Intel net income 26": "26",
      "Intel loss attributable (267)": "(267)",
      "Intel NCI 293": "293"}),
]

DEPTHS = [2, 3, 4, 5, 6]

# Plan once per question and reuse it for every depth. The plan does not depend on the
# selection knob, so re-planning per depth would pay five times for the same jobs AND
# introduce planner variance into a comparison that is supposed to isolate one variable.
plans = {}
for qid, question, needles in CASES:
    st = {"question": question, "jobs": [], "chunks": [], "seen_ids": [],
          "answer": "", "context": "", "rounds": 0, "companies": []}
    jobs = plan_node(st)["jobs"]
    plans[qid] = (jobs, [_search(j["query"], agent.K_PER_JOB, _chroma_filter(j)) for j in jobs])

print(f"\n{'=' * 92}")
print(f"  {'id':6} {'jobs':>4}  " + "  ".join(f"{'d=' + str(d):>16}" for d in DEPTHS))
print(f"{'=' * 92}")

totals = {d: 0 for d in DEPTHS}
misses = {d: [] for d in DEPTHS}
for qid, question, needles in CASES:
    jobs, per_job = plans[qid]
    cells = []
    for d in DEPTHS:
        sel = _select(per_job, set(), MIN_CHUNKS, d)
        text = "\n\n".join(c.page_content for c in sel)
        found = sum(1 for n in needles.values() if n in text)
        totals[d] += len(text)
        if found < len(needles):
            misses[d].append(qid)
        flag = " " if found == len(needles) else "*"
        cells.append(f"{found}/{len(needles)} {len(text):>6,}{flag}")
    print(f"  {qid:6} {len(jobs):>4}  " + "  ".join(f"{c:>16}" for c in cells))

print(f"{'=' * 92}")
print(f"  {'TOTAL':6} {'':>4}  " + "  ".join(f"{totals[d]:>15,} " for d in DEPTHS))
print(f"\n  needles missing at each depth ('*' above):")
for d in DEPTHS:
    print(f"    d={d}: {misses[d] or 'none'}")
print("\n  Round 1 only, no Reflect - the same simplification for every column, so the\n"
      "  comparison is fair even though the absolute numbers are floors.")
