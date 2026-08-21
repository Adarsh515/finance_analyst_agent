"""
probe_arith.py - does an answer's arithmetic agree with its own printed figures? FREE, no model.

WHY THIS IS WORTH A LOOK BEFORE ANYTHING IS BUILT. `d08` lists four revenues CORRECTLY and then
states a combined figure 400 short of their sum. Identical 400 in the 6.8 and the 6.10 gate, so
it is deterministic. Its ratio - 8.71% - is then computed from its own wrong total, so the
answer is internally consistent about being wrong in exactly one place.

Third appearance of the `d04` family. `d04` reported AMD's total liabilities as 13,932 in one
gate and 14,073 in the next against a verified 13,927, and **both scored 1/1**, because the
question's key fact survives the error and the groundedness judge does not verify arithmetic by
design. That limitation has been in PROJECT_TRACKER.md for four phases: *"intermediate figures
in multi-part answers are not checked by anything."*

THE IDEA. An answer that writes `$34,639 + $52,853 + $215,938 + $94,827` and then `$397,857`
CONTRADICTS ITSELF, and noticing that needs no model, no context, and no reference answer - just
the answer's own text. If that is true often enough to matter, this becomes a fourth scoreboard
that costs NOTHING to run, which is a rare thing in this repo.

THIS PROBE MAY CANCEL THE WORK. Same rule as probe_setgap.py and the Phase 4.2 calculator, which
was cancelled by exactly this kind of scan: if almost every answer's arithmetic already agrees
with itself, a checker is machinery for one item and the honest output is "documented, not
built".

TWO TIERS, and they are reported separately because their evidence is not equally strong.

  TIER 1 - EXPLICIT.  The operands are written beside the result:
                        (49,510 / 206,803) * 100 ≈ 23.94%
                        9,455 + 2,348 + 625 + 313 + 1,186   [= 13,927]
                        55.60% - (-0.51%) = 56.11
                      Nothing is inferred. A mismatch here is a defect in the answer.

  TIER 2 - INFERRED.  A COMPUTED total with no operands shown - "Combined Revenue: $397,857" -
                      checked by asking whether ANY subset of the figures the answer listed adds
                      up to it. Restricted to wordings that mean the answer did the adding
                      ("combined", "sum of", "total of all/these"), because a bare "Total
                      revenues" is a line item quoted from a filing and its components are not
                      required to be present. Tier 2 finds CANDIDATES; they get read.

Free: reads a stored run off disk. No API key, no index, no model, no network.

    python probe_arith.py                      # the 6.10 gate
    python probe_arith.py eval_68_gate.jsonl   # any stored run
"""

import io
import itertools
import json
import os
import re
import sys

# A money/number token as these answers actually write them:
#   $34,639   34,639   $(267)   (267)   -267   13.32   55.60%   23.94
# The parenthesised form is accounting negative and MUST be read as negative, or every Intel
# comparison in this corpus scores as a false mismatch.
_NUM = re.compile(r"""
    (?P<neg1>-)?\s*
    \$?\s*
    (?P<paren>\()?\s*
    (?P<neg2>-)?\s*\$?\s*
    (?P<body>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d+)
    \s*(?(paren)\)|)
""", re.X)


def to_num(text):
    """Parse one token. Returns None if it is not a number."""
    m = _NUM.fullmatch(text.strip())
    if not m:
        return None
    v = float(m.group("body").replace(",", ""))
    if m.group("neg1") or m.group("neg2") or m.group("paren"):
        v = -v
    return v


def all_numbers(text):
    """Every number in the text, in order, with accounting negatives honoured."""
    out = []
    for m in _NUM.finditer(text):
        v = float(m.group("body").replace(",", ""))
        if m.group("neg1") or m.group("neg2") or m.group("paren"):
            v = -v
        out.append(v)
    return out


def close(a, b, rel=0.006, absolute=0.02):
    """Is b the answer to a, allowing for the rounding the answers openly do?

    ONE TOLERANCE PER KIND OF ARITHMETIC, and the first version used one for all three and
    missed its own labelled mutation. `9,455 + 2,348 + 625 + 313 + 1,186 = 13,999` is wrong by
    72, which is 0.51% - under a 0.6% band chosen to stop '≈' from firing false alarms on
    rounded percentages. So a wrong SUM hid inside a tolerance that exists for RATIOS.

    A sum of figures the answer itself printed has NO rounding in it: the operands are exact
    and so is the result, so it is compared exactly (half a unit, for a decimal written to
    zero places). A ratio's printed result IS rounded, usually to two decimals, so it needs a
    real band. A difference of two already-rounded percentages inherits their rounding and
    needs a small absolute one.

    The consequence is worth stating rather than hiding: at 0.6%, THE RATIO CHECK CANNOT SEE
    d08's 400-in-398,257 (0.1%). It is caught as a SUM, where the comparison is exact. An
    arithmetic error small enough to hide inside a rounded percentage is not findable this way,
    and no choice of band fixes that - only quoting more decimals would.
    """
    if a is None or b is None:
        return True
    if abs(a - b) <= absolute:
        return True
    scale = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / scale <= rel


# ---------------------------------------------------------------------------------------
# TIER 1 - expressions whose operands are written down
# ---------------------------------------------------------------------------------------

# `%` may sit INSIDE the closing bracket - `(-0.51%)` - and the first version only allowed
# it outside, so the one difference in the corpus that subtracts a negative percentage
# was never matched. Found by a mutation test, not by reading: the corrupted "Gap: 55.60%
# - (-0.51%) = 99.99" sailed through.
# `$(267)` puts the dollar sign OUTSIDE the bracket and the first two versions only
# allowed `($267)`, so Intel - the one company in this corpus that reports a LOSS - was
# dropped from every list of figures. The consequence was a FALSE POSITIVE on x23, whose
# arithmetic (4,335 - 267 + 120,067 + 3,794 = 127,929) is exactly right: with the -267
# missing the remaining three sum to 128,196 and the probe reported a 267 discrepancy in
# a correct answer. Caught only because x23 was picked as a CONTROL for the repair probe.
_TOKEN = r"\$?\s*\(?\s*-?\s*\$?\s*\d[\d,]*(?:\.\d+)?\s*%?\s*\)?%?"
# "million" / "billion" sit BETWEEN the number and the operator in half these answers
# ("$102,718 million / $7,709 million ≈ 13.32") and the first version of this file had no
# room for them, so x24's division - a correct one - was never checked at all. A checker that
# silently examines two expressions out of a hundred reports a clean bill of health it never
# earned; that is how this probe's own first run said "2 expressions checked" while d03 alone
# contains four.
_UNIT = r"(?:\s*(?:million|billion|thousand|percentage\s+points?|bn|m))?"

_RATIO = re.compile(rf"\(?\s*({_TOKEN}){_UNIT}\s*/\s*({_TOKEN}){_UNIT}\s*\)?"
                    rf"(?:\s*\*\s*100)?\s*(?:=|≈|~|is)\s*\*{{0,2}}({_TOKEN})", re.I)

_SUM = re.compile(rf"({_TOKEN}{_UNIT}(?:\s*\+\s*{_TOKEN}{_UNIT}){{1,9}})"
                  rf"\s*(?:=|≈|~)\s*\*{{0,2}}({_TOKEN})", re.I)

_DIFF = re.compile(rf"({_TOKEN}){_UNIT}\s*[-−]\s*({_TOKEN}){_UNIT}"
                   rf"\s*(?:=|≈|~)\s*\*{{0,2}}({_TOKEN})", re.I)


def _clean(tok):
    """Parse one operand as the surrounding regex handed it over, brackets and all.

    A capture group inside `($4,335 / $34,639)` comes back as `($4,335` - one unbalanced
    parenthesis belonging to the EXPRESSION, not to the number. The first version passed that
    straight to to_num(), which correctly refused it, so every ratio in the run was skipped and
    the probe reported 0 disagreements out of 2 expressions. It looked like a clean result.

    So: balanced parentheses mean an accounting NEGATIVE; a lone one is punctuation and is
    dropped. Getting that backwards would turn every Intel figure positive.
    """
    t = (tok or "").strip().strip("*").replace("%", "").replace("$", "").replace(",", "")
    t = re.sub(r"\s*(?:million|billion|thousand|bn|m)\b", "", t, flags=re.I).strip()
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").strip()
    if t.startswith("-"):
        neg, t = True, t[1:].strip()
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def tier1_spans(answer):
    """Character spans of every explicit expression tier1() checks.

    🔴 THE THIRD EXTRACTION DEFECT IN THIS FILE, and it landed on the one answer the whole
    exercise fixed. Once `d08` started SHOWING its addition -
    `**Combined Revenue:** 34639 + 52853 + 215938 + 94827 = $398,257 million` - Tier 2 matched
    "Combined Revenue:" and took the FIRST number after it, 34,639, as the claimed total. It
    then reported that d08 claimed a total of 34,639 against three figures summing to 363,618.
    A false positive on a correct answer, produced by the fix succeeding.

    The rule that removes it is the honest one: AN EXPRESSION TIER 1 HAS ALREADY CHECKED
    EXACTLY IS NOT RE-CHECKED BY INFERENCE. Tier 2 exists only for totals whose operands are
    absent; the moment the operands are present, that is Tier 1's case and Tier 2 must stay out
    of it. Which is also the whole point of the arithmetic rule: it moves cases from the tier
    that guesses to the tier that does not.
    """
    spans = []
    for rx in (_SUM, _RATIO, _DIFF):
        for m in rx.finditer(answer):
            spans.append(m.span())
    return spans


def tier1(answer):
    """Every explicit expression, with a verdict. (kind, text, expected, stated, ok)"""
    found = []

    for m in _SUM.finditer(answer):
        parts = [_clean(p) for p in m.group(1).split("+")]
        got = _clean(m.group(2))
        if any(p is None for p in parts) or got is None:
            continue
        # EXACT: a sum of printed figures has no rounding in it. See close().
        found.append(("sum", m.group(0)[:90], sum(parts), got,
                      close(sum(parts), got, rel=0.0, absolute=0.5)))

    for m in _RATIO.finditer(answer):
        a, b, p = _clean(m.group(1)), _clean(m.group(2)), _clean(m.group(3))
        if None in (a, b, p) or b == 0:
            continue
        # the stated result may be a percentage or a bare ratio; accept whichever matches, and
        # say WHICH, because "13.32" and "1332%" are different claims
        if close(a / b * 100, p):
            found.append(("ratio%", m.group(0)[:90], a / b * 100, p, True))
        elif close(a / b, p):
            found.append(("ratio", m.group(0)[:90], a / b, p, True))
        else:
            # report against the reading that is closer, so the printed "expected" is the one
            # the answer was plausibly attempting
            as_pct = abs(a / b * 100 - p) <= abs(a / b - p)
            found.append(("ratio%" if as_pct else "ratio", m.group(0)[:90],
                          a / b * 100 if as_pct else a / b, p, False))

    for m in _DIFF.finditer(answer):
        a, b, c = _clean(m.group(1)), _clean(m.group(2)), _clean(m.group(3))
        if None in (a, b, c):
            continue
        # a difference inherits its operands' rounding, so a small ABSOLUTE band and
        # essentially no relative one - 55.60 - (-0.51) = 56.11 must pass, 99.99 must not
        found.append(("diff", m.group(0)[:90], a - b, c,
                      close(a - b, c, rel=0.0, absolute=0.02)))

    return found


# ---------------------------------------------------------------------------------------
# TIER 2 - a COMPUTED total with no operands shown
# ---------------------------------------------------------------------------------------
# Only wordings that mean the ANSWER did the adding. A bare "Total revenues | 94827" is a line
# item quoted from a filing, and its components are not required to be anywhere in the answer;
# flagging those would bury the real finding under dozens of false alarms.
#
# 🔴 NON-GREEDY, and the first version's GREEDY `{0,40}` produced a false positive on `d02`:
# it ate "sum of these reportable segments is $34,63" and captured the leftover "9" as the
# total, then reported that d02 claimed a total of 9 against figures summing to 34,639. A probe
# that invents a defect is worse than one that misses it, because somebody spends an hour on
# the invented one.
#
# 🔴 And the 40-character gap was too SHORT, which is the opposite failure and was invisible:
# `x23` writes "the combined net income attributable to shareholders for these companies in
# their most recent fiscal years is $127,929 million" - ninety characters between the trigger
# word and the number - so its total was never checked at all, in either gate. The probe
# reported "2 totals checked" and looked thorough. Found only when x23 was picked as a control
# for something else and the detector refused to fire on a deliberately broken version of it.
# **A coverage number is not a coverage measurement**: 2 checked out of what?
#
# So the gap is 120 now, and the SAFETY comes from requiring a connector - `is`, `was`,
# `comes to`, `:` or `=` - immediately before the figure, rather than from starving the gap.
_COMPUTED_TOTAL = re.compile(
    r"(?:combined|sum of|aggregate|added together|"
    r"total (?:of )?(?:all|these|the four|the companies))"
    r"(?P<gap>[^.\n]{0,120}?)"
    r"(?:\bis\b|\bwas\b|\bcomes to\b|[:=\u2248])\s*\*{0,2}\s*"
    rf"({_TOKEN})", re.I)

# A figure presented as one entity's value: a bulleted or bolded per-company line.
_LISTED = re.compile(rf"^\s*[*\-•\d.]+\s*\**[^:\n]{{2,60}}?\**\s*:\s*\**\s*({_TOKEN})",
                     re.M)


def tier2(answer):
    """(claim_text, stated_total, listed_figures, best_subset_sum, ok)

    Skips anything Tier 1 already covers - see tier1_spans() for the false positive that
    taught this.
    """
    listed = [v for v in (_clean(m.group(1)) for m in _LISTED.finditer(answer))
              if v is not None]
    covered = tier1_spans(answer)
    out = []
    for m in _COMPUTED_TOTAL.finditer(answer):
        total = _clean(m.group(2))
        if total is None or not listed:
            continue
        # the captured number's own position, not the whole claim's: the trigger word may sit
        # outside an expression while the figure sits inside one
        at = m.start(2)
        if any(lo <= at < hi for lo, hi in covered):
            continue
        pool = [v for v in listed if not close(v, total)]      # the total is not its own addend
        if len(pool) > 14:                                     # 2^14 subsets is the cap
            pool = pool[:14]
        ok, best = False, None
        for k in range(2, len(pool) + 1):
            for combo in itertools.combinations(pool, k):
                ssum = sum(combo)
                if best is None or abs(ssum - total) < abs(best - total):
                    best = ssum
                if close(ssum, total, rel=0.0005):
                    ok = True
                    break
            if ok:
                break
        out.append((m.group(0)[:80], total, pool, sum(pool), ok))
    return out


SELFTEST = [
    # (name, answer text, expected tier-1 disagreements, expected tier-2 flags)
    #
    # THESE ARE MUTATIONS, and they exist because the first version of this file reported
    # "2 expressions checked, 0 disagree" over a hundred answers and read like a clean result.
    # It was checking almost nothing: a capture group came back as `($4,335`, to_num refused
    # the unbalanced bracket, and every ratio in the corpus was skipped in silence. Lesson 138 -
    # before believing "nothing is wrong", prove the harness could have SEEN something wrong.
    #
    # Synthetic rather than replayed, on purpose: a self-test that needs a gate file cannot run
    # on a fresh clone, and this repo's rule is that the important checks are free AND runnable.
    ("a correct ratio passes",
     "*   Margin: ($4,335 / $34,639) ≈ **12.51%**", 0, 0),
    ("a corrupted ratio RESULT is caught",
     "*   Margin: ($4,335 / $34,639) ≈ **21.51%**", 1, 0),
    ("a corrupted ratio OPERAND is caught",
     "*   Margin: ($9,999 / $34,639) ≈ **12.51%**", 1, 0),
    ("a ratio written with units and no brackets passes",
     "$102,718 million / $7,709 million ≈ 13.32", 0, 0),
    ("the *100 form passes",
     "*   Percentage: ($49,510 / $206,803) * 100 ≈ **23.94%**", 0, 0),
    ("an accounting negative is read as negative, not positive",
     "*   Margin: (-$267 / $52,853) ≈ **-0.51%**", 0, 0),
    ("a difference subtracting a negative percentage passes",
     "*   Gap: 55.60% - (-0.51%) = **56.11 percentage points**", 0, 0),
    ("...and is caught when corrupted   [the % INSIDE the bracket, missed by v1]",
     "*   Gap: 55.60% - (-0.51%) = **99.99 percentage points**", 1, 0),
    ("a correct explicit sum passes",
     "Total: $9,455 + $2,348 + $625 + $313 + $1,186 = $13,927", 0, 0),
    ("a corrupted explicit sum is caught",
     "Total: $9,455 + $2,348 + $625 + $313 + $1,186 = $13,999", 1, 0),
    ("d08's shape: four listed figures, a combined total 400 short",
     "*   **AMD:** $34,639 million\n*   **Intel:** $52,853 million\n"
     "*   **NVIDIA:** $215,938 million\n*   **Tesla:** $94,827 million\n\n"
     "**Combined Revenue:** $397,857 million", 0, 1),
    ("...and the same answer with the total corrected does NOT flag",
     "*   **AMD:** $34,639 million\n*   **Intel:** $52,853 million\n"
     "*   **NVIDIA:** $215,938 million\n*   **Tesla:** $94,827 million\n\n"
     "**Combined Revenue:** $398,257 million", 0, 0),
    # 🔴 d02's shape. The first version's GREEDY quantifier ate "sum of these reportable
    # segments is $34,63" and captured the leftover "9" as the total, then reported a total of
    # 9 against figures summing to 34,639. A probe that invents a defect is worse than one that
    # misses it, because somebody spends an hour on the invented one.
    ("a correct in-sentence sum does not become a false positive",
     "*   Data Center: $16,635 million\n*   Client and Gaming: $14,550 million\n"
     "*   Embedded: $3,454 million\n\n"
     "Yes, the sum of these reportable segments is $34,639 million.", 0, 0),
    ("$(267) - a LOSS written with the dollar outside the bracket - is read as -267",
     "*   **AMD:** $4,335 million\n*   **Intel:** $(267) million (net loss)\n"
     "*   **NVIDIA:** $120,067 million\n*   **Tesla:** $3,794 million\n\n"
     "The combined net income for these companies is $127,929 million.", 0, 0),
    ("...and the same list with a genuinely wrong combined figure IS caught",
     "*   **AMD:** $4,335 million\n*   **Intel:** $(267) million (net loss)\n"
     "*   **NVIDIA:** $120,067 million\n*   **Tesla:** $3,794 million\n\n"
     "The combined net income for these companies is $127,000 million.", 0, 1),
    ("d08 AFTER the fix - the addition is SHOWN, so Tier 1 owns it and Tier 2 stays out",
     "*   **AMD:** $34,639 million\n*   **Intel:** $52,853 million\n"
     "*   **NVIDIA:** $215,938 million\n*   **Tesla:** $94,827 million\n\n"
     "**Combined Revenue:** 34639 + 52853 + 215938 + 94827 = $398,257 million\n"
     "**AMD's Share:** 34639 / 398257 = 0.086976 or approximately 8.70%", 0, 0),
    ("...and a SHOWN addition with a wrong result is still caught, by Tier 1",
     "*   **AMD:** $34,639 million\n*   **Intel:** $52,853 million\n"
     "*   **NVIDIA:** $215,938 million\n*   **Tesla:** $94,827 million\n\n"
     "**Combined Revenue:** 34639 + 52853 + 215938 + 94827 = $397,857 million", 1, 0),
    ("a quoted line item is NOT treated as a computed total",
     "*   Automotive: $82,056 million\n*   Energy: $12,771 million\n"
     "Total revenues were $94,827 million.", 0, 0),
]


def selftest():
    ok = 0
    print("\n  probe_arith.py - the extractor and the checker, on synthetic answers\n")
    for name, text, want1, want2 in SELFTEST:
        got1 = len([e for e in tier1(text) if not e[4]])
        got2 = len([t for t in tier2(text) if not t[4]])
        good = (got1, got2) == (want1, want2)
        ok += good
        print(f"  [{'ok  ' if good else 'FAIL'}] t1={got1}/{want1} t2={got2}/{want2}  {name}")
    print(f"\n  {ok}/{len(SELFTEST)} checks passed. No model, no gate file, no API key.")
    raise SystemExit(0 if ok == len(SELFTEST) else 1)


def main():
    if "--selftest" in sys.argv:
        selftest()
    path = sys.argv[1] if len(sys.argv) > 1 else "eval_610_gate.jsonl"
    here = os.path.dirname(os.path.abspath(__file__))
    full = path if os.path.isabs(path) else os.path.join(here, path)
    if not os.path.exists(full):
        raise SystemExit(f"  no such run file: {full} - this reads a run already paid for.")

    rows = [json.loads(l) for l in io.open(full, encoding="utf-8") if l.strip()]
    print(f"\n  {os.path.basename(full)}  -  {len(rows)} stored answers, no model called\n")

    with_t1 = t1_total = t1_bad = 0
    bad1, bad2, t2_checked = [], [], 0

    for r in rows:
        ans = r.get("answer") or ""
        exprs = tier1(ans)
        if exprs:
            with_t1 += 1
        t1_total += len(exprs)
        for kind, text, expected, stated, ok in exprs:
            if not ok:
                t1_bad += 1
                bad1.append((r["id"], r.get("correct"), kind, text, expected, stated))
        for claim, total, pool, poolsum, ok in tier2(ans):
            t2_checked += 1
            if not ok:
                bad2.append((r["id"], r.get("correct"), claim, total, pool, poolsum))

    print(f"{'=' * 100}")
    print(f"  TIER 1 - explicit expressions, operands written beside the result")
    print(f"{'=' * 100}")
    print(f"  answers containing at least one : {with_t1}/{len(rows)}")
    print(f"  expressions checked             : {t1_total}")
    print(f"  expressions that DISAGREE       : {t1_bad}")
    for qid, correct, kind, text, expected, stated in bad1:
        print(f"\n  {qid}  correct={correct}  [{kind}]")
        print(f"    wrote    : {text}")
        print(f"    computes : {expected:,.4f}")
        print(f"    stated   : {stated:,.4f}")

    print(f"\n{'=' * 100}")
    print(f"  TIER 2 - a COMPUTED total with no operands shown, checked by subset-sum")
    print(f"{'=' * 100}")
    print(f"  totals checked      : {t2_checked}")
    print(f"  no subset matches   : {len(bad2)}   <- candidates, to be READ")
    for qid, correct, claim, total, pool, poolsum in bad2:
        print(f"\n  {qid}  correct={correct}")
        print(f"    claim        : {claim.strip()}")
        print(f"    stated total : {total:,.0f}")
        print(f"    figures it listed: {[f'{v:,.0f}' for v in pool]}")
        print(f"    they sum to  : {poolsum:,.0f}   (difference {poolsum - total:,.0f})")

    print(f"\n{'=' * 100}")
    n_bad = t1_bad + len(bad2)
    if n_bad == 0:
        print("  🟡 Every checkable expression agrees with the answer's own figures. A checker")
        print("     would be machinery for a defect that this run does not contain - document")
        print("     d08 and do not build. That is the Phase 4.2 outcome, and it is a real one.")
    else:
        print(f"  🔴 {n_bad} arithmetic claim(s) contradict the answer's own printed figures.")
        print("     Every one of these is detectable with NO model, NO context and NO reference")
        print("     answer - which would make this the first scoreboard in the repo that is free")
        print("     to run. Read them before building anything.")
    print("  LOWER BOUND, and the reason is written into close(): the rounding tolerance that")
    print("  keeps '≈' from firing false alarms also hides small absolute errors in RATIOS.")
    print("  d08's 400 is caught as a SUM, where the comparison is exact, and would be invisible")
    print("  as a ratio. An arithmetic error small enough to hide inside a rounded percentage")
    print("  is not findable this way at all.")
    print(f"{'=' * 100}")


if __name__ == "__main__":
    main()
