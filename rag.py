"""
The ugly-baseline RAG pipeline as a reusable function.

Reads the ALREADY-BUILT Chroma index (from build_index.py) - it does NOT
re-embed. Given a question: retrieve top-k chunks -> stuff into one prompt ->
ask gemini-3.5-flash -> return the answer plus the context it used.

answer_question() returns BOTH the answer and the retrieved context, because
the groundedness judge (step 1.7) needs to see what the model was actually
given in order to check whether the answer is supported.
"""

from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_chroma import Chroma
from judges import log_cost, to_text
import re

load_dotenv()

# --- load the persisted index (same settings used to build it) ---
embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
vectorstore = Chroma(
    collection_name="sec_filings",
    embedding_function=embeddings,
    persist_directory="chroma_db",
)

# temperature=0 -> as deterministic as possible, so eval scores are reproducible
# model"gemini-3.5-flash" is the most capable, but "gemini-3.1-flash-lite" is cheaper and faster and still very good for grading.
llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0).with_retry(
    stop_after_attempt=5, wait_exponential_jitter=True,
)

PROMPT = """You are a financial analyst assistant. Answer the QUESTION using ONLY the \
CONTEXT below, which is extracted from SEC 10-K filings.
Each excerpt states which company and fiscal period it comes from. If the QUESTION is about \
a single company, use ONLY excerpts from that company - never mix figures across companies. \
If the QUESTION asks you to compare or combine the companies, use excerpts from both, and \
label every figure with the company and fiscal period it came from.
If the answer is not contained in the context, reply exactly: "Not stated in the filing."
Do not use any outside knowledge.

CONTEXT:
{context}

QUESTION: {question}

ANSWER:"""

# --- 3.3 entity detection: which companies is this question about? ---
COMPANY_ALIASES = {
    "NVIDIA": ["nvidia", "nvda"],
    "AMD":    ["amd", "advanced micro devices"],
}

def detect_companies(question):
    """Cheap, deterministic, free. Returns e.g. ['NVIDIA', 'AMD'] or []."""
    low = question.lower()
    return [company
            for company, aliases in COMPANY_ALIASES.items()
            if any(re.search(rf"\b{re.escape(alias)}\b", low) for alias in aliases)]

def retrieve(question, k=4):
    """Fan out per company when the question needs two; otherwise behave exactly as before."""
    companies = detect_companies(question)          # free, deterministic
    if not companies:                               # blank card -> pay for the specialist
        companies = llm_detect_companies(question)  # 3.5 fallback
    if len(companies) < 2:
        return vectorstore.similarity_search(question, k=k), companies   # unchanged path
    docs = []
    for c in companies:
        docs.extend(vectorstore.similarity_search(question, k=k, filter={"company": c}))
    return docs, companies

def answer_question(question: str, k: int = 4) -> dict:
    docs, companies = retrieve(question, k=k)                 # retrieve (now company-aware)
    context = "\n\n".join(d.page_content for d in docs)       # assemble context
    prompt = PROMPT.format(context=context, question=question)
    resp = llm.invoke(prompt)
    log_cost("gemini-3.1-flash-lite", resp, label="generation")
    answer = to_text(resp.content)
    return {"answer": answer, "context": context, "companies": companies}

# --- 3.5 LLM fallback: fires ONLY when the free scan finds nothing ---
ROUTER_PROMPT = """You route questions to company filings. The library contains \
exactly these companies, and no others:
NVIDIA
AMD

Which of them does the QUESTION need in order to be answered? A question may need \
one of them, both of them, or neither.
Reply with ONLY company names from the list above, separated by commas.
If the question needs neither, reply exactly: NONE
Do not explain. Do not add any other word.

QUESTION: {question}

COMPANIES:"""


def llm_detect_companies(question):
    """Paid fallback for a blank card. The LLM only SUGGESTS names; detect_companies()
    then VALIDATES them, so a hallucinated company can never reach the Chroma filter."""
    resp = llm.invoke(ROUTER_PROMPT.format(question=question))
    log_cost("gemini-3.1-flash-lite", resp, label="router")
    return detect_companies(to_text(resp.content))


if __name__ == "__main__":
    print("--- entity detection (costs nothing) ---")
    checks = [
        ("What was NVIDIA's total revenue for fiscal year 2026?", ["NVIDIA"]),
        ("What was AMD's net revenue for fiscal year 2025?", ["AMD"]),
        ("Which company had higher total revenue, NVIDIA or AMD?", ["NVIDIA", "AMD"]),
        ("What is the global AI accelerator market share?", []),
    ]
    for q, expected in checks:
        got = detect_companies(q)
        print(f"[{'OK' if got == expected else 'MISMATCH'}] {got} expected={expected} | {q[:45]}")


    from collections import Counter
    from cross_set import CROSS_SET

    implicit = [e["question"] for e in CROSS_SET if e["id"] >= "x18"]

    print("\n--- 3.5 gate A: does the fallback recover what the scan missed? ---")
    for q in implicit:
        print(f"  scan={str(detect_companies(q)):<8} llm={llm_detect_companies(q)}  | {q[:48]}")

    print("\n--- 3.5 gate B: router must NOT fire on named questions ---")
    for q in ["What was NVIDIA's total revenue for fiscal year 2026?",
              "What was AMD's net revenue for fiscal year 2025?"]:
        print(f"  scan={detect_companies(q)}  -> router skipped: {bool(detect_companies(q))}")

    print("\n--- 3.5 gate C: coverage after fallback ---")
    for q in implicit:
        docs, cos = retrieve(q)
        print(f"  {dict(Counter(d.metadata['company'] for d in docs))}  companies={cos}  | {q[:40]}")
