# probe_w02.py
# w02 came back PASS on correctness but grounded=0 - the first groundedness failure this
# project has recorded since the metric was added. That is worth more than a shrug.
#
# The answer printed a list headed "Total Assets Ranking" whose entries were not in rank
# order (NVIDIA 206,803 at #1, Intel 211,429 at #2) and then contradicted itself in a
# footnote. Every figure in it was correct and present in the context; the ORDER was the
# unsupported claim, and the groundedness judge is the only scorer that looks at that.
#
# Two things to separate, and n=1 cannot separate them:
#   VARIANCE  - one unlucky sample, and the same code answers cleanly on a re-run.
#   REGRESSION - the current context reliably produces this, and it must be fixed.
#
# So: five samples of w02, judged each time. Five generations plus ten judge calls is
# small change against a full run, and it is the difference between "fix it" and
# "write it down and move on".

from collections import Counter

from dotenv import load_dotenv

import agent
from judges import correctness_judge, groundedness_judge
from cross_set import CROSS_SET

load_dotenv()
agent.VERBOSE = False

N = 5
EX = next(e for e in CROSS_SET if e["id"] == "w02")

print(f"Q: {EX['question']}")
print(f"reference: {EX['reference_answer']}\n")

scores = []
for i in range(1, N + 1):
    out = agent.run_agent(EX["question"])
    c = correctness_judge(question=EX["question"], prediction=out["answer"],
                          reference=EX["reference_answer"])
    g = groundedness_judge(question=EX["question"], prediction=out["answer"],
                           context=out["context"])
    scores.append((c["score"], g["score"]))
    print(f"--- sample {i}: correct={c['score']}  grounded={g['score']}  "
          f"rounds={out['rounds']}  chunks={len(out['chunks'])}  ctx={len(out['context'])}")
    print("    " + out["answer"][:500].replace("\n", "\n    "))
    if g["score"] != 1:
        print(f"    GROUNDEDNESS JUDGE SAID: {str(g.get('reasoning', ''))[:300]}")

print(f"\n{'=' * 70}")
print(f"  correctness  : {sum(c for c, _ in scores)}/{N}")
print(f"  groundedness : {sum(g for _, g in scores)}/{N}")
print(f"  distinct outcomes: {Counter(scores)}")
# 5/5 grounded means the single 0 was a sample, not the system. Anything less means the
# context is reliably inviting an unsupported ordering claim, and that is a defect to fix
# before the gate - not after it.
