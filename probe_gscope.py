# probe_gscope.py
# Phase 4.5.5 - the groundedness judge has one measured false positive. Find out WHY before
# trying to fix it.
#
# WHAT WAS MEASURED (judge_groundedness.py, 16 calls):
#   controls 4/4, unsupported_add 3/3, number_invent 3/3, entity_swap 2/2,
#   structural_explicit 1/1 ... and phrasing_blunt 0/1, phrasing_hedged 0/1.
#   FALSE POSITIVE RATE 18%, and BOTH failures are the same claim on the same question.
#
# The claim was appended to w02's answer:
#     "Intel therefore holds the largest asset base in the global chip industry."
# The context holds three companies. It cannot support a statement about an industry. The
# judge said grounded=1 twice, and its reasoning gives the game away:
#     "All figures for total assets and net revenue for the three companies are correctly
#      extracted from the provided financial statements"
# It audited the NUMBERS and never looked at the sentence. That is a scope error: every
# figure is traceable, and the CLAIM still is not.
#
# Two explanations fit, and they lead to opposite fixes:
#
#   H1 CONTEXT LENGTH. w02 has the longest context of the eight (31,681 chars / 11,538
#      tokens); the three claims the judge DID catch sat on contexts of 11k-17k chars. If
#      long contexts degrade it, the fix is to the eval - and it is uncomfortable, because
#      PER_JOB_FLOOR=4 exists to make contexts LONGER, and it was justified by a
#      groundedness point. A metric degraded by the change it is used to justify is not a
#      metric.
#
#   H2 QUANTIFIER STRENGTH. The claim the judge caught on x28 says "among ALL publicly
#      traded semiconductor companies WORLDWIDE". The one it missed says "in the global chip
#      industry" - the same leap, stated softly. If a blunt quantifier is what trips it, the
#      fix is to the judge prompt, and every soft over-generalisation in production is
#      currently invisible.
#
# The 2x2 separates them, because each hypothesis predicts a different pattern:
#      H1 true  -> both LONG cells missed, both SHORT cells caught  (row effect)
#      H2 true  -> both SOFT cells missed, both HARD cells caught   (column effect)
#      neither  -> one cell, and the story is more specific than either hypothesis
#
# Then a length ladder, only meaningful if H1 survives: the SAME caught claim re-judged
# against its own context padded with real text from other filings. Padding only adds; the
# support for every real figure stays exactly where it was, so length (and the dilution that
# comes with it) is the only thing that moves. Each rung carries the UNMUTATED answer too -
# if the control also collapses, long contexts make the judge say 0 to everything, which is a
# different defect and would invalidate the ladder.
#
# No agent, no retrieval. Stored answers and stored contexts only.

import json
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

from judges import groundedness_judge
from golden_set import GOLDEN_SET
from cross_set import CROSS_SET

load_dotenv()

EX = {e["id"]: e for e in list(GOLDEN_SET) + list(CROSS_SET)}
RUN = {}
for line in open("eval_45_ctx.jsonl", encoding="utf-8"):
    r = json.loads(line)
    if "error" not in r:
        RUN[r["id"]] = r

# --- the 2x2 -----------------------------------------------------------------
# Rows: which context the claim is judged against. SHORT is x28 (16,605 chars, the cell the
# judge already got right); LONG is w02 (31,681 chars, the cell it already got wrong).
# Columns: the same over-generalisation, stated with an explicit universal quantifier and
# stated softly. Each claim is written for its own answer's subject, because a claim about
# Intel appended to an answer about AMD would be off-topic rather than unsupported - and
# "off-topic" is a third thing the judge might be reacting to.
CELLS = [
    ("x28", "SHORT", "hard",
     " This makes AMD the smallest chipmaker by assets among all publicly traded "
     "semiconductor companies worldwide."),
    ("x28", "SHORT", "soft",
     " AMD therefore holds the smallest asset base in the global chip industry."),
    ("w02", "LONG", "hard",
     " Intel therefore holds the largest asset base among all publicly traded semiconductor "
     "companies worldwide."),
    ("w02", "LONG", "soft",
     " Intel therefore holds the largest asset base in the global chip industry."),
]

# --- the length ladder -------------------------------------------------------
# Padding comes from OTHER questions' contexts: real filing text, none of it capable of
# supporting a claim about every semiconductor company on earth.
PAD_SOURCES = ["x17", "r01", "d05", "r03", "x10"]
LADDER = [1.0, 1.5, 2.0, 2.6]
LADDER_ID = "x28"
LADDER_CLAIM = (" This makes AMD the smallest chipmaker by assets among all publicly traded "
                "semiconductor companies worldwide.")


def padded(base_id, factor):
    """base_id's context grown to roughly `factor` times its length, using real text."""
    ctx = RUN[base_id]["context"]
    target = int(len(ctx) * factor)
    out = ctx
    i = 0
    while len(out) < target:
        src = RUN[PAD_SOURCES[i % len(PAD_SOURCES)]]["context"]
        out += "\n\n" + src[:max(0, target - len(out))]
        i += 1
        if i > 40:                       # cannot reach the target; stop rather than spin
            break
    return out


def judge(case):
    tag, qid, prediction, context, expected = case
    v = groundedness_judge(question=EX[qid]["question"], prediction=prediction,
                           context=context)
    return tag, expected, v["score"], v.get("reasoning", ""), len(context)


if __name__ == "__main__":
    cases = []
    for qid, row, col, claim in CELLS:
        cases.append((f"{row}/{col}", qid, RUN[qid]["answer"].rstrip() + claim,
                      RUN[qid]["context"], 0))
    for f in LADDER:
        ctx = padded(LADDER_ID, f)
        cases.append((f"ladder {f:.1f}x mutated", LADDER_ID,
                      RUN[LADDER_ID]["answer"].rstrip() + LADDER_CLAIM, ctx, 0))
        cases.append((f"ladder {f:.1f}x control", LADDER_ID,
                      RUN[LADDER_ID]["answer"], ctx, 1))

    print(f"\n{'=' * 88}\nGROUNDEDNESS SCOPE - {len(cases)} judge calls, no agent\n{'=' * 88}")
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(judge, cases))

    grid = {}
    print(f"\n  {'cell':24} {'ctx chars':>9} {'want':>4} {'got':>4}  verdict")
    for tag, want, got, why, n in results:
        ok = got == want
        grid[tag] = got
        print(f"  {tag:24} {n:>9,} {want:>4} {got:>4}  {'ok' if ok else 'MISSED'}")
        if not ok:
            print(f"        said: {str(why)[:150]}")

    print("\n  THE 2x2 - 0 means the judge caught the unsupported claim, 1 means it did not:")
    print(f"    {'':8}{'hard':>8}{'soft':>8}")
    for row in ("SHORT", "LONG"):
        print(f"    {row:8}{grid.get(f'{row}/hard', '?'):>8}"
              f"{grid.get(f'{row}/soft', '?'):>8}")

    short = [grid.get("SHORT/hard"), grid.get("SHORT/soft")]
    long_ = [grid.get("LONG/hard"), grid.get("LONG/soft")]
    hard = [grid.get("SHORT/hard"), grid.get("LONG/hard")]
    soft = [grid.get("SHORT/soft"), grid.get("LONG/soft")]
    print()
    if short == [0, 0] and long_ == [1, 1]:
        print("    ROW effect: context LENGTH drives it. H1. The fix is in the eval, and the")
        print("    depth decision that was justified by a groundedness point needs revisiting.")
    elif hard == [0, 0] and soft == [1, 1]:
        print("    COLUMN effect: QUANTIFIER strength drives it. H2. The fix is the judge")
        print("    prompt, and every softly-worded over-generalisation is invisible today.")
    else:
        print("    Neither clean row nor clean column. Both hypotheses are too simple; read")
        print("    the four reasonings above before proposing a third.")

    print("\n  LENGTH LADDER (only meaningful if the 2x2 pointed at length):")
    for f in LADDER:
        m, c = grid.get(f"ladder {f:.1f}x mutated"), grid.get(f"ladder {f:.1f}x control")
        note = ""
        if m == 1 and c == 1:
            note = "   <- claim now invisible, control still fine: length alone did this"
        elif c == 0:
            note = "   <- control collapsed too; the judge is failing wholesale, not on scope"
        print(f"    {f:.1f}x   mutated={m}  control={c}{note}")
