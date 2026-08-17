# probe_scope_ab.py
# Head-to-head: the existing groundedness judge vs the scope-aware one, on IDENTICAL inputs.
#
# Only the NEW judge is called. Every old verdict below was already measured and paid for -
# by judge_groundedness.py, probe_gscope.py, and the eval runs themselves - so re-running the
# old judge would buy nothing but a second copy of a deterministic answer. (Deterministic is
# not an assumption here: judge_calibration.py --repeat 3 produced zero flips over 40 items.)
#
# What a win looks like, and it is deliberately a high bar:
#   1. it must CATCH the three soft over-generalisations the old judge missed, and
#   2. it must not lose a single thing the old judge got right - not one mutation, and
#      above all not one REAL answer. A judge that catches scope errors by flagging good
#      answers has traded a false-positive rate for a false-negative rate and helped nobody.
#
# Condition 2 is why the nine real stored answers are in here. They are the closest thing to
# a regression set a judge can have: real system output, real contexts, verdicts already on
# the record. Only nine, because context has only been persisted since 4.5.0 - which is the
# cost of not instrumenting earlier, showing up again.

import argparse
import json
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

from judges_scope import scope_judge
from judge_groundedness import build, RUN, EX

load_dotenv()

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--recheck", action="store_true",
                    help="re-run ONLY the cases the scope judge previously caught (recorded "
                         "verdict 0). Use after any change that RELAXES the scoring rule: a "
                         "relaxation can only turn 0 into 1, so these are the only cases it "
                         "can break, and 8 calls settle it instead of 22.")
parser.add_argument("--recorded", action="store_true",
                    help="skip every API call and re-analyse the verdicts already measured "
                         "on 2026-08-16 (NEW_RECORDED below). Completely free. Use this to "
                         "re-score under a different combination rule without re-buying a "
                         "deterministic answer.")
args = parser.parse_args()

# d04's post-fix answer lives in its own file, and it is the single most interesting real
# answer here: it is the one the title fix repaired.
D04 = None
try:
    for line in open("eval_45_d04.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r.get("id") == "d04" and "error" not in r:
            D04 = r
except FileNotFoundError:
    pass

# Verdicts the OLD judge already gave, keyed (id, kind). Recorded, not re-run.
OLD = {
    ("x28", "control"): 1, ("w02", "control"): 1,
    ("r03", "control"): 1, ("x10", "control"): 1,
    ("x28", "unsupported_add"): 0, ("r03", "unsupported_add"): 0,
    ("x10", "unsupported_add"): 0,
    ("w02", "phrasing_blunt"): 1, ("w02", "phrasing_hedged"): 1,
    ("x28", "number_invent"): 0, ("w02", "number_invent"): 0,
    ("r03", "number_invent"): 0,
    ("x28", "entity_swap"): 0, ("x10", "entity_swap"): 0,
    ("r01", "structural_explicit"): 0, ("d04", "mislabel_explicit"): 0,
    # from probe_gscope.py - the two cells that were not already in the suite above
    ("x28", "soft_scope"): 1, ("w02", "hard_scope"): 0,
    # real answers, verdicts from the eval runs that produced them
    ("d04", "REAL post-fix"): 1, ("d05", "REAL"): 1,
    ("r01", "REAL"): 1, ("x17", "REAL"): 1,
}

# The two 2x2 cells that are not duplicates of a mutation already in judge_groundedness.py.
EXTRA = [
    ("x28", "soft_scope", RUN["x28"]["answer"].rstrip() +
     " AMD therefore holds the smallest asset base in the global chip industry.", 0),
    ("w02", "hard_scope", RUN["w02"]["answer"].rstrip() +
     " Intel therefore holds the largest asset base among all publicly traded "
     "semiconductor companies worldwide.", 0),
]

REAL = [("d05", "REAL"), ("r01", "REAL"), ("x17", "REAL")]

# Verdicts the SCOPE judge gave when this file was first run (2026-08-16), recorded for the
# same reason the old judge's are: the judge is deterministic, so re-running buys a second
# copy of the same answer. --recorded replays these, which makes trying a different
# combination rule cost nothing at all.
NEW_RECORDED = {
    ("x28", "control"): 1, ("w02", "control"): 1,
    ("r03", "control"): 1, ("x10", "control"): 1,
    ("x28", "unsupported_add"): 0,
    # r03 was 0 before the digit rule and is 1 after it. That change is REAL and is left
    # here rather than quietly reverted - see judges_scope._figures_ok. The AND still
    # catches r03, because the binary judge scores it 0; the recheck harness exists to make
    # exactly this kind of shift visible instead of letting it pass as a code tidy-up.
    ("r03", "unsupported_add"): 1,
    ("x10", "unsupported_add"): 0,
    ("w02", "phrasing_blunt"): 0, ("w02", "phrasing_hedged"): 0,
    ("x28", "number_invent"): 1, ("w02", "number_invent"): 1,
    ("r03", "number_invent"): 1,
    ("x28", "entity_swap"): 1, ("x10", "entity_swap"): 0,
    ("r01", "structural_explicit"): 1, ("d04", "mislabel_explicit"): 1,
    ("x28", "soft_scope"): 0, ("w02", "hard_scope"): 0,
    ("d04", "REAL post-fix"): 1, ("d05", "REAL"): 1,
    ("r01", "REAL"): 1, ("x17", "REAL"): 1,
}


def cases():
    out = []
    for i, kind, prediction, expected, graded in build():
        out.append((i, kind, prediction, RUN[i]["context"], expected, graded))
    for i, kind, prediction, expected in EXTRA:
        out.append((i, kind, prediction, RUN[i]["context"], expected, True))
    for i, kind in REAL:
        out.append((i, kind, RUN[i]["answer"], RUN[i]["context"], 1, True))
    if D04 is not None:
        out.append(("d04", "REAL post-fix", D04["answer"], D04["context"], 1, True))
    return out


def run(case):
    i, kind, prediction, context, expected, graded = case
    v = scope_judge(question=EX[i]["question"], prediction=prediction, context=context)
    return i, kind, expected, OLD.get((i, kind)), v["score"], v, graded


def replay(case):
    i, kind, _prediction, _context, expected, graded = case
    blank = {"claims": 0, "bad": 0, "detail": [], "reasoning": "(recorded run)"}
    return i, kind, expected, OLD.get((i, kind)), NEW_RECORDED[(i, kind)], blank, graded


if __name__ == "__main__":
    cs = cases()

    if args.recheck:
        # The guard for a relaxing change. judges_scope._figures_ok now passes any claim with
        # no digits in it, which fixed q21 - but three of the unsupported_add mutations are
        # themselves digit-free sentences, and if they were being caught by the FIGURES test
        # rather than the SCOPE test, this relaxation would have quietly un-caught them.
        # That is precisely the silent pass this project keeps finding, so it is checked.
        subset = [c for c in cs if NEW_RECORDED.get((c[0], c[1])) == 0]
        print(f"\n{'=' * 100}\nRECHECK after a relaxing change - {len(subset)} cases the "
              f"scope judge previously CAUGHT\n{'=' * 100}")
        with ThreadPoolExecutor(max_workers=6) as pool:
            out = list(pool.map(run, subset))
        broke = []
        for i, kind, _want, _old, new, v, _g in out:
            if new != 0:
                broke.append(f"{i}/{kind}")
            print(f"  {i:5} {kind:22} was 0  now {new}  "
                  f"{'ok' if new == 0 else 'UN-CAUGHT BY THE RELAXATION'}")
            if new != 0:
                print(f"        {str(v['reasoning'])[:160]}")
        print(f"\n  still caught {len(out) - len(broke)}/{len(out)}"
              + ("" if not broke else f"   BROKEN: {broke}"))
        print("  A broken row means the digit rule removed a real catch, and the fix has to")
        print("  move from code back into the model's observations (a rests_on_figures field).")
        raise SystemExit(1 if broke else 0)

    if args.recorded:
        print(f"\n{'=' * 100}\nSCOPE JUDGE A/B - replaying {len(cs)} recorded verdicts, "
              f"0 calls, $0\n{'=' * 100}")
        results = [replay(c) for c in cs]
    else:
        print(f"\n{'=' * 100}\nSCOPE JUDGE A/B - {len(cs)} calls (new judge only; "
              f"old verdicts are on the record)\n{'=' * 100}")
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(run, cs))

    fixed, broken, agree = [], [], 0
    print(f"\n  {'id':5} {'case':22} {'want':>4} {'old':>4} {'new':>4}  claims  outcome")
    for i, kind, want, old, new, v, graded in results:
        if not graded:
            # d04/mislabel_explicit: its context mislabels the table, so "the right verdict"
            # is not clean. Printed, never counted - see judge_groundedness.py's EXPLICIT.
            outcome = "not scored - ground truth not clean"
        elif old is None:
            outcome = "no recorded old verdict"
        elif old == new:
            outcome = "same as before" + ("" if new == want else "   (both wrong)")
            agree += 1
        elif new == want:
            outcome = "FIXED"
            fixed.append((i, kind))
        else:
            outcome = "REGRESSION"
            broken.append((i, kind, v))
        print(f"  {i:5} {kind:22} {want:>4} {str(old):>4} {new:>4}  {v['claims']:>5}   {outcome}")
        if new != want and graded:
            print(f"        {str(v['reasoning'])[:160]}")

    print(f"\n  FIXED by the scope judge : {len(fixed)}  {[f'{i}/{k}' for i, k in fixed]}")
    print(f"  REGRESSIONS              : {len(broken)}  "
          f"{[f'{i}/{k}' for i, k, _v in broken]}")
    print(f"  unchanged                : {agree}")

    scored = [r for r in results if r[6]]
    new_ok = sum(1 for _i, _k, w, _o, n, _v, _g in scored if n == w)
    old_ok = sum(1 for _i, _k, w, o, _n, _v, _g in scored if o == w)
    print(f"\n  agreement with intended verdict:  old {old_ok}/{len(scored)}   "
          f"new {new_ok}/{len(scored)}")

    real = [r for r in results if r[1].startswith("REAL") or r[1] == "control"]
    real_ok = sum(1 for _i, _k, w, _o, n, _v, _g in real if n == w)
    print(f"  REAL answers still grounded:      {real_ok}/{len(real)}"
          + ("" if real_ok == len(real) else "   <-- FALSE NEGATIVES, this is disqualifying"))

    # --- the two judges ANDed ------------------------------------------------------------
    # Neither judge is better than the other; they fail by OMISSION in opposite directions.
    # The old one checks figures and skips the sentence. The new one checks the sentence and
    # skips the figures - the same trade, mirrored, which is what one fused call buys you.
    # AND is intolerant of omission: a claim has to survive both readings.
    print("\n  COMBINED  (grounded = old AND new) - no new calls, this is arithmetic on the")
    print("  verdicts above:")
    print(f"\n  {'id':5} {'case':22} {'want':>4} {'old':>4} {'new':>4} {'AND':>4}  ")
    comb_ok = comb_tot = 0
    comb_fn = []
    for i, kind, want, old, new, _v, graded in results:
        if not graded or old is None:
            continue
        both = 1 if (old == 1 and new == 1) else 0
        comb_tot += 1
        comb_ok += both == want
        if both == 0 and want == 1:
            comb_fn.append(f"{i}/{kind}")
        print(f"  {i:5} {kind:22} {want:>4} {old:>4} {new:>4} {both:>4}  "
              f"{'ok' if both == want else 'WRONG'}")
    print(f"\n  old alone      {old_ok}/{len(scored)}")
    print(f"  new alone      {new_ok}/{len(scored)}")
    print(f"  old AND new    {comb_ok}/{comb_tot}")
    print(f"  false negatives introduced by ANDing: {len(comb_fn)} {comb_fn}")
    print("\n  Caveat, stated because the number above is flattering: only 8 REAL answers exist")
    print("  to test false negatives against, because context has only been stored since")
    print("  4.5.0. ANDing two checks can only ever turn 1s into 0s, so the false-negative")
    print("  risk it adds is real and is NOT measured by this suite. The next gate run is.")

    # A regression on a real answer is the failure mode that matters, so print what the judge
    # actually objected to rather than leaving it to be guessed at.
    for i, kind, v in broken:
        if kind.startswith("REAL") or kind == "control":
            print(f"\n  {i}/{kind} - every claim the judge extracted:")
            for claim, scope, covers, figs, absent in v["detail"]:
                mark = " " if (covers and figs) or absent else "x"
                print(f"    [{mark}] {claim[:66]:66} | over: {scope[:34]}")
