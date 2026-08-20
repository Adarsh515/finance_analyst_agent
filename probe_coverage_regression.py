"""
probe_coverage_regression.py - run the coverage judge over every stored answer, then READ what
it flags.

WHY THIS IS NOT OPTIONAL. The tracker's rule from Phase 4.5 is "an AND is a promise you owe a
regression run", and the reasoning behind it applies to a new AXIS just as much: a judge
validated only on the twelve cases its author chose has been tested against its author. The
labelled suite proves the judge can catch what it was built to catch. This proves it does not
also catch ninety things it should not.

WHAT IS PRE-REGISTERED, written down BEFORE the run so the result cannot be rationalised
afterwards - the discipline Phase 4.2 used to cancel the calculator tool:

  * Every item this judge flags gets READ BY HAND. Not sampled. Flagged items are the whole
    output of this run; a count with nothing read behind it is not evidence.
  * If more than 25% of flagged items are false positives on reading, the judge does NOT ship
    as a reported scoreboard. It goes back to the prompt, or it is documented and dropped.
  * A flagged item that is CORRECT is not automatically a false positive. x20 and x21 are
    correct and are real findings - they assert a superlative over four companies while
    accounting for two. The question to ask while reading is not "is the answer right?" but
    "did the answer account for every member of the set the question ranges over?"

WHAT THIS RUN CANNOT TELL YOU. Whether the judge misses coverage failures that are in these
102 answers but that it scored 1. False negatives are invisible to a run with no labels, and
the only labels that exist are the twelve in judge_coverage_suite.py. Stated because the
number below would otherwise read as a completeness claim, which is exactly the class of
defect this whole judge is about.

COST: 102 judge calls over stored contexts (median ~9k chars). ~$0.09, call it Rs 8. No agent
run, no retrieval, no generation - every answer already exists on disk.

    python probe_coverage_regression.py                       # all 102, 6 workers
    python probe_coverage_regression.py --workers 1           # serial
    python probe_coverage_regression.py --rescore out.jsonl   # FREE: re-apply the rule to a
                                                              # finished run's observations
"""

import io
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

GATE = "eval_610_gate.jsonl"
OUT = "coverage_regression.jsonl"


def _arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def rescore(path):
    """Re-apply verdict_from() to a finished run's stored observations. Costs nothing.

    This is why the model returns observations and code computes the score: changing the rule
    re-scores a paid run for $0. probe_scope_ab.py --recorded established the pattern in 4.5;
    it has paid for itself every time the rule moved since.
    """
    import judges_coverage
    from judges_coverage import CoverageReport

    rows = [json.loads(l) for l in io.open(path, encoding="utf-8") if l.strip()]

    # Re-scoring stored observations is only valid if the thing that PRODUCED them has not
    # moved. Checked rather than remembered - "I did not change the prompt" is exactly the kind
    # of claim this project has had to retract before.
    now = judges_coverage.observation_fingerprint()
    stale = {r.get("prompt_fingerprint") for r in rows} - {now}
    if stale:
        print(f"\n  🔴 STOP. These observations were produced by a different prompt/schema.")
        print(f"     stored : {', '.join(str(s) for s in stale)}")
        print(f"     current: {now}")
        print(f"     Re-scoring them under today's rule would compare two different")
        print(f"     measurements and call the difference a finding. Re-run the regression.")
        raise SystemExit(1)

    changed = []
    for r in rows:
        if not r.get("raw_report"):
            continue
        new = judges_coverage.verdict_from(CoverageReport(**r["raw_report"]))
        if new["score"] != r["score"]:
            changed.append((r["id"], r["score"], new["score"], new["reasoning"]))
    print(f"\n  re-scored {len(rows)} stored observations under the CURRENT rule, for $0")
    print(f"  verdicts that moved: {len(changed)}")
    for qid, old, new, why in changed:
        print(f"    {qid:6} {old} -> {new}   {why[:80]}")
    if not changed:
        print("    none - the rule on disk agrees with the rule that produced this file")
    raise SystemExit(0)


def redo_escalations(here, gate_name, out_name):
    """Re-run ONLY the second call, on the handful of items that made one.

    The escalation is a SEPARATE model call from the observations, so changing it does not
    invalidate the observations - and the fingerprint check in rescore() is what lets that be
    asserted instead of assumed. On the 102-answer regression exactly one item escalated, so
    the alternative to this is paying Rs 6 to re-derive 101 rows that cannot have moved.

    Cost: one coverage-exclusion call per escalated item. Pennies.

    It refuses if the OBSERVATIONS are stale, because then the escalation is not the only thing
    that changed and a targeted redo would quietly mix two measurements.
    """
    import judges
    import judges_coverage
    import telemetry
    from judges_coverage import CoverageReport
    telemetry.install(judges, judges_coverage)
    assert not telemetry.unpatched(judges_coverage), "cost capture never reached the judge"

    out_path = os.path.join(here, out_name)
    rows = [json.loads(l) for l in io.open(out_path, encoding="utf-8") if l.strip()]
    now = judges_coverage.observation_fingerprint()
    stored = {r.get("prompt_fingerprint") for r in rows}
    stale = stored - {now}
    if stale:
        if stored == {None}:
            raise SystemExit(
                "  🔴 This file PREDATES the fingerprint, so nothing can vouch for it.\n"
                "     I believe the observation prompt has not changed since it was written -\n"
                "     but 'I believe' is exactly what the fingerprint was added to replace, and\n"
                "     it was added one run too late to cover this one. Re-run the full\n"
                "     regression (~Rs 6); it will stamp fingerprints, and every later change to\n"
                "     the escalation alone becomes a paisa-level redo instead.")
        raise SystemExit(
            f"  🔴 the OBSERVATIONS are stale ({', '.join(str(s) for s in stale)} vs {now}).\n"
            f"     Only the escalation can be redone in isolation. Re-run the full regression.")

    gate = {json.loads(l)["id"]: json.loads(l)
            for l in io.open(os.path.join(here, gate_name), encoding="utf-8") if l.strip()}

    todo = [r for r in rows if r.get("escalated") or r.get("needs_escalation")]
    print(f"\n  {len(todo)} of {len(rows)} rows made an escalation call. Redoing only those.")
    if not todo:
        raise SystemExit(0)

    moved, spent = [], 0.0
    for r in todo:
        v = CoverageReport(**r["raw_report"])
        ctx = gate[r["id"]]["context"]
        with telemetry.capture() as calls:
            fx, evidence, rejected = judges_coverage._check_exclusions(
                r["question"], ctx, v.members_called_unavailable)
        spent += telemetry.usd(calls)
        new = judges_coverage.verdict_from(v, false_exclusions=fx)
        before = r["score"]
        r.update(new)
        r["escalated"] = True
        r["exclusion_evidence"] = evidence
        r["exclusion_rejected"] = rejected
        print(f"\n  {r['id']}  score {before} -> {r['score']}")
        for line in evidence:
            print(f"    VERIFIED : {line}")
        for line in rejected:
            print(f"    🔴 {line}")
        print(f"    {r['reasoning'][:150]}")
        if before != r["score"]:
            moved.append((r["id"], before, r["score"]))

    with io.open(out_path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    app = [r for r in rows if r["applicable"]]
    flagged = [r for r in app if r["score"] == 0]
    print(f"\n{'=' * 96}")
    print(f"  verdicts that moved: {len(moved)}  {moved if moved else ''}")
    print(f"  coverage now: {len(app) - len(flagged)}/{len(app)} = "
          f"{100 * (len(app) - len(flagged)) / max(1, len(app)):.0f}%")
    print(f"  spent: ${spent:.4f}  (~Rs {spent * 88:.2f})  - against ~Rs 6 for a full re-run")
    print(f"  written: {out_name}")
    raise SystemExit(0)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)

    if "--rescore" in sys.argv:
        rescore(os.path.join(here, _arg("--rescore", OUT)))

    if "--redo-escalations" in sys.argv:
        redo_escalations(here, _arg("--gate", GATE), _arg("--redo-escalations", OUT))

    workers = int(_arg("--workers", "6"))
    gate_path = os.path.join(here, _arg("--gate", GATE))
    if not os.path.exists(gate_path):
        raise SystemExit(f"  {gate_path} not found - this replays a run already paid for.")

    from cross_set import CROSS_SET
    from golden_set import GOLDEN_SET
    from tesla_set import TESLA_SET
    questions = {i["id"]: i for s in (GOLDEN_SET, CROSS_SET, TESLA_SET) for i in s}

    import judges
    import judges_coverage
    import telemetry
    telemetry.install(judges, judges_coverage)
    assert not telemetry.unpatched(judges_coverage), \
        "cost capture never reached judges_coverage - this run would under-report to zero"

    rows = [json.loads(l) for l in io.open(gate_path, encoding="utf-8") if l.strip()]
    print(f"\n  {len(rows)} stored answers from {os.path.basename(gate_path)}, "
          f"{workers} worker(s)")
    print(f"  observation fingerprint: {judges_coverage.observation_fingerprint()}  "
          f"(prompt + schema; changes here are what force a re-run)")
    print(f"  judge only - no agent, no retrieval, no generation\n")

    def one(r):
        item = questions.get(r["id"])
        if item is None:
            return None
        # capture() is THREAD-LOCAL (telemetry.py, by design, so --workers stays correct), so
        # the sink has to be opened inside the worker. A capture opened in the main thread
        # would collect nothing and this script would proudly report $0.000000 - the exact
        # false report lesson 125 is about, and it has already happened once in this repo.
        with telemetry.capture() as calls:
            v = judges_coverage.coverage_judge(question=item["question"],
                                               prediction=r.get("answer") or "",
                                               context=r.get("context") or "")
        v["id"] = r["id"]
        v["prompt_fingerprint"] = judges_coverage.observation_fingerprint()
        v["set"] = r.get("set")
        v["question"] = item["question"]
        v["answer"] = r.get("answer")
        v["correct"] = r.get("correct")
        v["grounded_and"] = r.get("grounded_and")
        v["usd"] = telemetry.usd(calls)
        return v

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = [v for v in pool.map(one, rows) if v is not None]

    with io.open(os.path.join(here, OUT), "w", encoding="utf-8") as fh:
        for v in results:
            fh.write(json.dumps(v, ensure_ascii=False) + "\n")

    spent = sum(v["usd"] for v in results)
    applicable = [v for v in results if v["applicable"]]
    flagged = [v for v in applicable if v["score"] == 0]
    declined = [v for v in applicable if v["declined"]]

    print(f"{'=' * 104}")
    print(f"  scored     : {len(results)}")
    print(f"  applicable : {len(applicable)}  (the rest do not rank or aggregate over a set)")
    print(f"  coverage   : {len(applicable) - len(flagged)}/{len(applicable)} = "
          f"{100 * (len(applicable) - len(flagged)) / max(1, len(applicable)):.0f}%"
          f"   <- a NEW axis, reported beside correctness and groundedness, never averaged")
    print(f"  declined to rank rather than guess: {len(declined)}")
    print(f"  spent: ${spent:.4f}  (~Rs {spent * 88:.1f})")
    print(f"  written: {OUT}   (re-score for free with --rescore)")

    print(f"\n{'=' * 104}")
    print(f"  EVERY FLAGGED ITEM, FOR READING. {len(flagged)} of them. "
          f"Pre-registered: >25% false positives and this does not ship.")
    print(f"{'=' * 104}")
    for v in sorted(flagged, key=lambda x: (x["correct"] or 0, x["id"])):
        print(f"\n  {v['id']}   correct={v['correct']}  groundedness_AND={v['grounded_and']}"
              f"   <- both existing scoreboards' verdicts, for contrast")
        print(f"    Q        : {v['question'][:96]}")
        print(f"    required : {v['required']}")
        print(f"    engaged  : {v['engaged']}")
        print(f"    missing  : {v['missing']}"
              + ("   AND IT SAID SO, then ranked anyway" if v["acknowledged"] else ""))
        first = (v["answer"] or "").strip().splitlines()
        print(f"    answer   : {first[0][:96] if first else ''}")
    if not flagged:
        print("  none")

    # The contrast that justifies the axis existing at all: how many of the flagged items were
    # already visible to something? If every one of them also fails correctness, this judge is
    # redundant and should be dropped rather than reported.
    novel = [v for v in flagged if v["correct"] == 1 and v["grounded_and"] == 1]
    print(f"\n{'=' * 104}")
    print(f"  flagged and ALREADY failing correctness      : "
          f"{sum(1 for v in flagged if v['correct'] == 0)}")
    print(f"  flagged while passing correctness AND groundedness: {len(novel)}"
          f"   <- what no existing scoreboard could see")
    if flagged and not novel:
        print("  🟡 Every flagged item was already caught by correctness. This axis adds no")
        print("     information over what the eval already reports - drop it rather than ship")
        print("     a scoreboard that only restates another one.")
    print(f"{'=' * 104}")
    print("  NOW READ THE FLAGGED ITEMS. A count with nothing read behind it is not evidence,")
    print("  and this judge exists because three answers passed three scoreboards unread.")


if __name__ == "__main__":
    main()
