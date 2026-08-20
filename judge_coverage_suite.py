"""
judge_coverage_suite.py - the mutation suite for judges_coverage.py, and the head-to-head that
had to come first.

ATTACK FIRST, THEN DEFEND, applied to a judge. Before the new judge is allowed to claim it
closes a hole, the EXISTING judges are run against the same labelled cases, so the hole is a
number rather than the single `x27` anecdote it started as. This is the order Phase 5 used on
the guards and Phase 4.5 used on the rubric judge, and both times the measurement changed the
plan - the rubric judge was killed by it.

A JUDGE IS PART OF THE SYSTEM UNDER TEST (tracker rule, Phase 4.5). So this judge gets its own
mutation suite exactly like the agent does, and the mutations are built the way that phase
learned to build them: **by editing REAL answers from a paid run**, not by writing synthetic
ones. A synthetic answer is written by someone who already knows what the judge should say
about it, which is how a suite ends up testing its author's intentions instead of the system.

Every case's context comes from eval_610_gate.jsonl - real retrieval, already paid for, never
re-fetched. Only the ANSWER is mutated, so a flipped verdict can have exactly one cause.

THE CONTROLS MATTER MORE THAN THE CATCHES, and there are four kinds:
  - a restricted set (`x06` names two companies; the corpus has four) must NOT be failed for
    the two it was never asked about
  - a complete ranking (`w01`, `x19`) must pass
  - a single-company question must come back N/A, not 1 - counting it as a pass would inflate
    this scoreboard every time an easy question was added
  - DECLINING to rank an incomplete set must PASS. That is the honest output, and a judge that
    punished every mention of a gap would push the system toward the confident guess it exists
    to discourage. This is the only control that tests the rule in the rewarding direction.

COST: about 25 model calls over contexts of 6k-20k characters. ~$0.03, call it Rs 2.5. No agent
runs, no retrieval, no generation - every answer already exists on disk.

WHAT THE FIRST RUN OF THIS SUITE FOUND, kept here because it is the argument for the suite.
It failed on `x27 REAL` - the one case the judge was built for - and it was the SPEC that was
wrong, not the model. Reporting a gap counts as accounting for a member, so an answer that says
"Tesla's margin is not stated" and then ranks the other three has, by the letter of the rule,
accounted for all four. What separates honest from broken is whether the gap is REAL, and that
is a question about the CONTEXT that no reading of the answer can settle. The judge now
escalates - one extra call, only on that shape, which occurred once in 102 answers - and this
file carries the control in both directions: a false gap that must fail, and a real one
(Tesla reports no Data Center segment) that must pass.

    python judge_coverage_suite.py                    # everything
    python judge_coverage_suite.py --new-only         # skip the old-judge head-to-head (~Rs 1)
"""

import io
import json
import os
import sys

GATE = "eval_610_gate.jsonl"


def load_gate(path=GATE):
    here = os.path.dirname(os.path.abspath(__file__))
    full = path if os.path.isabs(path) else os.path.join(here, path)
    if not os.path.exists(full):
        raise SystemExit(
            f"  {path} not found.\n"
            f"  This suite replays answers from a run that has ALREADY been paid for; it never\n"
            f"  calls the agent. Point it at any eval_*.jsonl that carries `answer` and\n"
            f"  `context`, or re-run the gate.")
    return {json.loads(l)["id"]: json.loads(l) for l in io.open(full, encoding="utf-8") if l.strip()}


def load_questions():
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    from cross_set import CROSS_SET
    from golden_set import GOLDEN_SET
    from tesla_set import TESLA_SET
    return {i["id"]: i for s in (GOLDEN_SET, CROSS_SET, TESLA_SET) for i in s}


# ------------------------------------------------------------------------------------------
# The mutations. Each takes the real stored answer and returns the edited one, so the diff is
# visible in this file rather than buried in a string constant.
# ------------------------------------------------------------------------------------------

def drop_a_line(answer, needle, renumber=False):
    """Remove the line naming one company. The cleanest possible positive control: the same
    answer, one member of the set removed, everything else byte-identical.

    renumber= closes a LEAK. Deleting item 2 from a numbered ranking leaves "1. 3. 4.", and a
    judge could then flag the case from the gap in the numbering rather than from the missing
    company - a check that passes for the wrong reason, which lesson 80 named and
    probe_scope_ab.py --recheck was written to catch. Renumbering makes the mutated answer look
    like a genuinely complete three-way ranking, so the ONLY available signal is the one under
    test.
    """
    kept = [ln for ln in answer.splitlines() if needle.lower() not in ln.lower()]
    out = "\n".join(kept)
    if out == answer:
        raise SystemExit(f"  mutation did nothing: no line mentions {needle!r}. The stored "
                         f"answer has changed shape and this case is now testing nothing.")
    if renumber:
        import re as _re
        n = 0
        fixed = []
        for ln in out.splitlines():
            m = _re.match(r"^(\s*)(\d+)\.\s", ln)
            if m:
                n += 1
                ln = _re.sub(r"^(\s*)\d+\.\s", rf"\g<1>{n}. ", ln, count=1)
            fixed.append(ln)
        out = "\n".join(fixed)
    return out


X27_FIXED_TAIL = (
    "*   **Tesla (fiscal year 2025):** Total gross margin was 18.0%.\n"
    "Comparing the stated gross margins, Tesla has the lowest gross margin at 18.0%. "
    "Tesla spent $6,411 million on research and development against revenue of $94,827 "
    "million, or about 6.8% of revenue.")

X27_DECLINED_TAIL = (
    "*   **Tesla (fiscal year 2025):** Not stated as a single percentage for the entire "
    "company.\n"
    "Because Tesla's company-wide gross margin is not stated, I cannot say which of these "
    "companies had the lowest gross margin, and therefore cannot report that company's R&D "
    "share of revenue.")


def rebuild_x19(answer, new_tail):
    """Replace x19's Tesla line and its conclusion, keeping the three real figures above."""
    lines = answer.splitlines()
    cut = next((i for i, ln in enumerate(lines) if "Tesla" in ln), None)
    if cut is None:
        raise SystemExit("  x19's stored answer no longer mentions Tesla - case is stale.")
    return "\n".join(lines[:cut]) + "\n" + new_tail


def rebuild_x27(answer, new_tail):
    """Keep the three margin lines the real answer got right, replace everything from the Tesla
    line onward. Preserves the real prose above it so the case is still a real answer."""
    lines = answer.splitlines()
    cut = next((i for i, ln in enumerate(lines) if "Tesla" in ln), None)
    if cut is None:
        raise SystemExit("  x27's stored answer no longer mentions Tesla - case is stale.")
    return "\n".join(lines[:cut]) + "\n" + new_tail


FALSE_GAP_TAIL = (
    "*   **Tesla (fiscal year 2025):** Research and development expense is not disclosed "
    "separately in the filing.\n"
    "Among the companies whose figures are stated, NVIDIA spent the most on research and "
    "development, with $18,497 million.")

# A question that is NOT in the eval set, because the eval set has no question whose metric is
# genuinely absent for one company - and without such a case the escalation branch would only
# ever be tested in the direction that punishes. Tesla reports no Data Center segment at all,
# so excluding it here is CORRECT and the judge has to say so. x21's context is reused because
# it already holds all four companies.
REAL_GAP_Q = ("Among the companies in these filings, which reported the largest Data Center "
              "segment revenue in its most recent fiscal year?")
REAL_GAP_ANSWER = (
    "Tesla does not report a Data Center segment, so it is not part of this comparison.\n"
    "*   **NVIDIA (fiscal year 2026):** Data Center revenue of $193,737 million\n"
    "*   **AMD (fiscal year 2025):** Data Center revenue of $16,635 million\n"
    "*   **Intel (fiscal year 2025):** Data Center revenue is not broken out in this filing.\n"
    "NVIDIA reported the largest Data Center segment revenue, at $193,737 million.")


def build_cases(gate):
    g = lambda qid: gate[qid]["answer"]
    return [
        # ---- the three real answers the 6.10 gate passed on every existing scoreboard -------
        ("x27 REAL - admitted Tesla's figure was missing, then crowned Intel anyway",
         "x27", g("x27"), 0, True),
        ("x20 REAL - ranks four by revenue, never accounts for Intel or Tesla",
         "x20", g("x20"), 0, True),
        ("x21 REAL - names the highest-margin company, never accounts for Intel or Tesla",
         "x21", g("x21"), 0, True),

        # ---- mutations: one member removed from an answer that was complete -----------------
        ("w01 MUTATED - the same complete ranking with Tesla's line deleted",
         "w01", drop_a_line(g("w01"), "Tesla", renumber=True), 0, True),
        ("x19 MUTATED - the same complete answer with Tesla's line deleted",
         "x19", drop_a_line(g("x19"), "Tesla"), 0, True),

        # ---- mutations: the two honest repairs of x27, which must both PASS ------------------
        ("x27 REPAIRED - Tesla's 18.0% supplied and Tesla named as lowest",
         "x27", rebuild_x27(g("x27"), X27_FIXED_TAIL), 1, False),
        ("x27 DECLINED - says the figure is missing and refuses to rank  [the honest output]",
         "x27", rebuild_x27(g("x27"), X27_DECLINED_TAIL), 1, False),

        # ---- controls: real answers that are already complete --------------------------------
        ("w01 REAL - a complete four-way ranking", "w01", g("w01"), 1, False),
        ("x19 REAL - all four R&D figures, then the winner", "x19", g("x19"), 1, False),

        # ---- control: a RESTRICTED set. The corpus has four; the question asked about two. ---
        # The single most important control here. A judge that merely counted corpus members
        # would fail this, and would then fail every two-company question in the eval set.
        ("x06 REAL - question names NVIDIA and AMD only; Intel and Tesla are irrelevant",
         "x06", g("x06"), 1, False),

        # ---- the ESCALATION branch, both directions ------------------------------------------
        # Added after the first run of this suite failed on x27 REAL. Reporting a gap COUNTS as
        # accounting for a member, and correctly so - so the rule passed the one defect it was
        # written for. What separates honest from broken is whether the gap is REAL, which is a
        # question about the context, and these two cases are the same shape with opposite
        # answers to it.
        ("x19 FALSE GAP - claims Tesla's R&D is not disclosed; the context holds $6,411M",
         "x19", rebuild_x19(g("x19"), FALSE_GAP_TAIL), 0, True),
        ("REAL GAP - Tesla reports no Data Center segment, so excluding it is CORRECT",
         "x21", REAL_GAP_ANSWER, 1, False, REAL_GAP_Q),

        # ---- controls: nothing to rank over --------------------------------------------------
        ("q01 REAL - a single-company question is N/A, not a pass", "q01", g("q01"), None, False),
        ("q25 REAL - a refusal to a single-company question", "q25", g("q25"), None, False),
    ]


def main():
    new_only = "--new-only" in sys.argv
    gate = load_gate()
    questions = load_questions()
    cases = build_cases(gate)

    # --only lets a change to ONE branch be measured for the cost of that branch. The
    # escalation was rewritten twice; re-running all fourteen cases each time would have spent
    # Rs 3 to re-confirm nine cases that could not have moved. The full suite is still what
    # licenses a ship - this is for the loop before it.
    if "--only" in sys.argv:
        needle = sys.argv[sys.argv.index("--only") + 1].lower()
        cases = [c for c in cases if needle in c[0].lower()]
        if not cases:
            raise SystemExit(f"  --only {needle!r} matched no case")
        print(f"\n  ⚠  --only {needle!r}: {len(cases)} of 14 cases. A PARTIAL run does not "
              f"license anything;\n     the full suite has to pass before this judge is "
              f"reported anywhere.")

    import judges
    import judges_coverage
    import judges_scope
    import telemetry

    # lesson 125's trap, sprung once already on the person who wrote it: judges_coverage and
    # judges_scope do `from judges import log_cost`, binding the function into their own
    # namespaces. Without install() the sink stays empty while real money is spent above it.
    telemetry.install(judges, judges_scope, judges_coverage)
    for m in (judges_scope, judges_coverage):
        assert not telemetry.unpatched(m), f"cost capture never reached {m.__name__}"

    print(f"\n  {len(cases)} labelled cases, every context replayed from {GATE}")
    print(f"  no agent run, no retrieval, no generation - only judges are called\n")

    rows = []
    with telemetry.capture() as calls:
        for case in cases:
            # A 6th element overrides the question. One case needs a question the eval set does
            # not contain, because no eval question has a metric that is genuinely absent for
            # one company - and without that case the escalation would only ever be tested in
            # the direction that punishes.
            name, qid, answer, expected, should_be_caught = case[:5]
            q = case[5] if len(case) > 5 else questions[qid]["question"]
            ctx = gate[qid]["context"]

            cov = judges_coverage.coverage_judge(question=q, prediction=answer, context=ctx)
            old_b = old_s = None
            if not new_only and should_be_caught:
                # Only the cases the new judge is SUPPOSED to catch are run past the old ones.
                # Running the controls through them too would cost more and prove nothing: the
                # question is not whether the old judges pass good answers, it is whether they
                # pass the bad ones.
                old_b = judges.groundedness_judge(question=q, prediction=answer, context=ctx)["score"]
                old_s = judges_scope.scope_judge(question=q, prediction=answer, context=ctx)["score"]

            rows.append((name, qid, expected, cov, old_b, old_s))

    spent = telemetry.usd(calls)

    print(f"{'=' * 108}")
    print(f"  {'case':58} {'exp':>4} {'cov':>4} {'esc':>4} {'bin':>4} {'scope':>6} {'AND':>4}  ")
    print(f"  {'-' * 58} {'-' * 4} {'-' * 4} {'-' * 4} {'-' * 4} {'-' * 6} {'-' * 4}  ----")
    ok = 0
    missed_by_old = 0
    caught_by_new = 0
    for name, qid, expected, cov, old_b, old_s in rows:
        got = cov["score"]
        good = got == expected
        ok += good
        old_and = None if old_b is None else (1 if (old_b and old_s) else 0)
        fmt = lambda v: "-" if v is None else str(v)
        print(f"  {name[:58]:58} {fmt(expected):>4} {fmt(got):>4} "
              f"{('yes' if cov.get('escalated') else '-'):>4} {fmt(old_b):>4} "
              f"{fmt(old_s):>6} {fmt(old_and):>4}  {'ok' if good else 'FAIL'}")
        if expected == 0:
            caught_by_new += (got == 0)
            if old_and == 1:
                missed_by_old += 1

    n_should_catch = sum(1 for r in rows if r[2] == 0)
    print(f"\n{'=' * 108}")
    print(f"  labelled cases passed : {ok}/{len(rows)}")
    print(f"  defect cases          : {n_should_catch}")
    print(f"    caught by coverage  : {caught_by_new}/{n_should_catch}")
    if not new_only:
        print(f"    MISSED by the existing groundedness AND : {missed_by_old}/{n_should_catch}"
              f"   <- the hole, as a number")
    print(f"  spent this run: ${spent:.6f}  (~Rs {spent * 88:.1f})")

    # Every escalation, pass or fail. The escalation is the branch that decides whether a
    # reported gap is real, it got that wrong on its first outing, and a branch whose working
    # is only printed when a case fails is a branch nobody audits.
    esc = [(n, c) for n, _q, _e, c, _b, _s in rows if c.get("escalated")]
    if esc:
        print(f"\n{'=' * 108}")
        print(f"  ESCALATIONS ({len(esc)}) - what the second call claimed, and what survived "
              f"the quote check")
        print(f"{'=' * 108}")
        for name, c in esc:
            print(f"  {name[:96]}")
            for line in c.get("exclusion_evidence") or []:
                print(f"    VERIFIED : {line}")
            for line in c.get("exclusion_rejected") or []:
                print(f"    🔴 {line}")
            if not (c.get("exclusion_evidence") or c.get("exclusion_rejected")):
                print(f"    nothing claimed - the reported gap is genuine")

    for name, qid, expected, cov, _b, _s in rows:
        if cov["score"] != expected:
            print(f"\n  FAILED: {name}")
            print(f"    expected {expected}, got {cov['score']}")
            print(f"    required : {cov['required']}")
            print(f"    engaged  : {cov['engaged']}")
            print(f"    missing  : {cov['missing']}   declined={cov['declined']}")
            print(f"    evidence : {cov.get('exclusion_evidence')}")
            print(f"    rejected : {cov.get('exclusion_rejected')}")
            print(f"    reasoning: {cov['reasoning']}")

    print(f"{'=' * 108}")
    if ok == len(rows):
        print("  Every labelled case scored as expected, controls included - a restricted-set")
        print("  question was not failed for members it never asked about, and DECLINING to")
        print("  rank an incomplete set passed, which is the behaviour this judge exists to")
        print("  reward rather than punish.")
        print("  This does NOT yet license the scoreboard. An AND owes a regression run and so")
        print("  does a new axis: probe_coverage_regression.py scores all 102 stored answers,")
        print("  and anything it newly flags has to be READ before this ships.")
    raise SystemExit(0 if ok == len(rows) else 1)


if __name__ == "__main__":
    main()
