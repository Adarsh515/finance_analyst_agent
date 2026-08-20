# Pointing Claude Desktop at `filing-search`

Phase 6.9. Five minutes, no cost. When it works, you can ask Claude Desktop about these
filings **without running the app**, without it holding your API key, and without it knowing
this repo exists — which is the entire argument for putting retrieval behind MCP.

---

## 1. The config file

Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Open it in a text editor. If the file does not exist, create it. If it already has an
`mcpServers` block, add `filing-search` inside it rather than replacing the block.

```json
{
  "mcpServers": {
    "filing-search": {
      "command": "A:\\Adarsh\\AI Learnings\\Finance Assignment\\finance_assignment\\.venv\\Scripts\\python.exe",
      "args": [
        "A:\\Adarsh\\AI Learnings\\Finance Assignment\\finance_assignment\\filing_search_server.py"
      ],
      "cwd": "A:\\Adarsh\\AI Learnings\\Finance Assignment\\finance_assignment"
    }
  }
}
```

Three things that are easy to get wrong, and all three fail the same silent way:

- **The venv's python, not the system one.** `chromadb`, `langchain_chroma` and `mcp` are
  installed in `.venv`; the system interpreter has none of them and the server dies on import.
- **Backslashes are doubled** in JSON. A single `\` starts an escape sequence, and
  `\A` is not one, so the file will not parse — and Claude Desktop will just show no server.
- **`cwd` matters.** `chroma_db/` and `.env` are resolved relative to it. Without it the
  server starts, reports **zero filings**, and every search politely returns nothing.

Restart Claude Desktop completely after saving — it reads this file only at launch.

---

## 2. What to ask it

Once the hammer/tools icon shows `filing-search`:

> *What companies and fiscal periods are in the filing-search corpus?*

It should call `list_filings` and come back with six filings and their chunk counts.

> *Using filing-search, what was Tesla's total revenue for fiscal year 2025?*

It should call `search_filings`, get excerpts, and answer **$94,827 million** — quoting the
company and period, because the tool description tells it to.

> *Using filing-search, what was Rivian's revenue?*

It should come back with **nothing found**. The corpus is closed, and the server does not
return the nearest thing it can find. This is the demo worth showing: the same discipline the
app has, enforced at the data layer rather than in a prompt.

---

## 3. What this proves, and what it does not

**Proves:** the retrieval layer is a real, separately-deployable capability with a documented
tool contract, usable by a client that was never written against this codebase. The model
chooses when to call it, from the tool descriptions alone.

**Does not prove:** that Claude Desktop's answer has this project's guardrails. It does not.
The server hands over **evidence only** — no answer, no groundedness judge, no injection
guards, no cache. A client reasons with its own model under its own rules. That boundary is
deliberate: handing out a generated answer would mean handing out guarantees that belong to
the pipeline that produced them.

---

## If the tools icon never appears

`%APPDATA%\Claude\logs\mcp-server-filing-search.log` has the server's stderr, which is where
every startup problem lands. Before touching the config, confirm the server itself is fine:

```powershell
python filing_search_server.py
```

It should print `[filing-search] serving 6 filings over stdio via ...` and then wait. `Ctrl+C`
to stop. If that works and Desktop still shows nothing, the fault is in the JSON — most often
single backslashes, or a trailing comma.
