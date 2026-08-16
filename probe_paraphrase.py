# probe_paraphrase.py
# Phase 4.5.2 - measure PHRASING SENSITIVITY, and test whether a rubric judge cures it.
#
# What n=3 already settled: the binary judge is deterministic. 40 answers, three runs each,
# zero flips. So "judge variance" was the wrong diagnosis, and the lesson written from it
# has to be corrected rather than quietly dropped.
#
# What is left is sharper. Two answers carrying IDENTICAL content in different words got
# opposite verdicts, reproducibly (r03, OLD config vs LIVE config). This probe turns that
# single observation into a measurement: hand-written paraphrase pairs, same facts, same
# omissions, different sentences. Any pair whose two halves score differently is phrasing
# sensitivity, and there is nowhere else for the difference to come from.
#
# The pairs are written by hand, not generated. A model-generated paraphrase can quietly
# add or drop a figure, and then a flip would mean nothing.
#
# Both judges see every variant, so the comparison is like-for-like on identical inputs.

import json
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

from judges import correctness_judge
from judges_rubric import rubric_judge
from golden_set import GOLDEN_SET
from cross_set import CROSS_SET

load_dotenv()

EX = {e["id"]: e for e in list(GOLDEN_SET) + list(CROSS_SET)}

# (id, variant name, answer text, what a fair judge should say)
# The r03 pair is the real one, both texts copied verbatim from probe_r03.py's output.
PAIRS = [
    ("r03", "OLD-wording",
     "For Intel, reported net income depends on whether non-controlling interests are "
     "included. Based on the Intel 10-K financial table for the fiscal year ended "
     "December 27, 2025, the net income (loss) attributable to non-controlling interests "
     "was $293 million.", 0),
    ("r03", "LIVE-wording",
     "Based on the provided filings, Intel is the company for which reported net income "
     "depends on the attribution of net income or loss to non-controlling interests.\n\n"
     "According to the Intel 10-K financial table, the net income (loss) attributable to "
     "non-controlling interests for the fiscal year ended December 27, 2025, was "
     "$293 million.", 0),

    # Same facts, three tones. A judge grading content cannot tell these apart.
    ("q01", "plain",
     "NVIDIA's total revenue for fiscal year 2026 was $215,938 million.", 1),
    ("q01", "hedged",
     "Based on the provided filings, it appears that NVIDIA's total revenue for fiscal "
     "year 2026 was approximately $215,938 million, though the filing should be consulted "
     "directly for confirmation.", 1),
    ("q01", "terse",
     "$215,938 million.", 1),

    ("x06", "figures-first",
     "NVIDIA: $215,938 million (FY2026). AMD: $34,639 million (FY2025). NVIDIA is higher "
     "by $181,299 million.", 1),
    ("x06", "prose",
     "NVIDIA had the higher total revenue in its most recent fiscal year. It reported "
     "$215,938 million for fiscal 2026, while AMD reported $34,639 million for fiscal "
     "2025, a difference of $181,299 million in NVIDIA's favour.", 1),

    # Both incomplete in exactly the same way - the second figure is missing from each.
    ("qq2", "incomplete-terse",
     "NVIDIA's revenue for the nine months ended October 26, 2025 was $147,811 million.", 0),
    ("qq2", "incomplete-verbose",
     "According to NVIDIA's Form 10-Q for the third quarter of fiscal year 2026, the "
     "company reported revenue of $147,811 million for the nine-month period ended "
     "October 26, 2025. This figure is drawn directly from the Consolidated Statements of "
     "Income presented in that filing.", 0),

    # The r01 shape: right answer, plus a self-contradicting extra. One states the
    # contradiction plainly, the other buries it in a longer list.
    ("w01", "clean",
     "1. NVIDIA $215,938 million (FY2026)  2. Intel $52,853 million (FY2025)  "
     "3. AMD $34,639 million (FY2025).", 1),
    ("w01", "self-contradicting",
     "Ranked by total revenue: 1. Intel $52,853 million  2. NVIDIA $215,938 million  "
     "3. AMD $34,639 million. NVIDIA therefore reported the highest revenue.", 0),
]


def run(case):
    i, name, text, expected = case
    b = correctness_judge(question=EX[i]["question"], prediction=text,
                          reference=EX[i]["reference_answer"])
    r = rubric_judge(question=EX[i]["question"], prediction=text,
                     reference=EX[i]["reference_answer"])
    return i, name, expected, b["score"], r["score"], r


with ThreadPoolExecutor(max_workers=6) as pool:
    results = list(pool.map(run, PAIRS))

print("\n" + "=" * 88)
print(f"  {'id':5} {'variant':22} {'want':>4} {'binary':>7} {'rubric':>7}   rubric detail")
print("=" * 88)
for i, name, want, b, r, detail in results:
    flag_b = " " if b == want else "X"
    flag_r = " " if r == want else "X"
    print(f"  {i:5} {name:22} {want:>4} {b:>6}{flag_b} {r:>6}{flag_r}   "
          f"{detail['facts_ok']}/{detail['facts_total']} facts"
          + (", self-contradicting" if detail["contradicts"] else ""))
    # Print the extracted facts whenever the rubric is unhappy. Fact-granularity is the
    # rubric's own failure mode - q01 scored 0 at 1/2 facts because the reference restated
    # one value in two units - and it is invisible unless the list is shown.
    if r != want or detail["facts_ok"] < detail["facts_total"]:
        for f, present, correct in detail.get("facts", []):
            print(f"          [{'x' if not (present and correct) else ' '}] {f[:78]}")

print("\n  PAIR CONSISTENCY - two wordings of the same content must score the same:")
groups = {}
for i, name, want, b, r, _d in results:
    groups.setdefault(i, []).append((name, want, b, r))
bin_split = rub_split = 0
for i, variants in groups.items():
    if len(variants) < 2:
        continue
    # Only compare variants that SHOULD score the same.
    for target in (0, 1):
        same = [v for v in variants if v[1] == target]
        if len(same) < 2:
            continue
        bs, rs = {v[2] for v in same}, {v[3] for v in same}
        bin_split += len(bs) > 1
        rub_split += len(rs) > 1
        mark = ""
        if len(bs) > 1:
            mark += "  BINARY SPLIT"
        if len(rs) > 1:
            mark += "  RUBRIC SPLIT"
        print(f"    {i} (expected {target}): binary {sorted(bs)}  rubric {sorted(rs)}{mark}")

agree_b = sum(1 for _i, _n, w, b, _r, _d in results if b == w)
agree_r = sum(1 for _i, _n, w, _b, r, _d in results if r == w)
n = len(results)
print(f"\n  matches the intended verdict:  binary {agree_b}/{n}   rubric {agree_r}/{n}")
print(f"  groups that SPLIT on wording:  binary {bin_split}      rubric {rub_split}")
print("\n  A split means one judge gave two different verdicts to two answers carrying the")
print("  same content. That is the defect under test; the totals above are secondary.")
