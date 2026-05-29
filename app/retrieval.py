from __future__ import annotations

import re
from collections import Counter


def retrieve_context(full_text: str, *, question: str, selected_text: str, max_chunks: int = 4) -> list[str]:
    chunks = chunk_text(full_text)
    if not chunks:
        return []

    query_terms = keywords(f"{question}\n{selected_text}")
    if not query_terms:
        return chunks[:max_chunks]

    selected_anchor = selected_text.strip()[:160]
    scored = []
    for index, chunk in enumerate(chunks):
        score = score_chunk(chunk, query_terms)
        if selected_anchor and selected_anchor in chunk:
            score += 20
        scored.append((score, index, chunk))

    scored.sort(key=lambda item: (-item[0], item[1]))
    selected = [chunk for score, _, chunk in scored[:max_chunks] if score > 0]
    return selected or chunks[:max_chunks]


def chunk_text(text: str, *, target_size: int = 2200, overlap: int = 250) -> list[str]:
    text = text.strip()
    if not text:
        return []

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 <= target_size:
            current = f"{current}\n\n{paragraph}".strip()
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= target_size:
            current = paragraph
        else:
            chunks.extend(split_long_text(paragraph, target_size, overlap))
            current = ""
    if current:
        chunks.append(current)
    return chunks


def split_long_text(text: str, target_size: int, overlap: int) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + target_size)
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start = max(0, end - overlap)
    return chunks


def score_chunk(chunk: str, query_terms: Counter[str]) -> float:
    chunk_terms = Counter(tokenize(chunk))
    return sum(min(count, chunk_terms.get(term, 0)) for term, count in query_terms.items())


def keywords(text: str) -> Counter[str]:
    terms = [term for term in tokenize(text) if len(term) > 2 and term not in STOPWORDS]
    return Counter(terms)


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z0-9_-]*", text.lower())


STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "because",
    "been",
    "but",
    "can",
    "could",
    "does",
    "for",
    "from",
    "has",
    "have",
    "how",
    "into",
    "its",
    "more",
    "not",
    "the",
    "their",
    "then",
    "there",
    "this",
    "that",
    "was",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
    "you",
}
