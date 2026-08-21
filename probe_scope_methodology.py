"""
probe_scope_methodology.py - what does the `is_methodology` category actually change?

WHY THIS COSTS MONEY AND IS RUN ANYWAY. `judges_scope.py` produced every scope and every
`binary AND scope` number in PROJECT_TRACKER.md. Adding a field to its Claim model changes the
PROMPT, which changes the observations, which can move any verdict anywhere - so the tracker's
own rule applies: **an AND is a promise you owe a regression run**, and so is a change to
either half of one.

WHAT PROVOKED IT. `d03` scored 1 three times out of three in the 6.10 gate and 0 three times
out of three after the arithmetic rule, on an answer whose figures, ratios and conclusion are
byte-identical and whose CONTEXT is byte-identical. The only difference is cosmetic formatting,
and the sentence it now objects to is:

    "To calculate the net profit margin, we divide the net income attributable to shareholders
     by the total net revenue"

That is a statement of METHOD. It asserts nothing about any company, so "does the context cover
the set this ranges over?" is a question with no true answer - and a judge forced to answer it
answers differently depending on the markup around the sentence. The repair is the missing
category, not a steadier judge.

THE THREE-WAY DECOMPOSITION, which is the whole reason this probe exists rather than a re-run.
One paid pass yields observations that can be scored under BOTH rules, so:

    A  stored scope column          old prompt, old rule    <- what the tracker says today
    B  this run, rule OFF           NEW prompt, old rule    <- isolates the PROMPT's effect
    C  this run, rule ON            NEW prompt, new rule    <- isolates the RULE's effect

B vs A is what adding a sixth step to the prompt did on its own. C vs B is what the category
did. Reporting only A vs C would blame one change for the other's effect, which is the
attribution failure Phase 5 built two separate flags to avoid.

PRE-REGISTERED, written before the run so the result cannot be rationalised afterwards:

  1. C must not turn any stored 1 into a 0. The rule only ever widens what counts as trivial,
     so it CANNOT do this by itself - any such flip is the PROMPT's doing and has to be read.
  2. `d03`'s post-arithmetic-rule answer must score 1 under C. If the category does not fix the
     case that motivated it, it does not ship.
  3. Every mover in either direction is printed and READ. A count with nothing read behind it
     is not evidence.

COST: one scope call per stored answer. ~Rs 8-10 over 108 answers. No agent, no retrieval, no
generation - every answer and context is replayed from a run already paid for.

    python probe_scope_methodology.py
    python probe_scope_methodology.py --workers 1
"""

import io
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

GATES = ["eval_610_gate.jsonl", "eval_arith_check.jsonl"]
OUT = "scope_methodology.jsonl"


def _arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def rescore(here, path):
    """Re-apply the CODE rules to stored observations. Free.

    Possible only because `detail` is stored. Any change to _figures_ok or _trivial - both of
    which are pure code - can now be measured across every stored answer for nothing, instead
    of buying 108 fresh judgements to find out what a regex did.
    """
    import judges_scope
    rows = [json.loads(l) for l in io.open(os.path.join(here, path), encoding="utf-8")
            if l.strip()]
    if not rows or "detail" not in rows[0]:
        raise SystemExit(
            "  this file predates per-claim storage, so the rules cannot be re-applied to it.\n"
            "  Re-run the probe once; every later code-rule change is then free.")

    class _C:
        def __init__(self, t):
            (self.claim, self.ranges_over, self.context_covers_that_whole_set,
             self.input_figures_in_context, self.asserts_absence,
             self.is_methodology) = t

    moved = []
    for r in rows:
        claims = [_C(t) for t in r["detail"]]
        bad = [c for c in claims
               if not judges_scope._trivial(c)
               and not (c.context_covers_that_whole_set and judges_scope._figures_ok(c))]
        now = 0 if bad else 1
        if now != r["C_rule_on"]:
            moved.append((r["src"], r["id"], r["C_rule_on"], now,
                          "; ".join(c.claim[:70] for c in bad[:2])))
    print(f"\n  re-scored {len(rows)} stored observations under today's CODE rules, for $0")
    print(f"  verdicts that moved: {len(moved)}")
    for src, qid, was, now, why in moved:
        print(f"    {qid:6} [{src[:22]:22}] {was} -> {now}   {why[:80]}")
    if not moved:
        print("    none - the rules on disk agree with the run that produced this file")
    raise SystemExit(0)


def inspect(qid, gate):
    """Print every CLAIM the scope judge extracted for one answer, with all six observations.

    Exists because the 108-answer run stored only the three SCORES and not the per-claim
    detail, so the one mover it could not explain - `r01` - could not be read without paying
    again. That is the fingerprint lesson in a second costume: the expensive pass is the one
    that should record everything, because the cheap follow-up is the one you have not thought
    of yet. One call, about Rs 0.15, instead of Rs 8.5 to re-derive 108 rows for one of them.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    import judges
    import judges_scope
    import telemetry
    telemetry.install(judges, judges_scope)

    from cross_set import CROSS_SET
    from golden_set import GOLDEN_SET
    from tesla_set import TESLA_SET
    q = next(i for s in (GOLDEN_SET, CROSS_SET, TESLA_SET) for i in s if i["id"] == qid)
    row = next(json.loads(l) for l in io.open(os.path.join(here, gate), encoding="utf-8")
               if l.strip() and json.loads(l)["id"] == qid)

    with telemetry.capture() as calls:
        v = judges_scope.scope_judge(question=q["question"], prediction=row["answer"],
                                     context=row["context"])
    print(f"\n  {qid} from {gate}   score={v['score']}  "
          f"(old rule would say {v['score_without_methodology']})")
    print(f"  {v['claims']} claims, {v['methodology_claims']} marked methodology\n")
    print(f"  {'covers':>6} {'figs':>5} {'absent':>7} {'method':>7}  claim")
    print(f"  {'-'*6} {'-'*5} {'-'*7} {'-'*7}  {'-'*70}")
    # 🔴 THE FLAG IS COMPUTED BY THE SHIPPED RULE, not re-derived from the raw fields.
    # The first version wrote `(cov and figs) or absent or meth` here - a second copy of the
    # scoring rule - and it disagreed with the real one immediately: after the year fix `r01`
    # printed "score=1" at the top and "<- THIS ONE FAILS" against the very claim that had
    # stopped failing, because the display was still reading the raw `figs` field while the
    # verdict came from _figures_ok(). Lesson 143 for the third time today: a re-implemented
    # rule is a rule that will disagree with itself.
    class _C:
        def __init__(self, t):
            (self.claim, self.ranges_over, self.context_covers_that_whole_set,
             self.input_figures_in_context, self.asserts_absence, self.is_methodology) = t

    for row_t in v["detail"]:
        claim, ranges, cov, figs, absent, meth = row_t
        c = _C(row_t)
        fails = not judges_scope._trivial(c) and not (
            c.context_covers_that_whole_set and judges_scope._figures_ok(c))
        flag = "   <- THIS ONE FAILS" if fails else ""
        note = ""
        if figs is False and judges_scope._figures_ok(c):
            note = "   (figures test waived: no figure in this claim)"
        print(f"  {str(cov):>6} {str(figs):>5} {str(absent):>7} {str(meth):>7}  "
              f"{claim[:70]}{flag}{note}")
        if flag or note:
            print(f"  {'':28}  ranges over: {ranges[:70]}")
            print(f"  {'':28}  FULL: {claim}")
    print(f"\n  spent ${telemetry.usd(calls):.5f}  (~Rs {telemetry.usd(calls)*88:.2f})")
    raise SystemExit(0)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    if "--inspect" in sys.argv:
        inspect(_arg("--inspect", "r01"), _arg("--gate", GATES[0]))
    if "--rescore" in sys.argv:
        rescore(here, _arg("--rescore", OUT))
    workers = int(_arg("--workers", "6"))

    import judges
    import judges_scope
    import telemetry
    telemetry.install(judges, judges_scope)
    assert not telemetry.unpatched(judges_scope), \
        "cost capture never reached judges_scope - this run would under-report to zero"
    assert hasattr(judges_scope, "HONOUR_METHODOLOGY"), \
        "judges_scope.py has no methodology switch - the edit did not land"

    from cross_set import CROSS_SET
    from golden_set import GOLDEN_SET
    from tesla_set import TESLA_SET
    questions = {i["id"]: i for s in (GOLDEN_SET, CROSS_SET, TESLA_SET) for i in s}

    # (source, row). The same id appears in both files - the 6.10 answer and the post-rule
    # answer - and they are DIFFERENT answers, so they are kept apart and labelled. Merging
    # them on id would silently compare one answer's verdict with another answer's.
    rows = []
    for g in GATES:
        p = os.path.join(here, g)
        if not os.path.exists(p):
            print(f"  (skipping {g} - not on disk)")
            continue
        for line in io.open(p, encoding="utf-8"):
            if line.strip():
                rows.append((g, json.loads(line)))
    if not rows:
        raise SystemExit("  no stored runs found - this probe never calls the agent.")

    print(f"\n  {len(rows)} stored answers from {len({g for g, _ in rows})} run file(s), "
          f"{workers} worker(s)")
    print(f"  scope judge only - no agent, no retrieval, no generation\n")

    def one(item):
        src, r = item
        q = questions.get(r["id"])
        if q is None:
            return None
        # capture() is thread-local by design, so the sink is opened inside the worker.
        with telemetry.capture() as calls:
            v = judges_scope.scope_judge(question=q["question"],
                                         prediction=r.get("answer") or "",
                                         context=r.get("context") or "")
        return {"src": src, "id": r["id"],
                # 🔴 STORE THE OBSERVATIONS, not just the verdicts. The first version of this
                # probe recorded three scores and nothing else, so when its single unexplained
                # mover needed reading, the detail had to be bought again. Then the year fix -
                # a pure CODE change - could not be re-scored offline either. The expensive
                # pass is the one that should record everything, because the cheap follow-up
                # is always the one you have not thought of yet. Same lesson as the observation
                # fingerprint, in a second costume, one day apart.
                "detail": v["detail"],
                "A_stored": r.get("scope"),
                "B_rule_off": v["score_without_methodology"],
                "C_rule_on": v["score"],
                "methodology_claims": v["methodology_claims"],
                "claims": v["claims"],
                "why": v["reasoning"][:300],
                "correct": r.get("correct"),
                "usd": telemetry.usd(calls)}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        res = [x for x in pool.map(one, rows) if x is not None]

    with io.open(os.path.join(here, OUT), "w", encoding="utf-8") as fh:
        for v in res:
            fh.write(json.dumps(v, ensure_ascii=False) + "\n")

    spent = sum(v["usd"] for v in res)
    main_run = [v for v in res if v["src"] == GATES[0]]
    n = len(main_run)

    def pct(k):
        s = sum(v[k] for v in main_run if v[k] is not None)
        return f"{s}/{n} = {s / max(1, n):.0%}"

    print(f"{'=' * 104}")
    print(f"  THE THREE-WAY DECOMPOSITION, on {GATES[0]} ({n} answers)")
    print(f"{'=' * 104}")
    print(f"  A  stored scope      (old prompt, old rule) : {pct('A_stored')}")
    print(f"  B  this run, rule OFF (NEW prompt, old rule) : {pct('B_rule_off')}"
          f"    <- what the extra prompt step did on its own")
    print(f"  C  this run, rule ON  (NEW prompt, new rule) : {pct('C_rule_on')}"
          f"    <- what the category then recovered")
    print(f"  answers containing at least one methodology claim: "
          f"{sum(1 for v in main_run if v['methodology_claims'])}/{n}")

    ab = [v for v in main_run if v["A_stored"] is not None and v["A_stored"] != v["B_rule_off"]]
    bc = [v for v in main_run if v["B_rule_off"] != v["C_rule_on"]]
    ac = [v for v in main_run if v["A_stored"] is not None and v["A_stored"] != v["C_rule_on"]]

    for label, movers, note in (
            ("A -> B  (the PROMPT change alone)", ab,
             "these moved because a sixth step was added, NOT because of the category"),
            ("B -> C  (the CATEGORY alone)", bc,
             "the rule only widens what counts as trivial, so every one of these is 0 -> 1"),
            ("A -> C  (net, stored vs today)", ac,
             "what a reader comparing the tracker with the next gate would see")):
        print(f"\n{'-' * 104}\n  {label}: {len(movers)}\n  {note}\n{'-' * 104}")
        for v in movers:
            print(f"  {v['id']:6} {v['A_stored']} -> {v['B_rule_off']} -> {v['C_rule_on']}"
                  f"   correct={v['correct']}  methodology_claims={v['methodology_claims']}")
            print(f"         {v['why'][:150]}")
        if not movers:
            print("  none")

    # --- the pre-registered conditions ----------------------------------------------------
    broke = [v for v in main_run if v["A_stored"] == 1 and v["C_rule_on"] == 0]
    d03_new = next((v for v in res
                    if v["id"] == "d03" and v["src"] == "eval_arith_check.jsonl"), None)

    print(f"\n{'=' * 104}")
    print(f"  PRE-REGISTERED CONDITIONS")
    print(f"{'=' * 104}")
    broke_ids = ", ".join(v["id"] for v in broke)
    print(f"  1. no stored 1 becomes 0            : "
          + ("PASS" if not broke else f"FAIL - {broke_ids}"))
    if d03_new is None:
        print(f"  2. d03 (post-rule answer) scores 1  : NOT TESTED - "
              f"eval_arith_check.jsonl is not on disk")
    else:
        print(f"  2. d03 (post-rule answer) scores 1  : "
              f"{'PASS' if d03_new['C_rule_on'] == 1 else 'FAIL'}"
              f"   (B={d03_new['B_rule_off']} -> C={d03_new['C_rule_on']}, "
              f"methodology_claims={d03_new['methodology_claims']})")
    print(f"  3. every mover printed above        : {len(ab) + len(bc)} movers, all listed")
    print(f"\n  spent: ${spent:.4f}  (~Rs {spent * 88:.1f})")
    print(f"  written: {OUT}")

    ok = (not broke) and (d03_new is None or d03_new["C_rule_on"] == 1)
    print(f"\n{'=' * 104}")
    if ok:
        print("  The category ships. Note what B says, though: if B differs from A, the extra")
        print("  prompt step moved verdicts BY ITSELF, and that effect is carried into the next")
        print("  gate whether or not the category is switched on.")
    else:
        print("  🔴 A pre-registered condition failed. Read the movers above before shipping.")
        print("     HONOUR_METHODOLOGY = False in judges_scope.py restores the old reading")
        print("     without reverting the prompt - which is NOT the same as reverting.")
    print(f"{'=' * 104}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
