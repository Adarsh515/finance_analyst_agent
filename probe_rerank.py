# probe_rerank.py
# Phase 4.4 post-mortem. The re-ranker cost 20 capability points (54/54 -> 34/54) and
# saved no tokens. Before changing one line of it, prove WHY it fails.
#
# The hypothesis under test:
#   A single question-embedding yardstick is COMPANY-BLIND and JOB-BLIND. In a
#   cross-company question, whichever company's chunks look most like the question
#   takes most of the ten slots, and the other companies get evicted - even though the
#   planner deliberately fetched them. That would explain the exact shape of the damage:
#   cross-company 22 -> 9, three-way 2/3, while single-company stayed 7/7.
#
# This probe runs NO generation calls. It plans (one cheap structured call per question),
# retrieves, scores, and then replays four different selection strategies over the SAME
# candidate set. The needles are figures the reference answer genuinely requires, written
# the way the index stores them: no thousands separators.
#
# What to read in the output:
#   - "candidates by company" vs "kept by company"  -> is a company being wiped out?
#   - needle table                                  -> was the needle FETCHED but EVICTED?
#     A needle present in ALL but absent in TOP-N is an eviction, not a retrieval miss.
#     That distinction decides whether the fix belongs in selection or in planning.

import numpy as np

import agent
from agent import plan_node, _chroma_filter, K_PER_JOB

TOP_N_CHUNKS = 10   # the value Phase 4.4 shipped and this probe replays. Pinned here
                    # on purpose: agent.py's knob is now MIN_CHUNKS and means a FLOOR,
                    # which is a different idea. Importing it would silently change
                    # what this post-mortem reproduces.
from rag import vectorstore, embeddings   # agent.py no longer imports embeddings; this
                                          # probe still needs one to REPLAY the bad idea.

agent.VERBOSE = False

# id -> (question, {label: needle}). Needles are stored-form figures, not display form.
CASES = {
    "x26": ("How much bigger was NVIDIA's gross profit than the other chipmaker's in "
            "these filings?",
            {"NVDA gross profit 153,463": "153463",
             "AMD  gross profit  17,152": "17152"}),

    "x28": ("How much smaller were AMD's total assets than the other chipmaker's in "
            "these filings?",
            {"AMD  total assets  76,926": "76926",
             "NVDA total assets 206,803": "206803"}),

    "w03": ("Rank all the companies in these filings by cash generated from operating "
            "activities, with the figures.",
            {"NVDA op CF 102,718": "102718",
             "Intel op CF  9,697": "9697",
             "AMD  op CF  7,709": "7709"}),

    "x13": ("Both NVIDIA and AMD report a Gaming segment. What was Gaming revenue for each?",
            {"NVDA Gaming 16,042": "16042",
             "AMD  Gaming  3,910": "3910"}),
}


def company_counts(chunks):
    out = {}
    for c in chunks:
        k = c.metadata.get("company", "?")
        out[k] = out.get(k, 0) + 1
    return "  ".join(f"{k}:{v}" for k, v in sorted(out.items()))


def coverage(chunks, needles):
    """Which needles survive in this selection. Returns a dict label -> bool."""
    text = "\n\n".join(c.page_content for c in chunks)
    return {label: (n in text) for label, n in needles.items()}, len(text)


def round_robin(per_job, cap):
    """Take rank 1 from every job, then rank 2 from every job, until cap is reached.

    This is the candidate FIX in simulated form: representation is guaranteed per job,
    so a job the planner thought was worth running can never be zeroed out by another
    job's chunks scoring higher. The global cap still applies - this changes WHICH
    chunks get cut, not HOW MANY.
    """
    kept, seen, depth = [], set(), 0
    while len(kept) < cap:
        progressed = False
        for docs in per_job:
            if depth < len(docs):
                progressed = True
                d = docs[depth]
                if d.id not in seen:
                    seen.add(d.id)
                    kept.append(d)
                    if len(kept) >= cap:
                        break
        if not progressed:
            break
        depth += 1
    return kept


for qid, (question, needles) in CASES.items():
    print("=" * 78)
    print(f"{qid}: {question}")
    print("=" * 78)

    plan = plan_node({"question": question, "jobs": [], "chunks": [], "seen_ids": [],
                      "answer": "", "context": "", "rounds": 0, "companies": []})
    jobs = plan["jobs"]
    for n, j in enumerate(jobs):
        print(f"  job {n}: {j['company'] or '-':7} | {j['period'][:30] or '-':32} | {j['query'][:60]}")

    # Retrieve per job, keeping provenance. De-dup is global, first job to fetch owns it -
    # exactly what retrieve_node does, so the candidate set here is the real one.
    per_job, allc, seen = [], [], set()
    for j in jobs:
        docs = vectorstore.similarity_search(j["query"], k=K_PER_JOB,
                                             filter=_chroma_filter(j))
        mine = []
        for d in docs:
            if d.id in seen:
                continue
            seen.add(d.id)
            mine.append(d)
            allc.append(d)
        per_job.append(mine)

    qvec = np.asarray(embeddings.embed_query(question), dtype=float)
    qvec = qvec / (np.linalg.norm(qvec) or 1.0)
    stored = vectorstore.get(ids=[c.id for c in allc], include=["embeddings"])
    by_id = {i: np.asarray(v, dtype=float) for i, v in zip(stored["ids"], stored["embeddings"])}

    def score(c):
        v = by_id.get(c.id)
        return -1.0 if v is None else float(qvec @ (v / (np.linalg.norm(v) or 1.0)))

    ranked = sorted(allc, key=score, reverse=True)
    topn = ranked[:TOP_N_CHUNKS]

    print(f"\n  candidates: {len(allc)}   by company -> {company_counts(allc)}")
    print(f"  TOP-{TOP_N_CHUNKS} kept    by company -> {company_counts(topn)}")
    print(f"\n  the ten survivors (score | company | which job fetched it | text):")
    owner = {d.id: n for n, docs in enumerate(per_job) for d in docs}
    for r, c in enumerate(topn, 1):
        print(f"    {r:2}. {score(c):.4f}  {c.metadata.get('company','?'):7} job{owner.get(c.id,'?')}  "
              f"{c.page_content[:64].replace(chr(10), ' ')}")

    # Where did each needle live in the ranking? A needle at rank 14 was fetched and
    # then thrown away - the planner did its job and selection undid it.
    print(f"\n  needle rank in the global ranking (-- means never fetched at all):")
    for label, n in needles.items():
        hit = next((r for r, c in enumerate(ranked, 1) if n in c.page_content), None)
        print(f"    {label:28} rank {hit if hit else '--'}")

    strategies = {
        "ALL candidates (upper bound)": allc,
        f"GLOBAL top-{TOP_N_CHUNKS} (shipped 4.4)": topn,
        f"ROUND-ROBIN per job, cap {TOP_N_CHUNKS}": round_robin(
            [sorted(d, key=score, reverse=True) for d in per_job], TOP_N_CHUNKS),
        "ROUND-ROBIN per job, cap 3*jobs": round_robin(
            [sorted(d, key=score, reverse=True) for d in per_job], 3 * max(1, len(jobs))),
    }
    print(f"\n  {'strategy':36} {'chunks':>6} {'chars':>7}  needles")
    for name, sel in strategies.items():
        cov, chars = coverage(sel, needles)
        flags = " ".join(("Y" if v else "n") for v in cov.values())
        print(f"    {name:36} {len(sel):>6} {chars:>7}  {flags}   "
              f"({company_counts(sel)})")
    print()
