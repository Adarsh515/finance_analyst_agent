# probe_telemetry_equiv.py
# Phase 6.3 - prove that moving the cost capture out of run_eval.py into telemetry.py did not
# change what gets captured.
#
# WHY A PROBE AND NOT "JUST RE-RUN THE EVAL". Generation is not deterministic (lesson 64: five
# identical calls once produced two different answers), so two full runs would differ in token
# counts for reasons that have nothing to do with this refactor. A re-run therefore cannot
# distinguish "the extraction changed the numbers" from "the model answered differently" -
# which is the same trap as comparing two measurements in different units.
#
# So this compares the MECHANISM instead, deterministically and for free: the pre-refactor
# capture code is pasted below verbatim, the identical sequence of fake calls is pushed
# through both, and the outputs must match exactly.
#
# WHAT THIS DOES NOT PROVE: that run_eval.py still WIRES the capture correctly - that the
# context managers open and close around the right regions. That is plumbing, it needs the
# real harness, and it is checked by one 3-question --ids run costing about a rupee.

import threading

import judges
import telemetry

# --- the OLD implementation, copied verbatim from run_eval.py before the extraction ---------
_calls = threading.local()
_ORIGINAL_LOG_COST = judges.log_cost


def _tracked_log_cost(model, response, label=""):
    bucket_ = getattr(_calls, "sink", None)
    if bucket_ is not None:
        u = getattr(response, "usage_metadata", None) or {}
        bucket_.append((label,
                        u.get("input_tokens", 0) or 0,
                        u.get("output_tokens", 0) or 0,
                        model))
    return None                      # the print is not what is under test


def _usd(calls):
    total = 0.0
    for _label, intok, outok, model in calls:
        p_in, p_out = judges.PRICES.get(model, (0.0, 0.0))
        total += (intok * p_in + outok * p_out) / 1_000_000
    return total


class FakeResponse:
    def __init__(self, intok, outok):
        self.usage_metadata = {"input_tokens": intok, "output_tokens": outok}


# One question's worth of calls, in the order the agent actually makes them, including the
# 6.0 requarantine retry and a Reflect round - the shapes that a naive capture gets wrong.
M = "gemini-3.1-flash-lite"
PRODUCT = [("agent-plan", 912, 118), ("agent-generation", 3736, 207),
           ("agent-generation-requarantine", 3104, 191), ("agent-reflect", 640, 44)]
JUDGE = [("correctness", 1420, 96), ("groundedness", 3980, 88), ("scope", 3980, 132)]

if __name__ == "__main__":
    ok = 0

    # --- OLD path ---------------------------------------------------------------------------
    _calls.sink = []
    for lab, i, o in PRODUCT:
        _tracked_log_cost(M, FakeResponse(i, o), label=lab)
    old_product, _calls.sink = _calls.sink, []
    for lab, i, o in JUDGE:
        _tracked_log_cost(M, FakeResponse(i, o), label=lab)
    old_judge, _calls.sink = _calls.sink, None

    old = {
        "product": old_product,
        "judge": old_judge,
        "gen_in": sum(i for lab, i, o, m in old_product if "generation" in lab),
        "gen_calls": sum(1 for lab, i, o, m in old_product if "generation" in lab),
        "prod_in": sum(i for _l, i, _o, _m in old_product),
        "prod_out": sum(o for _l, _i, o, _m in old_product),
        "prod_usd": _usd(old_product),
        "judge_usd": _usd(old_judge),
    }

    # --- NEW path ---------------------------------------------------------------------------
    import types
    caller = types.ModuleType("fake_caller")
    caller.log_cost = judges.log_cost
    telemetry.install(caller)

    with telemetry.capture() as new_product:
        for lab, i, o in PRODUCT:
            caller.log_cost(M, FakeResponse(i, o), label=lab)
    with telemetry.capture() as new_judge:
        for lab, i, o in JUDGE:
            caller.log_cost(M, FakeResponse(i, o), label=lab)

    prod = telemetry.summarise(new_product)
    new = {
        "product": new_product,
        "judge": new_judge,
        "gen_in": prod["gen_in"],
        "gen_calls": prod["gen_calls"],
        "prod_in": prod["input_tokens"],
        "prod_out": prod["output_tokens"],
        "prod_usd": prod["usd"],
        "judge_usd": telemetry.usd(new_judge),
    }

    # --- compare ------------------------------------------------------------------------------
    print(f"\n  {'field':12} {'old':>14} {'new':>14}   match")
    for k in ("gen_in", "gen_calls", "prod_in", "prod_out", "prod_usd", "judge_usd"):
        same = old[k] == new[k]
        fmt = (lambda v: f"{v:.8f}") if isinstance(old[k], float) else (lambda v: f"{v}")
        print(f"  {k:12} {fmt(old[k]):>14} {fmt(new[k]):>14}   {'ok' if same else 'DIFFERENT'}")
        assert same, f"FAIL: {k} changed in the extraction: {old[k]} -> {new[k]}"
    assert old["product"] == new["product"], "FAIL: the captured product tuples differ"
    assert old["judge"] == new["judge"], "FAIL: the captured judge tuples differ"
    ok += 1

    # The requarantine retry MUST be counted as a generation call. It was added in 6.0, after
    # the capture was written, and "generation" is a substring match - so this is exactly the
    # kind of thing that silently starts or stops counting when a label is renamed.
    assert new["gen_calls"] == 2 and new["gen_in"] == 3736 + 3104, (
        "the 6.0 requarantine retry is not being counted as a generation call")
    ok += 1

    # And the probe must be able to fail. If both sides were empty, everything above would
    # match perfectly and prove nothing.
    assert new["prod_in"] > 0 and new["judge_usd"] > 0, "the comparison ran on empty buckets"
    ok += 1

    print(f"\nprobe_telemetry_equiv: {ok}/{ok} checks passed - the extraction is faithful.")
    print("  Still owed: one 3-question --ids run, to prove run_eval.py WIRES it correctly.")
