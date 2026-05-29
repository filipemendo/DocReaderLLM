from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


DocumentKind = Literal["pdf", "epub", "html", "text", "unknown"]


class DocumentMetadata(BaseModel):
    id: str
    title: str
    kind: DocumentKind
    source_type: Literal["upload", "url"]
    source_name: str
    source_url: str | None = None
    mime_type: str | None = None
    created_at: datetime
    text_length: int = 0


class ImportUrlRequest(BaseModel):
    url: HttpUrl


class ImportUrlResponse(BaseModel):
    document: DocumentMetadata


class ChatRequest(BaseModel):
    document_id: str
    question: str = Field(min_length=1)
    selected_text: str = ""
    location: str | None = None
    provider: str | None = None
    model: str | None = None


class ChatResponse(BaseModel):
    answer: str
    provider: str
    model: str | None = None
    context_chunks: list[str] = []
