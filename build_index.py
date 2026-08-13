"""
Build the Chroma index for every filing listed in corpus.py.

Pipeline: .htm -> tables lifted out whole (each with a generated title line) +
narrative split around them -> gemini-embedding-001 -> Chroma, persisted to
./chroma_db.

Chunk ids are namespaced by FILING (corpus.py's slug), not by company. Two
filings from the same company generate the same positional ids otherwise, and
Chroma resolves that collision silently - one filing overwrites the other with
no error. Measured on 2026-08-12: the old company-only scheme produced 424
colliding ids across three filings, exactly the size of the NVIDIA FY2026 set.

This script APPENDS. A change to the id scheme therefore leaves the old ids
behind as orphan duplicates - the same text under two ids, which de-duplication
by id cannot see. So it refuses to run against a non-empty collection unless
--force is passed. For a clean rebuild: delete chroma_db/ and run again.
"""

import sys
import time
import warnings
from collections import Counter

from dotenv import load_dotenv
from bs4 import XMLParsedAsHTMLWarning
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_chroma import Chroma

from corpus import DOCS
from parse_filing import parse_filing

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
load_dotenv()

BATCH = 80          # embedding requests are throttled below the rate limit

embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
store = Chroma(
    collection_name="sec_filings",
    embedding_function=embeddings,
    persist_directory="chroma_db",
)

existing = store._collection.count()
if existing and "--force" not in sys.argv:
    print(f"REFUSING TO RUN: the collection already holds {existing} items.")
    print("Appending on top of an existing index duplicates the corpus whenever the id")
    print("scheme has changed, and such duplicates are invisible to de-duplication by id.")
    print("Delete the chroma_db/ folder and run again for a clean rebuild,")
    print("or pass --force if appending is genuinely what you want.")
    sys.exit(1)

# --- parse everything BEFORE embedding anything ------------------------------
# A parse failure on the third filing must not leave a half-embedded index behind.
# Parsing is free; embedding is not and is not easily undone.
batches, all_ids = [], []
for doc in DOCS:
    pieces = parse_filing(doc["path"], doc["company"], doc["period"])
    ids = [f"{doc['slug']}-piece-{i}" for i in range(len(pieces))]
    batches.append((doc, pieces, ids))
    all_ids += ids
    n_tab = sum(1 for p in pieces if p["type"] == "table")
    print(f"parsed {doc['slug']:16} {len(pieces):4} pieces "
          f"({n_tab} tables, {len(pieces) - n_tab} narrative)")

dupes = [i for i, c in Counter(all_ids).items() if c > 1]
if dupes:
    print(f"\nABORT: {len(dupes)} duplicate chunk ids, e.g. {dupes[:5]}")
    print("Fix the slugs in corpus.py before embedding anything.")
    sys.exit(1)
print(f"\n{len(all_ids)} chunk ids, all unique. Embedding now.\n")

# --- embed -------------------------------------------------------------------
for doc, pieces, ids in batches:
    texts = [p["text"] for p in pieces]
    metadatas = [{"company": p["company"], "period": p["period"],
                  "type": p["type"], "source_table": p.get("source_table", -1)}
                 for p in pieces]
    print(f"{doc['slug']}:")
    for i in range(0, len(texts), BATCH):
        store.add_texts(texts[i:i + BATCH],
                        metadatas=metadatas[i:i + BATCH],
                        ids=ids[i:i + BATCH])
        print(f"  embedded {min(i + BATCH, len(texts))}/{len(texts)}")
        if i + BATCH < len(texts):
            time.sleep(1)

# --- verify what actually landed, do not assume it matches what was sent ------
got = store.get(include=["metadatas"])
print(f"\nindex holds {len(got['ids'])} items (expected {len(all_ids)})")
print(f"unique ids in index: {len(set(got['ids']))}")
for (company, period), n in sorted(Counter(
        (m["company"], m["period"]) for m in got["metadatas"]).items()):
    print(f"  {company:7} {period:44} {n:4}")

# --- the moment of truth: can retrieval tell two periods of ONE company apart? -
for q in ["What was NVIDIA's total revenue for fiscal year 2026?",
          "What was NVIDIA's total revenue for fiscal year 2025?",
          "What was AMD's net revenue for fiscal year 2025?"]:
    print(f"\nQ: {q}")
    for d in store.similarity_search(q, k=3):
        print(f"   [{d.metadata['company']:<6} {d.metadata['period'][:26]:28}] "
              f"{d.page_content[:66]}")
