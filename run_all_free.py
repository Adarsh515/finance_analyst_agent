"""
run_all_free.py - Phase 6.10. Every check in this repo that costs nothing, in one command.

WHY THIS EXISTS AT A GATE. Eighteen free checks are scattered across eighteen files, and running
them one at a time is what has actually happened all project - so the honest answer to "is the
repo consistent right now?" has always been "probably; I ran most of them". A gate needs ONE
number.

WHAT COUNTS AS FREE, and the line is drawn strictly: no generation call, no judge call. Two
scripts embed a query, which costs a fraction of a paisa at $0.15 per 1M tokens. They are
marked NEAR-FREE and their cost is stated rather than rounded away, because "free" is a claim
and this project has retracted enough of those.

WHAT IS DELIBERATELY NOT RUN HERE: run_eval.py, red_team.py, rewrite_eval.py, smoke_api.py,
smoke_cache.py, judge_coverage_suite.py and probe_coverage_regression.py. Those are the paid
gates and judge calibrations; they are run on purpose, by name, with their cost quoted first.
A "run everything" command that quietly spent Rs 25 would be exactly the kind of convenience
that erodes cost discipline.

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
    ("version.py",               False, "the run digest: deterministic, and every input moves it"),
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
    ("test_app.py",              False, "35 route checks against a stubbed agent"),
    ("test_server.py",           False, "6 checks against a real uvicorn thread pool"),
    ("probe_concurrency.py",     False, "12 simultaneous writes; the rate limit under a burst"),
    ("probe_telemetry_equiv.py", False, "the eval and the API record cost identically"),
    ("judges_scope.py",          True,  "figures/methodology rules; a year is not a figure"),
    ("judges_coverage.py",       True,  "the set-coverage scoring rule, no model called"),
    ("probe_arith.py --selftest", False, "arithmetic self-consistency: extractor + checker"),
    ("ci_gate.py --selftest",    False, "the merge gate, both directions, no files read"),
    ("test_mcp_server.py",       True,  "11 checks over real stdio JSON-RPC  [NEAR-FREE]"),
    ("probe_mcp_equivalence.py", True,  "MCP vs in-process, byte-identical    [NEAR-FREE]"),
]

# judges_coverage.py needs_index=True and it is worth saying why, because its self-test calls
# no model at all: it does `from rag import llm` at module level, and rag.py derives its
# company list from the index. The SCORING RULE is free and index-independent; the IMPORT is
# not. A file's cost and a file's dependencies are two different questions, and this list has
# already been wrong once about the first one.

SUBPROCESS_HEAVY = {"test_mcp_server.py", "probe_mcp_equivalence.py",
                    "test_server.py", "probe_concurrency.py"}

# The `script` field may include arguments; needs_index is checked against the file name.


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
        # An entry may carry arguments ("probe_arith.py --selftest"): its self-test is
        # index-free and gate-file-free on purpose, but its DEFAULT mode reads a stored run,
        # so the free list has to ask for the right one rather than hoping.
        parts = script.split()
        # 🔴 PYTHONIOENCODING, and this runner found the need for it BY FAILING TWO CHECKS THAT
        # PASS BY HAND. capture_output=True makes the child's stdout a PIPE, and on Windows
        # Python encodes a pipe with the LOCALE codec (cp1252) rather than the console's UTF-8.
        # So `python judges_scope.py` printed 10/10 in the terminal and the identical command
        # under this runner died on a 🔴 in a test-case name - UnicodeEncodeError, exit 1, a red
        # FAIL against a file with nothing wrong in it.
        #
        # That is lesson 124 inverted: usually the harness is SIMPLER than production and misses
        # things; here the harness is DIFFERENT from the terminal and invents things. Either way
        # the rule is the same - a check must run in the environment it is judged in. Forcing
        # UTF-8 on the child fixes the class rather than deleting one emoji, because the next
        # non-ASCII character anybody prints would land in exactly the same place.
        #
        # errors="replace" on the capture is a separate guard: a decode failure in the PARENT
        # must never be able to hide a real failure in the child.
        proc = subprocess.run([sys.executable, os.path.join(here, parts[0])] + parts[1:],
                              capture_output=True, text=True, cwd=here,
                              encoding="utf-8", errors="replace",
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})
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
    print("  smoke_cache.py, judge_coverage_suite.py, probe_coverage_regression.py - the paid")
    print("  gates and judge calibrations, run by name with their cost quoted first.")
    print(f"{'=' * 92}")


if __name__ == "__main__":
    main()
