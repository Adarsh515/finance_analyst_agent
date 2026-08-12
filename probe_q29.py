# probe_q29.py
import agent
agent.VERBOSE = True
from judges import groundedness_judge

Q = "By how much did NVIDIA's net income grow from fiscal 2025 to fiscal 2026, in dollars and percent?"         # q28/q29 ka exact text golden_set.py se copy kijiye
out = agent.run_agent(Q)
g = groundedness_judge(question=Q, prediction=out["answer"], context=out["context"])
print("\nGROUNDED:", g)
print("\nANSWER:\n", out["answer"])