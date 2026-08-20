"""
probe_mcp_equivalence.py - Phase 6.9. Does going through MCP change what comes back?

WHY THIS EXISTS INSTEAD OF A GATE. The question "did the MCP layer change anything?" could be
answered by re-running the 94-question eval through it: ~Rs 22 and half an hour, and the
answer would arrive as a scoreboard that moved or did not. This answers the same question at
the SEAM for a fraction of a paisa, and answers it more strictly: if the chunk ids and their
order are byte-identical, then nothing downstream - planner, context assembly, generation,
judges - can possibly differ, because they receive the same bytes.

probe_telemetry_equiv.py made the same argument in 6.3. Prove equivalence where the two paths
meet, not where their effects are eventually visible.

WHAT COULD ACTUALLY DIFFER, which is the reason this is not a tautology. Both paths call
agent._search, so the retrieval itself is shared by construction. What the server ADDS is a
JSON round trip, a k bound, a company/period filter mapped into a Chroma `where`, and a
subprocess boundary. Any of those could silently reorder, truncate, drop a field, or mangle a
unicode character in the text - and none of it is visible from inside the process.

COST: two embeddings per case (one each side), no generation, no judge. Roughly a paisa.
"""

import asyncio
import json
import os
import sys

CASES = [
    {"query": "total revenue", "company": "Tesla", "k": 3},
    {"query": "total revenue", "company": "AMD", "k": 5},
    {"query": "research and development expense", "company": "Intel", "k": 4},
    {"query": "Data Center segment revenue", "company": "NVIDIA", "k": 6},
    {"query": "total liabilities", "company": "", "k": 6},          # unfiltered
    {"query": "employee headcount", "company": "", "k": 4},         # unfiltered
    {"query": "gross margin", "company": "Tesla",
     "period": "fiscal year 2025 (ended December 31, 2025)", "k": 3},   # period filter too
    {"query": "revenue", "company": "", "k": 20},                   # the upper bound
]


def in_process(case):
    """What agent._search returns when nobody is in the way."""
    import agent
    # The same builder the server uses. This probe's own first version hand-rolled the filter
    # too, and made the identical mistake - which is the argument for having one builder,
    # restated by two files getting it wrong independently on the same afternoon.
    where = agent._chroma_filter({"company": case.get("company") or "",
                                  "period": case.get("period") or ""})
    docs = agent._search(case["query"], k=case["k"], where=where)
    return [{"chunk_id": d.id,
             "company": (d.metadata or {}).get("company"),
             "rank": (d.metadata or {}).get("_rank"),
             "text": d.page_content} for d in docs]


async def via_mcp(session, case):
    payload = json.loads((await session.call_tool("search_filings", {
        "query": case["query"], "company": case.get("company", ""),
        "period": case.get("period", ""), "k": case["k"]})).content[0].text)
    return [{"chunk_id": h["chunk_id"], "company": h["company"],
             "rank": h["rank"], "text": h["text"]} for h in payload["results"]]


async def main():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    import agent
    if not agent.FILINGS:
        raise SystemExit("  the index is empty - run build_index.py first")

    here = os.path.dirname(os.path.abspath(__file__))
    params = StdioServerParameters(command=sys.executable,
                                   args=[os.path.join(here, "filing_search_server.py")],
                                   env={**os.environ}, cwd=here)
    errlog = open(os.path.join(here, "_mcp_server_stderr.log"), "w+", encoding="utf-8")

    same = diff = 0
    print(f"\n  {'query':38} {'filter':10} {'k':>3}  {'in-process':>10} {'via MCP':>8}  match")
    print(f"  {'-'*38} {'-'*10} {'-'*3}  {'-'*10} {'-'*8}  -----")

    async with stdio_client(params, errlog=errlog) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for case in CASES:
                direct = in_process(case)
                served = await via_mcp(session, case)
                match = direct == served
                same, diff = (same + 1, diff) if match else (same, diff + 1)
                print(f"  {case['query'][:38]:38} {(case.get('company') or '-')[:10]:10} "
                      f"{case['k']:>3}  {len(direct):>10} {len(served):>8}  "
                      f"{'ok' if match else 'DIFFERS'}")
                if not match:
                    # Say WHICH field, not just "they differ" - a diagnostic that stops at
                    # "not equal" makes the reader do the work the script was written to do.
                    for i, (a, b) in enumerate(zip(direct, served)):
                        for key in ("chunk_id", "company", "rank", "text"):
                            if a[key] != b[key]:
                                print(f"        [{i}] {key}: in-process {a[key]!r:.60}")
                                print(f"        [{i}] {key}: via MCP    {b[key]!r:.60}")
                    if len(direct) != len(served):
                        print(f"        LENGTH differs: {len(direct)} vs {len(served)}")

    print(f"\n{'=' * 92}")
    print(f"  {same}/{len(CASES)} cases byte-identical between in-process retrieval and MCP")
    if diff:
        print("  🔴 The MCP layer CHANGED what comes back. Until this is 8/8, an answer served")
        print("     through MCP is not the answer this project measured.")
    else:
        print("  Same chunk ids, same order, same text, through a subprocess and a JSON round")
        print("  trip. Nothing downstream can differ, because nothing downstream sees anything")
        print("  different - which is why no eval gate was needed to establish it.")
    print(f"{'=' * 92}")
    print("  No generation model was called. Two embeddings per case.")
    raise SystemExit(0 if diff == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
