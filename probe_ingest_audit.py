# probe_ingest_audit.py
# Pre-ingest audit. Parses only - no embeddings, no API calls, no writes to the index.
#   1. How many pieces does each filing produce?
#   2. Do the generated chunk ids collide under the CURRENT scheme?
#   3. What is in the index right now?

from collections import Counter
from parse_filing import parse_filing
from rag import vectorstore

DOCS = [
    {"path": "data/nvidia_10k.htm",        "company": "NVIDIA",
     "period": "fiscal year 2026 (ended January 25, 2026)"},
    {"path": "data/nvidia_10k_fy2025.htm", "company": "NVIDIA",
     "period": "fiscal year 2025 (ended January 26, 2025)"},
    {"path": "data/amd_10k.htm",           "company": "AMD",
     "period": "fiscal year 2025 (ended December 27, 2025)"},
]

old_ids, new_ids = [], []
for d in DOCS:
    pieces = parse_filing(d["path"], d["company"], d["period"])
    n_tab = sum(1 for p in pieces if p["type"] == "table")
    print(f"\n{d['company']:6} {d['period'][:34]:36} {len(pieces):4} pieces "
          f"({n_tab} tables, {len(pieces) - n_tab} narrative)")
    print("       first title:", pieces[0]["text"].splitlines()[0][:95])

    old_ids += [f"{d['company'].lower()}-piece-{i}" for i in range(len(pieces))]
    year = d["period"].split()[2]                      # "2026" / "2025"
    new_ids += [f"{d['company'].lower()}-fy{year}-piece-{i}" for i in range(len(pieces))]

print(f"\nOLD scheme: {len(old_ids)} ids, {len(set(old_ids))} unique "
      f"-> {len(old_ids) - len(set(old_ids))} COLLISIONS")
print(f"NEW scheme: {len(new_ids)} ids, {len(set(new_ids))} unique "
      f"-> {len(new_ids) - len(set(new_ids))} collisions")
print("example colliding ids:", [i for i, c in Counter(old_ids).items() if c > 1][:5])

cur = vectorstore.get(include=["metadatas"])
print(f"\ncurrent index: {len(cur['ids'])} items")
print("  by company+period:",
      dict(Counter((m["company"], m["period"][:24]) for m in cur["metadatas"])))
print("  sample ids:", cur["ids"][:3])