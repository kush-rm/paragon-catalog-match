"""
Deterministic abbreviation expansion for fastener catalog queries.

This is "policy in code" — we expand known industrial abbreviations before
sending to Claude, so Claude reasons over fully-spelled-out descriptions
rather than hoping it catches every abbreviation every time.

All expansions use whole-word matching (word boundaries) to avoid partial
replacements (e.g. "BOX" should not expand "BO" in "BOXED").

Ordering rules:
  1. Multi-word patterns before single-word patterns (HX HD before HX).
  2. The digit+FT pattern (length, e.g. "6FT") must come BEFORE the
     standalone FT pattern (thread attribute, i.e. "FULL THREAD"), so that
     "6 FT" → "6FT" and not "6 FULL THREAD".
"""

import re

# Each entry is (pattern_regex, replacement).
# Patterns are applied top-to-bottom, so specificity matters.

ABBREVIATION_MAP = [
    # ── Screw / Bolt Types ───────────────────────────────────────────────────
    (r'\bSHCS\b',          'SOCKET HEAD CAP SCREW'),
    (r'\bBHCS\b',          'BUTTON HEAD CAP SCREW'),
    (r'\bFHCS\b',          'FLAT HEAD CAP SCREW'),
    (r'\bHCS\b',           'HEX CAP SCREW'),
    (r'\bHHB\b',           'HEX HEAD BOLT'),

    # ── Head / Drive Style ───────────────────────────────────────────────────
    (r'\bHX\s+HD\b',       'HEX HEAD'),   # two-word first
    (r'\bHX\b',            'HEX'),
    (r'\bSOC\b',           'SOCKET'),
    (r'\bBTN\b',           'BUTTON'),

    # ── Thread / Rod ─────────────────────────────────────────────────────────
    (r'\bLAG\s+SCR\b',     'LAG SCREW'),       # two-word first
    (r'\bFULL\s+THREAD\b', 'FULL THREAD'),     # already spelled out — no-op normalise

    # IMPORTANT: digit+FT must be checked BEFORE standalone FT.
    # "6 FT" and "6FT" are length tokens (catalog: "6FT FULL THREAD ROD").
    # Standalone "FT" (not preceded by a digit) means Full Thread.
    (r'\b(\d+)\s+FT\b',    r'\1FT'),           # "6 FT" → "6FT" (length, preserve)
    (r'(?<!\d)\bFT\b',     'FULL THREAD'),     # standalone FT → attribute

    # ── Material ─────────────────────────────────────────────────────────────
    (r'\bSS\b',            'STAINLESS STEEL'),

    # ── Finish ───────────────────────────────────────────────────────────────
    (r'\bBO\b',            'BLACK OXIDE'),
    (r'\bHDG\b',           'HOT DIP GALVANIZED'),
    (r'\bMECH\s+ZN\b',     'MECHANICAL ZINC'),  # two-word first
    (r'\bMZ\b',            'MECHANICAL ZINC'),
    (r'\bYEL\s+ZN\b',      'YELLOW ZINC'),      # two-word first
    (r'\bYZ\b',            'YELLOW ZINC'),
    (r'\bZC\b',            'ZINC'),
    (r'\bZN\b',            'ZINC'),
    (r'\bPLN\b',           'PLAIN'),
    (r'\bPL\b',            'PLAIN'),
]


def expand_abbreviations(query: str) -> str:
    """
    Expand common fastener abbreviations in *query* (case-insensitive).

    Steps:
      1. Normalise to UPPERCASE so all comparisons are case-insensitive.
      2. Apply each regex substitution in declared order.
      3. Collapse any extra whitespace introduced by substitutions.

    Returns the expanded, uppercased string.
    """
    text = query.upper().strip()

    for pattern, replacement in ABBREVIATION_MAP:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    # Collapse multiple spaces (can appear after multi-word expansions)
    text = re.sub(r' {2,}', ' ', text).strip()
    return text
