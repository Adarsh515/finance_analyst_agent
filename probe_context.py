# probe_context.py
# Phase 4.4 exists to answer one question: does the agent send FEWER tokens per answer?
# That claim needs a before-number, and there was none - context size only became a metric
# in 4.4 itself, after the old selection was already gone.
#
# This measures the OLD path and several candidate caps over the WHOLE eval set without
# generating a single answer. Planning is one cheap structured call per question, retrieval
# is local, and every candidate cap is then applied to the SAME fetched chunks - so a sweep
# of five configurations costs exactly the same as measuring one. Roughly three cents for
# 94 questions, against a 20-minute paid run.
#
# What the first run of this probe found, and why the sweep exists:
#   REGRESSION  old 283,131 chars -> new 377,432   = +33%   cap bit on 0 of 40 questions
#   CAPABILITY  old 685,896 chars -> new 587,195   = -14%   cap bit on 31 of 54
# A floor of 10 chunks was inflating every two-job question. The floor, not the evidence,
# was setting the context size. Hence MIN_CHUNKS.
#
# Round 1 only, for every configuration. Reflect rounds depend on what the answer says and
# no answers are produced here, so this is a floor - but an equally-applied one, since
# Reflect is unchanged across all columns.

import statistics
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

import agent
from agent import plan_node, _chroma_filter, _select, vectorstore
from golden_set import GOLDEN_SET
from cross_set import CROSS_SET

load_dotenv()
agent.VERBOSE = False

OLD_K = 4          # what K_PER_JOB was before Phase 4.4

# (label, min_total, per_job_slots). The live agent config is marked so the table always
# says which row is actually shipping, even after these numbers are edited.
SWEEP = [
    ("floor 6,  2/job  <-- LIVE", 6, 2),
    ("floor 10, 2/job  (4.4b)", 10, 2),
    ("floor 6,  3/job", 6, 3),
    ("floor 4,  2/job", 4, 2),
    ("no floor, 2/job", 0, 2),
]


def chars(chunks):
    # Same assembly answer_node uses, so this is the real context string's length.
    return len("\n\n".join(d.page_content for d in chunks))


def measure(ex):
    question = ex["question"]
    plan = plan_node({"question": question, "jobs": [], "chunks": [], "seen_ids": [],
                      "answer": "", "context": "", "rounds": 0, "companies": []})
    jobs = plan["jobs"]

    # OLD: fetch shallow, keep every distinct chunk. No selection step existed.
    old, seen = [], set()
    for j in jobs:
        for d in vectorstore.similarity_search(j["query"], k=OLD_K, filter=_chroma_filter(j)):
            if d.id not in seen:
                seen.add(d.id)
                old.append(d)

    # NEW: fetch once at the live depth, then apply every candidate cap to the same catch.
    deep = [vectorstore.similarity_search(j["query"], k=agent.K_PER_JOB,
                                          filter=_chroma_filter(j)) for j in jobs]

    row = {"id": ex["id"], "jobs": len(jobs), "old_n": len(old), "old_c": chars(old)}
    for label, min_total, per_job in SWEEP:
        sel = _select(deep, set(), min_total, per_job)
        row[label] = (len(sel), chars(sel))
    return row


def line(label, ns, cs, base=None):
    cs_sorted = sorted(cs)
    p95 = cs_sorted[min(len(cs_sorted) - 1, int(0.95 * len(cs_sorted)))]
    delta = "" if base is None else f"  {(sum(cs) - base) / base * 100:+6.1f}%"
    print(f"  {label:28} chunks med {statistics.median(ns):>5.1f}   "
          f"chars med {statistics.median(cs):>7,.0f}  p95 {p95:>7,}  "
          f"max {max(cs):>7,}  total {sum(cs):>9,}{delta}")


def report(name, rows):
    print(f"\n{'=' * 96}\n{name}   ({len(rows)} questions)\n{'=' * 96}")
    base = sum(r["old_c"] for r in rows)
    line(f"OLD  k={OLD_K}, keep all", [r["old_n"] for r in rows], [r["old_c"] for r in rows])
    for label, _, _ in SWEEP:
        line(label, [r[label][0] for r in rows], [r[label][1] for r in rows], base)

    live = SWEEP[0][0]
    # A cap that never binds is not a feature, it is a comment. A cap that binds on
    # everything is a truncation policy in disguise. Both extremes are worth seeing.
    bit = sum(1 for r in rows if r[live][0] < r["old_n"])
    grew = [r for r in rows if r[live][1] > r["old_c"]]
    print(f"\n  LIVE config: cut the chunk count on {bit}/{len(rows)} questions; "
          f"context grew on {len(grew)}")
    if grew:
        worst = sorted(grew, key=lambda r: r["old_c"] - r[live][1])[:5]
        print("  biggest INCREASES vs old: "
              + ", ".join(f"{r['id']} {r['old_c']:,}->{r[live][1]:,}" for r in worst))
    by_jobs = {}
    for r in rows:
        by_jobs.setdefault(r["jobs"], []).append(r)
    print("  job-count spread: "
          + "  ".join(f"{k} jobs x{len(v)}" for k, v in sorted(by_jobs.items())))


if __name__ == "__main__":
    all_rows = []
    for name, examples in (("REGRESSION - NVIDIA only", GOLDEN_SET),
                           ("CAPABILITY - cross-document", CROSS_SET)):
        with ThreadPoolExecutor(max_workers=6) as pool:
            rows = list(pool.map(measure, examples))
        report(name, rows)
        all_rows += rows

    report("BOTH SETS COMBINED - the number Phase 4.4 is judged on", all_rows)
    print("\n  Round 1 only. Wherever Reflect fires the real context is larger than every\n"
          "  column here - equally, since Reflect is unchanged.")
