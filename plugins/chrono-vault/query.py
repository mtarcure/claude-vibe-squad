"""Compile natural-language text into a bounded, literal FTS5 query."""

from __future__ import annotations

import re


MAX_TERMS = 32
NO_TERMS_SENTINEL = "__chrono_no_terms__"
TOKEN_PATTERN = re.compile(r"\w+(?:[.+/$'-]\w+)*", re.UNICODE)
STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "should",
        "that",
        "the",
        "this",
        "to",
        "use",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
    }
)


def _quote_term(term: str) -> str:
    """Return one FTS5 literal with embedded quotes escaped defensively."""
    escaped = term.replace('"', '""')
    return f'"{escaped}"'


def _deduplicate(terms: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for term in terms:
        folded = term.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        unique.append(term)
    return unique


def build_fts_query(user_query: str) -> str:
    """Build an OR query whose terms cannot act as FTS5 syntax.

    Recall validates the public input bounds. This pure helper tokenizes the
    accepted string, drops a deliberately small English stopword set, and
    quotes every remaining term. If stopword removal empties the query, the
    sanitized original terms are retained so callers still receive a valid,
    graceful lookup rather than an empty MATCH expression.
    """
    if not isinstance(user_query, str):
        raise TypeError("user_query must be a string")

    raw_terms = _deduplicate(TOKEN_PATTERN.findall(user_query))
    searchable_terms = [
        term for term in raw_terms if term.casefold() not in STOPWORDS
    ][:MAX_TERMS]
    terms = searchable_terms or raw_terms[:MAX_TERMS] or [NO_TERMS_SENTINEL]
    return " OR ".join(_quote_term(term) for term in terms)
