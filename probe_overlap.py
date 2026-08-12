# probe_overlap.py
# 1. Do the agent's two NVIDIA jobs overlap at all?
# 2. Does dropping the fiscal year from the query change what comes back?

from rag import vectorstore

FILTER = {"company": "NVIDIA"}
K = 4

QUERIES = {
    "agent_revenue":  "total revenue",
    "agent_cashflow": "net cash provided by operating activities",
    "dated_revenue":  "fiscal year 2026 total revenue",
    "dated_cashflow": "fiscal year 2026 net cash provided by operating activities",
}

ids = {}
for name, q in QUERIES.items():
    docs = vectorstore.similarity_search(q, k=K, filter=FILTER)
    ids[name] = [d.id for d in docs]
    print(f"{name:16} {q!r}\n    {ids[name]}")

print("\n--- do the agent's two jobs overlap?")
print("overlap:", sorted(set(ids["agent_revenue"]) & set(ids["agent_cashflow"])))

print("\n--- does the fiscal year in the query matter?")
for c in ("revenue", "cashflow"):
    a, d = set(ids[f"agent_{c}"]), set(ids[f"dated_{c}"])
    print(f"{c:9} identical={a == d}  only_undated={sorted(a - d)}  only_dated={sorted(d - a)}")