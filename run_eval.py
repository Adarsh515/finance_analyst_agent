from dotenv import load_dotenv
from collections import defaultdict
from judges import correctness_judge, groundedness_judge
from golden_set import GOLDEN_SET
from cross_set import CROSS_SET, bucket
import sys

# --- A/B switch -------------------------------------------------------------
# The old path is the default and stays untouched. Pass --agent for the LangGraph path.
USE_AGENT = "--agent" in sys.argv

if USE_AGENT:
    import agent
    agent.VERBOSE = False              # silence node logs during a full eval run
    answer_fn = agent.run_agent
    PATH_NAME = "AGENT (LangGraph: plan -> retrieve -> answer)"
else:
    from rag import answer_question as answer_fn
    PATH_NAME = "BASELINE (rag.answer_question)"

load_dotenv()

def run_set(name, examples, bucket_fn=None):
    print(f"\n{'=' * 70}\n{name}   ({len(examples)} questions)\n{'=' * 70}")
    results, errors = [], []

    for ex in examples:
        try:
            out = answer_fn(question=ex["question"])
            ans = out["answer"]
            c = correctness_judge(question=ex["question"], prediction=ans,
                                  reference=ex["reference_answer"])
            g = groundedness_judge(question=ex["question"], prediction=ans,
                                   context=out["context"])
            results.append({"ex": ex, "answer": ans, "c": c, "g": g})
            mark = "PASS" if c["score"] == 1 else "FAIL"
            print(f"  {ex['id']}  {mark}  grounded={g['score']}  {ans[:80]}")
        except Exception as e:
            errors.append(ex["id"])
            print(f"  {ex['id']}  INFRA ERROR, skipped: {str(e)[:60]}")

    n = len(results)
    if n:
        corr = sum(r["c"]["score"] for r in results)
        grnd = sum(r["g"]["score"] for r in results)
        print(f"\n  Scored {n}/{len(examples)}  ({len(errors)} infra errors skipped)")
        print(f"  Correctness : {corr}/{n} = {corr/n:.0%}")
        print(f"  Groundedness: {grnd}/{n} = {grnd/n:.0%}")

    if bucket_fn:
        by = defaultdict(lambda: [0, 0])
        for r in results:
            b = bucket_fn(r["ex"])
            by[b][1] += 1
            by[b][0] += 1 if r["c"]["score"] == 1 else 0   # adjust if your judge uses a different key
        print("\n  correctness by bucket:")
        for b, (ok, n) in sorted(by.items()):
            print(f"    {b:<16} {ok}/{n}")

    if errors:
        print(f"\n  infra errors (NOT scored as wrong): {errors}")

    fails = [r for r in results if r["c"]["score"] != 1]
    if fails:
        print(f"\n  --- {len(fails)} FAILURES ---")
        for r in fails:
            grp = bucket_fn(r["ex"]) if bucket_fn else "-"
            print(f"\n  {r['ex']['id']}  [{grp}]")
            print(f"    Q:        {r['ex']['question']}")
            print(f"    expected: {r['ex']['reference_answer'][:150]}")
            print(f"    got:      {r['answer'][:600]}")
            print(f"    judge:    {str(r['c'].get('reasoning', ''))[:150]}")
            print(f"    grounded: {r['g']['score']}")
    return results


if __name__ == "__main__":
    print(f"\n### PATH: {PATH_NAME}\n")
    run_set("REGRESSION - NVIDIA only", GOLDEN_SET)
    run_set("CAPABILITY - cross-document", CROSS_SET, bucket_fn=bucket)

