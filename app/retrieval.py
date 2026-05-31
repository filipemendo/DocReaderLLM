from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from app.documents import DocumentStore


@dataclass
class RetrievedChunk:
    document_id: str
    document_title: str
    chunk_index: int
    text: str
    score: float


class LexicalDocumentRetriever:
    def __init__(self, document_store: DocumentStore):
        self.document_store = document_store

    def retrieve(
        self,
        *,
        document_ids: list[str],
        question: str,
        selected_text: str,
        active_document_id: str | None = None,
        top_k: int = 6,
    ) -> list[RetrievedChunk]:
        candidates = self._candidate_chunks(document_ids)
        if not candidates:
            return []

        query_terms = keywords(f"{question}\n{selected_text}")
        if not query_terms:
            return candidates[:top_k]

        document_frequency = Counter()
        chunk_terms = []
        for candidate in candidates:
            terms = Counter(tokenize(candidate.text))
            chunk_terms.append(terms)
            document_frequency.update(set(terms))

        selected_anchor = selected_text.strip()[:160]
        total_chunks = len(candidates)
        scored = []
        for candidate, terms in zip(candidates, chunk_terms, strict=True):
            score = bm25ish_score(terms, query_terms, document_frequency, total_chunks)
            if selected_anchor and selected_anchor in candidate.text:
                score += 8.0
            if active_document_id and candidate.document_id == active_document_id:
                score += 0.25
            candidate.score = score
            scored.append(candidate)

        scored.sort(key=lambda chunk: (-chunk.score, chunk.document_title, chunk.chunk_index))
        matches = [chunk for chunk in scored if chunk.score > 0]
        return (matches or scored)[:top_k]

    def _candidate_chunks(self, document_ids: list[str]) -> list[RetrievedChunk]:
        candidates = []
        for document_id in document_ids:
            metadata = self.document_store.get_metadata(document_id)
            if not metadata:
                continue
            text = self.document_store.get_text(document_id)
            for index, chunk in enumerate(chunk_text(text)):
                candidates.append(
                    RetrievedChunk(
                        document_id=document_id,
                        document_title=metadata.title,
                        chunk_index=index,
                        text=chunk,
                        score=0.0,
                    )
                )
        return candidates


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


def format_retrieved_chunks(chunks: list[RetrievedChunk]) -> list[str]:
    formatted = []
    for chunk in chunks:
        location = infer_location(chunk.text, chunk.chunk_index)
        formatted.append(
            f"[{chunk.document_title} | {location} | chunk {chunk.chunk_index + 1}]\n{chunk.text}"
        )
    return formatted


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


def bm25ish_score(
    chunk_terms: Counter[str],
    query_terms: Counter[str],
    document_frequency: Counter[str],
    total_chunks: int,
) -> float:
    score = 0.0
    for term, query_count in query_terms.items():
        term_frequency = chunk_terms.get(term, 0)
        if not term_frequency:
            continue
        idf = math.log((total_chunks + 1) / (document_frequency.get(term, 0) + 0.5))
        saturation = term_frequency / (term_frequency + 1.2)
        score += query_count * idf * saturation
    return score


def infer_location(text: str, chunk_index: int) -> str:
    page = re.search(r"\[Page\s+([0-9]+)\]", text)
    if page:
        return f"page {page.group(1)}"
    heading = re.search(r"^(?:[0-9]+(?:\.[0-9]+)*\s+)?([A-Z][^\n]{4,90})$", text, re.MULTILINE)
    if heading:
        return heading.group(1)
    return f"part {chunk_index + 1}"


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
