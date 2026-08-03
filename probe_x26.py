# probe_failures.py - throwaway diagnostic for the Phase 4.0 failures.
import sys
from cross_set import CROSS_SET
from rag import retrieve

BY_ID = {e["id"]: e for e in CROSS_SET}
ids = sys.argv[1:] or ["x26", "x28", "x29", "x30"]

for qid in ids:
    q = BY_ID[qid]["question"]
    docs, companies = retrieve(q)
    print("=" * 78)
    print(f"{qid}   detected={companies}   chunks={len(docs)}")
    print(f"   Q: {q}")
    for i, d in enumerate(docs, 1):
        m = d.metadata
        head = d.page_content[:85].replace("\n", " ")
        print(f"  {i}. {str(m.get('company')):<7} | {str(m.get('type')):<9} "
              f"| tbl={str(m.get('source_table')):<4} | {head}")