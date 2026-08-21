"""
probe_arith_repair.py - if the model is shown its OWN arithmetic contradiction, does it fix it?

WHY THIS RUNS BEFORE ANYTHING IS BUILT. probe_arith.py can now DETECT that `d08` lists four
revenues and states a combined figure 400 short of their sum. Detection is not a fix. The
proposed fix is Reflect's shape - a free check gates one expensive call - and Reflect earned
that shape by being measured, not by sounding right. If the model cannot repair its own
answer when handed the contradiction, the mechanism is dead here, for Rs 0.3, instead of
after it has been wired into agent.py and validated by a Rs 25 gate.

FOUR CASES, and two of them are CONTROLS because a repair that only ever fires on a broken
answer has not been tested for what it does to a good one.

  1. d08, NO CONTEXT      - the answer plus the contradiction, nothing else. If this works it
                            is nearly free: ~700 tokens against ~5,000 with the filings.
  2. d08, WITH CONTEXT    - the expensive version. Worth knowing whether it buys anything.
  3. x23 MUTATED          - a correct answer (combined net income 127,929) with its total
                            broken to 127,000. The detector must fire, and the repair must
                            restore 127,929. Unlike d08 we KNOW the right answer here, so this
                            is the only case that can prove the repair lands on correct rather
                            than merely on different.
  4. 🔴 x23 CORRECT + A FALSE ALARM - a correct answer handed a contradiction that is NOT real.
                            The repair must leave it ALONE. If the model simply obeys whatever
                            the harness tells it, then the day the detector false-positives it
                            will corrupt a correct answer, and this whole mechanism becomes a
                            way to turn a reporting bug into a wrong number. This is the case
                            that can cancel the design.

WHAT CODE IS AND IS NOT ALLOWED TO ASSERT. Python adding four figures THE ANSWER ITSELF PRINTED
is arithmetic, not a claim about any filing, so the prompt may state that sum. What it must not
do is tell the model which of the two numbers is wrong: the listed figures could be the error
and the total right. The prompt says both, says they disagree, and leaves the judgement where
it belongs.

COST: 4 generation calls, two of them over a full context. About $0.004 - call it Rs 0.35.
No agent run, no retrieval: every answer and context is replayed from the stored gate.
"""

import io
import json
import os
import re
import sys

GATE = "eval_610_gate.jsonl"

REPAIR_PROMPT = """A previous answer to the QUESTION below contains an arithmetic
inconsistency, found by adding up the figures the answer itself printed.

{finding}

One of those two numbers is wrong - either a figure in the list, or the total. Decide which,
and rewrite the answer correctly. Do not change anything the inconsistency does not touch: keep
the same structure, the same wording and the same figures everywhere they were already right.

If, on checking, you find the answer was actually consistent and the report above is mistaken,
say so and return the answer completely unchanged. Do not invent a correction to satisfy the
report.
{context_block}
QUESTION: {question}

THE ANSWER TO CHECK:
{answer}

Return only the corrected answer."""

CONTEXT_BLOCK = """
CONTEXT (the filings the answer was written from):
{context}
"""


def finding_text(total_stated, figures, total_computed):
    return (f"The answer lists these figures: "
            f"{', '.join(f'{v:,.0f}' for v in figures)}.\n"
            f"Added together they come to {total_computed:,.0f}.\n"
            f"The answer states a total of {total_stated:,.0f}.\n"
            f"The difference is {total_computed - total_stated:,.0f}.")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)

    gate_path = os.path.join(here, GATE)
    if not os.path.exists(gate_path):
        raise SystemExit(f"  {GATE} not found - this replays a run already paid for.")
    rows = {json.loads(l)["id"]: json.loads(l)
            for l in io.open(gate_path, encoding="utf-8") if l.strip()}

    import judges
    import probe_arith
    import rag
    import telemetry
    telemetry.install(judges, rag)
    # rag holds its own binding of log_cost; without this the run prints per-call costs above
    # a total of $0.000000. Lesson 125, sprung once already on the person who wrote it.
    assert not telemetry.unpatched(rag), "cost capture never reached rag"

    llm = getattr(rag.llm, "bound", rag.llm)

    # --- case material ------------------------------------------------------------------
    d08 = rows["d08"]
    x23 = rows["x23"]
    x23_broken = x23["answer"].replace("$127,929", "$127,000", 1)
    assert x23_broken != x23["answer"], "x23's stored answer no longer states 127,929"

    def detect(answer):
        """What probe_arith would report for this answer, or None."""
        for claim, total, pool, poolsum, ok in probe_arith.tier2(answer):
            if not ok:
                return finding_text(total, pool, poolsum)
        return None

    d08_finding = detect(d08["answer"])
    x23_finding = detect(x23_broken)
    assert d08_finding, "the detector no longer fires on d08 - the case is stale"
    assert x23_finding, "the detector did not fire on the mutated x23 - the mutation is stale"
    assert detect(x23["answer"]) is None, \
        "the detector fires on UNMUTATED x23, which would make case 4 meaningless"

    FALSE_ALARM = finding_text(127929, [4335.0, -267.0, 120067.0, 3794.0], 128329.0)

    cases = [
        ("1. d08, NO context", d08, d08["answer"], d08_finding, False, "398,257"),
        ("2. d08, WITH context", d08, d08["answer"], d08_finding, True, "398,257"),
        ("3. x23 broken to 127,000, WITH context", x23, x23_broken, x23_finding, True, "127,929"),
        ("4. 🔴 x23 CORRECT + a FALSE alarm", x23, x23["answer"], FALSE_ALARM, True, "127,929"),
    ]

    print(f"\n  4 repair attempts on stored answers. No agent run, no retrieval.\n")
    spent = 0.0
    results = []
    for name, row, answer, finding, with_ctx, want in cases:
        ctx_block = (CONTEXT_BLOCK.format(context=row["context"]) if with_ctx else "\n")
        prompt = REPAIR_PROMPT.format(finding=finding, context_block=ctx_block,
                                      question=_question_for(row["id"]), answer=answer)
        with telemetry.capture() as calls:
            resp = llm.invoke(prompt)
            judges.log_cost("gemini-3.1-flash-lite", resp, label="arith-repair")
        spent += telemetry.usd(calls)
        out = judges.to_text(resp.content)

        # Did it land on the right number, and did it leave everything else alone?
        want_n = float(want.replace(",", ""))
        hit = any(abs(v - want_n) < 0.5 for v in probe_arith.all_numbers(out))
        still_flags = detect(out) is not None
        results.append((name, want, hit, still_flags, out))

    print(f"{'=' * 104}")
    print(f"  {'case':44} {'wanted':>10} {'found':>6} {'still flags':>12}")
    print(f"  {'-' * 44} {'-' * 10} {'-' * 6} {'-' * 12}")
    for name, want, hit, still_flags, _out in results:
        print(f"  {name:44} {want:>10} {('yes' if hit else 'NO'):>6} "
              f"{('YES' if still_flags else 'no'):>12}")

    print(f"\n{'=' * 104}")
    for name, want, hit, still_flags, out in results:
        print(f"\n  ---- {name} ----")
        print("  " + "\n  ".join(out.strip().splitlines()[:14]))

    print(f"\n{'=' * 104}")
    print(f"  spent: ${spent:.5f}  (~Rs {spent * 88:.2f})")
    ok13 = all(r[2] and not r[3] for r in results[:3])
    case4 = results[3]
    print(f"\n  cases 1-3 (must repair)          : {'ALL PASS' if ok13 else 'NOT ALL PASS'}")
    print(f"  case 4 (must NOT be damaged)     : "
          f"{'held - the correct figure survived' if case4[2] else '🔴 DAMAGED'}")
    if ok13 and case4[2]:
        print("\n  The mechanism works on stored answers. Next: wire it behind the free check in")
        print("  agent.py, the way Reflect is wired, and measure what it costs on a real gate.")
        print("  Compare cases 1 and 2 before deciding whether the context is worth paying for.")
    else:
        print("\n  🔴 Read the outputs above before building anything. A repair that lands on a")
        print("     different-but-still-wrong number, or that edits a correct answer to satisfy")
        print("     a false report, is worse than the defect it was meant to fix.")
    print(f"{'=' * 104}")


def _question_for(qid):
    from cross_set import CROSS_SET
    from golden_set import GOLDEN_SET
    from tesla_set import TESLA_SET
    for s in (GOLDEN_SET, CROSS_SET, TESLA_SET):
        for item in s:
            if item["id"] == qid:
                return item["question"]
    raise SystemExit(f"  no question with id {qid}")


if __name__ == "__main__":
    main()
