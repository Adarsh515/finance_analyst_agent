# Financial Research & Compliance Analyst Agent

A retrieval-augmented question-answering system over SEC filings, built as a capstone project.
It answers questions about six 10-K/10-Q filings from four companies, refuses when the filings
do not contain the answer, defends against prompt injection, and — the part the project is
actually about — **measures all of that, and publishes what the measurements got wrong.**

Latest gate, 102 questions:

| | result |
|---|---|
| correctness | **102/102** |
| groundedness (binary) | 102/102 |
| groundedness (scope) | 102/102 |
| groundedness (binary AND scope) | 102/102 |
| red team, 25 attacks, 5 families | **25/25 held, 0 landed** |
| cost of the run | $0.334 (~₹29) |

---

## Run it

```bash
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt

# .env in the project root:
#   GOOGLE_API_KEY=...
#   LANGSMITH_API_KEY=...        (optional)
#   LANGSMITH_TRACING=true       (optional)
#   LANGSMITH_PROJECT=...        (optional)

python build_index.py        # parse the filings and embed them (~2,686 chunks)
python reset_db.py --init    # create the application database
python app.py                # http://127.0.0.1:8000
```

`build_index.py` refuses to append to a non-empty collection, parses everything before
embedding anything, and aborts on duplicate chunk ids — a second NVIDIA filing once produced
424 colliding ids that Chroma resolved silently, which is why those three guards exist.

### Check everything that costs nothing

```bash
python run_all_free.py
```

Eighteen self-tests and equivalence probes in one command — schema migrations, the cache, cost
capture, the guards, every eval set's internal consistency, 29 API route checks, the MCP server
over real stdio. Two of them embed a query (a fraction of a paisa) and say so. **The paid gates
are deliberately excluded** and are run by name with their cost quoted first.

---

## What it is made of

```
question
   ↓
rewriter.py        turns a follow-up into a standalone question, using the conversation
   ↓
agent.py           LangGraph: plan → retrieve → answer → reflect
   ├── plan        an LLM proposes retrieval jobs; CODE bounds them (MAX_JOBS, MAX_ROUNDS)
   ├── retrieve    per-job round-robin over Chroma, de-duplicated by chunk id
   ├── answer      generation from the fenced context
   └── reflect     reads its own draft and queues a follow-up retrieval if it needs one
   ↓
guards.py          context fence, quarantine + regenerate-from-trusted, leak detection
   ↓
app.py             FastAPI: accounts, sessions, chat history, per-answer cost trace
```

**Corpus** — six filings, four companies: NVIDIA FY2026 10-K, NVIDIA FY2025 10-K, NVIDIA Q3
FY2026 10-Q, AMD FY2025 10-K, Intel FY2025 10-K, Tesla FY2025 10-K. 2,686 chunks. The filings
themselves are committed; the index is not.

**Also here** — an MCP server (`filing_search_server.py`) that exposes the retrieval layer to
any MCP client. It returns **evidence, never an answer**: a test asserts that no tool is ever
named `answer` or `ask`, because handing out a generated answer would mean handing out
groundedness guarantees that belong to the pipeline. `MCP_SETUP.md` wires it into Claude Desktop.

---

## How it is measured

Four judges, run side by side and **never averaged into one number**:

| judge | asks | file |
|---|---|---|
| correctness | does this match the human-written reference? | `judges.py` |
| groundedness (binary) | is every figure supported by the context? | `judges.py` |
| groundedness (scope) | does the answer's claim range over more than the context covers? | `judges_scope.py` |
| set coverage | did the answer account for every member of the set it ranked over? | `judges_coverage.py` |

The two groundedness judges are **ANDed** — they fail by opposite omissions, so a claim has to
survive both readings. Set coverage is a **separate axis and is never ANDed**, which turned out
to matter: when it de-calibrated (below), the groundedness column was untouched.

```bash
python run_eval.py --agent --set all --out gate.jsonl    # 102 questions, ~₹29
python red_team.py --out rt.jsonl                        # 25 attacks, ~₹3
python probe_arith.py                                    # arithmetic self-consistency, free
```

Every run stores the full context and the judges' raw observations, so **re-scoring a finished
run under a changed rule costs nothing**. That is not a convenience; it is the reason several
findings below were affordable.

---

## What went wrong, and how it was found

This is the part worth reading. The tracker (`PROJECT_TRACKER.md`, not in this repo) carries
**162 numbered lessons**. A few that shaped the system:

**A data bug that looked like three separate model failures.** `parse_filing.table_title()`
titled AMD's acquisition note *"AMD Consolidated Balance Sheets"*, because "Total assets
**acquired**" contains "total assets". Retriever, generator and judge all behaved correctly on a
false heading. Three days of investigation had been looking downstream of it. Fixed with a
row-label veto that can only demote a title, never promote one.

**A defence that did nothing, shipped disabled with the measurement attached.** The Phase 5
prompt-hardening layer killed 0 of its 4 target attacks and broke a fifth. Code guards killed
4/4. `HARDENED_PROMPT` is still in `guards.py`, switched off, next to the numbers.

**Four features cancelled by the measurement taken to justify them** — a calculator tool, a
semantic cache, a canonical rewriter, and an automatic arithmetic repair. The last one is the
sharpest: handed a real contradiction it fixed the answer 3/3, and handed a *fabricated* report
about a *correct* answer it rewrote 127,929 to 128,329, ignoring a prompt line telling it not to.
An automatic repair is only as trustworthy as its detector.

**A judge with a hole nobody had looked for.** Both groundedness judges ask *"is this claim
supported?"* Neither can ask *"was the set you compared over complete?"* — so an answer that
crowned a winner over four companies while accounting for two scored a perfect 102/102. Building
`judges_coverage.py` found seven more of them, all passing every existing scoreboard.

**A judge that de-calibrated without being touched.** That new judge went from 0 false positives
to 43% between two gates. Nothing in it changed; the *answers* changed, because a prompt rule
asked them to show their arithmetic and they began writing *"not stated as a percentage…
however, calculating…"*. A pre-registered 25% ceiling had been written down before the run, so
the ambitious half of the judge was retired rather than argued with. **A calibration is a
statement about its inputs, and it expires when they change.**

**Eleven reporting defects — every one found by reading output, none by a test.** Including one
in this project's own record: for three phases the tracker explained a failure by quoting a line
of a filing that is in neither gate's stored context. It was written from memory and never
re-opened. The correction is in the file, with the original struck through.

---

## Things this project deliberately did not build

- **A web-search lane** for companies outside the corpus. Planned, scoped, attack-first plan
  written — and not built, because it adds a feature and no evidence, at a cost the measurement
  budget could not justify. The agent has no HTTP client anywhere and always refuses.
- **OAuth.** Local email + password with argon2id is enough to demonstrate the security work;
  a second identity provider adds no failure mode worth measuring.
- **A calculator tool, a semantic cache, a canonical rewriter, an arithmetic self-repair.**
  Each was designed, measured, and cancelled by its own evidence. The measurements are in the
  tracker.

## Known limitations, carried on purpose

- `/ask` is not rate limited. Login is.
- The answer cache is exact-match, so a reworded repeat pays again. Making it semantic was
  tried and cancelled: a poisoning test showed it would serve one question's answer to another.
- Set coverage is reported as a candidate list, not a score, until it is recalibrated against
  the current answer style.
- Intermediate figures inside multi-part answers are checked only for self-consistency
  (`probe_arith.py`), never against the filings.
