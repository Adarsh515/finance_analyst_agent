# rescore_scope.py
# Re-run the scope judge over answers a completed run already paid for, and report what
# moved. No agent, no retrieval, no generation - the run stored the exact context each
# answer was written from, so re-judging costs one judge call per question.
#
# WHY THIS EXISTS. The first full run flagged exactly one answer (q21 of 94) that the
# binary judge called grounded and the scope judge did not, and reading it showed a false
# negative: a claim with no numbers in it, failed by a test that asks whether its numbers
# are in the context. `judges_scope._figures_ok` now makes that test vacuous when the claim
# has no digits.
#
# That fix RELAXES - it can only turn a 0 into a 1 - so no answer that passed can start
# failing, and the only score that can move is the one that was 0. Re-running one question
# therefore settles the whole scoreboard, and re-running 94 would be buying 93 answers we
# can already derive. Same argument as the 2026-08-12 groundedness change.
#
#   python -X utf8 -u rescore_scope.py --jsonl eval_45_gate.jsonl --ids q21
#   python -X utf8 -u rescore_scope.py --jsonl eval_45_gate.jsonl --only-flagged
#   python -X utf8 -u rescore_scope.py --jsonl eval_45_gate.jsonl            # all of them

import argparse
import json
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

from judges_scope import scope_judge
from golden_set import GOLDEN_SET
from cross_set import CROSS_SET

load_dotenv()

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--jsonl", default="eval_45_gate.jsonl")
parser.add_argument("--ids", default="", help="comma-separated ids; default is every record")
parser.add_argument("--only-flagged", action="store_true",
                    help="only the answers the stored run scored scope=0 - the only ones a "
                         "relaxing change can move")
parser.add_argument("--workers", type=int, default=6)
args = parser.parse_args()

EX = {e["id"]: e for e in list(GOLDEN_SET) + list(CROSS_SET)}
WANT = {i.strip() for i in args.ids.split(",") if i.strip()}

RECORDS = []
for line in open(args.jsonl, encoding="utf-8"):
    r = json.loads(line)
    if "error" in r or "context" not in r:
        continue
    if WANT and r["id"] not in WANT:
        continue
    if args.only_flagged and r.get("scope") != 0:
        continue
    RECORDS.append(r)

assert RECORDS, "nothing to re-score - check --ids / --only-flagged / the jsonl path"


def one(r):
    v = scope_judge(question=EX[r["id"]]["question"], prediction=r["answer"],
                    context=r["context"])
    return r, v


if __name__ == "__main__":
    print(f"\n{'=' * 92}\nRE-SCORE SCOPE - {len(RECORDS)} stored answers, no agent\n{'=' * 92}")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        out = list(pool.map(one, RECORDS))

    moved, same, tightened = [], 0, []
    print(f"\n  {'id':6} {'was':>4} {'now':>4}  claims  note")
    for r, v in out:
        was, now = r.get("scope"), v["score"]
        if was == now:
            same += 1
        elif now == 1:
            moved.append(r["id"])
        else:
            tightened.append(r["id"])
        note = "unchanged" if was == now else ("RELAXED 0 -> 1" if now == 1 else "TIGHTENED 1 -> 0")
        print(f"  {r['id']:6} {str(was):>4} {now:>4}  {v['claims']:>5}   {note}")
        if now == 0:
            print(f"          {str(v['reasoning'])[:150]}")

    print(f"\n  unchanged {same}   relaxed {len(moved)} {moved}   tightened "
          f"{len(tightened)} {tightened}")
    if tightened:
        print("  A TIGHTENED row means the change was not relaxation-only after all, and the")
        print("  argument for re-scoring a subset instead of the whole file no longer holds.")
