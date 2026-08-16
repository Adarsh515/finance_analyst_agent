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

Phase 4.5 added token, cost and latency accounting, and it exists because of a specific
failure: Phase 4.4 set out to prove a token reduction and could not, because the baseline
had been recorded in TOKENS and the new metric in CHARACTERS. Two measurements in different
units cannot be compared. The rule that came out of it - instrument the metric you intend to
improve BEFORE you start improving it - is implemented here.

Product cost and measurement cost are reported SEPARATELY. Judge calls are the price of
knowing, not the price of answering; a user would never pay them. Folding them into one
number makes an expensive eval look like an expensive product.

Examples:
  python -X utf8 -u run_eval.py --agent
  python -X utf8 -u run_eval.py --agent --set capability --ids x18,x20,x24
  python -X utf8 -u run_eval.py --workers 1          # serial, for debugging
"""

import argparse
import json
import statistics
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv

import judges
import rag
from judges import correctness_judge, groundedness_judge
from golden_set import GOLDEN_SET
from cross_set import CROSS_SET, bucket

load_dotenv()

# --- token / cost accounting -------------------------------------------------
# Every paid call in this project already passes through judges.log_cost() to be printed.
# Wrapping that one function captures all of them without touching rag.py (contract 1:
# rag.py is never modified) and without threading a counter through the graph.
#
# Each module that did `from judges import log_cost` holds its OWN name binding, so every
# one of them has to be re-pointed. Patching only judges.log_cost would silently capture
# nothing from rag.py and agent.py - the exact class of silent failure this project keeps
# finding. The assertion below refuses to let that happen quietly.

_calls = threading.local()          # per-worker-thread, so --workers > 1 stays correct


def _tracked_log_cost(model, response, label=""):
    bucket_ = getattr(_calls, "sink", None)
    if bucket_ is not None:
        u = getattr(response, "usage_metadata", None) or {}
        bucket_.append((label,
                        u.get("input_tokens", 0) or 0,
                        u.get("output_tokens", 0) or 0,
                        model))
    return _ORIGINAL_LOG_COST(model, response, label=label)


_ORIGINAL_LOG_COST = judges.log_cost


def _install_cost_tracking(*modules):
    patched = []
    for mod in modules:
        if mod is not None and getattr(mod, "log_cost", None) is _ORIGINAL_LOG_COST:
            mod.log_cost = _tracked_log_cost
            patched.append(mod.__name__)
    return patched


def _usd(calls):
    total = 0.0
    for _label, intok, outok, model in calls:
        p_in, p_out = judges.PRICES.get(model, (0.0, 0.0))
        total += (intok * p_in + outok * p_out) / 1_000_000
    return total

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
    _patched = _install_cost_tracking(judges, rag, agent)
else:
    import rag as _rag_mod
    answer_fn = _rag_mod.answer_question
    PATH_NAME = "BASELINE (rag.answer_question)"
    _patched = _install_cost_tracking(judges, rag)

# A metric that silently measures nothing is worse than no metric. If the wrapper failed to
# reach a module, say so now and loudly, not after a 25-minute run reports 0 tokens.
assert len(_patched) >= 2, f"cost tracking reached only {_patched}"

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
    """Answer and judge one example. Returns a result dict, or raises for infra errors.

    The answering calls and the judging calls are captured into two separate buckets. That
    split is the point: judge tokens are the cost of KNOWING, product tokens are the cost of
    ANSWERING, and only the second is what a user would ever pay for.
    """
    _calls.sink = []
    t0 = time.perf_counter()
    out = answer_fn(question=ex["question"])
    secs = time.perf_counter() - t0
    product_calls, _calls.sink = _calls.sink, []

    ans = out["answer"]
    c = correctness_judge(question=ex["question"], prediction=ans,
                          reference=ex["reference_answer"])
    g = groundedness_judge(question=ex["question"], prediction=ans,
                           context=out["context"])
    judge_calls, _calls.sink = _calls.sink, None

    # "generation" is the answer-writing call. It is isolated because it is the ONLY figure
    # comparable with the pre-4.4 baseline (368,502 input tokens over 97 calls), which was
    # recorded before planner and Reflect tokens were logged separately.
    gen_in = sum(i for lab, i, o, m in product_calls if "generation" in lab)
    gen_calls = sum(1 for lab, i, o, m in product_calls if "generation" in lab)
    # Context size is a first-class metric from Phase 4.4 on. Characters, not tokens:
    # exact, free, tokenizer-independent, and available for both paths. Roughly 4 chars
    # per token for this corpus. A metric that is not on the scoreboard does not get
    # optimised, and "I cut context by N%" is a claim that needs a before-number.
    return {"ex": ex, "answer": ans, "c": c, "g": g, "ctx": len(out["context"]),
            "ctx_text": out["context"],
            "gen_in": gen_in, "gen_calls": gen_calls,
            "prod_in": sum(i for _l, i, _o, _m in product_calls),
            "prod_out": sum(o for _l, _i, o, _m in product_calls),
            "prod_usd": _usd(product_calls), "judge_usd": _usd(judge_calls),
            "secs": secs, "rounds": out.get("rounds")}


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
                               "gen_input_tokens": r["gen_in"], "gen_calls": r["gen_calls"],
                               "product_input_tokens": r["prod_in"],
                               "product_output_tokens": r["prod_out"],
                               "product_usd": round(r["prod_usd"], 8),
                               "judge_usd": round(r["judge_usd"], 8),
                               "seconds": round(r["secs"], 2), "rounds": r["rounds"],
                               "answer": r["answer"],
                               # The context is stored in full, and it is not for reading -
                               # it is so that every FUTURE judge experiment is free. Re-judging
                               # a stored answer needs the exact context it was grounded in;
                               # without it, groundedness work means re-running the agent.
                               # Same rule as the token metric: record it before you need it.
                               "context": r["ctx_text"],
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

        def dist(label, values, fmt="{:,.0f}"):
            v = sorted(values)
            p95 = v[min(len(v) - 1, int(0.95 * len(v)))]
            print(f"  {label:22} median {fmt.format(statistics.median(v)):>9}  "
                  f"mean {fmt.format(statistics.mean(v)):>9}  p95 {fmt.format(p95):>9}  "
                  f"max {fmt.format(v[-1]):>9}  total {fmt.format(sum(v)):>11}")

        dist("Context chars:", [r["ctx"] for r in results])
        dist("Generation in-tokens:", [r["gen_in"] for r in results])
        dist("Product in-tokens:", [r["prod_in"] for r in results])
        dist("Seconds/question:", [r["secs"] for r in results], "{:,.1f}")

        prod_usd = sum(r["prod_usd"] for r in results)
        judge_usd = sum(r["judge_usd"] for r in results)
        gen_calls = sum(r["gen_calls"] for r in results)
        print(f"  PRODUCT cost ${prod_usd:.4f}  (${prod_usd / n:.6f}/question, "
              f"{gen_calls} generation calls)")
        print(f"  MEASURE cost ${judge_usd:.4f}  (judging, {judge_usd / max(prod_usd, 1e-9):.1f}x "
              f"the product cost - the price of knowing, not of answering)")
        rounds2 = [r for r in results if r["rounds"] == 2]
        if rounds2:
            print(f"  Reflect ran a second round on {len(rounds2)}/{n} "
                  f"({len(rounds2) / n:.0%}): {[r['ex']['id'] for r in rounds2]}")

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
