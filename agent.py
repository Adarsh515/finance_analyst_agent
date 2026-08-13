# agent.py
# LangGraph agent for multi-hop retrieval over SEC filings.
# Runs BESIDE rag.py, never inside it. rag.py stays byte-identical.
#
# Graph:  plan -> retrieve -> answer -> reflect -> (retrieve | END)
#
# Design contracts:
#   1. The old path in rag.py is never modified. run_eval.py selects between them.
#   2. The Answer prompt is reused unchanged - groundedness is already 100%, so
#      generation is not the variable under test.
#   3. The retry cap lives in code (should_retry), never in a prompt.
#   4. The planner may only ADD to what the old path already retrieves; a baseline
#      job on the raw question is always appended so the agent can never retrieve
#      less than the baseline does.
#   5. Nothing about the corpus is hardcoded here. The list of filings is read from
#      the index, because the index is what actually gets searched. corpus.py says
#      what we INTENDED to ingest; only the index knows what really landed.

from typing import TypedDict, List

from langchain_core.documents import Document
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field

from rag import llm, detect_companies, vectorstore, PROMPT, log_cost, to_text


# --- Configuration ----------------------------------------------------------

K_PER_JOB = 4      # chunks per job. Jobs vary with the question; k does not.
MAX_JOBS = 6       # hard bound on planner jobs, enforced in code and never in the prompt.
MAX_ROUNDS = 2     # hard bound on retrieval rounds. A bound in a prompt is negotiable.
VERBOSE = True     # node-level logging. run_eval.py switches this off for full eval runs.

# rag.llm is wrapped in a retry policy, and the wrapper hides with_structured_output().
# Unwrap to the underlying chat model. getattr keeps this working if rag.py ever
# stops wrapping it.
BASE_LLM = getattr(llm, "bound", llm)


# --- What is actually in the index ------------------------------------------
# Read once at import. This is a plain Chroma read: no embeddings, no API cost.

def _index_filings():
    """Return the (company, period) pairs present in the index, sorted."""
    metas = vectorstore.get(include=["metadatas"])["metadatas"]
    return sorted({(m["company"], m["period"]) for m in metas})


FILINGS = _index_filings()                       # e.g. [("AMD", "fiscal year 2025 ..."), ...]
KNOWN_PAIRS = set(FILINGS)                       # for validating what the planner returns
CORPUS_LINES = "\n".join(f"- {c} | {p}" for c, p in FILINGS)


# --- Graph state ------------------------------------------------------------

class SearchJob(TypedDict):
    """One planned search: which filing to restrict to, and what to look for."""
    company: str    # "NVIDIA" | "AMD" | "" (empty string means no company filter)
    period: str     # exact period string from the index, or "" for any period
    query: str      # targeted search text for this job


class AgentState(TypedDict):
    """Shared state passed between nodes. Each node reads it and returns a partial update."""
    question: str            # the user's original question - NEVER overwritten
    jobs: List[SearchJob]    # work queue: Plan and Reflect enqueue, Retrieve drains
    chunks: List[Document]   # accumulated across rounds, de-duplicated by chunk id
    seen_ids: List[str]      # chunk ids already collected - the de-dup key
    answer: str              # output of the Answer node
    context: str             # exact context string sent to the model, needed by the judge
    rounds: int              # retrieval rounds completed - the hard loop bound
    companies: List[str]     # validated entities, kept for logging and eval


# --- Planner output schema --------------------------------------------------

class PlannedJob(BaseModel):
    """One search the planner wants to run."""
    company: str = Field(description='A company name from the corpus list, or "" if not company-specific')
    period: str = Field(description='A period string copied EXACTLY from the corpus list, '
                                    'or "" if the question is not tied to one period')
    query: str = Field(description="Short phrase naming the data to find, written like a "
                                   "table heading or statement line, not like a question")


class SearchPlan(BaseModel):
    """The complete set of searches for one question."""
    jobs: List[PlannedJob]


PLAN_PROMPT = """You are a retrieval planner for a search system over SEC filings.

The corpus contains exactly these filings, written as "COMPANY | PERIOD":
{corpus}

Break the QUESTION into independent search jobs.

Rules:
- If answering needs figures from more than one company, emit a job for each one, even
  when only one company is named in the question.
- Set "period" to a period string copied EXACTLY, character for character, from the list
  above, and only ever paired with that same line's company. Use "" when the question
  spans several periods or does not depend on one.
- "latest", "most recent" or "current" means the newest period listed for that company.
- Each job targets exactly ONE figure from ONE financial statement. Never combine
  figures from different statements in a single query: "revenue and operating cash flow"
  must become two jobs. Line items from the SAME statement may appear together, because
  they sit in the same passage.
- Write each query the way the filing reads: name the section the figure lives in, then
  two or three line items near it. Do NOT assume every figure lives in a financial
  statement - segment and product-line figures live in the segment note, not in the
  Consolidated Statements of Operations. Match the figure to its section:
    income statement figure : "Consolidated Statements of Operations net revenue cost of sales gross profit"
    cash flow figure        : "Consolidated Statements of Cash Flows net cash provided by operating activities"
    balance sheet figure    : "Consolidated Balance Sheets total assets total liabilities stockholders equity"
    segment figure          : "revenue by reportable segment Data Center Gaming Client Embedded"
    narrative figure        : the wording the filing's discussion would use
- Questions often ask for a DERIVED figure - a rate, margin, ratio, growth, or per-share
  amount. Filings publish the inputs, not the derivation. Query for the input line items
  and never for the name of the derived figure.
    "effective tax rate" -> "Consolidated Statements of Operations income tax expense income before income taxes"
    "revenue growth"     -> "Consolidated Statements of Operations revenue" (both years sit in one table)
    "gross margin"       -> "Consolidated Statements of Operations revenue cost of revenue gross profit"
- Never use a bare one- or two-word concept - it appears in too many passages to
  retrieve anything precise.
- Companies label the same figure differently ("Revenue" vs "Net revenue"). Naming the
  statement makes a query work across both.
- Prefer fewer jobs, but never merge concepts just to reduce the count.

QUESTION: {question}"""


# --- Nodes ------------------------------------------------------------------

def plan_node(state: AgentState) -> dict:
    """Turn the question into a bounded list of validated search jobs."""
    # Configure first, then wrap for resilience - never the other way round.
    # include_raw=True keeps the underlying AIMessage so token usage can be logged.
    # Without it, with_structured_output() swallows the response and planner cost is invisible.
    planner = BASE_LLM.with_structured_output(SearchPlan, include_raw=True).with_retry(
        stop_after_attempt=3
    )

    try:
        result = planner.invoke(
            PLAN_PROMPT.format(corpus=CORPUS_LINES, question=state["question"])
        )
        log_cost("gemini-3.1-flash-lite", result["raw"], label="agent-plan")
        plan = result["parsed"]
        if plan is None:
            raise ValueError(f"planner output did not parse: {result.get('parsing_error')}")
        raw_jobs = plan.jobs
    except Exception as e:
        # Never crash the pipeline. Degrade to the old path's single unfiltered search.
        if VERBOSE:
            print("[plan] planner failed, falling back to one unfiltered job:", e)
        return {"jobs": [{"company": "", "period": "", "query": state["question"]}],
                "companies": []}

    jobs: List[SearchJob] = []
    for j in raw_jobs[:MAX_JOBS]:                  # bound enforced here, in code
        # The LLM suggests, the code decides. Re-validate every company name:
        # an unrecognised filter value returns zero chunks SILENTLY from Chroma.
        valid = detect_companies(j.company)
        company = valid[0] if valid else ""

        # Validate the PAIR, not the two fields separately. "AMD" is a real company and
        # "fiscal year 2026 ..." is a real period, but that combination exists in no
        # filing, and filtering on it returns nothing at all - silently.
        period = j.period.strip()
        if period and (company, period) not in KNOWN_PAIRS:
            if VERBOSE:
                print(f"[plan] dropping unknown filing pair ({company!r}, {period!r})")
            period = ""                            # degrade to company-only: less precise, honest

        jobs.append({"company": company, "period": period, "query": j.query})

    # Always run the baseline retrieval too: the same unfiltered search on the raw question
    # that the old path performs. The planner may only ADD to what the old path already
    # found - it must never take chunks away. This is the retrieval-level version of
    # "build beside the old path, not inside it". Appended after the MAX_JOBS cut so it
    # can never be truncated away.
    jobs.append({"company": "", "period": "", "query": state["question"]})

    companies = sorted({j["company"] for j in jobs if j["company"]})
    if VERBOSE:
        print("[plan]", len(jobs), "job(s):")
        for j in jobs:
            print(f"        {j['company'] or '-':7} | {j['period'][:38] or '-':40} | {j['query'][:70]}")
    return {"jobs": jobs, "companies": companies}


def _chroma_filter(job: SearchJob):
    """Build a Chroma where-filter from a job. None means no filter at all.

    Passing {} instead of None is not the same thing for every Chroma version, and a
    filter that matches nothing returns zero chunks with no error - which looks exactly
    like a corrupt index. So build the filter explicitly and pass None when empty.
    """
    conds = []
    if job["company"]:
        conds.append({"company": job["company"]})
    if job["period"]:
        conds.append({"period": job["period"]})
    if not conds:
        return None
    return conds[0] if len(conds) == 1 else {"$and": conds}


def retrieve_node(state: AgentState) -> dict:
    """Run every queued job, accumulate new chunks, then drain the queue."""
    chunks = list(state["chunks"])       # copy: never mutate graph state in place
    seen = list(state["seen_ids"])
    added = 0

    for job in state["jobs"]:
        docs = vectorstore.similarity_search(job["query"], k=K_PER_JOB,
                                             filter=_chroma_filter(job))
        for d in docs:
            if d.id in seen:             # the same chunk can satisfy two jobs
                continue
            seen.append(d.id)
            chunks.append(d)
            added += 1

    if VERBOSE:
        print(f"[retrieve] round {state['rounds'] + 1}: {len(state['jobs'])} job(s) "
              f"-> +{added} new, {len(chunks)} total")

    # Drain the queue. jobs is a work order list, not a record of what was planned.
    return {"chunks": chunks, "seen_ids": seen, "jobs": [], "rounds": state["rounds"] + 1}


def answer_node(state: AgentState) -> dict:
    """Generate the grounded answer.
    Prompt and context assembly are copied from rag.answer_question() with ZERO changes.
    Groundedness is already 100%, so generation is not the variable under test here."""
    context = "\n\n".join(d.page_content for d in state["chunks"])
    prompt = PROMPT.format(context=context, question=state["question"])
    resp = llm.invoke(prompt)                    # retry-wrapped llm, same object the old path uses
    log_cost("gemini-3.1-flash-lite", resp, label="agent-generation")
    answer = to_text(resp.content)

    if VERBOSE:
        print(f"[answer] {len(state['chunks'])} chunk(s), {len(context)} chars of context")
    return {"answer": answer, "context": context}


def reflect_node(state: AgentState) -> dict:
    """Judge whether the answer is complete; enqueue a follow-up job if not.
    STUB: always satisfied, enqueues nothing. Deferred until a measured failure
    needs it - see PROJECT_TRACKER.md, Phase 4.1."""
    if VERBOSE:
        print("[reflect] after round", state["rounds"])
    return {}


def should_retry(state: AgentState) -> str:
    """Conditional edge. Loop back ONLY if Reflect queued new work AND we are under the cap.
    The cap lives here in code, never in a prompt."""
    if state["jobs"] and state["rounds"] < MAX_ROUNDS:
        return "retrieve"
    return "end"


# --- Graph wiring -----------------------------------------------------------

builder = StateGraph(AgentState)
builder.add_node("plan", plan_node)
builder.add_node("retrieve", retrieve_node)
builder.add_node("answer", answer_node)
builder.add_node("reflect", reflect_node)

builder.add_edge(START, "plan")
builder.add_edge("plan", "retrieve")
builder.add_edge("retrieve", "answer")
builder.add_edge("answer", "reflect")
builder.add_conditional_edges("reflect", should_retry, {"retrieve": "retrieve", "end": END})

agent = builder.compile()


def run_agent(question: str) -> dict:
    """Entry point. Returns a dict so run_eval.py can A/B it against answer_question()."""
    initial: AgentState = {
        "question": question,
        "jobs": [],
        "chunks": [],
        "seen_ids": [],
        "answer": "",
        "context": "",
        "rounds": 0,
        "companies": [],
    }
    return agent.invoke(initial)


if __name__ == "__main__":
    print("corpus read from the index:")
    for c, p in FILINGS:
        print(f"  {c:7} | {p}")

    tests = [
        "What was NVIDIA's total revenue in fiscal year 2026?",
        "What was NVIDIA's total revenue in fiscal year 2025?",
        "Compare NVIDIA and AMD gross margin for the latest fiscal year.",
        "How does NVIDIA's data center revenue compare with its main competitor's?",
        "How did NVIDIA's gross margin move from fiscal 2025 to fiscal 2026?",
    ]
    for q in tests:
        print("\n===", q)
        out = run_agent(q)
        print("ANSWER:", out["answer"])
