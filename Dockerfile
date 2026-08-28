# Dockerfile - Phase 7. Run the API anywhere, without the API key and without the index
# inside the image.
#
# THE THREE THINGS THIS IMAGE DELIBERATELY DOES NOT CONTAIN, because each one would trade a
# real property for a smaller command line:
#
#   1. the API key      it is passed at run time, never built in. A key in a layer is a key
#                       in every copy of the image, and `docker history` will show it.
#   2. the index        chroma_db/ is built by PAID embedding calls. Baking it in means
#                       rebuilding the image to add a filing, and shipping someone else's
#                       spend to anyone who pulls it. Mounted - and mounted WRITABLE, which
#                       is a real weakening of the boundary `filing_search_server.py` states
#                       for itself ("THE INDEX IS READ-ONLY HERE"), forced by Chroma rather
#                       than chosen. See the run command below for why, and for the named
#                       volume that gets the property back if you need it.
#   3. the database     app.db holds users, sessions and the cost ledger. A container is
#                       disposable; that file is not. Mounted, via the APP_DB env var the
#                       code already reads (db.py line 25).
#
# WHAT CONTAINERISING ACTUALLY EXPOSED, and it is a real defect rather than a packaging
# detail: `app.py`'s `__main__` binds `uvicorn.run(app, host="127.0.0.1", port=8000)`. That
# is the correct default for a laptop - loopback is not reachable from the network, so the
# app is private by default - and it is UNREACHABLE from outside a container, where the
# publish flag maps a host port to the container's interface and finds nothing listening on
# it. This file therefore does not run `python app.py`; it invokes uvicorn directly with an
# explicit bind. No code changed: the safe default stays the default for anyone running it
# locally, and the container states its own exception out loud.
#
# THE COMMAND BELOW IS THE ONE THAT WAS ACTUALLY RUN, on Windows with Docker Desktop, on
# 2026-08-28: built in 85s, container reported `Up (healthy)`, `/health` returned 6 filings.
# The first three commands written here were wrong, and each was wrong for a reason worth
# keeping rather than quietly deleting:
#
#   `-v "$PWD/chroma_db:...`   `-v` splits its argument on ':', and on Windows the path
#                              STARTS with one (`A:`). Use --mount, which is key=value and
#                              has no ambiguity - it also survives the spaces in this
#                              project's path.
#   `...:/app/chroma_db:ro`    FAILED: `attempt to write a readonly database`. The app never
#                              writes to the index, and that turns out to be beside the
#                              point - Chroma's PersistentClient opens its SQLite file
#                              read-write whatever you intend to do with it, because it
#                              claims the right to journal. "Our code does not write" and
#                              "the library needs no write permission" are two different
#                              claims and only the first one was true.
#   `--env-file .env`          REFUSED the file: `variable 'GOOGLE_API_KEY ' contains
#                              whitespaces`. `python-dotenv` silently strips space around
#                              both the name and the value, so `KEY = value` had worked here
#                              since Phase 1 and nothing ever revealed it. Docker refuses the
#                              name outright - and, worse, would have PASSED a trailing space
#                              inside the value, producing a key that fails authentication
#                              with no explanation. One file, two parsers, and only the
#                              stricter one told us.
#
#   docker build -t finance-agent .
#   docker run -d --name fa -p 8001:8000 `
#     --env-file .env `
#     --mount "type=bind,source=<absolute path>\chroma_db,target=/app/chroma_db" `
#     --mount "type=volume,source=finance-agent-data,target=/data" `
#     finance-agent
#
# Host port 8001, not 8000, because the development server usually holds 8000 - and a health
# check pointed at a port already answered by something else is the most convincing wrong
# answer available. That happened here before the port was moved.
#
# IF THE CONTAINER MUST NOT BE ABLE TO TOUCH THE REAL INDEX, and `:ro` cannot give you that,
# copy the index into a named volume once and mount that instead. The container then writes
# only to its own copy:
#
#   docker volume create finance-agent-index
#   docker run --rm -v finance-agent-index:/dst \
#     --mount "type=bind,source=<absolute path>\chroma_db,target=/src" \
#     python:3.11-slim sh -c "cp -a /src/. /dst/"

# ---------------------------------------------------------------------------------------
# Build stage. Compilers live here and are thrown away, because a toolchain in a running
# image is attack surface that nothing in this project needs.
# ---------------------------------------------------------------------------------------
FROM python:3.11-slim AS build

# 3.11 is not a guess. The venv this project was developed and measured in is 3.11.7, and
# `requirements.txt` was verified against it on Windows AND on a clean Ubuntu runner. A
# different minor version would be a dependency set nobody has ever installed.

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install --no-install-recommends -y build-essential \
 && rm -rf /var/lib/apt/lists/*

# A venv rather than the system interpreter, purely so the final stage can copy ONE directory
# and inherit nothing else from this one.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# requirements.txt on its own layer, before the source. Editing app.py must not re-run a
# multi-minute install, and this is the only reason the two COPY lines are separate.
COPY requirements.txt .
RUN pip install -r requirements.txt

# `pywin32==312; sys_platform == "win32"` is in that file and is correctly SKIPPED here. It
# carries a platform marker for exactly this reason - the file has to install on the machine
# it was frozen on and on the one it is deployed to, and a marker is how one file does both.

# ---------------------------------------------------------------------------------------
# Runtime stage.
# ---------------------------------------------------------------------------------------
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_DB=/data/app.db

# PYTHONUNBUFFERED is not cosmetic. Without it Python buffers stdout when it is a pipe rather
# than a terminal, and `docker logs` shows nothing at all until the buffer fills - so the one
# tool anybody reaches for during a failure stays empty during the failure.

COPY --from=build /opt/venv /opt/venv

# A non-root user, with a FIXED uid, and the uid is fixed because it is load-bearing rather
# than decorative: the /data volume is written by this uid on the host, and an image that
# renumbers its user between builds leaves a volume its own next version cannot write.
RUN useradd --create-home --uid 10001 app \
 && mkdir -p /data /app/chroma_db \
 && chown -R app:app /data /app

WORKDIR /app

# The working directory is load-bearing for the same reason the MCP server had to chdir to
# its own folder on 2026-08-28: rag.py resolves `.env` and `chroma_db` RELATIVE TO THE
# PROCESS WORKING DIRECTORY, and db.py falls back to a relative `app.db`. Here WORKDIR fixes
# it, and APP_DB above moves the database off it deliberately.
COPY --chown=app:app . .

USER app

EXPOSE 8000

# A health check that asserts the INDEX, not just the process, and the difference is the
# whole point. `/health` was written in Phase 6.0 to report the configuration rather than the
# word "ok", after a red-team harness spent a phase testing a prompt layer that ships
# disabled. A container whose volume mount is missing or misspelled starts perfectly, answers
# "ok" forever, and returns "Not stated in the filing" to every question - which is the same
# silent failure the MCP server had. So the check reads `filings` and fails on zero.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "import json,urllib.request,sys; \
h=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)); \
sys.exit(0 if h.get('filings', 0) > 0 else 1)"

# ONE worker, on purpose. The app is FastAPI sync endpoints on a threadpool over SQLite in
# WAL mode - WAL gives many readers and ONE writer, and that writer is safe across threads in
# one process. Multiple uvicorn workers are separate PROCESSES contending for the same file,
# which turns a working design into intermittent "database is locked" under exactly the load
# that would justify adding them. Scaling this out is a real piece of work (a shared
# database), not a flag.
#
# NOT MEASURED, and the tracker says so: concurrency here is CONFIGURED, not proved. The
# concurrency probe is still open in Phase 7.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
