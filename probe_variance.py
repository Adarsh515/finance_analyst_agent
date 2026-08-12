# probe_variance.py
# Two questions we have never asked: does x15's arithmetic slip come back, and how much
# does this system vary run to run? Every score in the tracker so far is n = 1.

import agent
from cross_set import CROSS_SET

agent.VERBOSE = False
N = 5
IDS = ["x15", "d04"]          # x15 broke once at 13,937; d04 needs the same derivation

for qid in IDS:
    ex = next(e for e in CROSS_SET if e["id"] == qid)
    print("\n" + "=" * 78)
    print(qid, "|", ex["question"])
    print("expected to contain: 13,927 / 13927")
    for i in range(N):
        out = agent.run_agent(ex["question"])
        hit = ("13,927" in out["answer"]) or ("13927" in out["answer"])
        print(f"  run {i+1}: correct={hit}  chunks_ctx={len(out['context'])}  | {out['answer'][:90]!r}")