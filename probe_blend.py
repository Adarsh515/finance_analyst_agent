# probe_blend.py
# One-variable check: does a blended query retrieve as well as two focused ones?
# Same filter, same k. ONLY the query text changes.

from rag import vectorstore

FILTER = {"company": "NVIDIA"}   # match the filter syntax used in rag.py retrieve()
K = 4

QUERIES = {
    "blended":          "fiscal year 2026 revenue and operating cash flow",
    "focused_revenue":  "fiscal year 2026 total revenue",
    "focused_cashflow": "fiscal year 2026 net cash provided by operating activities",
}

results = {}
for name, q in QUERIES.items():
    docs = vectorstore.similarity_search(q, k=K, filter=FILTER)
    results[name] = [d.id for d in docs]
    print(f"\n--- {name}: {q}")
    for d in docs:
        print("  ", d.id, "| table", d.metadata.get("source_table"),
              "|", d.page_content[:70].replace("\n", " "))

blended = set(results["blended"])
focused = set(results["focused_revenue"]) | set(results["focused_cashflow"])
print("\nblended ids      :", sorted(blended))
print("focused union    :", sorted(focused))
print("MISSED BY BLEND  :", sorted(focused - blended))