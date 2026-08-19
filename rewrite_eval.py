# rewrite_eval.py
# Phase 6.4 - run the 22-item rewrite set and score it mechanically.
#
# COST: one cheap call per item. 22 items at roughly 900 in / 30 out is about $0.003 - call it
# Rs 0.30 for the whole set, which is the point of grading with substrings instead of a judge.
# It is cheap enough to run on every change, and a measurement people avoid because it is
# expensive stops being a measurement.
#
# TWO SCOREBOARDS, NEVER AVERAGED - the same rule this project applies to regression and
# capability. A rewriter has two jobs that fail in opposite directions:
#
#   REWRITE      14 items whose raw question does NOT pass. Did it fill in what was missing?
#   DO-NO-HARM    8 items whose raw question ALREADY passes. Did it leave them alone?
#
# One number over all 22 would let a timid rewriter that changes nothing score 8/22 and look
# like a weak rewriter, when it is actually a perfect do-no-harm and a total rewrite failure.
# Those are different defects with different fixes.
#
#   python -X utf8 -u rewrite_eval.py
#   python -X utf8 -u rewrite_eval.py --ids rw05,rw12 --repeat 3

import argparse
import json
import os
import time

from dotenv import load_dotenv

import agent          # for FILINGS only - the rewriter needs to know which fiscal
                      # years the corpus actually holds, or it will name one it does not
import judges
import rag
import rewriter
import telemetry
from rewrite_set import REWRITE_SET, score

load_dotenv()

_patched = telemetry.install(judges, rag, rewriter)
assert "rewriter" in _patched or getattr(rewriter, "log_cost", None) is not judges.log_cost, \
    f"cost tracking did not reach rewriter: {_patched}"

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--ids", default="", help="comma-separated item ids; default is all")
parser.add_argument("--bucket", default="", help="run one bucket only")
parser.add_argument("--repeat", type=int, default=1,
                    help="run each item N times. Generation is not deterministic (lesson 64), "
                         "so a single run of a borderline item measures the generator.")
parser.add_argument("--out", default="", help="append every result as JSONL")
parser.add_argument("--append", action="store_true",
                    help="allow --out to append to a file that already holds records")


def _guard_out_path(path, append):
    """Same refusal as run_eval.py and red_team.py. A duplicated run cost Rs 45 once."""
    if not path or append:
        return
    if os.path.exists(path) and os.path.getsize(path) > 0:
        n = sum(1 for _ in open(path, encoding="utf-8"))
        raise SystemExit(f"\nREFUSING TO RUN: {path} already holds {n} records.\n"
                         f"Use a new --out name, or pass --append.\n")


if __name__ == "__main__":
    args = parser.parse_args()
    _guard_out_path(args.out, args.append)

    items = REWRITE_SET
    if args.ids:
        want = {i.strip() for i in args.ids.split(",") if i.strip()}
        items = [i for i in items if i["id"] in want]
    if args.bucket:
        items = [i for i in items if i["bucket"] == args.bucket]
    assert items, "no items selected"

    plan = [i for i in items for _ in range(args.repeat)]
    print(f"\n{'=' * 100}")
    print(f"REWRITE EVAL - {len(items)} items x {args.repeat}")
    print(f"{'=' * 100}\n")
    print(f"  {'id':6} {'bucket':11} {'kind':11} {'ok':4} {'s':>5}  rewritten")

    results = []
    fh = open(args.out, "a", encoding="utf-8") if args.out else None
    for item in plan:
        t0 = time.perf_counter()
        with telemetry.capture() as calls:
            try:
                # The eval measures the SHIPPED rewriter, so it gets the same corpus
                # knowledge the product gives it. Without this, rw23 and rw24 would keep
                # failing here while passing in the app - a harness measuring a system
                # nobody runs.
                out, note = rewriter.rewrite(item["question"], item["history"],
                                             filings=agent.FILINGS)
                err = None
            except Exception as e:                       # infra, not a rewrite failure
                out, note, err = item["question"], "ERROR", f"{type(e).__name__}: {e}"
        secs = time.perf_counter() - t0
        passed, why = score(item, out)
        kind = "do-no-harm" if item.get("raw_ok") else "rewrite"
        row = {"id": item["id"], "bucket": item["bucket"], "kind": kind,
               "question": item["question"], "rewritten": out, "note": note,
               "passed": passed, "why": why, "error": err,
               "seconds": round(secs, 2), **telemetry.summarise(calls, "rewrite")}
        results.append(row)
        if fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
        mark = "ok" if passed else "FAIL"
        print(f"  {item['id']:6} {item['bucket']:11} {kind:11} {mark:4} {secs:5.1f}  "
              f"{out[:80]}")
        if not passed:
            print(f"         {why}")
            print(f"         was: {item['question'][:80]}")
    if fh:
        fh.close()

    # --- stability, when asked ------------------------------------------------------------
    if args.repeat > 1:
        seen = {}
        for r in results:
            seen.setdefault(r["id"], []).append(r["passed"])
        print(f"\n{'=' * 100}\n  STABILITY over {args.repeat} runs\n{'=' * 100}")
        for i, vs in seen.items():
            flip = len(set(vs)) > 1
            print(f"  {i:6} passed={vs}  "
                  f"{'UNSTABLE - generator variance, not a rewriter verdict' if flip else 'stable'}")

    # --- the two scoreboards, side by side, never added together ----------------------------
    print(f"\n{'=' * 100}\n  RESULTS\n{'=' * 100}")
    for kind in ("rewrite", "do-no-harm"):
        rows = [r for r in results if r["kind"] == kind]
        if not rows:
            continue
        n_ok = sum(r["passed"] for r in rows)
        print(f"\n  {kind.upper():12} {n_ok}/{len(rows)}")
        by_bucket = {}
        for r in rows:
            b = by_bucket.setdefault(r["bucket"], [0, 0])
            b[0] += r["passed"]
            b[1] += 1
        for b, (o, n) in sorted(by_bucket.items()):
            fails = [r["id"] for r in rows if r["bucket"] == b and not r["passed"]]
            print(f"    {b:11} {o}/{n}   {', '.join(sorted(set(fails))) or '-'}")

    errs = [r["id"] for r in results if r["error"]]
    if errs:
        print(f"\n  INFRA ERRORS on {sorted(set(errs))} - these scored nothing")

    # Three different things used to be reported as one, and the report said something
    # untrue about two of them: rw22 was listed as "the cleaner rejected the model's output"
    # when in fact no model was called at all. A report that misattributes a cause sends the
    # next hour to the wrong file.
    #
    # 🔴 AND IT HAPPENED AGAIN, in Phase 6.8, for the same structural reason. The fix above
    # named two cases and left a CATCH-ALL that assumed everything else was a cleaner
    # rejection. When drop_future_period() started returning a note, rw05, rw21, rw23 and rw24
    # were all reported as "the cleaner rejected the model's output and kept the original" -
    # untrue: the rewrite happened and was used, and only a future fiscal year was removed
    # from it. A default branch that ASSERTS a cause is a misattribution waiting for the next
    # note to be added. Unrecognised notes are now reported as unrecognised.
    def _note_kind(note):
        if not note:
            return None
        if note.startswith("acknowledgement"):
            return "short-circuited before the model (no call, no cost)"
        if note.startswith("history-guard"):
            return "the history guard dropped a turn"
        if note.startswith("dropped future period"):
            return ("a fiscal year later than that company's newest filing was removed "
                    "(the rewrite itself was used)")
        if note.startswith(("empty", "too long")):
            return "the cleaner rejected the model's output and kept the original"
        if note == "no-history":
            return None
        return f"UNCLASSIFIED note - add it to _note_kind: {note[:60]!r}"

    kinds = {}
    for r in results:
        k = _note_kind(r["note"])
        if k:
            kinds.setdefault(k, set()).add(r["id"])
    for kind, who in sorted(kinds.items()):
        print(f"\n  {kind}: {sorted(who)}")
        if kind.startswith("the cleaner"):
            print("  That is the safe direction, and it is also a rewrite that did not "
                  "happen - check it is not happening silently.")

    total = sum(r["usd"] for r in results)
    tok_in = sum(r["input_tokens"] for r in results)
    # Items, not calls. An item that short-circuits makes no call, and counting it as one
    # would quietly overstate what the rewriter costs - in the direction that flatters it
    # least, but wrong either way.
    paid = sum(1 for r in results if r["input_tokens"] > 0)
    print(f"\n  {len(results)} items, {paid} paid calls   {tok_in:,} input tokens   "
          f"${total:.5f}   (~Rs {total * 88:.2f})")
    print(f"  per PAID rewrite: ${total / max(paid, 1):.6f} - this is added to every "
          f"follow-up question that reaches the model.")
