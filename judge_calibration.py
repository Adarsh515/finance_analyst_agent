# judge_calibration.py
# Phase 4.5.1 - measure the judge instead of trusting it.
#
# Part A: agreement with human labels on 40 real answers (judge_labels.py). Free - the
#         answers were already paid for in eval_44_gate2.jsonl, nothing is re-run.
#
# Part B: MUTATION TESTING, and this is the part that matters.
#
# Part A alone cannot calibrate anything, and the reason is worth stating plainly. The
# system scores 98%, so a sample of its answers is 39 positives to 1 negative. On a set that
# lopsided, "100% agreement" is what you get from a judge that always says 1, and Cohen's
# kappa - which corrects for exactly this - becomes unstable or undefined. You cannot
# calibrate a judge on a set where the system almost never fails.
#
# So manufacture the negatives. Take answers the judge scored 1, corrupt ONE thing in a
# defined way, and re-judge. The ground truth is certain because we made the change:
#
#   digit_swap    215,938 -> 215,398          a real figure, two digits transposed
#   magnitude     $10,605 million -> billion  right number, wrong scale
#   company_swap  AMD's -> Intel's            right figure, wrong company
#   period_swap   fiscal 2026 -> fiscal 2025  right figure, wrong year
#   sign_flip     operating loss -> income    the sign IS the finding
#   drop_half     delete the second required figure from a two-part answer
#
# Every one of these MUST score 0. A judge that scores them 1 is not strict, it is blind,
# and the false-positive rate below is the number that says how blind. This is the same
# idea as mutation testing for unit tests: a test suite that passes on deliberately broken
# code is not testing anything.
#
# Cost: one correctness-judge call per mutation. No agent, no retrieval, no generation.
#
# Groundedness is NOT mutation-tested here: re-judging groundedness needs the exact context
# the answer was written from, and eval_44_gate2.jsonl predates run_eval.py storing it.
# The harness now persists context, so the next gate run unlocks this for free.

import argparse
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

from judges import correctness_judge
from judge_labels import LABELS
from golden_set import GOLDEN_SET
from cross_set import CROSS_SET

load_dotenv()

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--jsonl", default="eval_44_gate2.jsonl",
                    help="a completed run to draw stored answers from")
parser.add_argument("--workers", type=int, default=6)
parser.add_argument("--skip-mutations", action="store_true",
                    help="Part A only - completely free, no API calls at all")
parser.add_argument("--repeat", type=int, default=0,
                    help="Part C: judge each labelled answer this many times and count flips")
args = parser.parse_args()

EX = {e["id"]: e for e in list(GOLDEN_SET) + list(CROSS_SET)}
RUN = {}
for line in open(args.jsonl, encoding="utf-8"):
    r = json.loads(line)
    if "error" not in r:
        RUN[r["id"]] = r


# --- Part A: agreement with human labels -------------------------------------

def kappa(pairs):
    """Cohen's kappa. Returns None when it is not meaningful.

    kappa = (observed agreement - chance agreement) / (1 - chance agreement). When one
    class dominates, chance agreement approaches 1 and the denominator collapses, so a tiny
    change in one item swings kappa wildly. Reporting a number in that regime is worse than
    reporting nothing, so this returns None and says why.
    """
    n = len(pairs)
    if not n:
        return None, "no items"
    po = sum(1 for a, b in pairs if a == b) / n
    a1 = sum(a for a, _b in pairs) / n
    b1 = sum(b for _a, b in pairs) / n
    pe = a1 * b1 + (1 - a1) * (1 - b1)
    if pe > 0.90:
        return None, (f"not meaningful: chance agreement is already {pe:.1%} because "
                      f"{max(a1, 1 - a1):.0%} of items share one label")
    if abs(1 - pe) < 1e-9:
        return None, "undefined: one label everywhere"
    return (po - pe) / (1 - pe), ""


print("=" * 78)
print("PART A - judge vs human labels on real answers")
print("=" * 78)
for metric in ("correct", "grounded"):
    idx = 0 if metric == "correct" else 1
    pairs = [(LABELS[i][idx], RUN[i][metric]) for i in LABELS if i in RUN]
    agree = sum(1 for a, b in pairs if a == b)
    k, why = kappa(pairs)
    print(f"\n  {metric}: agreement {agree}/{len(pairs)} = {agree / len(pairs):.1%}")
    print(f"    human label distribution: {dict(Counter(a for a, _b in pairs))}")
    print(f"    Cohen's kappa: {f'{k:.3f}' if k is not None else 'NOT REPORTED - ' + why}")
    for i in LABELS:
        if i in RUN and LABELS[i][idx] != RUN[i][metric]:
            print(f"    DISAGREE {i}: judge={RUN[i][metric]} human={LABELS[i][idx]}")
            print(f"             {LABELS[i][3][:200]}")

border = [i for i in LABELS if LABELS[i][2]]
print(f"\n  borderline items flagged by the labeller: {border}")


# --- Part B: mutation testing -------------------------------------------------
# (id, kind, find, replace). Every mutation must score 0. `find` is asserted to exist:
# a mutation that silently fails to apply would be scored as a judge success, which is
# precisely the kind of silent pass this project keeps finding.

MUTATIONS = [
    ("q01", "digit_swap",   "215,938", "215,398"),
    ("q01", "magnitude",    "$215,938 million", "$215,938 billion"),
    ("q01", "period_swap",  "fiscal year 2026", "fiscal year 2024"),
    ("x02", "company_swap", "AMD's net income", "Intel's net income"),
    ("x02", "digit_swap",   "4,335", "4,353"),
    ("q05", "digit_swap",   "4.93", "4.39"),
    ("q09", "digit_swap",   "10,605", "16,050"),
    ("q09", "magnitude",    "$10,605 million", "$10,605 billion"),
    ("q33", "digit_swap",   "9,812", "9,182"),
    ("d06", "digit_swap",   "85.55", "58.55"),
    ("d07", "digit_swap",   "90,307", "90,703"),
    ("qq1", "digit_swap",   "57,006", "57,600"),
    ("x23", "digit_swap",   "124,135", "124,153"),
    ("x14", "period_swap",  "December 27, 2025", "December 27, 2024"),
    ("r02", "sign_flip",    "Operating loss", "Operating income"),
    ("x27", "company_swap", "Intel had the lowest gross margin", "AMD had the lowest gross margin"),
]

# drop_half: cut everything from a marker onwards, leaving a half-answered two-part question.
# This is the r03 failure shape, reproduced deliberately so the judge can be tested on it.
TRUNCATIONS = [
    ("qq2", "drop_half", "NVIDIA's total revenue for the full fiscal year"),
    ("d08", "drop_half", "**AMD's Share:**"),
    ("d03", "drop_half", "**Gap Calculation:**"),
]

# Controls: unchanged answers the judge already scored 1. If a control comes back 0 the
# harness itself is broken and every mutation result below it is meaningless.
CONTROLS = ["q01", "x02", "d06", "qq2"]


def build_cases():
    cases = []
    for i in CONTROLS:
        cases.append((i, "control", RUN[i]["answer"], 1))
    for i, kind, find, repl in MUTATIONS:
        ans = RUN[i]["answer"]
        assert find in ans, f"mutation {i}/{kind}: {find!r} not in the stored answer"
        cases.append((i, kind, ans.replace(find, repl), 0))
    for i, kind, marker in TRUNCATIONS:
        ans = RUN[i]["answer"]
        assert marker in ans, f"truncation {i}: {marker!r} not in the stored answer"
        cases.append((i, kind, ans[:ans.index(marker)].rstrip(), 0))
    return cases


def judge_one(case):
    i, kind, prediction, expected = case
    v = correctness_judge(question=EX[i]["question"], prediction=prediction,
                          reference=EX[i]["reference_answer"])
    return i, kind, expected, v["score"], v.get("reasoning", "")


if not args.skip_mutations:
    cases = build_cases()
    print("\n" + "=" * 78)
    print(f"PART B - mutation testing   ({len(cases)} judge calls, no agent)")
    print("=" * 78)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(judge_one, cases))

    by_kind = {}
    print(f"\n  {'id':5} {'mutation':13} {'want':>4} {'got':>4}  verdict")
    for i, kind, expected, got, why in results:
        ok = got == expected
        by_kind.setdefault(kind, [0, 0])
        by_kind[kind][1] += 1
        by_kind[kind][0] += ok
        print(f"  {i:5} {kind:13} {expected:>4} {got:>4}  {'ok' if ok else 'JUDGE MISSED IT'}")
        if not ok:
            print(f"        judge said: {str(why)[:170]}")

    print(f"\n  by mutation type:")
    for kind, (ok, tot) in sorted(by_kind.items()):
        print(f"    {kind:13} {ok}/{tot}")

    muts = [r for r in results if r[1] != "control"]
    caught = sum(1 for _i, _k, e, g, _w in muts if g == e)
    ctrl = [r for r in results if r[1] == "control"]
    ctrl_ok = sum(1 for _i, _k, e, g, _w in ctrl if g == e)
    print(f"\n  controls passed      {ctrl_ok}/{len(ctrl)}"
          + ("" if ctrl_ok == len(ctrl) else "   <-- HARNESS BROKEN, ignore everything above"))
    print(f"  mutations caught     {caught}/{len(muts)} = {caught / len(muts):.0%}")
    print(f"  FALSE POSITIVE RATE  {(len(muts) - caught) / len(muts):.0%}"
          f"   (deliberately wrong answers the judge scored correct)")


# --- Part C: judge variance ---------------------------------------------------
# Phase 4.4 caught two near-identical r03 answers scoring 1/1 and 0/0. That was n=1 twice,
# on two DIFFERENT answers, so it was suggestive and not conclusive. This is the clean test:
# the SAME stored answer, judged N times, nothing else changed. Any flip is variance in the
# judge itself, and there is nowhere else for it to come from.
#
# This matters more than it looks. A judge that flips on 5% of items puts +/-5% of noise on
# every score in the tracker, and Phase 4.4's whole 3-vs-4-slots decision turned on ONE
# groundedness point.

if args.repeat > 1:
    print("\n" + "=" * 78)
    print(f"PART C - judge variance   (same answer, n={args.repeat}, "
          f"{len(LABELS) * args.repeat} judge calls)")
    print("=" * 78)

    def repeat_one(i):
        scores = []
        for _ in range(args.repeat):
            v = correctness_judge(question=EX[i]["question"], prediction=RUN[i]["answer"],
                                  reference=EX[i]["reference_answer"])
            scores.append(v["score"])
        return i, scores

    ids = [i for i in LABELS if i in RUN]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        var = list(pool.map(repeat_one, ids))

    flips = [(i, s) for i, s in var if len(set(s)) > 1]
    print(f"\n  items judged {len(var)}   UNSTABLE {len(flips)}   "
          f"stable {len(var) - len(flips)} = {(len(var) - len(flips)) / len(var):.1%}")
    for i, s in flips:
        print(f"    FLIPPED {i}: {s}   human label={LABELS[i][0]}   "
              f"borderline={LABELS[i][2]}")
    if not flips:
        print("    every item returned the same verdict every time - correctness judging is")
        print("    stable on THESE answers. That does not clear the groundedness judge, which")
        print("    needs stored context to re-run and is where both disagreements sit.")
