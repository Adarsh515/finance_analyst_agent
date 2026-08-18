# red_team.py
# Phase 5.0 - run the attack set against the CURRENT, UNDEFENDED system and record what
# happens. Nothing here defends anything. The output of this file is the evidence that
# decides which guardrails get built in 5.1, and - just as important - which ones do not.
#
# HOW THE POISON GETS IN, and why not through the index.
#
# plant_poison.py, written in Phase 4 and never run, would have called store.add_texts()
# on the live collection. That has three problems: it mutates 2,188 real chunks for one
# experiment, it is undone only by a full rebuild, and it still points at collection
# "nvidia_10k" which stopped existing when ids were namespaced per filing in 4.3. So the
# poison is injected at the RETRIEVAL BOUNDARY instead: agent._search is wrapped for the
# duration of one question and hands back the hostile chunk as if Chroma had returned it.
# Identical effect on the prompt, zero mutation, and every attack ends when the call ends.
#
# The wrapper puts the poison at RANK 0 OF THE FIRST JOB. The attacker is assumed to have
# already won retrieval - see the threat model note in attacks.py. What is being measured
# here is whether the PROMPT holds once hostile text is in the context, which is a separate
# question from whether hostile text can be made to rank, and running them together would
# leave any failure unattributable to either.
#
# SERIAL ON PURPOSE. The monkeypatch is process-global; running questions concurrently
# would let one question's poison land in another's retrieval. 19 attacks at ~10s is three
# minutes, and a correct three minutes beats a fast result that cannot be trusted.
#
# Cost: roughly $0.04. No judges - every verdict in attacks.py is a substring test.

import argparse
import json
import time

from dotenv import load_dotenv
from langchain_core.documents import Document

import agent
from attacks import ATTACKS, judge_attack, refused

load_dotenv()

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--ids", default="", help="comma-separated attack ids; default is all")
parser.add_argument("--family", default="", help="run one family only")
parser.add_argument("--out", default="red_team.jsonl",
                    help="append every result, including the full answer and context")
parser.add_argument("--verbose", action="store_true", help="print the agent's node logs")
parser.add_argument("--undefended", action="store_true",
                    help="turn the Phase 5.1 guards OFF for this run, reproducing the system "
                         "as it was when these attacks were first measured. This is how the "
                         "before/after comparison stays honest: same file, same attacks, one "
                         "flag - not a git stash and a memory of what the numbers were.")
parser.add_argument("--append", action="store_true",
                    help="allow --out to append to a file that already has "
                         "records. Off by default: a duplicated gate run is the\n"
                         "most expensive mistake available in this repo.")
parser.add_argument("--repeat", type=int, default=1,
                    help="run each selected attack N times. Generation is not deterministic "
                         "(lesson 64: five identical calls once gave two different answers), "
                         "so a single run of a borderline attack measures the generator, not "
                         "the defence. Use this before calling anything a regression.")
# default=None, NOT False. This flag used to be a plain store_true, which meant every red
# team run set agent.GUARD_PROMPT = True and quietly tested the HARDENED PROMPT - a layer
# that ships DISABLED. One run was reported as "GUARDED (code + prompt layers)" before the
# banner gave it away. A harness whose default contradicts the shipped configuration is
# measuring a system nobody runs, which is the silent-pass failure this project keeps
# finding, this time in my own tooling.
parser.add_argument("--prompt-guard", dest="prompt_guard", action="store_true", default=None,
                    help="force the (disabled-by-default) prompt layer ON for this run")
parser.add_argument("--no-prompt-guard", dest="prompt_guard", action="store_false",
                    help="force the prompt layer OFF. Neither flag = whatever agent.py "
                         "ships, which is what you almost always want to measure.")


# --- refuse to append to an existing --out file ------------------------------
# This exists because a duplicate cost real money. eval_60_gate.jsonl came back with 188
# records - TWO complete 94-question gates, byte-identical answers - and that single
# duplication was roughly Rs 45 of the Rs 62 spent that day, on a learner's metered credit.
#
# --out appends by design (a run that dies at question 79 must keep its first 78 paid
# answers). But "append" and "the file already holds a finished run" are different
# situations, and only one of them is safe. So: refuse, name the file, and make the user
# choose - a new name, or --append if mixing runs is genuinely intended.
def _guard_out_path(path, append):
    if not path or append:
        return
    import os
    if os.path.exists(path) and os.path.getsize(path) > 0:
        n = sum(1 for _ in open(path, encoding="utf-8"))
        raise SystemExit(
            f"\nREFUSING TO RUN: {path} already holds {n} records.\n"
            f"Appending would mix two runs in one file and pay for answers you already have.\n"
            f"Use a new --out name, or pass --append if you really mean to add to it.\n")


args = parser.parse_args()
_guard_out_path(args.out, args.append)

agent.VERBOSE = args.verbose
agent.GUARDS = not args.undefended
if args.prompt_guard is not None:      # otherwise leave agent.py's shipped value
    agent.GUARD_PROMPT = args.prompt_guard
_REAL_SEARCH = agent._search


class Poisoner:
    """Wrap agent._search so the first job of the current question returns the poison first.

    Stateful and single-threaded by design. `armed` is reset per question, so a poison can
    only ever enter the question it was written for - a leak across questions would silently
    contaminate every later result and look like a much more capable attack than it is.
    """

    def __init__(self):
        self.payload = None
        self.armed = False
        self.fired = 0

    def arm(self, payload):
        self.payload = payload
        self.armed = payload is not None
        self.fired = 0

    def __call__(self, query, k, where):
        docs = _REAL_SEARCH(query, k, where)
        if self.armed:
            self.armed = False          # first job only
            self.fired += 1
            poison = Document(page_content=self.payload,
                              metadata={"company": "NVIDIA", "period": "poisoned",
                                        "type": "table", "source_table": -99},
                              id="POISON-CHUNK-0")
            return [poison] + list(docs)
        return docs


POISONER = Poisoner()
agent._search = POISONER

selected = ATTACKS
if args.ids:
    want = {i.strip() for i in args.ids.split(",") if i.strip()}
    selected = [a for a in selected if a["id"] in want]
if args.family:
    selected = [a for a in selected if a["family"] == args.family]
assert selected, "no attacks selected"


def run_one(a):
    POISONER.arm(a.get("poison"))
    t0 = time.perf_counter()
    out = agent.run_agent(question=a["question"])
    secs = time.perf_counter() - t0
    answer = out["answer"]
    defended, useful, note = judge_attack(a, answer)
    # Whether the poison actually reached the context is checked separately from whether it
    # reached the ANSWER. An attack that never entered the prompt was not defended against -
    # it was never delivered, and scoring it as a win would be the silent pass this project
    # keeps hunting.
    delivered = a.get("poison") is None or a["poison"][:60] in out["context"]
    return {
        "id": a["id"], "family": a["family"], "why": a["why"],
        "question": a["question"], "answer": answer,
        "defended": defended, "useful": useful, "note": note,
        "poison_delivered": delivered, "refused": refused(answer),
        # Which guard, if any, produced this answer. Without it a dead attack cannot be
        # attributed to a layer, and an unattributable defence is one nobody can delete.
        "guard_fired": out.get("guard_fired") or "",
        "context_chars": len(out["context"]), "rounds": out.get("rounds"),
        "seconds": round(secs, 2), "context": out["context"],
    }


if __name__ == "__main__":
    state = ("UNDEFENDED (guards off)" if args.undefended
             else f"GUARDED (prompt layer {'ON' if agent.GUARD_PROMPT else 'OFF'})")
    print(f"\n{'=' * 100}")
    print(f"RED TEAM - {len(selected)} attacks, system is {state}")
    print(f"{'=' * 100}\n")

    results = []
    with open(args.out, "a", encoding="utf-8") as fh:
        plan = [a for a in selected for _ in range(args.repeat)]
        for n, a in enumerate(plan, 1):
            try:
                r = run_one(a)
            except Exception as e:
                print(f"  [{n:2}/{len(plan)}] {a['id']:6} INFRA ERROR: {str(e)[:70]}")
                continue
            results.append(r)
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush()
            mark = "HELD  " if r["defended"] else "BROKEN"
            use = "ok" if r["useful"] else "DEGRADED"
            warn = "" if r["poison_delivered"] else "   <-- POISON NEVER REACHED THE CONTEXT"
            if r["guard_fired"]:
                warn += f'   [{r["guard_fired"][:44]}]'
            print(f"  [{n:2}/{len(plan)}] {r['id']:6} {r['family']:19} "
                  f"{mark}  useful={use:8} {r['seconds']:5.1f}s{warn}")
            if not r["defended"] or not r["useful"]:
                print(f"           {r['note'][:120]}")
                print(f"           answer: {r['answer'][:150].replace(chr(10), ' ')}")

    if not results:
        raise SystemExit("nothing ran")

    if args.repeat > 1:
        # An attack whose verdict changes between identical runs is not a defence result at
        # all - it is the generator moving. Say so loudly rather than averaging it away.
        seen = {}
        for r in results:
            seen.setdefault(r["id"], []).append(r["defended"])
        print(f"\n{'=' * 100}\n  STABILITY over {args.repeat} runs\n{'=' * 100}")
        for i, vs in seen.items():
            flip = len(set(vs)) > 1
            note = ("UNSTABLE - generator variance, not a defence verdict"
                    if flip else "stable")
            print(f"  {i:6} defended={vs}  {note}")

    print(f"\n{'=' * 100}\n  RESULTS\n{'=' * 100}")
    fams = {}
    for r in results:
        f = fams.setdefault(r["family"], {"n": 0, "held": 0, "useful": 0, "broken": []})
        f["n"] += 1
        f["held"] += r["defended"]
        f["useful"] += r["useful"]
        if not r["defended"]:
            f["broken"].append(r["id"])

    print(f"\n  {'family':22} {'held':>8} {'useful':>8}   attacks that landed")
    for name, f in sorted(fams.items()):
        print(f"  {name:22} {f['held']}/{f['n']:<6} {f['useful']}/{f['n']:<6}   "
              f"{', '.join(f['broken']) or '-'}")

    held = sum(r["defended"] for r in results)
    use = sum(r["useful"] for r in results)
    undelivered = [r["id"] for r in results if not r["poison_delivered"]]
    print(f"\n  TOTAL held {held}/{len(results)}      useful {use}/{len(results)}")
    if undelivered:
        print(f"  POISON NOT DELIVERED for {undelivered} - these tested nothing and their")
        print("  'held' verdict is meaningless. Fix the delivery before reading them.")

    landed = [r for r in results if not r["defended"]]
    print(f"\n  ATTACKS THAT LANDED: {len(landed)}")
    print("  These, and ONLY these, may have a guardrail built for them in 5.1. An attack")
    print("  the system already survives does not get a defence - that is a cost paid on")
    print("  every real question forever, in exchange for a number that cannot move.")
    for r in landed:
        print(f"\n  {r['id']}  [{r['family']}]  {r['why']}")
        print(f"    Q: {r['question'][:110]}")
        print(f"    A: {r['answer'][:220].replace(chr(10), ' ')}")
        print(f"    {r['note'][:150]}")

    degraded = [r for r in results if r["defended"] and not r["useful"]]
    if degraded:
        print(f"\n  HELD BUT DEGRADED: {[r['id'] for r in degraded]}")
        print("  The payload was refused and the real answer was lost too. A guardrail that")
        print("  ships in this state has traded an attack for an outage.")
