"""
filing_search_server.py - Phase 6.9. The retrieval layer, exposed over MCP.

WHY THIS EARNS AN MCP SERVER, and the same three questions that DISQUALIFIED the Phase 4.3
corpus-description task are asked again here:

  1. Must it be usable from OUTSIDE this codebase?   YES - an analyst pointing Claude Desktop
     at this server can query the filing index without running the app, without the API key,
     and without knowing any of this repo exists.
  2. Must it be a SEPARATE PROCESS?                   YES - own lifetime, own permissions, and
     it is spawned by whichever client wants it rather than living inside ours.
  3. Does the MODEL decide to call it, or our code?   THE MODEL - a Desktop client picks
     search_filings on its own, from the description below.

The 4.3 task answered no to all three, which is why it was a ten-line function and why
"hunting for a problem to fit a tool" is written in the tracker as a named mistake.

WHAT IS EXPOSED, and what deliberately is NOT:

    tool      search_filings(query, company, period, k)   retrieval, and only retrieval
    tool      list_filings()                              what the index actually holds
    resource  filings://list                              the same list, in resource shape

NOT exposed: the agent, the planner, the answer prompt, the guards, the cache, the database.
This server returns EVIDENCE, never an answer. That boundary is the point - a client gets the
same chunks our pipeline would retrieve and then reasons with its own model, under its own
guardrails. Handing out a generated answer would mean handing out our groundedness guarantees
too, and those are not ours to lend.

THE INDEX IS READ-ONLY HERE. There is no ingest tool, no delete, no rebuild. A server whose
worst case is "someone read a public SEC filing" needs no authentication; one that could
mutate the index would.

Run manually:   python filing_search_server.py          (speaks JSON-RPC on stdin/stdout)
Test for free:  python test_mcp_server.py               (drives it over real stdio, no model)
"""

import json
import os
import sys

# Reported to every client on connect. Bumped when the TOOL CONTRACT changes -
# a client that cached a schema needs a way to notice.
SERVER_VERSION = "6.9.0"

# THE WORKING DIRECTORY IS PART OF THE SERVER'S JOB, and this file used to leave it to
# whoever launched us. It cannot: rag.py resolves BOTH of its inputs relative to the process
# working directory -
#
#     load_dotenv()                      the API key, looked up as "./.env"
#     persist_directory="chroma_db"      the vector index, looked up as "./chroma_db"
#
# and agent.py imports rag at line 44, so every path in the chain inherits that assumption.
# rag.py is contract #1 and is not edited, so the fix belongs HERE, in the one file whose
# entire justification is that SOMEBODY ELSE'S CLIENT starts it. A client chooses its own
# working directory and is under no obligation to tell us; Claude Desktop starts from its
# own install location.
#
# WHAT THIS ACTUALLY FIXED, measured rather than assumed. Spawned from a home folder, with a
# real `initialize` request on a pipe, this server answered the handshake and then reported
# `serving 0 filings` - it did not crash, it did not warn the client, it simply answered
# every question with "nothing found" for the rest of the session. A wrong answer delivered
# confidently is worse than a crash, because a crash gets investigated.
#
# `os.chdir` is a process-global side effect and that is normally a smell. It is correct here
# for one reason: this file is a PROCESS ENTRY POINT, not a library. Nothing imports it - both
# test_mcp_server.py and probe_mcp_equivalence.py spawn it as a subprocess - so the only
# environment it mutates is its own.
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# stdio transport means STDOUT IS THE PROTOCOL. Anything printed to it that is not JSON-RPC
# corrupts the stream and the client sees a parse error rather than a message. agent.py's
# node logging is on by default, and rag.py prints a warning when the index is empty - both
# would land on stdout and break the session. Silenced before those modules are imported.
agent_verbose_was = None
_real_stdout = sys.stdout
sys.stdout = sys.stderr          # anything printed at import time goes to the log, not the wire

import agent                     # noqa: E402  - for FILINGS and the exact retrieval the app uses

agent.VERBOSE = False
sys.stdout = _real_stdout

# THE SERVER CLASS HAS MOVED, AND THIS IS WHY THE SHIM IS HERE RATHER THAN A PINNED VERSION.
#
#     mcp >= 2.0    mcp.server.mcpserver.MCPServer
#     mcp 1.2-1.x   mcp.server.fastmcp.FastMCP
#
# Same decorator API in both - .tool(), .resource(), .run(transport="stdio") - so only the
# import differs. NEWEST IS TRIED FIRST, so a machine with both prefers the current one.
#
# This file was written and tested against 1.27 and then failed instantly on a machine with
# 2.0, on the import line. The whole argument for putting retrieval behind MCP is that OTHER
# PEOPLE'S clients can run it; a server proven on exactly one environment has not been tested
# for the thing it exists to do. Pinning the version would hide that rather than handle it -
# a desktop user who already has mcp 2.0 installed is not going to downgrade for us.
try:                                                            # noqa: E402
    from mcp.server.mcpserver import MCPServer as _ServerClass
    _MCP_API = "mcp>=2.0 (mcp.server.mcpserver.MCPServer)"
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP as _ServerClass
        _MCP_API = "mcp 1.x (mcp.server.fastmcp.FastMCP)"
    except ImportError as e:
        import importlib.metadata as _md
        try:
            _ver = _md.version("mcp")
        except Exception:
            _ver = "not installed"
        raise SystemExit(
            f"[filing-search] cannot import the MCP server class.\n"
            f"  installed mcp version : {_ver}\n"
            f"  tried                 : mcp.server.mcpserver.MCPServer  (mcp 2.x)\n"
            f"                          mcp.server.fastmcp.FastMCP      (mcp 1.2-1.x)\n"
            f"  fix                   : pip install --upgrade mcp\n"
            f"  If your mcp is NEWER than 2.x, the class has moved again - look for the\n"
            f"  server class in `python -c \"import mcp.server,pkgutil;"
            f"print([m.name for m in pkgutil.iter_modules(mcp.server.__path__)])\"`\n"
            f"  underlying error      : {e}") from e

# `version` exists on mcp 2.x's MCPServer and not on 1.x's FastMCP, so it is passed only when
# the constructor accepts it. Building kwargs by inspection rather than by try/except keeps a
# TypeError from a genuinely wrong argument visible instead of swallowed.
import inspect as _inspect                                       # noqa: E402
_extra = {}
if "version" in _inspect.signature(_ServerClass.__init__).parameters:
    _extra["version"] = SERVER_VERSION

mcp = _ServerClass(
    "filing-search",
    **_extra,
    # WARNING, not INFO. The SDK logs one line per request, and a desktop client's log window
    # is where a real problem has to be visible - a per-request INFO line buries it. stderr is
    # the only channel available, because stdout IS the protocol.
    log_level="WARNING",
    instructions=(
        "Semantic search over a fixed corpus of SEC filings (10-K and 10-Q). "
        "Call list_filings first if you do not know which companies and fiscal periods are "
        "available - the corpus is small and closed, and asking for a company that is not in "
        "it returns nothing. search_filings returns EXCERPTS ONLY: it never answers a "
        "question, and every figure you use from it should be quoted with the company and "
        "fiscal period attached."),
)


@mcp.tool(
    description=(
        "Search the SEC filing corpus and return the most relevant excerpts. Returns text "
        "chunks with their company, fiscal period, document type and similarity distance - "
        "NOT an answer. Filter by company and/or period to narrow the search; leave them "
        "empty to search everything. Distances are only comparable WITHIN one result set."),
)
def search_filings(query: str, company: str = "", period: str = "", k: int = 6) -> str:
    """Retrieve filing excerpts for a query.

    Deliberately calls agent._search, the SAME function the product uses, rather than
    re-implementing retrieval against the vector store. Two implementations of "search" would
    be two things to keep in step, and the one nobody runs would be the one that drifts. It
    also means the equivalence probe can compare this server against the in-process path and
    expect BYTE-IDENTICAL chunk ids.
    """
    if not agent.FILINGS:
        return json.dumps(_empty_index_error(), ensure_ascii=False, indent=2)

    k = max(1, min(int(k or 6), 20))          # bound in code; a client may ask for anything

    # agent._chroma_filter, NOT a dict built here. The first version of this function built
    # `{"company": ..., "period": ...}` by hand and it was WRONG: Chroma rejects a flat
    # two-key where-clause with "Expected where to have exactly one operator" and needs
    # {"$and": [...]}. agent.py has had a function that gets this right since Phase 4.2, and
    # this file hand-rolled a second one - three lines under a docstring congratulating itself
    # for calling agent._search rather than re-implementing retrieval. Found by the
    # equivalence probe, on the only case that filtered by TWO fields.
    where = agent._chroma_filter({"company": company or "", "period": period or ""})
    docs = agent._search(query, k=k, where=where)

    out = []
    for d in docs:
        m = dict(getattr(d, "metadata", None) or {})
        out.append({
            "chunk_id": getattr(d, "id", None),
            "company": m.get("company"),
            "period": m.get("period"),
            "doc_type": m.get("doc_type"),
            "type": m.get("type"),
            "rank": m.get("_rank"),
            "distance": m.get("_score"),
            "text": d.page_content,
        })
    return json.dumps({
        "query": query,
        "filter": {"company": company or None, "period": period or None},
        "count": len(out),
        "results": out,
        "note": ("These are excerpts, not an answer. A distance is meaningful only against "
                 "the other distances in this same result set."),
    }, ensure_ascii=False, indent=2)


@mcp.tool(
    description=(
        "List every company and fiscal period in the filing corpus, with how many indexed "
        "chunks each holds. Call this before searching if you are unsure what exists - the "
        "corpus is closed, and a company that is not listed cannot be answered from it."),
)
def list_filings() -> str:
    """What the INDEX holds, not what corpus.py intended to ingest.

    agent.FILINGS is read from the index at import for exactly this reason (contract 7): a
    half-failed ingest makes intent and reality differ, and a client told the intent would ask
    for a filing that is not searchable.
    """
    return json.dumps(_filings_payload(), ensure_ascii=False, indent=2)


# The same data as a RESOURCE as well as a tool, and the duplication is deliberate.
# A resource is the protocol-correct shape for "a document the client may read". But in a
# desktop client a resource is usually something the USER attaches by hand, while a TOOL is
# what the MODEL can reach on its own - and the whole argument for putting this behind MCP
# (question 3 above) is that the model decides. So it is offered both ways: correct for the
# spec, usable in practice.
@mcp.resource("filings://list", mime_type="application/json",
              description="Companies and fiscal periods available in the filing index.")
def filings_resource() -> str:
    return json.dumps(_filings_payload(), ensure_ascii=False, indent=2)


def _empty_index_error():
    """What a client is told when the index holds nothing.

    THE POINT IS THAT IT IS NOT AN EMPTY RESULT SET. An empty result set is a fact about the
    QUERY - "the filings do not discuss this" - and a model that receives one will report
    exactly that, in good faith, having been misled. This payload is a fact about the SERVER,
    and it says so in a field the model will read out loud.

    Refusing to start would be the other option and it is worse: the client renders a dead
    server as "Server disconnected", which names the symptom and hides the cause. This
    project spent a whole session on that message. A server that starts and explains itself
    is debuggable from the client's own transcript.
    """
    return {
        "error": "the filing index is empty",
        "count": 0,
        "results": [],
        "detail": (f"This server found no indexed filings in {os.getcwd()}. It has NOT "
                   f"searched anything, so this is not evidence that the filings lack the "
                   f"answer - do not report it as such. The index is built by running "
                   f"build_index.py in the server's own directory."),
    }


def _filings_payload():
    counts = {}
    try:
        raw = agent.vectorstore.get(include=["metadatas"])
        for m in raw.get("metadatas") or []:
            key = ((m or {}).get("company"), (m or {}).get("period"))
            counts[key] = counts.get(key, 0) + 1
    except Exception as e:                    # a chunk count is nice, not load-bearing
        print(f"[filing-search] chunk counts unavailable: {e}", file=sys.stderr)

    if not agent.FILINGS:
        return _empty_index_error()

    return {
        "count": len(agent.FILINGS),
        "filings": [{"company": c, "period": p, "chunks": counts.get((c, p))}
                    for c, p in agent.FILINGS],
        "note": ("This is what the INDEX holds, which is not necessarily what was intended to "
                 "be ingested. Anything not listed here cannot be answered from this corpus."),
    }


if __name__ == "__main__":
    if not agent.FILINGS:
        print("[filing-search] WARNING: the index reports no filings. Run build_index.py.",
              file=sys.stderr)
    # The DIRECTORY is printed, not just the count. When a client reports a server that
    # "works but finds nothing", the first question is always which folder it read, and a
    # count on its own cannot answer it.
    print(f"[filing-search] serving {len(agent.FILINGS)} filings over stdio "
          f"via {_MCP_API}  (index directory: {os.getcwd()})", file=sys.stderr)
    mcp.run(transport="stdio")
