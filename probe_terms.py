# probe_terms.py
# Hypothesis M4: one canonical query phrase does not match every issuer's wording.
# NVIDIA's line is "Revenue"; AMD's is "Net revenue".
# Question: is there a SINGLE phrasing that retrieves the revenue figure for BOTH?

from rag import vectorstore

K = 4
TARGETS = {"NVIDIA": "215938", "AMD": "34639"}      # no thousands separators in the index

CANDIDATES = [
    "total revenue",
    "net revenue",
    "revenue",
    "total net revenue for the fiscal year",
    "Consolidated Statements of Operations net revenue cost of sales gross profit",
    "annual revenue and cost of sales",
]

print(f"{'query':72} NVIDIA  AMD")
for q in CANDIDATES:
    hits = []
    for company, needle in TARGETS.items():
        docs = vectorstore.similarity_search(q, k=K, filter={"company": company})
        hits.append(any(needle in d.page_content for d in docs))
    print(f"{q:72} {str(hits[0]):6}  {hits[1]}")