"""
probe_scope_variance.py - the scope judge scored the SAME sentence 1 and then 0. Which was it?

WHAT HAPPENED. The d08 arithmetic rule shipped, and on the six-question check `d03`'s scope
verdict went 1 -> 0 while its correctness stayed 1. The reason string names the answer's opening
methodology sentence:

    'To calculate the net profit margin, we divide the net income' ranges over
    'the methodology for calculating net prof' - CONTEXT DOES NOT COVER THAT SET

**That sentence is byte-identical in both answers.** The diff between them is entirely cosmetic:
`($4,335 / $34,639) ≈ **12.51%**` became `4,335 / 34,639 = 12.51%`. No figure moved, no claim was
added, and the flagged sentence was not touched.

So one of two things is true, and they call for opposite responses:

  (a) VARIANCE - the scope judge is not deterministic on this item, and the 1 in the 6.10 gate
      and the 0 here are two samples of an unstable verdict. Then the arithmetic rule caused
      nothing, and what needs recording is that a judge this project has trusted since Phase 4.5
      flips. Every scope number in the tracker is n=1.

  (b) FORMATTING SENSITIVITY - the judge reads the same claim differently depending on the
      formatting AROUND it. That is the phrasing-sensitivity defect Phase 4.5 measured and
      documented for the CORRECTNESS judge, appearing in the scope judge, where nobody has
      looked for it. Then the arithmetic rule did cause this, indirectly, and the gate would
      carry the effect.

Either way it is not "the arithmetic rule made the answer worse" - the answer's claims are
unchanged. The tracker's rule applies: **a quality change that appears the same day a guard
ships is not proof the guard caused it.** Phase 5 wrote that after spending a day on the wrong
suspect.

HOW IT IS TOLD APART. Replay the scope judge n=3 on the OLD answer and n=3 on the NEW one, each
with the context it was actually produced from. If the OLD answer also flips, it is (a). If the
old holds at 1 and the new holds at 0, it is (b). A control (`d04`, unchanged verdict) runs
twice alongside, because a probe that only looks at the item that moved cannot tell a flipping
judge from a flipping item.

COST: 8 scope calls over ~8k-char contexts. About $0.012 - call it Rs 1.1. No agent run, no
retrieval, no generation: both answers already exist on disk.
"""

import io
import json
import os
import sys
from collections import Counter

N = 3


def load(path):
    here = os.path.dirname(os.path.abspath(__file__))
    full = os.path.join(here, path)
    if not os.path.exists(full):
        raise SystemExit(f"  {path} not found - this replays runs already paid for.")
    return {json.loads(l)["id"]: json.loads(l) for l in io.open(full, encoding="utf-8") if l.strip()}


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)

    old = load("eval_610_gate.jsonl")          # the answer that scored scope=1
    new = load("eval_arith_check.jsonl")       # the answer that scored scope=0

    from cross_set import CROSS_SET
    questions = {i["id"]: i["question"] for i in CROSS_SET}

    import judges
    import judges_scope
    import telemetry
    telemetry.install(judges, judges_scope)
    assert not telemetry.unpatched(judges_scope), "cost capture never reached judges_scope"

    # d03 is the item that moved. d04 is the CONTROL: same run, same prompt change, verdict
    # unchanged. If d04 also flips, the judge is unstable generally and d03 was never evidence
    # of anything.
    plan = [("d03 OLD  (scored 1 in the 6.10 gate)", old["d03"], N),
            ("d03 NEW  (scored 0 after the rule)",   new["d03"], N),
            ("d04 OLD  control",                     old["d04"], 1),
            ("d04 NEW  control",                     new["d04"], 1)]

    # State the strength of each comparison rather than letting the reader assume it. d03's
    # two runs retrieved the SAME context byte for byte, so the only thing that differs between
    # the two judged inputs is the cosmetic formatting - which makes it a clean experiment.
    # d04's do NOT: Reflect ran a second round on the new one and added chunks, so d04 is a
    # weak control and cannot settle anything on its own. Saying so here is cheaper than
    # someone later reading a 4-row table as four equal experiments.
    print(f"\n  scope judge replayed on stored answers - no agent, no retrieval")
    for label, row, _n in plan:
        other = (new if "NEW" in label else old)[row["id"]]
        same_ctx = old[row["id"]]["context"] == new[row["id"]]["context"]
        print(f"    {label:40} context identical across the two runs: {same_ctx}")
    print()
    rows, spent = [], 0.0
    for label, row, n in plan:
        scores, whys = [], []
        with telemetry.capture() as calls:
            for _ in range(n):
                v = judges_scope.scope_judge(question=questions[row["id"]],
                                             prediction=row["answer"],
                                             context=row["context"])
                scores.append(v["score"])
                whys.append(v["reasoning"][:110])
        spent += telemetry.usd(calls)
        rows.append((label, scores, whys))

    print(f"{'=' * 100}")
    print(f"  {'case':40} {'n':>3}  scores        distinct")
    print(f"  {'-' * 40} {'-' * 3}  {'-' * 12}  --------")
    for label, scores, _ in rows:
        c = Counter(scores)
        print(f"  {label:40} {len(scores):>3}  {str(scores):12}  {len(c)}")

    print(f"\n{'=' * 100}")
    for label, scores, whys in rows:
        print(f"\n  {label}")
        for i, (s, w) in enumerate(zip(scores, whys), 1):
            print(f"    [{i}] score={s}  {w}")

    d03_old = rows[0][1]
    d03_new = rows[1][1]
    old_stable = len(set(d03_old)) == 1
    new_stable = len(set(d03_new)) == 1

    print(f"\n{'=' * 100}")
    print(f"  spent: ${spent:.4f}  (~Rs {spent * 88:.2f})")
    print()
    if not old_stable or not new_stable:
        print("  🔴 (a) THE JUDGE FLIPS. The scope verdict is not stable on this item, so the")
        print("     1 in the 6.10 gate and the 0 after the rule are two samples of one unstable")
        print("     number - the arithmetic rule is exonerated, and something larger is owed:")
        print("     EVERY scope figure in PROJECT_TRACKER.md is n=1, including the 54/54 that")
        print("     licensed the AND in Phase 4.5.")
    elif set(d03_old) == {1} and set(d03_new) == {0}:
        print("  🔴 (b) FORMATTING SENSITIVITY. Both verdicts are stable and they disagree, on")
        print("     answers whose CLAIMS are identical and whose formatting is not. The scope")
        print("     judge reads the same sentence differently depending on the markup around")
        print("     it - the phrasing-sensitivity defect Phase 4.5 found in the CORRECTNESS")
        print("     judge, in the one place nobody looked for it. The arithmetic rule did cause")
        print("     this, by changing formatting, and the gate will carry the effect.")
    else:
        print("  Both stable and in agreement - the single 0 was not reproducible at all, which")
        print("  is its own finding and needs reading before anything is concluded.")
    print(f"{'=' * 100}")
    print("  Whatever this says, it does NOT say the arithmetic rule made the answer worse:")
    print("  d03's figures, ratios and conclusion are byte-identical across the two answers.")


if __name__ == "__main__":
    main()
