"""
Build the ugly-baseline vector index for the NVIDIA FY2026 10-K.

Pipeline: load .htm -> plain text -> naive 1000-char chunks ->
gemini-embedding-001 embeddings -> Chroma (persisted to ./chroma_db).

Embedding is throttled to respect the free-tier limit of 100 requests/minute,
and auto-retries a batch if it still gets rate-limited. Runs once; the index
persists to disk, so you only re-run it if you delete ./chroma_db.
"""

import time
import warnings
from dotenv import load_dotenv
from bs4 import XMLParsedAsHTMLWarning
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_chroma import Chroma
from parse_filing import parse_filing

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
load_dotenv()

# One place that lists every filing in the corpus. Adding a 3rd company = one more dict.
DOCS = [
    {"path": "data/nvidia_10k.htm", "company": "NVIDIA",
     "period": "fiscal year 2026 (ended January 25, 2026)"},
    {"path": "data/amd_10k.htm", "company": "AMD",
     "period": "fiscal year 2025 (ended December 27, 2025)"},
]

embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
store = Chroma(
    collection_name="sec_filings",          # renamed: it is no longer NVIDIA-only
    embedding_function=embeddings,
    persist_directory="chroma_db",
)

BATCH = 80

for doc in DOCS:
    pieces = parse_filing(doc["path"], doc["company"], doc["period"])
    slug = doc["company"].lower()
    print(f"\n{doc['company']}: parsed {len(pieces)} pieces")

    texts = [p["text"] for p in pieces]
    metadatas = [{"company": p["company"], "period": p["period"],
                  "type": p["type"], "source_table": p.get("source_table", -1)}
                 for p in pieces]
    ids = [f"{slug}-piece-{i}" for i in range(len(pieces))]   # namespaced => no collisions

    for i in range(0, len(texts), BATCH):
        store.add_texts(texts[i:i + BATCH], metadatas=metadatas[i:i + BATCH], ids=ids[i:i + BATCH])
        print(f"  embedded {min(i + BATCH, len(texts))}/{len(texts)}")
        if i + BATCH < len(texts):
            time.sleep(1)

print("\nTotal items in index:", store._collection.count())

# --- the moment of truth: does retrieval keep the two companies apart? ---
for q in ["What was NVIDIA's total revenue for fiscal year 2026?",
          "What was AMD's net revenue for fiscal year 2025?"]:
    print(f"\nQ: {q}")
    for d in store.similarity_search(q, k=3):
        print(f"   [{d.metadata['company']:<6} {d.metadata['type']:<9}] {d.page_content[:85]}")
