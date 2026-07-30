"""Diagnostic: when a question needs BOTH companies, does retrieval actually
give both a share of the k slots? Re-run this in Phase 3 to prove improvement."""

from collections import Counter
from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_chroma import Chroma

load_dotenv()

store = Chroma(
    collection_name="sec_filings",
    embedding_function=GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001"),
    persist_directory="chroma_db",
)

QUERIES = [
    "Which company had higher total revenue, NVIDIA or AMD?",
    "Compare research and development spending at NVIDIA and AMD.",
    "Whose gross margin was higher, NVIDIA or AMD?",
    "How much more revenue did NVIDIA generate than AMD?",
    "What was total revenue?",              # names no company - ambiguous on purpose
]

for q in QUERIES:
    docs = store.similarity_search(q, k=4)
    mix = Counter(d.metadata["company"] for d in docs)
    print(f"\nQ: {q}")
    print(f"   company mix: {dict(mix)}")
    for d in docs:
        first_line = d.page_content.split("\n")[0]
        print(f"   [{d.metadata['company']:<6} {d.metadata['type']:<9}] {first_line[:78]}")

print("\n--- same question, but forced to visit BOTH aisles ---")
q = "How much more revenue did NVIDIA generate than AMD?"
for co in ["NVIDIA", "AMD"]:
    for d in store.similarity_search(q, k=2, filter={"company": co}):
        print(f"   [{co:<6}] {d.page_content.split(chr(10))[0][:78]}")