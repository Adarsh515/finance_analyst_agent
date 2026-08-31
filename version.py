"""
version.py - Phase 7. One digest that changes whenever the thing that produces an answer
changes, and does not change otherwise.

THE DEFECT THIS EXISTS FOR, and it is a live one rather than a tidiness argument. The cache
key folds in `cache.index_fingerprint(agent.FILINGS)`, which is a digest of the (company,
period) pairs in the index and NOTHING ELSE. So today:

    edit the answer prompt      -> the fingerprint does not move -> every cached answer from
                                   the OLD prompt keeps being served, forever, silently
    change the model            -> same
    change MAX_ROUNDS or K_PER_JOB -> same
    rebuild the index with a different chunk_size, same six filings -> same

The last one is the sharpest, because the machinery to catch it was already written and never
wired: `index_fingerprint(filings, chunk_count=None)` takes a chunk count, and app.py has
always called it with one argument. A parameter that exists, is documented, and is never
passed is worse than one that was never written - it makes the file read as though the case
is handled.

AND THE SECOND HALF IS LLMOPS, not caching. `traces` records what an answer cost, which chunks
it used and which guard fired, and cannot answer "which prompt produced this?" A trace that
cannot be attributed to a configuration is a receipt with no date on it - fine while nothing
changes, useless the moment something does, which is exactly when the trace is wanted.

WHAT IS HASHED, and each entry is here because changing it can change an answer:

    answer_prompt    the template ACTUALLY SELECTED at import - which folds in GUARD_PROMPT
                     and SHOW_ARITHMETIC without hashing them separately
    plan_prompt      the planner
    reflect_prompt   Reflect
    rewrite_prompt   the follow-up rewriter, which decides what question is even asked
    model            id and temperature
    bounds           every number that shapes retrieval, from code, never from a prompt
    index            the filings AND the chunk count

WHAT IS DELIBERATELY NOT HASHED: `guards.HARDENED_PROMPT` when GUARD_PROMPT is False. It is
present in the tree and unused, and hashing an unused prompt would invalidate every cached
answer on an edit that cannot change a single one of them. A version that moves when nothing
moved trains people to ignore it.

    python version.py        # self-test: free, no model, no index, no network
"""

import hashlib
import json


def _digest(*parts):
    """Stable short digest. Deterministic ACROSS PROCESSES, which is the whole requirement.

    Python's hash() is salted per process and would give this file a different answer on every
    restart - a cache that misses everything after a redeploy, for no stated reason. sha256 of
    a canonical JSON encoding is boring and reproducible, and boring is the point.
    """
    blob = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def components(*, answer_prompt, plan_prompt, reflect_prompt, rewrite_prompt,
               model, temperature, bounds, filings, chunk_count):
    """Per-part digests. A dict, ordered, so that a change can be LOCATED and not just seen.

    One overall digest would say "something moved" - which is enough for the cache and useless
    for a person. Reporting the parts means /health answers "the answer prompt moved and the
    index did not" without anyone diffing two deployments by hand.
    """
    return {
        "answer_prompt":  _digest(answer_prompt),
        "plan_prompt":    _digest(plan_prompt),
        "reflect_prompt": _digest(reflect_prompt),
        "rewrite_prompt": _digest(rewrite_prompt),
        "model":          _digest(model, temperature),
        # sort_keys in _digest makes this independent of the order the caller built the dict.
        "bounds":         _digest(bounds),
        # sorted, because Chroma does not promise an order and an index digest that depends on
        # read order would change on its own - the worst kind of version, one that moves when
        # nothing did.
        "index":          _digest(sorted(map(list, filings)), chunk_count),
    }


def run_version(comps):
    """The single value that goes into the cache key and onto every trace row."""
    return _digest(comps)


def describe(comps):
    """One line per component, for /health and for a human reading a deployment."""
    return {"run_version": run_version(comps), **comps}


# --- self-test ---------------------------------------------------------------------------
# Free, and it imports nothing from the application: this file must be checkable without an
# index, without an API key and without loading langchain, or it cannot run in CI.

def _selftest():
    ok = 0
    base = dict(answer_prompt="ANSWER {context} {question}", plan_prompt="PLAN",
                reflect_prompt="REFLECT", rewrite_prompt="REWRITE",
                model="gemini-3.1-flash-lite", temperature=0,
                bounds={"MAX_JOBS": 6, "MAX_ROUNDS": 2, "K_PER_JOB": 10},
                filings=[("NVIDIA", "fiscal year 2026"), ("AMD", "fiscal year 2025")],
                chunk_count=2686)

    v0 = run_version(components(**base))

    # DETERMINISM FIRST. Every other assertion below is meaningless if the same inputs can
    # produce two answers, and a per-process hash would pass all of them individually.
    assert run_version(components(**base)) == v0, "the same inputs gave two versions"
    assert len(v0) == 12 and all(ch in "0123456789abcdef" for ch in v0), v0
    ok += 1

    # ORDER MUST NOT MATTER, for the two inputs that have no natural order. Chroma returns
    # metadata in whatever order it likes.
    shuffled = dict(base, filings=list(reversed(base["filings"])))
    assert run_version(components(**shuffled)) == v0, "the index digest depends on read order"
    reordered = dict(base, bounds={"K_PER_JOB": 10, "MAX_ROUNDS": 2, "MAX_JOBS": 6})
    assert run_version(components(**reordered)) == v0, "the bounds digest depends on dict order"
    ok += 1

    # EVERY INPUT MUST MOVE THE VERSION, checked one at a time. A loop rather than four
    # assertions, because the failure that matters is "one of them is not wired" and a
    # hand-written list is where that hides.
    changes = {
        "answer_prompt":  dict(base, answer_prompt="ANSWER {context} {question} "),
        "plan_prompt":    dict(base, plan_prompt="PLAN v2"),
        "reflect_prompt": dict(base, reflect_prompt="REFLECT v2"),
        "rewrite_prompt": dict(base, rewrite_prompt="REWRITE v2"),
        "model":          dict(base, model="gemini-3.5-flash"),
        "temperature":    dict(base, temperature=0.2),
        "bounds":         dict(base, bounds={"MAX_JOBS": 7, "MAX_ROUNDS": 2, "K_PER_JOB": 10}),
        "filings":        dict(base, filings=base["filings"] + [("Intel", "fiscal year 2025")]),
        # THE ONE THE OLD FINGERPRINT COULD NOT SEE. Same filings, re-chunked: retrieval
        # changes, answers change, and the cache used to hand back the old ones.
        "chunk_count":    dict(base, chunk_count=2687),
    }
    for name, changed in changes.items():
        v = run_version(components(**changed))
        assert v != v0, f"changing {name} did NOT change the run version"
        ok += 1

    # A trailing space in a prompt is a real edit and must count. Prompts are whitespace
    # sensitive in ways nobody predicts, so this file does not get to decide which edits are
    # cosmetic - the run above already covers it, and this names why it is not normalised.
    assert run_version(components(**dict(base, answer_prompt="ANSWER {context} {question}"))) == v0
    ok += 1

    # AND THE COMPONENTS MUST LOCALISE THE CHANGE, not merely differ somewhere. A digest that
    # changes every component when one input moved would be useless for saying what happened.
    c0 = components(**base)
    c1 = components(**changes["plan_prompt"])
    moved = [k for k in c0 if c0[k] != c1[k]]
    assert moved == ["plan_prompt"], f"changing the plan prompt moved {moved}"
    ok += 1

    d = describe(c0)
    assert d["run_version"] == v0 and d["index"] == c0["index"], d
    ok += 1

    print(f"version.py self-test: {ok}/{ok} checks passed, $0.00 spent")
    print("  Deterministic across processes, order-independent, and every input moves it -")
    print("  including the chunk count, which the old cache fingerprint never received.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
