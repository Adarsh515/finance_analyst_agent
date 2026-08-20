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
import judges_coverage
import judges_rubric
import judges_scope
import rag
from judges import correctness_judge, groundedness_judge
from judges_coverage import coverage_judge
from judges_rubric import rubric_judge
from judges_scope import scope_judge
from golden_set import GOLDEN_SET
from cross_set import CROSS_SET, bucket
from tesla_set import TESLA_SET, bucket as tesla_bucket

# Ids must be unique ACROSS the three sets, checked HERE because this is the file that selects
# by id: `--ids t01` cannot mean two different questions. tesla_set.py shipped with t01..t08
# while cross_set.py already used t01..t03 for TREND questions, and nothing noticed, because
# each set only checked itself. The check belongs where the ambiguity would be resolved.
_ALL_IDS = [e["id"] for e in GOLDEN_SET] + [e["id"] for e in CROSS_SET] + \
           [e["id"] for e in TESLA_SET]
_DUPES = sorted({i for i in _ALL_IDS if _ALL_IDS.count(i) > 1})
assert not _DUPES, (f"duplicate question ids across the eval sets: {_DUPES}. --ids selects by "
                    f"id alone, so a collision silently runs the wrong question.")

load_dotenv()

# --- token / cost accounting -------------------------------------------------
# MOVED to telemetry.py in Phase 6.3, unchanged in behaviour. The API has to record the same
# per-call tuple this harness records, and a second implementation of one definition is the
# cheapest possible way to make the product and the measurement disagree - two copies, each
# self-consistent, drifting quietly. So there is one implementation and both import it.
#
# The mechanism is unchanged and its sharp edge is unchanged with it: every module here does
# `from judges import log_cost`, binding the function object into its OWN namespace, so each
# importing module has to be re-pointed by name. telemetry.install() returns what it actually
# patched and the assertion below still refuses a partial install - a capture that reached
# three modules of five would under-report cost and look exactly like a cheap system.

import telemetry

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--agent", action="store_true",
                    help="use the LangGraph agent instead of the baseline path")
parser.add_argument("--set", dest="which", default="both",
                    choices=["regression", "capability", "both", "tesla", "all"],
                    help="both = regression+capability, the historic pair, so gate-to-gate\n"
                         "comparisons stay against the same population. Phase 6.8 added a\n"
                         "sixth filing and its own set; 'all' includes it.")
parser.add_argument("--ids", default="",
                    help="comma-separated question ids; runs only these")
parser.add_argument("--workers", type=int, default=6,
                    help="concurrent questions (1 = serial)")
parser.add_argument("--out", default="",
                    help="append each scored result to this JSONL file as it completes")
parser.add_argument("--append", action="store_true",
                    help="allow --out to append to a file that already has "
                         "records. Off by default: a duplicated gate run is the\n"
                         "most expensive mistake available in this repo.")
parser.add_argument("--repeat", type=int, default=1,
                    help="run each selected question N times. Generation is not "
                         "deterministic (lesson 64), so a format or verdict question "
                         "answered at n=1 measures the generator, not the change.")
parser.add_argument("--rubric", action="store_true",
                    help="also run the rubric correctness judge. OFF by default since 4.5.7: "
                         "it was killed on evidence (24 false positives on 94 real answers, "
                         "zero catches) and a parked metric should not be billed for on "
                         "every run. Kept switchable because the code and the finding stay.")
parser.add_argument("--no-guards", action="store_true",
                    help="run the agent with the Phase 5/6 guards OFF. Added when the w02 "
                         "gate failure needed attributing: a quality change that appears "
                         "the same day a guard ships is not proof the guard caused it, and "
                         "a flag is cheaper than an argument.")
parser.add_argument("--no-extra", action="store_true",
                    help="skip the two Phase 4.5 scoreboards (rubric correctness, scope "
                         "groundedness) and score exactly as before 4.5. They are ON by "
                         "default deliberately: a scoreboard you have to remember to "
                         "switch on is a scoreboard that will be missing from the run that "
                         "mattered.")
parser.add_argument("--no-coverage", action="store_true",
                    help="skip the Phase 6.10b set-coverage scoreboard. ON by default, same "
                         "argument as --no-extra: the 6.10 gate passed three answers on every "
                         "existing scoreboard that had ranked over a set they never covered, "
                         "and a scoreboard nobody remembers to switch on would have missed "
                         "them again. Costs about Rs 3 on a 102-question gate, and only the "
                         "questions that rank over a set are counted in its denominator.")


# --- refuse to append to an existing --out file ------------------------------
# This exists because a duplicate cost real money. eval_60_gate.jsonl came back with 188
# records - TWO complete 94-question gates, byte-identical answers - and that single
# duplication was roughly Rs 45 of the Rs 62 spent that day, on a learner's metered credit.
#
# --out appends by design (a run that dies at question 79 must keep its first 78 paid
# answers). But "append" and "the file already holds a finished run" are different
# situations, and only one of them is safe. So: refuse, name the file, and make the user
# choose - a new name, or --append if mixing runs is genuinely intended.
def _guard_out_path(path, append):
    if not path or append:
        return
    import os
    if os.path.exists(path) and os.path.getsize(path) > 0:
        n = sum(1 for _ in open(path, encoding="utf-8"))
        raise SystemExit(
            f"\nREFUSING TO RUN: {path} already holds {n} records.\n"
            f"Appending would mix two runs in one file and pay for answers you already have.\n"
            f"Use a new --out name, or pass --append if you really mean to add to it.\n")


args = parser.parse_args()
_guard_out_path(args.out, args.append)
EXTRA = not args.no_extra
COVERAGE = not args.no_coverage

if args.agent:
    import agent
    agent.VERBOSE = False              # silence node logs during a full eval run
    agent.GUARDS = not args.no_guards
    answer_fn = agent.run_agent
    PATH_NAME = "AGENT (LangGraph: plan -> retrieve -> answer)"
    import rewriter
    # rewriter did `from judges import log_cost` through rag, so it holds its OWN binding.
    # Leaving it out would drop every rewrite call from the token count - the exact silent
    # undercount this install() was written to prevent, reappearing the moment a new module
    # joins the paid path.
    _patched = telemetry.install(judges, rag, agent, rewriter, judges_rubric, judges_scope,
                                 judges_coverage)
else:
    import rag as _rag_mod
    answer_fn = _rag_mod.answer_question
    PATH_NAME = "BASELINE (rag.answer_question)"
    _patched = telemetry.install(judges, rag, judges_rubric, judges_scope, judges_coverage)

# A metric that silently measures nothing is worse than no metric. If the wrapper failed to
# reach a module, say so now and loudly, not after a 25-minute run reports 0 tokens.
assert len(_patched) >= 4, f"cost tracking reached only {_patched}"

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
    with telemetry.capture() as product_calls:
        t0 = time.perf_counter()
        out = answer_fn(question=ex["question"])
        secs = time.perf_counter() - t0

    ans = out["answer"]
    with telemetry.capture() as judge_calls:
        c = correctness_judge(question=ex["question"], prediction=ans,
                              reference=ex["reference_answer"])
        g = groundedness_judge(question=ex["question"], prediction=ans,
                               context=out["context"])

    # --- the two Phase 4.5 scoreboards, ADDED, never substituted ------------------------
    # Every historical number in PROJECT_TRACKER.md was produced by the two judges above.
    # Swapping either one would silently redefine the y-axis of every comparison in that
    # file, so they keep running unchanged and these sit beside them.
    #
    # rubric   : correctness scored in CODE from per-fact observations. Beat the binary judge
    #            11/11 vs 10/11 on hand-written paraphrases, with 0 wording-splits vs 1.
    # scope    : groundedness of the CLAIM rather than of the figures. Measured 21/21 when
    #            ANDed with the binary judge, against 18/21 for the binary judge alone.
    #
    # The AND is the operative part. Both groundedness judges fail by OMISSION - the binary
    # one audits figures and skips the sentence, the scope one reads the sentence and waves
    # through invented figures - so a claim has to survive both readings. What is NOT yet
    # measured is what ANDing costs in false negatives on real answers at full scale; eight
    # stored answers is not a sample. That is exactly what this run is for.
        rub = sc = None
        if EXTRA and args.rubric:
            rub = rubric_judge(question=ex["question"], prediction=ans,
                               reference=ex["reference_answer"])
        if EXTRA:
            sc = scope_judge(question=ex["question"], prediction=ans, context=out["context"])
        # A THIRD axis, added 6.10b, and it answers a question neither of the two above can.
        # Both of them ask "is this claim supported?" - so an answer that names a winner over
        # a set it never covered is grounded, because every sentence in it is traceable. This
        # one asks "was the set you compared over complete?" It is NOT part of any AND and is
        # never averaged in: it can flag an answer that is correct and grounded, and on the
        # 6.10 gate seven of its eight flags were exactly that. score is None when the
        # question does not rank over a set, and those are EXCLUDED from the denominator
        # rather than counted as passes.
        cov = None
        if COVERAGE:
            cov = coverage_judge(question=ex["question"], prediction=ans,
                                 context=out["context"])

    # "generation" is the answer-writing call. It is isolated because it is the ONLY figure
    # comparable with the pre-4.4 baseline (368,502 input tokens over 97 calls), which was
    # recorded before planner and Reflect tokens were logged separately.
    prod = telemetry.summarise(product_calls)
    gen_in, gen_calls = prod["gen_in"], prod["gen_calls"]
    # Context size is a first-class metric from Phase 4.4 on. Characters, not tokens:
    # exact, free, tokenizer-independent, and available for both paths. Roughly 4 chars
    # per token for this corpus. A metric that is not on the scoreboard does not get
    # optimised, and "I cut context by N%" is a claim that needs a before-number.
    return {"ex": ex, "answer": ans, "c": c, "g": g, "rub": rub, "sc": sc, "cov": cov,
            "ctx": len(out["context"]),
            "ctx_text": out["context"],
            "gen_in": gen_in, "gen_calls": gen_calls,
            "prod_in": prod["input_tokens"],
            "prod_out": prod["output_tokens"],
            "prod_usd": prod["usd"], "judge_usd": telemetry.usd(judge_calls),
            "secs": secs, "rounds": out.get("rounds")}


def run_set(name, examples, bucket_fn=None):
    examples = [e for e in examples if not ONLY_IDS or e["id"] in ONLY_IDS]
    if args.repeat > 1:
        # Repeat by duplicating the work list. The scoreboard totals then read n*len, which
        # is correct - each repetition is an independent measurement, not a re-scoring of
        # the same answer.
        examples = [e for e in examples for _ in range(args.repeat)]
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
            extra = ""
            if r["rub"] is not None:
                # Only shown when a new judge DISAGREES with the old one. A column that
                # repeats the previous column on 95% of rows teaches nothing and hides the
                # 5% that matter.
                flags = []
                if r["rub"]["score"] != r["c"]["score"]:
                    flags.append(f"rubric={r['rub']['score']}")
                if r["sc"]["score"] != r["g"]["score"]:
                    flags.append(f"scope={r['sc']['score']}")
                extra = ("  [" + " ".join(flags) + "]") if flags else ""
            _emit(f"  [{done:3}/{total}] {ex['id']}  {mark}  grounded={r['g']['score']}"
                  f"{extra}  {r['answer'][:70]}")
            _record(args.out, {"set": name, "id": ex["id"], "correct": r["c"]["score"],
                               "grounded": r["g"]["score"],
                               "rubric": r["rub"]["score"] if r["rub"] else None,
                               "scope": r["sc"]["score"] if r["sc"] else None,
                               "grounded_and": (min(r["g"]["score"], r["sc"]["score"])
                                                if r["sc"] else None),
                               "rubric_facts": (f"{r['rub']['facts_ok']}/"
                                                f"{r['rub']['facts_total']}") if r["rub"] else None,
                               "scope_why": r["sc"]["reasoning"][:300] if r["sc"] else None,
                               # None here means "this question does not rank over a set",
                               # which is NOT a pass - see the denominator below.
                               "coverage": r["cov"]["score"] if r["cov"] else None,
                               "coverage_required": r["cov"]["required"] if r["cov"] else None,
                               "coverage_missing": r["cov"]["missing"] if r["cov"] else None,
                               "coverage_why": (r["cov"]["reasoning"][:300]
                                                if r["cov"] else None),
                               # the observations, so a changed rule re-scores this run for $0
                               "coverage_report": (r["cov"].get("raw_report")
                                                   if r["cov"] else None),
                               "context_chars": r["ctx"],
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
        print(f"  Correctness : {corr}/{n} = {corr/n:.0%}   <- the historical metric, "
              f"comparable with every number in the tracker")
        print(f"  Groundedness: {grnd}/{n} = {grnd/n:.0%}   <- likewise")

        if results[0]["sc"] is not None:
            scop = sum(r["sc"]["score"] for r in results)
            andd = sum(min(r["g"]["score"], r["sc"]["score"]) for r in results)
            print(f"\n  NEW SCOREBOARDS (Phase 4.5) - reported beside the two above, never "
                  f"averaged with them:")
            if results[0]["rub"] is not None:
                rubr = sum(r["rub"]["score"] for r in results)
                print(f"  Correctness (rubric)     : {rubr}/{n} = {rubr/n:.0%}"
                      f"   (parked metric, --rubric)")
            print(f"  Groundedness (scope only): {scop}/{n} = {scop/n:.0%}")
            print(f"  Groundedness (binary AND scope): {andd}/{n} = {andd/n:.0%}"
                  f"   <- the strict one")

        # --- SET COVERAGE (Phase 6.10b) -------------------------------------------------
        # Printed apart from the block above and never folded into it. The denominator is
        # only the questions that RANK over a set; an inapplicable item is excluded, not
        # counted as a pass, or this number would rise every time an easy single-company
        # question was added to a set.
        cov_rows = [r for r in results if r["cov"] and r["cov"]["applicable"]]
        cov_ran = [r for r in results if r["cov"]]
        if cov_ran and not cov_rows:
            # SAY SO. The judge was called on every question and billed for every question;
            # printing nothing because none of them turned out to rank over a set makes a paid
            # call invisible, which is how a cost stops being noticed. The first run of this
            # wiring did exactly that on the regression set.
            print(f"\n  SET COVERAGE (Phase 6.10b): not applicable to any of these {n} "
                  f"questions - none rank or aggregate over a set.")
            print(f"    The judge still ran on all {len(cov_ran)} to find that out; "
                  f"applicability is its first observation, not a guess made before calling.")
        if cov_rows:
            covn = len(cov_rows)
            covok = sum(r["cov"]["score"] for r in cov_rows)
            declined = sum(1 for r in cov_rows if r["cov"]["declined"])
            print(f"\n  SET COVERAGE (Phase 6.10b) - a THIRD axis, not part of any AND:")
            print(f"  Coverage: {covok}/{covn} = {covok/covn:.0%}  of the {covn} questions "
                  f"that rank or aggregate over a set ({n - covn} do not and are excluded)")
            print(f"    declined to rank rather than guess: {declined}   <- the honest "
                  f"output, and it scores 1")

            flagged = [r for r in cov_rows if r["cov"]["score"] == 0]
            novel = [r for r in flagged
                     if r["c"]["score"] == 1
                     and (r["sc"] is None or min(r["g"]["score"], r["sc"]["score"]) == 1)]
            print(f"    flagged: {len(flagged)}, of which {len(novel)} pass correctness AND "
                  f"groundedness   <- what no other scoreboard here can see")
            # The flagged items ARE the output. This axis exists because three answers passed
            # three scoreboards unread; printing a percentage and no rows would repeat that.
            for r in flagged:
                cv = r["cov"]
                tag = "" if r["c"]["score"] == 0 else "   (correct + grounded)"
                why = (f"missing {cv['missing']}" if cv["missing"]
                       else "then excluded a member on a gap that is not real")
                print(f"    {r['ex']['id']:5} ranked over {len(cv['required'])}, {why}{tag}")
                if cv.get("exclusion_evidence"):
                    for line in cv["exclusion_evidence"]:
                        print(f"          excluded on a gap that is not real: {line[:96]}")
            if not flagged:
                print(f"    nothing flagged - every ranking accounted for its whole set")

            # The disagreements ARE the measurement. Two judges that always agree tell you
            # nothing; the rows where they part company are where the truth is contested,
            # and every one of them needs reading by hand.
            cdis = ([r for r in results if r["rub"]["score"] != r["c"]["score"]]
                    if results[0]["rub"] is not None else [])
            gdis = [r for r in results if r["sc"]["score"] != r["g"]["score"]]
            print(f"\n  correctness disagreements (binary vs rubric): {len(cdis)}")
            for r in cdis:
                print(f"    {r['ex']['id']:5} binary={r['c']['score']} rubric={r['rub']['score']}"
                      f"  facts {r['rub']['facts_ok']}/{r['rub']['facts_total']}"
                      f"  {str(r['rub']['reasoning'])[:90]}")
            print(f"  groundedness disagreements (binary vs scope): {len(gdis)}")
            for r in gdis:
                print(f"    {r['ex']['id']:5} binary={r['g']['score']} scope={r['sc']['score']}"
                      f"  {str(r['sc']['reasoning'])[:110]}")

            # The number this run exists to produce. Every one of these is an answer the old
            # scoreboard called grounded and the strict one does not - either a scope error
            # the eval has been blind to, or a false negative the AND has just introduced.
            # There is no way to tell which from the counts, so they are listed for reading.
            newly = [r for r in results if r["g"]["score"] == 1 and r["sc"]["score"] == 0]
            print(f"\n  answers the AND newly marks ungrounded: {len(newly)}/{grnd}"
                  f" = {len(newly)/max(grnd,1):.0%} of previously-grounded answers")
            print("  Each one is EITHER a scope error the eval could not see before, OR a")
            print("  false negative the AND just introduced. The counts cannot tell them")
            print("  apart - these have to be read:")
            for r in newly:
                print(f"    {r['ex']['id']:5} {str(r['sc']['reasoning'])[:150]}")

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

    if args.which in ("regression", "both", "all"):
        run_set("REGRESSION - NVIDIA only", GOLDEN_SET)
    if args.which in ("capability", "both", "all"):
        run_set("CAPABILITY - cross-document", CROSS_SET, bucket_fn=bucket)
    if args.which in ("tesla", "all"):
        run_set("TESLA - the sixth filing", TESLA_SET, bucket_fn=tesla_bucket)
