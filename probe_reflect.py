# probe_reflect.py
# x30 is the failure Reflect was built for: hop 1 identifies AMD from a tax-benefit clue,
# hop 2 needs AMD's balance sheet, and that search cannot be written until hop 1 returns.
# Watch for a SECOND [retrieve] round and rounds == 2.

import agent
agent.VERBOSE = True

Q = ("For whichever company in these filings reported an income tax benefit rather than "
     "an expense, what were its total liabilities at fiscal year end?")
out = agent.run_agent(Q)

print(f"\nrounds={out['rounds']}  chunks={len(out['chunks'])}  context={len(out['context'])} chars")
for label, needle in {"AMD total assets 76,926": "76926",
                      "AMD equity      62,999": "62999",
                      "AMD tax benefit   (103)": "103"}.items():
    print(f"  {label:26} present={needle in out['context']}")
print("\nANSWER:", out["answer"])
