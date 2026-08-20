"""
run_all_free.py - Phase 6.10. Every check in this repo that costs nothing, in one command.

WHY THIS EXISTS AT A GATE. Fifteen free checks are scattered across fifteen files, and running
them one at a time is what has actually happened all project - so the honest answer to "is the
repo consistent right now?" has always been "probably; I ran most of them". A gate needs ONE
number.

WHAT COUNTS AS FREE, and the line is drawn strictly: no generation call, no judge call. Two
scripts embed a query, which costs a fraction of a paisa at $0.15 per 1M tokens. They are
marked NEAR-FREE and their cost is stated rather than rounded away, because "free" is a claim
and this project has retracted enough of those.

WHAT IS DELIBERATELY NOT RUN HERE: run_eval.py, red_team.py, rewrite_eval.py, smoke_api.py and
smoke_cache.py. Those are the paid gates; they are run on purpose, by name, with their cost
quoted first. A "run everything" command that quietly spent Rs 25 would be exactly the kind of
convenience that erodes cost discipline.

...and judges.py, WHICH THIS SCRIPT CAUGHT ON ITS FIRST RUN. It was in the free list because
it looks like a self-test from the outside - it prints scores and pass marks - and its
`__main__` is actually a judge CALIBRATION that sends real questions to a real model. Fifteen
files had been run by hand for weeks and nobody had noticed one of them was billing. That is
the argument for a single command, made by the command itself.

    python run_all_free.py            # all of them
    python run_all_free.py --quick    # skip the three that need a subprocess or an index
"""

import os
import subprocess
import sys
import time

# (script, needs_index, note). needs_index=True means it degrades to a SKIP without a built
# index rather than failing - a fresh clone should still be able to run this.
CHECKS = [
    ("db.py",                    False, "schema, migrations, cascade, spend"),
    ("cache.py",                 False, "keys, refusals, fingerprint, purge"),
    ("telemetry.py",             False, "capture, pricing, thread isolation"),
    ("corpus_facts.py",          False, "every figure traced to a verified set"),
    ("auth.py",                  False, "argon2, rate limit, timing control arm"),
    ("guards.py",                False, "fence, scrub, leak detection"),
    ("attacks.py",               False, "the attack set checks itself"),
    ("rewrite_set.py",           False, "25 items, ids unique across all three sets"),
    ("tesla_set.py",             False, "8 items, evidence supports every figure"),
    ("rewriter.py",              False, "bounds, cleaner, future-period rule"),
    ("test_app.py",              False, "29 route checks against a stubbed agent"),
    ("test_server.py",           False, "6 checks against a real uvicorn thread pool"),
    ("probe_telemetry_equiv.py", False, "the eval and the API record cost identically"),
    ("test_mcp_server.py",       True,  "11 checks over real stdio JSON-RPC  [NEAR-FREE]"),
    ("probe_mcp_equivalence.py", True,  "MCP vs in-process, byte-identical    [NEAR-FREE]"),
]

SUBPROCESS_HEAVY = {"test_mcp_server.py", "probe_mcp_equivalence.py", "test_server.py"}


def main():
    quick = "--quick" in sys.argv
    here = os.path.dirname(os.path.abspath(__file__))

    have_index = True
    try:
        sys.path.insert(0, here)
        import agent
        have_index = bool(agent.FILINGS)
    except Exception as e:
        print(f"  could not import agent to check the index: {e}")
        have_index = False

    print(f"\n  {len(CHECKS)} free checks" + ("  (--quick: skipping subprocess ones)" if quick else ""))
    print(f"  index: {'present' if have_index else 'EMPTY - index-dependent checks will skip'}\n")
    print(f"  {'script':28} {'result':>8}  {'s':>5}  what it covers")
    print(f"  {'-'*28} {'-'*8}  {'-'*5}  {'-'*46}")

    passed = failed = skipped = 0
    failures = []
    t_all = time.perf_counter()

    for script, needs_index, note in CHECKS:
        if quick and script in SUBPROCESS_HEAVY:
            print(f"  {script:28} {'skip':>8}  {'':>5}  {note}")
            skipped += 1
            continue
        if needs_index and not have_index:
            print(f"  {script:28} {'skip':>8}  {'':>5}  needs a built index")
            skipped += 1
            continue

        t = time.perf_counter()
        proc = subprocess.run([sys.executable, os.path.join(here, script)],
                              capture_output=True, text=True, cwd=here)
        secs = time.perf_counter() - t
        if proc.returncode == 0:
            print(f"  {script:28} {'ok':>8}  {secs:5.1f}  {note}")
            passed += 1
        else:
            print(f"  {script:28} {'FAIL':>8}  {secs:5.1f}  {note}")
            failed += 1
            failures.append((script, proc))

    total = time.perf_counter() - t_all
    print(f"\n{'=' * 92}")
    print(f"  {passed} passed, {failed} failed, {skipped} skipped, in {total:.0f}s")

    # A failing check's OUTPUT is the point. Printing only "3 failed" makes the reader run
    # them again one at a time, which is the work this script was written to remove.
    for script, proc in failures:
        print(f"\n{'-' * 92}\n  {script} FAILED (exit {proc.returncode})\n{'-' * 92}")
        tail = (proc.stdout or "").strip().splitlines()[-15:]
        err = (proc.stderr or "").strip().splitlines()[-20:]
        for line in tail:
            print(f"  {line}")
        if err:
            print("  --- stderr ---")
            for line in err:
                print(f"  {line}")

    if failed:
        print(f"\n{'=' * 92}")
        print("  The repo is NOT internally consistent. Fix these before paying for a gate:")
        print("  a paid run against a broken tree measures the wrong system.")
        raise SystemExit(1)

    print("  Every free check passes. Two of them embed a query (a fraction of a paisa);")
    print("  nothing here called a generation model or a judge.")
    print("  NOT run here, on purpose: run_eval.py, red_team.py, rewrite_eval.py, smoke_api.py,")
    print("  smoke_cache.py - the paid gates, run by name with their cost quoted first.")
    print(f"{'=' * 92}")


if __name__ == "__main__":
    main()
