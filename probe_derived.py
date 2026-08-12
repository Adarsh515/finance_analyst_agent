# probe_derived.py
# The judge scored the derived bucket 10/10. The judge is uncalibrated, and this is
# exactly the question type we claimed was broken. Print the full answers and check
# every number by hand before believing that score.

import agent
from cross_set import CROSS_SET

agent.VERBOSE = False

EXPECTED = {
    "d01": "AMD larger by ~14.8 pp   (AMD 8,091/34,639 = 23.4%  vs  NVIDIA 18,497/215,938 = 8.6%)",
    "d02": "yes: 16,635 + 10,640 + 3,910 + 3,454 = 34,639",
    "d03": "NVIDIA 55.6%, AMD 12.5%, gap ~43.1 pp",
    "d04": "NVIDIA 23.9%, AMD 18.1% (76,926 - 62,999 = 13,927), AMD lower by ~5.8 pp",
    "d05": "NVIDIA 89.7%, AMD 48.0%",
    "d06": "85.6%   (102,718 / 120,067)",
    "d07": "+$90,307M, about 4.0x   (120,067 - 29,760)",
    "d08": "$250,577M combined, AMD ~13.8%",
    "d09": "$6,493M (7,709 - 1,216), about 18.7% of net revenue",
    "d10": "153,463 - 18,497 = 134,966 -> 62.5% of revenue",
}

for ex in CROSS_SET:
    if not ex.get("derived"):
        continue
    out = agent.run_agent(ex["question"])
    print("\n" + "=" * 78)
    print(ex["id"], "|", ex["question"])
    print("EXPECTED:", EXPECTED[ex["id"]])
    print("-" * 78)
    print(out["answer"])