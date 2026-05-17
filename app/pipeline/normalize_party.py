"""Name/party normalization helpers used by sanctions matching.

Three transforms, intentionally tiny and side-effect-free:

- `fold_unicode`: NFKD-decompose then ASCII-fold — `"Müller"` → `"Muller"`,
  `"Société Générale"` → `"Societe Generale"`. Pure code-point operations; we do
  not attempt transliteration of non-Latin scripts here. Cyrillic, Arabic, CJK
  pass through untouched (those need a real transliterator; out of scope).
- `strip_corp_suffix`: drop trailing corporate suffixes (Ltd, LLC, GmbH, S.A., …).
- `normalize_party`: compose the two, lower-case, collapse whitespace.

A short-name guard (`is_short_name`) lets the matching code suppress
trigram-fuzzy hits on surnames like "Smith" / "Lee" which would otherwise firehose
false positives.
"""
from __future__ import annotations

import re
import unicodedata

# Common legal-entity suffixes, in lower-cased form. Order matters only when one
# suffix is a substring of another (we anchor on word boundary so this is moot).
_CORP_SUFFIXES = (
    r"ltd",
    r"llc",
    r"l\.l\.c\.",
    r"gmbh",
    r"inc",
    r"incorporated",
    r"corp",
    r"corporation",
    r"plc",
    r"ag",
    r"a\.g\.",
    r"bv",
    r"b\.v\.",
    r"nv",
    r"n\.v\.",
    r"sa",
    r"s\.a\.",
    r"s\.a\.r\.l\.",
    r"sarl",
    r"sas",
    r"s\.r\.l\.",
    r"srl",
    r"spa",
    r"s\.p\.a\.",
    r"kk",
    r"k\.k\.",
    r"pte",
    r"pvt",
    r"co",
    r"co\.",
    r"company",
    r"holdings?",
    r"group",
    r"oao",
    r"ojsc",
    r"jsc",
    r"pjsc",
    r"zao",
)

# Longer alternatives first so regex alternation doesn't greedily consume a
# shorter prefix ("S.A." inside "S.A.R.L.").
# The trailing assertion is `(?=\W|$)` not `\b` because suffix patterns that
# end in an escaped dot (`s\.a\.`) leave the cursor on a non-word char, so a
# `\b` after them can't fire against end-of-string.
_CORP_SUFFIX_RE = re.compile(
    r"\b(?:" + "|".join(sorted(_CORP_SUFFIXES, key=len, reverse=True)) + r")(?=\W|$)",
    flags=re.IGNORECASE,
)

_WS_RE = re.compile(r"\s+")
_PUNCT_TAIL_RE = re.compile(r"[\s.,;:!?\-]+$")


def fold_unicode(s: str) -> str:
    """NFKD decompose, drop combining marks, keep ASCII-printable.

    Non-Latin scripts (Cyrillic, Arabic, CJK) decompose into characters that
    are not in the ASCII range; those are dropped. For Latin-with-diacritics
    inputs this collapses to plain ASCII.
    """
    if not s:
        return ""
    decomposed = unicodedata.normalize("NFKD", s)
    # Strip combining marks (category Mn) and non-ASCII fallthrough.
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn" and ord(c) < 128)


def strip_corp_suffix(s: str) -> str:
    """Repeatedly strip trailing corporate suffix tokens from `s`.

    "ACME Holdings Ltd." → "ACME"
    "Foo S.A.R.L." → "Foo"
    """
    if not s:
        return ""
    prev = None
    cur = s
    while prev != cur:
        prev = cur
        cur = _CORP_SUFFIX_RE.sub("", cur)
        cur = _PUNCT_TAIL_RE.sub("", cur).strip()
    return cur


def normalize_party(s: str) -> str:
    """fold_unicode → strip_corp_suffix → lower → collapse whitespace."""
    if not s:
        return ""
    folded = fold_unicode(s)
    stripped = strip_corp_suffix(folded)
    return _WS_RE.sub(" ", stripped.lower()).strip()


def is_short_name(s: str, min_tokens: int = 2, min_chars: int = 4) -> bool:
    """True if `s` is likely too generic to safely fuzzy-match on alone.

    "Smith" → True (1 token). "John Smith" → False. "Acme" → True (under min_chars).
    """
    if not s:
        return True
    tokens = [t for t in s.split() if t]
    if len(tokens) < min_tokens:
        return True
    if len(s.replace(" ", "")) < min_chars:
        return True
    return False
