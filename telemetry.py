# telemetry.py
# Phase 6.3 - the per-call token and cost capture, extracted so that the eval harness and the
# API record answers the SAME way.
#
# WHY THIS FILE EXISTS. run_eval.py has captured every paid call since Phase 4.5 by wrapping
# judges.log_cost. The API needs exactly that record to fill the `traces` and `trace_calls`
# tables the UI reads. Writing a second capture in app.py would be the cheapest possible way
# to make the product and the measurement disagree - two implementations of one definition,
# drifting quietly, each self-consistent. So there is one implementation and both import it.
#
# THE MECHANISM, and the sharp edge in it. Every module in this repo does
# `from judges import log_cost`, which binds the function object into THAT module's namespace.
# Rebinding judges.log_cost afterwards changes nothing for them. So install() must re-point
# every importing module by name, and it returns the list of modules it actually patched so
# the caller can assert on it. A capture that silently reaches three of five modules would
# under-report cost and look exactly like a cheap system.
#
# Free: no API key, no network. `python telemetry.py` proves the capture is faithful.

import threading
from contextlib import contextmanager

import judges

# Thread-local, so run_eval.py's --workers > 1 stays correct: two questions answered
# concurrently must not pour their calls into one bucket.
_state = threading.local()

_ORIGINAL_LOG_COST = judges.log_cost


def _tracked_log_cost(model, response, label=""):
    sink = getattr(_state, "sink", None)
    if sink is not None:
        u = getattr(response, "usage_metadata", None) or {}
        sink.append((label,
                     u.get("input_tokens", 0) or 0,
                     u.get("output_tokens", 0) or 0,
                     model))
    return _ORIGINAL_LOG_COST(model, response, label=label)


def install(*modules):
    """Re-point log_cost inside each module that imported it by name. Returns those patched.

    Idempotent: a module already pointing at the tracked version is skipped, so importing
    this from two places cannot double-count.

    NOTE what this return value is and is NOT. It reports what this CALL changed, not what
    is now true. On a second call it is correctly empty - and a caller that asserts on its
    length reads "nothing was patched" as "nothing is patched", which is the opposite of the
    truth. Assert on unpatched() instead; see the comment there.
    """
    patched = []
    for mod in modules:
        if mod is not None and getattr(mod, "log_cost", None) is _ORIGINAL_LOG_COST:
            mod.log_cost = _tracked_log_cost
            patched.append(mod.__name__)
    return patched


def unpatched(*modules):
    """Return the names of modules whose log_cost is NOT the tracked one. Empty means safe.

    This is the postcondition the callers actually care about: "every module that can make a
    paid call routes through the capture". install()'s return value is a DIFF - what changed
    this time - and a diff is worthless as a safety check the moment the work has already
    been done by someone else.

    That distinction was not academic. `python app.py` executes app.py once as `__main__`,
    then uvicorn imports it AGAIN as `app`; the second pass patched nothing because the first
    pass had already patched everything, and `assert len(install(...)) >= 3` killed a fully
    correct process at start-up. Checking state instead of change fixes that AND still catches
    the original danger - a module silently missed, under-reporting cost - by NAME.
    """
    return [mod.__name__ for mod in modules
            if mod is not None and getattr(mod, "log_cost", None) is not _tracked_log_cost]


@contextmanager
def capture():
    """Collect every paid call made inside the block into a list.

    Nests correctly: an inner capture takes the calls and the outer one resumes empty-handed
    for that span. That is the behaviour the eval wants - product calls and judge calls are
    two buckets, never one - and it is why this is a context manager rather than a pair of
    assignments a caller has to remember to unwind in the right order.
    """
    previous = getattr(_state, "sink", None)
    sink = []
    _state.sink = sink
    try:
        yield sink
    finally:
        _state.sink = previous


def usd(calls):
    """Price a list of captured calls. One pricing table, judges.PRICES, for everything."""
    total = 0.0
    for _label, intok, outok, model in calls:
        p_in, p_out = judges.PRICES.get(model, (0.0, 0.0))
        total += (intok * p_in + outok * p_out) / 1_000_000
    return total


def rows_for_db(calls):
    """Shape captured calls for db.save_trace(): (label, in, out, model, usd) per call.

    The per-call price is computed here from the same table used for the totals, so the
    trace panel's line items and its header can only ever be two views of one number.
    """
    out = []
    for label, intok, outok, model in calls:
        p_in, p_out = judges.PRICES.get(model, (0.0, 0.0))
        out.append((label, intok, outok, model,
                    (intok * p_in + outok * p_out) / 1_000_000))
    return out


def summarise(calls, generation_label="generation"):
    """The numbers run_eval.py reports per question, computed in one place.

    `gen_in` is isolated because it is the ONLY figure comparable with the pre-4.4 baseline
    (368,502 input tokens over 97 calls), recorded before planner and Reflect tokens were
    logged separately. Every later comparison in PROJECT_TRACKER.md is against that number,
    so its definition - substring match on the call label - is pinned here rather than
    re-typed at each call site.
    """
    return {
        "gen_in": sum(i for lab, i, _o, _m in calls if generation_label in lab),
        "gen_calls": sum(1 for lab, _i, _o, _m in calls if generation_label in lab),
        "input_tokens": sum(i for _l, i, _o, _m in calls),
        "output_tokens": sum(o for _l, _i, o, _m in calls),
        "usd": usd(calls),
    }


# --- self-test ------------------------------------------------------------------------------
# Proves the capture is faithful WITHOUT making a paid call, by pushing fake response objects
# through log_cost exactly as the real code does.

if __name__ == "__main__":
    import types

    class FakeResponse:
        def __init__(self, intok, outok):
            self.usage_metadata = {"input_tokens": intok, "output_tokens": outok}

    ok = 0
    M = "gemini-3.1-flash-lite"

    # a module that did `from judges import log_cost` - the case that makes this hard
    fake_mod = types.ModuleType("fake_agent")
    fake_mod.log_cost = judges.log_cost
    assert install(fake_mod) == ["fake_agent"], "install() did not patch an importing module"
    assert install(fake_mod) == [], "install() is not idempotent - it would double-count"
    ok += 1

    # ...and the difference between "nothing changed" and "nothing is installed", which is the
    # bug that took the API down at start-up. install() returning [] above must NOT mean the
    # module is unprotected - unpatched() is the check that can tell those two apart.
    assert unpatched(fake_mod) == [], "unpatched() called a patched module unpatched"
    missed = types.ModuleType("forgotten_mod")
    missed.log_cost = judges.log_cost              # imported it, never passed to install()
    assert unpatched(fake_mod, missed) == ["forgotten_mod"], \
        "unpatched() did not name a module that would under-report cost"
    ok += 1

    with capture() as calls:
        fake_mod.log_cost(M, FakeResponse(900, 120), label="agent-plan")
        fake_mod.log_cost(M, FakeResponse(3736, 210), label="agent-generation")
    assert calls == [("agent-plan", 900, 120, M), ("agent-generation", 3736, 210, M)]
    ok += 1

    # outside a capture, nothing is collected and nothing throws - the API must be able to
    # call the same code paths without a sink installed
    fake_mod.log_cost(M, FakeResponse(1, 1), label="uncaptured")
    assert getattr(_state, "sink", None) is None
    ok += 1

    # nesting: the inner block takes its own calls, the outer keeps only what it saw itself
    with capture() as outer:
        fake_mod.log_cost(M, FakeResponse(10, 1), label="outer-a")
        with capture() as inner:
            fake_mod.log_cost(M, FakeResponse(20, 2), label="inner")
        fake_mod.log_cost(M, FakeResponse(30, 3), label="outer-b")
    assert [c[0] for c in outer] == ["outer-a", "outer-b"]
    assert [c[0] for c in inner] == ["inner"]
    ok += 1

    # pricing matches judges.PRICES, and the per-call rows sum to the total. These are the
    # two numbers the trace panel shows side by side; if they can disagree, one of them lies.
    p_in, p_out = judges.PRICES[M]
    expect = ((900 * p_in + 120 * p_out) + (3736 * p_in + 210 * p_out)) / 1_000_000
    assert abs(usd(calls) - expect) < 1e-15
    assert abs(sum(r[4] for r in rows_for_db(calls)) - usd(calls)) < 1e-15
    ok += 1

    s = summarise(calls)
    assert s["gen_in"] == 3736 and s["gen_calls"] == 1
    assert s["input_tokens"] == 4636 and s["output_tokens"] == 330
    ok += 1

    # thread isolation - run_eval.py runs 6 questions at once and their costs must not mix
    import threading as _t
    seen = {}

    def worker(n):
        with capture() as mine:
            for _ in range(20):
                fake_mod.log_cost(M, FakeResponse(n, n), label=f"w{n}")
        seen[n] = mine

    ts = [_t.Thread(target=worker, args=(i,)) for i in range(1, 7)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    for n, got in seen.items():
        assert len(got) == 20 and {c[1] for c in got} == {n}, \
            f"FAIL: thread {n} collected another thread's calls - buckets are not isolated"
    ok += 1

    # an unpriced model must cost 0.0 and must NOT raise - a new model id appearing in a log
    # should show up as a suspicious zero, not as a crashed run that loses paid answers
    assert usd([("x", 100, 100, "some-future-model")]) == 0.0
    ok += 1

    print(f"telemetry.py self-test: {ok}/{ok} checks passed, $0.00 spent")
