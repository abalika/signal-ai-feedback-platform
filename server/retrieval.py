"""Deterministic Chinese/English document retrieval with explainable scores.

The portfolio corpus is intentionally small, so a dependency-free BM25
implementation is easier to inspect and reproduce than an external vector
database.  Chinese unigrams preserve recall while bigrams add phrase signal;
Latin text is tokenized by word.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence, TypeVar


MAX_RETRIEVED_DOCUMENTS = 5
RETRIEVAL_ALGORITHM = "bm25_zh_bigram_v1"

RowT = TypeVar("RowT", bound=Mapping[str, Any])


@dataclass(frozen=True)
class RankedDocument:
    row: Mapping[str, Any]
    score: float
    matched_terms: int


def tokenize(value: str) -> list[str]:
    """Return normalized Latin words plus Chinese unigrams and bigrams."""

    lowered = value.lower()
    tokens = re.findall(r"[a-z0-9_]+", lowered)
    for sequence in re.findall(r"[\u3400-\u9fff]+", lowered):
        tokens.extend(sequence)
        tokens.extend(sequence[index : index + 2] for index in range(len(sequence) - 1))
    return tokens


def legacy_overlap_rank(documents: Sequence[RowT], query: str) -> list[RowT]:
    """The original overlap baseline, kept only for reproducible comparison."""

    query_tokens = set(re.findall(r"[A-Za-z0-9_]+|[\u3400-\u9fff]", query.lower()))
    ranked: list[tuple[int, int, RowT]] = []
    for row in documents:
        document_tokens = set(
            re.findall(
                r"[A-Za-z0-9_]+|[\u3400-\u9fff]",
                f"{row['title']} {row['content']}".lower(),
            )
        )
        ranked.append((len(query_tokens & document_tokens), -int(row["id"]), row))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in ranked]


def rank_documents(documents: Sequence[RowT], query: str) -> list[RankedDocument]:
    """Rank documents with BM25 and a small title boost.

    The score is diagnostic rather than a probability. A stable document-id
    tie break keeps tests and interview demonstrations reproducible.
    """

    if not documents:
        return []
    query_terms = list(dict.fromkeys(tokenize(query)))
    title_tokens = [tokenize(str(row["title"])) for row in documents]
    body_tokens = [tokenize(str(row["content"])) for row in documents]
    combined = [title + body for title, body in zip(title_tokens, body_tokens)]
    average_length = max(1.0, sum(len(tokens) for tokens in combined) / len(combined))
    document_frequency = Counter(
        term for tokens in combined for term in set(tokens)
    )
    k1, b, title_boost = 1.5, 0.75, 1.8
    ranked: list[RankedDocument] = []
    for row, title, tokens in zip(documents, title_tokens, combined):
        frequencies = Counter(tokens)
        title_terms = Counter(title)
        score = 0.0
        matched = 0
        for term in query_terms:
            frequency = frequencies[term]
            if frequency == 0:
                continue
            matched += 1
            frequency += title_boost * title_terms[term]
            frequency_in_documents = document_frequency[term]
            inverse_frequency = math.log(
                1 + (len(documents) - frequency_in_documents + 0.5) / (frequency_in_documents + 0.5)
            )
            normalization = frequency + k1 * (1 - b + b * len(tokens) / average_length)
            # A Chinese bigram carries more phrase meaning than either of its
            # single characters, while unigrams still preserve recall.
            term_weight = 1.6 if len(term) == 2 and re.fullmatch(r"[\u3400-\u9fff]{2}", term) else 1.0
            score += term_weight * inverse_frequency * (frequency * (k1 + 1)) / normalization
        ranked.append(RankedDocument(row=row, score=score, matched_terms=matched))
    ranked.sort(key=lambda item: (item.score, -int(item.row["id"])), reverse=True)
    return ranked


def retrieve_documents(
    documents: Sequence[RowT], query: str, limit: int = MAX_RETRIEVED_DOCUMENTS
) -> list[RowT]:
    """Return a bounded result set while preserving a safe no-match fallback."""

    ranked = rank_documents(documents, query)
    matched = [item.row for item in ranked if item.score > 0][:limit]
    return matched or [item.row for item in ranked[:limit]]


def retrieval_diagnostics(documents: Sequence[RowT], query: str, limit: int = 5) -> dict[str, Any]:
    """Return safe retrieval metadata for traces; document content is omitted."""

    ranked = rank_documents(documents, query)[:limit]
    return {
        "algorithm": RETRIEVAL_ALGORITHM,
        "query_token_count": len(set(tokenize(query))),
        "ranking": [
            {
                "document_id": int(item.row["id"]),
                "score": round(item.score, 4),
                "matched_terms": item.matched_terms,
            }
            for item in ranked
        ],
    }
