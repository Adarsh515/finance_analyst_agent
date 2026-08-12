# probe_dedup.py
# Force the de-dup guard to fire. An untested guard is an unknown guard.

from agent import retrieve_node

job = {"company": "NVIDIA", "query": "total revenue"}
state = {
    "question": "forced duplicate test",
    "jobs": [job, job],           # the SAME job twice, on purpose
    "chunks": [], "seen_ids": [], "answer": "", "rounds": 0, "companies": [],
}
out = retrieve_node(state)
print("chunks:", len(out["chunks"]), "| expected 4, NOT 8")
print("jobs after:", out["jobs"], "| expected [] - queue must be drained")