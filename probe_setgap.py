"""
probe_setgap.py - how BIG is the failure class `x27` exposed? Free, no model, no index.

WHAT `x27` DID, and why one item is not yet a reason to build a judge.

The question asks which company had the LOWEST gross margin. The answer listed AMD 50%,
Intel 34.8%, NVIDIA 71.1%, said Tesla's was "not stated as a single percentage" - having just
computed 16.2% for Tesla's automotive segment on the same line - and then concluded "Intel has
the lowest gross margin at 34.8%". When one member of the comparison went missing it SILENTLY
DROPPED THAT MEMBER and answered the superlative as though the set were complete.

Binary groundedness, scope groundedness and their AND all scored it grounded, because every
sentence is traceable to the context. Both judges ask "is this claim supported?"; neither asks
"was the set you compared over complete?"

THIS PROBE IS RUN BEFORE ANY JUDGE IS WRITTEN, and it is allowed to cancel the judge. The
Phase 4.2 calculator tool was cancelled by exactly this kind of measurement, and the rule
written down afterwards was: find out how much surface area a defect has before building
machinery for it. If this scan says the class is one item on one gate, the honest output is
"documented, not built".

WHAT IT MEASURES, in three widening circles:

  1. POPULATION AT RISK - questions whose reference answer requires ranking or selecting
     across a set. Only these can suffer the defect at all.
  2. ADMITTED GAPS - answers that both report a member's figure as unavailable AND still
     commit to a winner. This is `x27`'s exact shape.
  3. SILENT GAPS - answers that never mention a member of the set the question ranges over.
     Weaker evidence, more of it, and it needs reading.

WHAT IT CANNOT MEASURE, stated because the number below would otherwise be read as complete.
An answer that drops a member WITHOUT SAYING SO, using no phrase this file matches, is
invisible here. **Every count this prints is a LOWER BOUND.** It finds candidates; a human
reads them. A regex that claimed to find defects would be the third reporting defect of the
month.

Free: reads eval_610_gate.jsonl and the eval sets off disk. No API key, no index, no model.

    python probe_setgap.py                      # the default gate file
    python probe_setgap.py eval_68_gate.jsonl   # any stored run
"""

import io
import json
import os
import re
import sys

# Superlative / ranking language in the QUESTION. These are the questions whose reference
# answer cannot be produced without comparing every member of a set, so they are the only
# ones the defect can occur on.
_RANKING_Q = re.compile(
    r"\b(lowest|highest|largest|smallest|greatest|biggest|most|least|"
    r"whichever|which company|which of the|rank|ranked|ranking|top|"
    r"more than any|less than any|combined|all (?:of )?the companies)\b", re.I)

# The answer says a member's figure could not be obtained. `x27`'s exact tell.
_GAP_A = re.compile(
    r"\b(not stated|not disclosed|not provided|not reported|not available|"
    r"not explicitly|cannot be (?:determined|calculated|computed)|"
    r"no (?:single|company-wide|consolidated|overall) [a-z ]{0,20}(?:figure|percentage|"
    r"margin|number)|is not (?:stated|given|shown|broken out))", re.I)

# The answer nonetheless commits to a winner. Without this, "not stated" is just a refusal,
# which is the CORRECT behaviour and must not be counted as a defect.
_COMMITS = re.compile(
    r"\b(?:has|had|is|was|reported|holds|shows)\s+the\s+"
    r"(?:lowest|highest|largest|smallest|greatest|biggest|most|least)\b"
    r"|\bthe\s+(?:lowest|highest|largest|smallest|greatest|biggest)\s+"
    r"(?:gross margin|margin|revenue|assets|income|share|figure|percentage|"
    r"value|amount|of (?:these|the|all))"
    r"|\btherefore[, ]+[A-Z][A-Za-z]+\s+(?:has|is|had|was)\b", re.I)


def load_sets():
    """id -> item, across all three eval sets. Ids are unique across them by assert."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from cross_set import CROSS_SET
    from golden_set import GOLDEN_SET
    from tesla_set import TESLA_SET
    out = {}
    for s in (GOLDEN_SET, CROSS_SET, TESLA_SET):
        for item in s:
            out[item["id"]] = item
    return out


def corpus_companies(items):
    """Every company named by any eval item - the universe a corpus-wide question ranges over.

    Derived from the SETS rather than hardcoded, so it cannot go stale the next time a filing
    is added. That is the same mistake cross_set.py's own docstring says it made twice.
    """
    names = set()
    for it in items.values():
        for c in it.get("companies") or []:
            names.add(c)
    return sorted(names)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "eval_610_gate.jsonl"
    here = os.path.dirname(os.path.abspath(__file__))
    full = path if os.path.isabs(path) else os.path.join(here, path)
    if not os.path.exists(full):
        raise SystemExit(f"  no such run file: {full}\n"
                         f"  this probe reads a run that has ALREADY been paid for; it never "
                         f"calls a model.")

    items = load_sets()
    rows = [json.loads(line) for line in io.open(full, encoding="utf-8") if line.strip()]
    companies = corpus_companies(items)

    print(f"\n  run file : {os.path.basename(full)}  ({len(rows)} rows)")
    print(f"  corpus   : {', '.join(companies)}  (derived from the eval sets, not hardcoded)")

    at_risk, admitted, silent = [], [], []

    for r in rows:
        item = items.get(r["id"])
        if not item:
            continue
        q = item["question"]
        if not _RANKING_Q.search(q):
            continue

        # Which companies does this question actually range over? An item that names its
        # companies is trusted; one that says "the companies in these filings" ranges over
        # all of them.
        named = item.get("companies") or []
        ranges_over = companies if (len(named) >= len(companies) or
                                    re.search(r"these filings|all (?:of )?the companies",
                                              q, re.I)) else named
        at_risk.append((r["id"], r.get("correct"), q, ranges_over))

        ans = r.get("answer") or ""
        if _GAP_A.search(ans) and _COMMITS.search(ans):
            admitted.append((r["id"], r.get("correct"), q, ans))
        else:
            missing = [c for c in ranges_over
                       if not re.search(rf"\b{re.escape(c)}\b", ans, re.I)]
            if missing and _COMMITS.search(ans):
                silent.append((r["id"], r.get("correct"), missing, ans))

    print(f"\n{'=' * 96}")
    print(f"  1. POPULATION AT RISK : {len(at_risk)}/{len(rows)} questions rank or select "
          f"across a set")
    print(f"{'=' * 96}")
    for qid, correct, q, rng in at_risk:
        mark = "  " if correct else "✗ "
        print(f"  {mark}{qid:5} over {len(rng)}  {q[:78]}")

    print(f"\n{'=' * 96}")
    print(f"  2. ADMITTED GAP + STILL PICKED A WINNER : {len(admitted)}   <- x27's exact shape")
    print(f"{'=' * 96}")
    for qid, correct, q, ans in admitted:
        print(f"\n  {qid}  (correct={correct})")
        print(f"    Q: {q[:88]}")
        for line in ans.strip().splitlines():
            if _GAP_A.search(line) or _COMMITS.search(line):
                print(f"    > {line.strip()[:104]}")
    if not admitted:
        print("  none")

    print(f"\n{'=' * 96}")
    print(f"  3. A MEMBER NEVER MENTIONED, AND A WINNER NAMED ANYWAY : {len(silent)}")
    print(f"     Weaker evidence - the member may be legitimately out of scope. READ THESE.")
    print(f"{'=' * 96}")
    for qid, correct, missing, ans in silent:
        print(f"  {'  ' if correct else '✗ '}{qid:5} never mentions {missing}")
    if not silent:
        print("  none")

    # ---- the verdict this probe exists to deliver, including the one that cancels work ----
    print(f"\n{'=' * 96}")
    n_bad = len(admitted) + len(silent)
    print(f"  {len(at_risk)} questions can suffer this defect. {n_bad} candidate(s) found; "
          f"{sum(1 for x in admitted if not x[1])} of the admitted ones already FAIL "
          f"correctness.")
    if len(at_risk) < 5:
        print("  🟡 The population at risk is tiny. A judge for it would cost more to maintain")
        print("     than the defect costs to document. Recommend: document, do not build.")
    elif n_bad == 0:
        print("  🟡 No candidate outside x27 itself. One item on one gate is an anecdote, not")
        print("     a class - recommend documenting it and revisiting when a second appears.")
    else:
        print("  🔴 The class has surface area: a judge is worth building, and these candidates")
        print("     are its first labelled cases.")
    print("  LOWER BOUND. An answer that drops a member using words this file does not match")
    print("  is invisible here. This finds candidates; the reading is still yours.")
    print(f"{'=' * 96}")


if __name__ == "__main__":
    main()
