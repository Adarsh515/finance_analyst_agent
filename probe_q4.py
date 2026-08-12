# probe_q4.py
# Q4 refused with 16 chunks. Are the required figures missing, or present but unused?
# NOTE: the index stores figures WITHOUT thousands separators - search "215938", not "215,938".

from agent import run_agent

Q = ("Which company converted revenue into operating cash flow more efficiently, "
     "and what were the margins?")

WANTED = {
    "NVIDIA revenue      (215,938)": "215938",
    "NVIDIA operating CF (102,718)": "102718",
    "AMD revenue         ( 34,639)": "34639",
    "AMD operating CF    (  7,709)": "7709",
}

out = run_agent(Q)
ctx = out["context"]

print("\ncontext chars:", len(ctx))
for label, needle in WANTED.items():
    print(f"  {label}  present={needle in ctx}")
print("\nANSWER:", out["answer"])