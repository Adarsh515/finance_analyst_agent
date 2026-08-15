# probe_w02b.py
# w02 is grounded=0 five times out of five, bit-identical each time. That kills the
# variance explanation: it is a reproducible defect, not an unlucky sample.
#
# The defect is not retrieval. Every figure the answer needs is in the context - the
# needle probe confirms all six. The model prints a list headed "Total Assets Ranking"
# in which NVIDIA (206,803) sits above Intel (211,429), and then a footnote that says
# Intel is largest. Correct numbers, correct conclusion, unsorted list. The groundedness
# judge is the only scorer that reads that as a claim, and it is right to.
#
# The one thing not yet established: is this MINE? Groundedness was 100% on all 54
# questions at the Reflect gate, before any of Phase 4.4 existed. Either the old
# configuration produced a differently-shaped answer that happened to avoid the trap, or
# this question was always one token away from failing and the corpus grew into it.
#
# So run the SAME question under four configurations and judge each. The only variable is
# how many chunks reach the model. If OLD comes back grounded=1, Phase 4.4 caused this and
# owes a fix. If OLD is also 0, the gate's 100% was luck and the honest move is to record
# that, not to tune caps until the number comes back.

from dotenv import load_dotenv

import agent
from judges import correctness_judge, groundedness_judge
from cross_set import CROSS_SET

load_dotenv()
agent.VERBOSE = False

EX = next(e for e in CROSS_SET if e["id"] == "w02")

# (label, K_PER_JOB, MIN_CHUNKS, PER_JOB_FLOOR, ceiling)
# The ceiling knob was removed from agent.py after this probe showed it was the cause.
# It is kept here as a local monkey-patch so the failing configurations stay reproducible.
# "OLD" reproduces the pre-4.4 path: shallow fetch, no selection at all. PER_JOB_FLOOR and
# MAX_CHUNKS are set high enough that the cap can never bind, which is what "keep all" was.
CONFIGS = [
    ("OLD  pre-4.4: k=4, keep all", 4, 0, 999, 9999),
    ("LIVE k=10, floor 6, 3/job, no ceiling", 10, 6, 3, 9999),
    ("TIGHT k=10, floor 6, 2/job, max 10", 10, 6, 2, 10),
    ("WIDE k=10, floor 6, 3/job, max 20", 10, 6, 3, 20),
]

print(f"Q: {EX['question']}")
print(f"reference: {EX['reference_answer']}\n")

for label, k, floor, per_job, ceiling in CONFIGS:
    agent.K_PER_JOB, agent.MIN_CHUNKS = k, floor
    agent.PER_JOB_FLOOR = per_job
    agent.MAX_CHUNKS = ceiling        # no-op against current agent.py; see note above

    out = agent.run_agent(EX["question"])
    c = correctness_judge(question=EX["question"], prediction=out["answer"],
                          reference=EX["reference_answer"])
    g = groundedness_judge(question=EX["question"], prediction=out["answer"],
                           context=out["context"])

    print("=" * 78)
    print(f"{label}")
    print(f"  correct={c['score']}  grounded={g['score']}  rounds={out['rounds']}  "
          f"chunks={len(out['chunks'])}  ctx={len(out['context'])} chars")
    print("  " + out["answer"][:600].replace("\n", "\n  "))
    if g["score"] != 1:
        print(f"  JUDGE: {str(g.get('reasoning', ''))[:280]}")
    print()
