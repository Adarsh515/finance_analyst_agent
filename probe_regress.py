# probe_regress.py
# Two regression failures. First look at the jobs the planner wrote,
# then check whether the required figures reached the context.

import agent
agent.VERBOSE = True

CASES = {
    "q14 revenue growth": (
        "By how much did NVIDIA's total revenue grow from fiscal 2025 to fiscal 2026, in dollars and percent?",
        {"FY26 revenue 215,938": "215938", "FY25 revenue 130,497": "130497"},
    ),
    "q28 effective tax rate": (
        "What was NVIDIA's effective tax rate in fiscal year 2026?",
        {"income tax expense 21,383": "21383", "income before tax 141,450": "141450"},
    ),
}

for name, (q, wanted) in CASES.items():
    print("\n" + "=" * 70)
    print(name)
    out = agent.run_agent(q)
    for label, needle in wanted.items():
        print(f"  {label:28} present={needle in out['context']}")
    print("  ANSWER:", out["answer"][:250])