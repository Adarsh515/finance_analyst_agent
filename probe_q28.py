# probe_q28b.py
# Two questions, in the right order:
#  1. Does ANY chunk contain the figures at all? (index problem vs query problem)
#  2. If yes, which query wording actually retrieves that chunk?

from rag import vectorstore

TARGETS = ["21383", "141450"]

# --- 1. scan the whole collection -------------------------------------------
res = vectorstore.get()                       # all chunks, no search involved
docs, ids, metas = res["documents"], res["ids"], res["metadatas"]
print(f"collection size: {len(ids)}")

home = {}
for t in TARGETS:
    owners = [(i, m.get("source_table")) for i, d, m in zip(ids, docs, metas) if t in d]
    home[t] = [o[0] for o in owners]
    print(f"  {t}: found in {len(owners)} chunk(s) -> {owners[:5]}")

# --- 2. which wording retrieves them? ---------------------------------------
CANDIDATES = [
    "Consolidated Statements of Operations provision for income taxes effective tax rate",
    "Consolidated Statements of Operations income tax expense income before income tax net income",
    "income tax expense and income before income taxes",
    "effective tax rate",
]

print(f"\n{'query':78} 21383  141450")
for q in CANDIDATES:
    got = vectorstore.similarity_search(q, k=4, filter={"company": "NVIDIA"})
    text = " ".join(d.page_content for d in got)
    print(f"{q:78} {str('21383' in text):6} {'141450' in text}")