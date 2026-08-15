"""
Run an eval set through one of the two answer paths and score it.

Two paths, one scorer. The baseline (rag.answer_question) is the default; --agent
selects the LangGraph path. Everything downstream - judges, buckets, failure dump -
is shared, so a run compares SYSTEMS and never compares scorers.

Three things exist here purely to make measuring cheap enough to do often:

  --ids / --set   Run a subset. Re-checking six repaired items should cost six
                  questions, not eighty. A measurement people avoid because it is
                  slow stops being a measurement.
  --workers       Questions are independent, so they run concurrently. Same calls,
                  same cost, same scores - only wall-clock changes.
  --out           Every scored result is appended to a JSONL file as soon as it is
                  computed. A run that dies at question 79 keeps its first 78 paid
                  answers. This exists because a UnicodeEncodeError in a print
                  statement once threw away a completed 80-question run.

Examples:
  python -X utf8 -u run_eval.py --agent
  python -X utf8 -u run_eval.py --agent --set capability --ids x18,x20,x24
  python -X utf8 -u run_eval.py --workers 1          # serial, for debugging
"""

import argparse
import json
import statistics
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv

from judges import correctness_judge, groundedness_judge
from golden_set import GOLDEN_SET
from cross_set import CROSS_SET, bucket

load_dotenv()

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--agent", action="store_true",
                    help="use the LangGraph agent instead of the baseline path")
parser.add_argument("--set", dest="which", default="both",
                    choices=["regression", "capability", "both"])
parser.add_argument("--ids", default="",
                    help="comma-separated question ids; runs only these")
parser.add_argument("--workers", type=int, default=6,
                    help="concurrent questions (1 = serial)")
parser.add_argument("--out", default="",
                    help="append each scored result to this JSONL file as it completes")
args = parser.parse_args()

if args.agent:
    import agent
    agent.VERBOSE = False              # silence node logs during a full eval run
    answer_fn = agent.run_agent
    PATH_NAME = "AGENT (LangGraph: plan -> retrieve -> answer)"
else:
    from rag import answer_question as answer_fn
    PATH_NAME = "BASELINE (rag.answer_question)"

ONLY_IDS = {i.strip() for i in args.ids.split(",") if i.strip()}
_print_lock = threading.Lock()
_out_lock = threading.Lock()


def _emit(line):
    """Print from a worker thread without interleaving with another thread's line."""
    with _print_lock:
        print(line, flush=True)


def _record(path, payload):
    if not path:
        return
    with _out_lock:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def score_one(ex):
    """Answer and judge one example. Returns a result dict, or raises for infra errors."""
    out = answer_fn(question=ex["question"])
    ans = out["answer"]
    c = correctness_judge(question=ex["question"], prediction=ans,
                          reference=ex["reference_answer"])
    g = groundedness_judge(question=ex["question"], prediction=ans,
                           context=out["context"])
    # Context size is a first-class metric from Phase 4.4 on. Characters, not tokens:
    # exact, free, tokenizer-independent, and available for both paths. Roughly 4 chars
    # per token for this corpus. A metric that is not on the scoreboard does not get
    # optimised, and "I cut context by N%" is a claim that needs a before-number.
    return {"ex": ex, "answer": ans, "c": c, "g": g, "ctx": len(out["context"])}


def run_set(name, examples, bucket_fn=None):
    examples = [e for e in examples if not ONLY_IDS or e["id"] in ONLY_IDS]
    if not examples:
        return []

    print(f"\n{'=' * 70}\n{name}   ({len(examples)} questions)\n{'=' * 70}")
    results, errors = [], []
    done = 0
    total = len(examples)

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(score_one, ex): ex for ex in examples}
        for fut in as_completed(futures):
            ex = futures[fut]
            done += 1
            try:
                r = fut.result()
            except Exception as e:
                errors.append(ex["id"])
                _emit(f"  [{done:3}/{total}] {ex['id']}  INFRA ERROR, skipped: {str(e)[:60]}")
                _record(args.out, {"set": name, "id": ex["id"], "error": str(e)[:200]})
                continue
            results.append(r)
            mark = "PASS" if r["c"]["score"] == 1 else "FAIL"
            _emit(f"  [{done:3}/{total}] {ex['id']}  {mark}  grounded={r['g']['score']}  "
                  f"{r['answer'][:70]}")
            _record(args.out, {"set": name, "id": ex["id"], "correct": r["c"]["score"],
                               "grounded": r["g"]["score"], "context_chars": r["ctx"],
                               "answer": r["answer"],
                               "judge": r["c"].get("reasoning", "")})

    # Sort back into set order so two runs of the same set produce comparable files.
    order = {e["id"]: n for n, e in enumerate(examples)}
    results.sort(key=lambda r: order[r["ex"]["id"]])

    n = len(results)
    if n:
        corr = sum(r["c"]["score"] for r in results)
        grnd = sum(r["g"]["score"] for r in results)
        print(f"\n  Scored {n}/{len(examples)}  ({len(errors)} infra errors skipped)")
        print(f"  Correctness : {corr}/{n} = {corr/n:.0%}")
        print(f"  Groundedness: {grnd}/{n} = {grnd/n:.0%}")

        ctx = sorted(r["ctx"] for r in results)
        p95 = ctx[min(len(ctx) - 1, int(0.95 * len(ctx)))]
        print(f"  Context chars: median {statistics.median(ctx):,.0f}  "
              f"mean {statistics.mean(ctx):,.0f}  p95 {p95:,}  max {ctx[-1]:,}  "
              f"total {sum(ctx):,}")

    if bucket_fn:
        by = defaultdict(lambda: [0, 0])
        for r in results:
            b = bucket_fn(r["ex"])
            by[b][1] += 1
            by[b][0] += 1 if r["c"]["score"] == 1 else 0
        print("\n  correctness by bucket:")
        for b, (ok, tot) in sorted(by.items()):
            print(f"    {b:<16} {ok}/{tot}")

    if errors:
        print(f"\n  infra errors (NOT scored as wrong): {errors}")

    fails = [r for r in results if r["c"]["score"] != 1]
    if fails:
        print(f"\n  --- {len(fails)} FAILURES ---")
        for r in fails:
            grp = bucket_fn(r["ex"]) if bucket_fn else "-"
            print(f"\n  {r['ex']['id']}  [{grp}]")
            print(f"    Q:        {r['ex']['question']}")
            print(f"    expected: {r['ex']['reference_answer'][:150]}")
            print(f"    got:      {r['answer'][:600]}")
            print(f"    judge:    {str(r['c'].get('reasoning', ''))[:150]}")
            print(f"    grounded: {r['g']['score']}")
    return results


if __name__ == "__main__":
    print(f"\n### PATH: {PATH_NAME}")
    print(f"### workers={args.workers}  set={args.which}"
          + (f"  ids={sorted(ONLY_IDS)}" if ONLY_IDS else "")
          + (f"  out={args.out}" if args.out else "") + "\n")

    if args.which in ("regression", "both"):
        run_set("REGRESSION - NVIDIA only", GOLDEN_SET)
    if args.which in ("capability", "both"):
        run_set("CAPABILITY - cross-document", CROSS_SET, bucket_fn=bucket)
