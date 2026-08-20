"""
test_mcp_server.py - Phase 6.9. Drive the MCP server the way a real client does.

WHY NOT JUST IMPORT THE FUNCTIONS AND CALL THEM. Because then this would test Python, and the
thing that can break is the PROTOCOL: a stray print on stdout corrupting the stream, a tool
whose schema the client cannot parse, a resource URI that does not resolve, a handler that
raises and returns an error object instead of a result. None of that is visible from inside
the process. This spawns `python filing_search_server.py` as a subprocess and speaks JSON-RPC
to it over stdin/stdout, which is exactly what Claude Desktop does.

The same argument as test_server.py, one layer out: a harness simpler than production only
covers what it happens to model (lesson 124).

Free: no API key is needed for the LIST calls; the SEARCH calls embed a query, which costs a
fraction of a paisa. No generation model is invoked, and no answer is produced anywhere.
"""

import asyncio
import os
import sys


async def run():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    # An ABSOLUTE path to the script, and the project directory as cwd. A relative arg works
    # when the test is launched from the repo root and fails silently when it is not - and a
    # server that cannot find its own file dies before printing anything, which surfaces to
    # the client as the singularly unhelpful "Connection closed".
    here = os.path.dirname(os.path.abspath(__file__))
    params = StdioServerParameters(
        command=sys.executable,
        args=[os.path.join(here, "filing_search_server.py")],
        env={**os.environ},
        cwd=here,
    )

    # The server's stderr is CAPTURED rather than left to the terminal, and replayed if
    # anything goes wrong. The first version let it default to the parent's stderr and the
    # first real failure printed a client-side traceback with no server-side cause anywhere
    # in it. A test that hides the reason it failed costs more than no test.
    errlog = open(os.path.join(here, "_mcp_server_stderr.log"), "w+", encoding="utf-8")

    ok = 0
    async with stdio_client(params, errlog=errlog) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            # `serverInfo` in mcp 1.x, `server_info` in 2.x. The client API is otherwise
            # identical across both, and a test that only speaks one of them cannot check the
            # portability this whole server exists for.
            info = getattr(init, "server_info", None) or getattr(init, "serverInfo", None)
            assert info is not None, f"no server info on {type(init).__name__}"
            print(f"\n  connected: {info.name} v{info.version}")
            assert info.name == "filing-search", info
            ok += 1

            # --- the tools a client can discover -------------------------------------------
            tools = (await session.list_tools()).tools
            names = sorted(t.name for t in tools)
            print(f"  tools    : {names}")
            assert names == ["list_filings", "search_filings"], names
            # every tool needs a description, or a model has no basis to choose it - which is
            # the entire justification for putting this behind MCP rather than a function call
            for t in tools:
                assert t.description and len(t.description) > 60, \
                    f"{t.name} has no usable description - a model cannot choose it"
            ok += 1

            resources = (await session.list_resources()).resources
            uris = sorted(str(r.uri) for r in resources)
            print(f"  resources: {uris}")
            assert "filings://list" in uris, uris
            ok += 1

            # --- list_filings tells the truth about the INDEX --------------------------------
            import json
            listed = json.loads((await session.call_tool("list_filings", {})).content[0].text)
            print(f"  index    : {listed['count']} filings")
            for f in listed["filings"]:
                print(f"             {f['company']:7} {f['period'][:44]:46} {f['chunks']}")
            assert listed["count"] == len(listed["filings"])
            if listed["count"] == 0:
                print("\n  the index is empty - run build_index.py. Protocol checks passed;")
                print("  the retrieval checks below need an index and are SKIPPED.")
                print(f"\ntest_mcp_server.py: {ok} protocol checks passed, retrieval SKIPPED")
                return
            ok += 1

            # the resource must return the SAME payload as the tool. Two shapes of one fact is
            # two things to keep in step, and this asserts they are actually one.
            res = await session.read_resource("filings://list")
            assert json.loads(res.contents[0].text) == listed, \
                "the resource and the tool disagree about what the index holds"
            ok += 1

            # --- search returns EVIDENCE, and only evidence ----------------------------------
            r = json.loads((await session.call_tool(
                "search_filings",
                {"query": "total revenue", "company": "Tesla", "k": 3})).content[0].text)
            print(f"\n  search   : {r['count']} results for Tesla 'total revenue'")
            assert r["count"] == 3, r["count"]
            for hit in r["results"]:
                assert hit["company"] == "Tesla", hit["company"]
                assert hit["chunk_id"] and hit["text"], hit
                assert hit["rank"] and hit["distance"] is not None, hit
                print(f"             rank {hit['rank']}  d={hit['distance']}  "
                      f"{hit['text'][:60]!r}")
            # ranks must be 1..n in order - the client is trusting this ordering
            assert [h["rank"] for h in r["results"]] == [1, 2, 3], r["results"]
            ok += 1

            # the company filter must actually filter, not merely reorder
            r2 = json.loads((await session.call_tool(
                "search_filings",
                {"query": "total revenue", "company": "AMD", "k": 3})).content[0].text)
            assert all(h["company"] == "AMD" for h in r2["results"]), r2["results"]
            assert {h["chunk_id"] for h in r2["results"]} != \
                   {h["chunk_id"] for h in r["results"]}, "the filter changed nothing"
            ok += 1

            # TWO filters at once. The suite had no such case, and that gap let a broken
            # where-clause ship: Chroma needs {"$and": [...]} for two conditions and rejects a
            # flat dict, so company+period raised while company-only passed. Every earlier
            # check used at most one filter.
            # the period string is read back from list_filings rather than typed here - a
            # literal would rot the day a filing is replaced, and this suite would then be
            # testing a period the index no longer has
            tesla_period = next((f["period"] for f in listed["filings"]
                                 if f["company"] == "Tesla"), None)
            assert tesla_period, "no Tesla filing to test a two-field filter against"
            both = json.loads((await session.call_tool("search_filings", {
                "query": "gross margin", "company": "Tesla",
                "period": tesla_period, "k": 3})).content[0].text)
            assert both["count"] > 0, "company+period returned nothing - is the filter valid?"
            assert all(h["company"] == "Tesla" for h in both["results"]), both["results"]
            ok += 1

            # k is bounded in CODE, not trusted from the client
            big = json.loads((await session.call_tool(
                "search_filings", {"query": "revenue", "k": 500})).content[0].text)
            assert big["count"] <= 20, f"k was not bounded: {big['count']}"
            ok += 1

            # a company that is not in the corpus returns NOTHING, rather than the nearest
            # thing it can find. This is the server's version of "Not stated in the filing."
            none = json.loads((await session.call_tool(
                "search_filings",
                {"query": "total revenue", "company": "Rivian", "k": 3})).content[0].text)
            assert none["count"] == 0, f"an unknown company returned {none['count']} results"
            ok += 1

            # --- the server must never hand out an ANSWER ------------------------------------
            # The boundary this phase exists to draw: evidence crosses it, generated prose does
            # not. If a tool named "answer" ever appears here, someone has lent out the
            # groundedness guarantees along with the data.
            assert not any("answer" in t.name.lower() or "ask" in t.name.lower()
                           for t in tools), [t.name for t in tools]
            ok += 1

    print(f"\ntest_mcp_server.py: {ok}/{ok} checks passed over real stdio JSON-RPC")
    print("  Spawned the server as a subprocess and spoke the protocol, exactly as a")
    print("  desktop client does. No generation model was called.")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except BaseException:
        # Replay whatever the server said before it died. "Connection closed" on the client
        # means the subprocess exited; the reason is only ever on the server's stderr.
        import traceback
        traceback.print_exc()
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "_mcp_server_stderr.log")
        print("\n" + "=" * 78)
        print("  WHAT THE SERVER ITSELF SAID BEFORE IT DIED")
        print("=" * 78)
        try:
            with open(path, encoding="utf-8") as fh:
                out = fh.read().strip()
            print(out if out else "  (nothing - it died before it could print, so suspect "
                                  "the spawn itself: wrong path, wrong interpreter, or an "
                                  "import that fails at line 1)")
        except OSError as e:
            print(f"  could not read {path}: {e}")
        raise SystemExit(1)
