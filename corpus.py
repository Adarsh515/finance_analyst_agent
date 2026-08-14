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
     "doc_type": "10-K",
     "period": "fiscal year 2026 (ended January 25, 2026)"},

    {"slug": "nvidia-fy2025",
     "path": "data/nvidia_10k_fy2025.htm",
     "company": "NVIDIA",
     "doc_type": "10-K",
     "period": "fiscal year 2025 (ended January 26, 2025)"},

    {"slug": "amd-fy2025",
     "path": "data/amd_10k.htm",
     "company": "AMD",
     "doc_type": "10-K",
     "period": "fiscal year 2025 (ended December 27, 2025)"},

    {"slug": "intel-fy2025",
     "path": "data/intel_10k_fy2025.htm",
     "company": "Intel",
     "doc_type": "10-K",
     "period": "fiscal year 2025 (ended December 27, 2025)"},

    # The first quarterly filing, held back one wave so it did not land in the same
    # measurement as the third company. It overlaps the FY2026 10-K on purpose: its
    # income statement carries BOTH a three-month and a nine-month column for a period
    # already covered annually, so "NVIDIA revenue" now has three defensible values
    # (57,006 / 147,811 / 215,938) depending on the period asked for.
    {"slug": "nvidia-q3fy2026",
     "path": "data/nvidia_10q_q3fy2026.htm",
     "company": "NVIDIA",
     "doc_type": "10-Q",
     "period": "third quarter of fiscal year 2026 (ended October 26, 2025)"},
]

# The slug is written out by hand rather than derived from company + period.
# Deriving it would mean parsing a human-readable period string, which breaks the
# first time a 10-Q arrives ("third quarter of fiscal year 2026"). A slug is an
# identity, and an identity should be stated, not computed from prose.
#
# Note that Intel and AMD share the same period string: both fiscal years ended on
# 27 December 2025. Period alone is therefore NOT unique - only the (company, period)
# pair is. Anything that validates a filing must validate the pair.
#
# doc_type is carried so chunk text can say what the document actually is. Labelling a
# 10-Q's chunks "10-K" would put a false statement inside the text the model reads and
# cites. Retrieval strategy can be measured before it is fixed; corrupt data cannot.
