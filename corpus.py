"""
The single list of filings this project ingests.

This file answers ONE question: what do we INTEND to index. It is the input to
build_index.py and nothing else.

It is deliberately NOT the source for anything a prompt says about the corpus.
A prompt must describe what actually made it into the index, and that is read
back from the index itself. Intent and reality are different facts, and a prompt
built from intent will lie the first time an ingest half-fails.

Adding a filing = one more dict here, then delete chroma_db/ and rebuild.
"""

DOCS = [
    {"slug": "nvidia-fy2026",
     "path": "data/nvidia_10k.htm",
     "company": "NVIDIA",
     "period": "fiscal year 2026 (ended January 25, 2026)"},

    {"slug": "nvidia-fy2025",
     "path": "data/nvidia_10k_fy2025.htm",
     "company": "NVIDIA",
     "period": "fiscal year 2025 (ended January 26, 2025)"},

    {"slug": "amd-fy2025",
     "path": "data/amd_10k.htm",
     "company": "AMD",
     "period": "fiscal year 2025 (ended December 27, 2025)"},
]

# The slug is written out by hand rather than derived from company + period.
# Deriving it would mean parsing a human-readable period string, which breaks the
# first time a 10-Q arrives ("third quarter of fiscal year 2026"). A slug is an
# identity, and an identity should be stated, not computed from prose.
