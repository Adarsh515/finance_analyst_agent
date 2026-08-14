# probe_t03.py
# t03 asks about fiscal 2023. That data exists only as the third column inside the
# FY2025 filing, and no "fiscal year 2023" period exists in the index. Look at the
# jobs the planner wrote before deciding anything.

import agent
agent.VERBOSE = True

Q = "What was NVIDIA's revenue in fiscal 2023, and how many times larger was fiscal 2026's revenue?"
out = agent.run_agent(Q)

for label, needle in {"FY2023 revenue 26,974": "26974",
                      "FY2026 revenue 215,938": "215938"}.items():
    print(f"  {label:26} present={needle in out['context']}")
print("\nANSWER:", out["answer"])