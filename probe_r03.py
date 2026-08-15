# probe_r03.py
# r03 is the last failure standing, and the only one costing groundedness. Before deciding
# whether it is MY regression or a judge that is being unfair, measure it the same way w02
# was measured: same question, several configurations, judged each time.
#
# The answer under suspicion:
#   "Intel is the company ... the net income (loss) attributable to non-controlling
#    interests for the fiscal year ended December 27, 2025, was $293 million."
#
# Correct company. Correct 293. But the question asks "by how much do the TWO FIGURES
# differ", and the draft never states the two figures (26 and (267)). The correctness
# judge calls that incomplete, which is defensible. The GROUNDEDNESS 0 is the part that
# does not obviously follow - 293 is a real line on Intel's income statement.
#
# Two things this probe separates, and neither can be settled by opinion:
#   1. Are 26 and (267) even IN the context? If not, the draft could not have stated them
#      and this is a retrieval gap wearing a generation costume.
#   2. Does the OLD pre-4.4 configuration answer it differently? w02 turned out to be my
#      regression exactly this way. If OLD scores 1/1 here too, Phase 4.4 owes another fix.
#      If OLD fails identically, this was never a 4.4 problem and belongs to Phase 4.5's
#      judge calibration - to be written down, not tuned away.

from dotenv import load_dotenv

import agent
from judges import correctness_judge, groundedness_judge
from cross_set import CROSS_SET

load_dotenv()
agent.VERBOSE = False

EX = next(e for e in CROSS_SET if e["id"] == "r03")

# "(267)" is the parenthesised loss as a table renders it; "267" is the bare digits, in case
# the chunk strips the brackets. Reporting both stops a formatting quirk from masquerading
# as a missing figure - the mistake made once already with AMD's "(103)".
NEEDLES = {
    "Intel net income incl NCI 26": "26",          # weak on its own, printed for completeness
    "Intel loss attributable (267)": "(267)",
    "Intel loss attributable 267": "267",
    "NCI line 293": "293",
}

# (label, K_PER_JOB, MIN_CHUNKS, PER_JOB_FLOOR)
CONFIGS = [
    ("OLD  pre-4.4: k=4, keep all", 4, 0, 999),
    ("LIVE k=10, floor 6, 3/job", 10, 6, 3),
    ("WIDE k=10, floor 6, 5/job", 10, 6, 5),
]

print(f"Q: {EX['question']}")
print(f"reference: {EX['reference_answer']}\n")

for label, k, floor, per_job in CONFIGS:
    agent.K_PER_JOB, agent.MIN_CHUNKS, agent.PER_JOB_FLOOR = k, floor, per_job

    out = agent.run_agent(EX["question"])
    c = correctness_judge(question=EX["question"], prediction=out["answer"],
                          reference=EX["reference_answer"])
    g = groundedness_judge(question=EX["question"], prediction=out["answer"],
                           context=out["context"])

    print("=" * 78)
    print(f"{label}")
    print(f"  correct={c['score']}  grounded={g['score']}  rounds={out['rounds']}  "
          f"chunks={len(out['chunks'])}  ctx={len(out['context'])} chars")
    for name, n in NEEDLES.items():
        print(f"    {name:32} in context = {n in out['context']}")
    print("  " + out["answer"][:600].replace("\n", "\n  "))
    if c["score"] != 1:
        print(f"  CORRECTNESS JUDGE: {str(c.get('reasoning', ''))[:250]}")
    if g["score"] != 1:
        print(f"  GROUNDEDNESS JUDGE: {str(g.get('reasoning', ''))[:250]}")
    print()
